"""Dual-horizon derivatives factors with fixed clock-equivalent lookbacks.

The 4h and 1h lookbacks preserve the same elapsed horizons and cannot be tuned.
Funding and OI are joined backward by availability time to enforce causality.
The ``delay`` parameter controls OI publication delay — delayed OI cannot
change earlier factor values.
"""

from __future__ import annotations

import re

import numpy as np
import pandas as pd

from bian_quant.factors.derivatives import relative_funding_pressure
from bian_quant.factors.price import momentum, realized_volatility, reversal
from bian_quant.factors.spec import FactorSpec
from bian_quant.factors.volume import amihud_illiquidity, volume_surprise
from bian_quant.regimes.classifier import REGIME_LABELS

LOOKBACKS: dict[str, dict[str, int]] = {
    "4h": {"momentum": 24, "reversal": 12, "volatility": 24, "volume": 24},
    "1h": {"momentum": 96, "reversal": 48, "volatility": 96, "volume": 96},
}

FACTOR_COLUMNS = (
    "momentum_24",
    "reversal_12",
    "realized_vol_24",
    "volume_surprise_24",
    "amihud_24",
    "funding_zscore",
    "relative_funding_pressure",
    "oi_change",
    "leverage_crowding",
)


def dual_horizon_factor_specs(primary_interval: str = "4h") -> tuple[FactorSpec, ...]:
    """Return the nine interpretable factor specifications.

    The factor IDs are fixed: momentum_24, reversal_12, realized_vol_24,
    volume_surprise_24, amihud_24, funding_zscore, relative_funding_pressure,
    oi_change, leverage_crowding.
    """
    regimes = list(REGIME_LABELS)
    lookups = LOOKBACKS[primary_interval]
    horizon = primary_interval

    def build(
        *,
        factor_id: str,
        formula: str,
        direction: str,
        hypothesis: str,
        required_columns: list[str],
    ) -> FactorSpec:
        return FactorSpec.model_validate(
            {
                "factor_id": factor_id,
                "version": "1.0.0",
                "formula": formula,
                "direction": direction,
                "hypothesis": hypothesis,
                "required_columns": required_columns,
                "horizon": horizon,
                "missing_policy": "preserve",
                "winsor_limits": (0.01, 0.99),
                "valid_regimes": regimes,
                "failure_conditions": [
                    "walk-forward RankIC is unstable after multiple-testing correction"
                ],
                "parent_factors": [],
            }
        )

    m = lookups["momentum"]
    r = lookups["reversal"]
    v = lookups["volatility"]
    vol = lookups["volume"]

    return (
        build(
            factor_id="momentum_24",
            formula=f"close / close.shift({m}) - 1",
            direction="positive",
            hypothesis="persistent medium-horizon price movement may continue into the next bar",
            required_columns=["close"],
        ),
        build(
            factor_id="reversal_12",
            formula=f"-(close / close.shift({r}) - 1)",
            direction="positive",
            hypothesis="short-horizon price dislocations may mean-revert during the next bar",
            required_columns=["close"],
        ),
        build(
            factor_id="realized_vol_24",
            formula=f"std(log_return, {v})",
            direction="two_sided",
            hypothesis="recent realized volatility may condition the magnitude of the next return",
            required_columns=["close"],
        ),
        build(
            factor_id="volume_surprise_24",
            formula=f"zscore(volume, {vol})",
            direction="two_sided",
            hypothesis="unusual trading activity may reveal short-lived information flow",
            required_columns=["volume"],
        ),
        build(
            factor_id="amihud_24",
            formula=f"mean(abs(log_return) / dollar_volume, {vol})",
            direction="two_sided",
            hypothesis="recent price impact may identify liquidity-dependent return behavior",
            required_columns=["close", "volume"],
        ),
        build(
            factor_id="funding_zscore",
            formula=f"zscore(funding_rate, {m})",
            direction="two_sided",
            hypothesis=(
                "extreme funding rates may signal crowded positioning and subsequent reversal"
            ),
            required_columns=["funding_rate"],
        ),
        build(
            factor_id="relative_funding_pressure",
            formula=(
                "clip((funding_rate - cross_sectional_median(funding_rate)) / "
                "(1.4826 * cross_sectional_mad(funding_rate)), -5, 5)"
            ),
            direction="two_sided",
            hypothesis=(
                "relative funding extremes may reveal asset-specific leveraged "
                "crowding and subsequent return asymmetry"
            ),
            required_columns=[
                "funding_rate",
                "funding_available_time",
                "funding_interval_hours",
            ],
        ),
        build(
            factor_id="oi_change",
            formula="open_interest.pct_change(24)",
            direction="two_sided",
            hypothesis="rapid open interest changes may indicate leveraged positioning shifts",
            required_columns=["open_interest"],
        ),
        build(
            factor_id="leverage_crowding",
            formula="oi_change * funding_zscore",
            direction="two_sided",
            hypothesis="combined OI growth and funding stress may identify leverage crowding",
            required_columns=["open_interest", "funding_rate"],
        ),
    )


