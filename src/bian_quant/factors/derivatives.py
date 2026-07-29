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
