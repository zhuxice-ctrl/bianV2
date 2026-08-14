"""Point-in-time derivatives factors.

All factors use backward as-of joins on ``available_time`` and only
backward-looking rolling statistics.  A funding/OI record whose
``available_time`` is after the decision bar cannot influence the factor
at that bar.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def asof_join(
    bars: pd.DataFrame,
    aux: pd.DataFrame,
    *,
    on: str = "available_time",
    by: str | None = "asset",
) -> pd.DataFrame:
    """Backward as-of join of auxiliary data onto bar timestamps.

    Parameters
    ----------
    bars
        DataFrame with a sorted datetime column named *on*.
    aux
        DataFrame with a sorted datetime column named *on*.
    on
        Column name for the as-of timestamp (default ``available_time``).
    by
        Column to group by (default ``asset``).  Set to ``None`` for
        single-asset data.

    Returns
    -------
    Merged DataFrame with the source ``available_time`` from *aux*
    exposed as ``aux_available_time`` for audit.
    """
    bars = bars.copy()
    aux = aux.copy()

    bars[on] = pd.to_datetime(bars[on])
    aux[on] = pd.to_datetime(aux[on])

    bars = bars.sort_values(on)
    aux = aux.sort_values(on).copy()
    aux = aux.rename(columns={on: "aux_available_time"})

    if by is not None:
        merged = pd.merge_asof(
            bars,
            aux,
            left_on=on,
            right_on="aux_available_time",
            by=by,
            direction="backward",
            allow_exact_matches=True,
        )
    else:
        merged = pd.merge_asof(
            bars,
            aux,
            left_on=on,
            right_on="aux_available_time",
            direction="backward",
            allow_exact_matches=True,
        )
    known_aux = merged["aux_available_time"].notna()
    if (merged.loc[known_aux, "aux_available_time"] > merged.loc[known_aux, on]).any():
        raise AssertionError("as-of join exposed auxiliary data before publication")
    return merged


def funding_zscore(funding_rate: pd.Series, *, periods: int) -> pd.Series:
    """Z-score of funding rate relative to its rolling statistics."""
    if periods <= 1:
        raise ValueError("periods must be greater than one")
    mean = funding_rate.rolling(periods, min_periods=periods).mean()
    std = funding_rate.rolling(periods, min_periods=periods).std(ddof=1)
    return ((funding_rate - mean) / std.replace(0.0, np.nan)).rename(f"funding_zscore_{periods}")


def oi_change(open_interest: pd.Series, *, periods: int) -> pd.Series:
    """Percentage change in open interest over *periods* bars."""
    if periods <= 0:
        raise ValueError("periods must be positive")
    return open_interest.pct_change(periods=periods, fill_method=None).rename(
        f"oi_change_{periods}"
    )


def leverage_crowding(funding_z: pd.Series, oi_delta: pd.Series) -> pd.Series:
    """Interaction of positive funding z-score and OI growth."""
    return (funding_z * oi_delta.clip(lower=0.0)).rename("leverage_crowding")


def relative_funding_pressure(
    frame: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    """Cross-sectional relative funding pressure factor.

    For each decision time ``available_time`` the function collects the
    latest canonical funding record of every asset whose
    ``funding_available_time <= available_time`` and whose age has not
    exceeded the declared ``funding_interval_hours``.  When at least two
    peers are available it computes a robust z-score against the
    cross-sectional median and MAD; otherwise the value is missing with a
    structured exclusion reason.

    The function is pure: it never reads paths, writes artifacts, modifies
    the input frame, or imports research/dashboard modules.
    """
    required = {
        "asset",
        "available_time",
        "funding_available_time",
        "funding_interval_hours",
        "funding_rate",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"relative funding frame missing columns: {sorted(missing)}")
    working = frame.copy()
    working["available_time"] = pd.to_datetime(
        working["available_time"], utc=True, errors="coerce", format="mixed"
    )
    working["funding_available_time"] = pd.to_datetime(
        working["funding_available_time"], utc=True, errors="coerce", format="mixed"
    )
    if working.duplicated(["asset", "available_time"]).any():
        raise ValueError("duplicate asset/available_time rows")
    working["funding_rate"] = pd.to_numeric(working["funding_rate"], errors="coerce")
    working["funding_interval_hours"] = pd.to_numeric(
        working["funding_interval_hours"], errors="coerce"
    )

    values = np.full(len(working), np.nan, dtype=float)
    reasons = np.full(len(working), pd.NA, dtype=object)

    rate = working["funding_rate"].to_numpy(dtype=float)
    interval = working["funding_interval_hours"].to_numpy(dtype=float)
    available_time = working["available_time"]
    funding_available_time = working["funding_available_time"]
    available = (
        available_time.notna().to_numpy()
        & funding_available_time.notna().to_numpy()
        & (funding_available_time <= available_time).to_numpy()
    )
    finite_rate = np.isfinite(rate)
    finite_interval = np.isfinite(interval)
    positive_interval = finite_interval & (interval > 0)
    max_interval_hours = np.iinfo(np.int64).max / pd.Timedelta(hours=1).value
    representable_interval = positive_interval & (interval <= max_interval_hours)
    age = available_time - funding_available_time
    interval_td = pd.to_timedelta(
        pd.Series(interval).where(representable_interval), unit="h", errors="coerce"
    )
    fresh = age.to_numpy() <= interval_td.to_numpy()
    valid = available & finite_rate & representable_interval & fresh

    reasons[~valid] = "FUNDING_UNAVAILABLE_OR_GAPPED"

    for positions in working.groupby("available_time", sort=True).indices.values():
        valid_positions = positions[valid[positions]]
        valid_rates = rate[valid_positions]
        if valid_rates.size < 2:
            reasons[valid_positions] = "INSUFFICIENT_PEER_COVERAGE"
            continue
        median_rate = float(np.median(valid_rates))
        mad = float(np.median(np.abs(valid_rates - median_rate)))
        if mad <= 0:
            reasons[valid_positions] = "ZERO_CROSS_SECTIONAL_MAD"
            continue
        scale = 1.4826 * mad
        values[valid_positions] = np.clip((valid_rates - median_rate) / scale, -5.0, 5.0)

    return (
        pd.Series(values, index=frame.index, name="relative_funding_pressure"),
        pd.Series(
            reasons,
            index=frame.index,
            dtype="object",
            name="relative_funding_pressure_exclusion_reason",
        ),
    )