def build_derivatives_factor_frame(
    bars: pd.DataFrame,
    funding: pd.DataFrame,
    oi: pd.DataFrame,
    *,
    delay: int = 5,
    interval: str = "4h",
) -> pd.DataFrame:
    """Build a derivatives factor frame with causal funding/OI joins.

    The ``delay`` parameter (in minutes) controls OI publication delay.
    Factor values computed with a given delay must not change when a larger
    delay is applied to data AFTER the cutoff time.
    """
    if interval not in LOOKBACKS:
        raise ValueError(f"unsupported factor interval: {interval}")
    required = {
        "bars": {"asset", "close", "volume", "available_time"},
        "funding": {"asset", "funding_rate"},
        "oi": {"asset"},
    }
    for name, (table, columns) in {
        "bars": (bars, required["bars"]),
        "funding": (funding, required["funding"]),
        "oi": (oi, required["oi"]),
    }.items():
        missing = columns - set(table.columns)
        if missing:
            raise ValueError(f"{name} missing columns: {sorted(missing)}")
    if "open_interest" not in oi and "sum_open_interest" not in oi:
        raise ValueError("oi missing columns: ['open_interest or sum_open_interest']")

    output: list[pd.DataFrame] = []
    for asset, asset_bars in bars.groupby("asset", sort=True):
        frame = asset_bars.sort_values("available_time").copy()
        frame["available_time"] = pd.to_datetime(frame["available_time"], utc=True)
        asset_funding = funding.loc[funding["asset"] == asset].copy()
        if not asset_funding.empty:
            funding_key = "available_time" if "available_time" in asset_funding else "event_time"
            asset_funding[funding_key] = pd.to_datetime(asset_funding[funding_key], utc=True)
            funding_columns = [funding_key, "funding_rate"]
            if "funding_interval_hours" in asset_funding:
                funding_columns.append("funding_interval_hours")
            frame = pd.merge_asof(
                frame,
                asset_funding.sort_values(funding_key)[funding_columns].rename(
                    columns={funding_key: "funding_available_time"}
                ),
                left_on="available_time",
                right_on="funding_available_time",
                direction="backward",
            )
            funding_interval = (
                pd.to_numeric(frame["funding_interval_hours"], errors="coerce").fillna(8.0)
                if "funding_interval_hours" in frame
                else pd.Series(8.0, index=frame.index)
            )
            funding_age = frame["available_time"] - frame["funding_available_time"]
            funding_gap = funding_age > pd.to_timedelta(funding_interval, unit="h")
            frame.loc[funding_gap, "funding_rate"] = np.nan
            funding_reason = pd.Series(pd.NA, index=frame.index, dtype="string")
            funding_reason.loc[frame["funding_rate"].isna()] = "FUNDING_UNAVAILABLE_OR_GAPPED"
            frame["funding_exclusion_reason"] = funding_reason
        else:
            frame["funding_rate"] = np.nan
            frame["funding_available_time"] = pd.NaT
            frame["funding_exclusion_reason"] = "FUNDING_ASSET_MISSING"

        asset_oi = oi.loc[oi["asset"] == asset].copy()
        if not asset_oi.empty:
            oi_key = "available_time" if "available_time" in asset_oi else "event_time"
            if "open_interest" not in asset_oi and "sum_open_interest" in asset_oi:
                asset_oi = asset_oi.rename(columns={"sum_open_interest": "open_interest"})
            asset_oi[oi_key] = pd.to_datetime(asset_oi[oi_key], utc=True)
            asset_oi["oi_available_time"] = asset_oi[oi_key]
            if "availability_assumption" in asset_oi.columns:
                existing_delay = asset_oi["availability_assumption"].map(
                    _availability_delay_minutes
                )
                additional_delay = (delay - existing_delay).clip(lower=0)
                asset_oi["oi_available_time"] += pd.to_timedelta(additional_delay, unit="m")
            else:
                asset_oi["oi_available_time"] += pd.Timedelta(minutes=delay)
            frame = pd.merge_asof(
                frame,
                asset_oi.sort_values("oi_available_time")[["oi_available_time", "open_interest"]],
                left_on="available_time",
                right_on="oi_available_time",
                direction="backward",
            )
            oi_age = frame["available_time"] - frame["oi_available_time"]
            oi_gap = oi_age > _interval_timedelta(interval)
            frame.loc[oi_gap, "open_interest"] = np.nan
            oi_reason = pd.Series(pd.NA, index=frame.index, dtype="string")
            oi_reason.loc[frame["open_interest"].isna()] = "OI_UNAVAILABLE_OR_GAPPED"
            frame["oi_exclusion_reason"] = oi_reason
        else:
            frame["open_interest"] = np.nan
            frame["oi_available_time"] = pd.NaT
            frame["oi_exclusion_reason"] = "OI_ASSET_MISSING"
        output.append(frame)
    if not output:
        return bars.copy()
    joined = pd.concat(output, ignore_index=True).sort_values(["asset", "available_time"])
    return compute_dual_horizon_factor_columns(joined, interval=interval)


def compute_dual_horizon_factor_columns(
    frame: pd.DataFrame, *, interval: str = "4h"
) -> pd.DataFrame:
    """Compute the fixed factor map independently inside each asset."""
    if interval not in LOOKBACKS:
        raise ValueError(f"unsupported factor interval: {interval}")
    required = {"asset", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"factor frame missing columns: {sorted(missing)}")

    work = frame.copy()
    has_available_time = "available_time" in work
    if has_available_time:
        work = work.sort_values(["available_time", "asset"]).reset_index(drop=True)

    # Cross-sectional relative funding pressure (computed before per-asset loop
    # so that every asset at the same available_time sees the same peer set).
    funding_meta = ("funding_rate", "funding_available_time", "funding_interval_hours")
    for col in funding_meta:
        if col not in work:
            work[col] = np.nan
    if has_available_time:
        pressure_values, pressure_reasons = relative_funding_pressure(work)
    else:
        pressure_values = pd.Series(np.nan, index=work.index, name="relative_funding_pressure")
        pressure_reasons = pd.Series(
            pd.NA,
            index=work.index,
            dtype="object",
            name="relative_funding_pressure_exclusion_reason",
        )
    work["relative_funding_pressure"] = pressure_values
    work["relative_funding_pressure_exclusion_reason"] = pressure_reasons

    lookups = LOOKBACKS[interval]
    output: list[pd.DataFrame] = []
    sort_columns = ["available_time"] if has_available_time else []
    for _asset, asset_frame in work.groupby("asset", sort=True):
        asset_work = (
            asset_frame.sort_values(sort_columns).copy() if sort_columns else asset_frame.copy()
        )
        if "funding_rate" not in asset_work:
            asset_work["funding_rate"] = np.nan
        if "open_interest" not in asset_work:
            asset_work["open_interest"] = np.nan
        m = lookups["momentum"]
        r = lookups["reversal"]
        v = lookups["volatility"]
        vol = lookups["volume"]
        asset_work["momentum_24"] = momentum(asset_work["close"], periods=m)
        asset_work["reversal_12"] = reversal(asset_work["close"], periods=r)
        asset_work["realized_vol_24"] = realized_volatility(asset_work["close"], periods=v)
        asset_work["volume_surprise_24"] = volume_surprise(asset_work["volume"], periods=vol)
        asset_work["amihud_24"] = amihud_illiquidity(
            asset_work["close"], asset_work["volume"], periods=vol
        )
        funding_mean = asset_work["funding_rate"].rolling(m, min_periods=1).mean()
        funding_std = asset_work["funding_rate"].rolling(m, min_periods=1).std()
        asset_work["funding_zscore"] = (
            asset_work["funding_rate"] - funding_mean
        ) / funding_std.replace(0.0, np.nan)
        asset_work["oi_change"] = asset_work["open_interest"].pct_change(m, fill_method=None)
        asset_work["leverage_crowding"] = asset_work["oi_change"] * asset_work["funding_zscore"]
        output.append(asset_work)
    if not output:
        return work.copy()
    return (
        pd.concat(output, ignore_index=True)
        .sort_values(["asset", *sort_columns])
        .reset_index(drop=True)
    )


def _availability_delay_minutes(value: object) -> int:
    match = re.search(r"DELAY_(\d+)M", str(value).upper())
    return int(match.group(1)) if match else 0


def _interval_timedelta(interval: str) -> pd.Timedelta:
    return pd.Timedelta(hours=4 if interval == "4h" else 1)
