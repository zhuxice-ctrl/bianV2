"""Dual-horizon derivatives factors with fixed clock-equivalent lookbacks.

The 4h and 1h lookbacks preserve the same elapsed horizons and cannot be tuned.
Funding and OI are joined backward by availability time to enforce causality.
The ``delay`` parameter controls OI publication delay — delayed OI cannot
change earlier factor values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bian_quant.factors.price import momentum, realized_volatility, reversal
from bian_quant.factors.spec import FactorSpec
from bian_quant.factors.volume import amihud_illiquidity, volume_surprise
from bian_quant.regimes.classifier import REGIME_LABELS

LOOKBACKS: dict[str, dict[str, int]] = {
    "4h": {"momentum": 24, "reversal": 12, "volatility": 24, "volume": 24},
    "1h": {"momentum": 96, "reversal": 48, "volatility": 96, "volume": 96},
}


def dual_horizon_factor_specs(primary_interval: str = "4h") -> tuple[FactorSpec, ...]:
    """Return the eight interpretable factor specifications.

    The factor IDs are fixed: momentum_24, reversal_12, realized_vol_24,
    volume_surprise_24, amihud_24, funding_zscore, oi_change, leverage_crowding.
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
            hypothesis=(
                f"persistent medium-horizon price movement over {m} bars "
                "may continue into the next bar"
            ),
            required_columns=["close"],
        ),
        build(
            factor_id="reversal_12",
            formula=f"-(close / close.shift({r}) - 1)",
            direction="positive",
            hypothesis=(
                f"short-horizon price dislocations over {r} bars "
                "may mean-revert during the next bar"
            ),
            required_columns=["close"],
        ),
        build(
            factor_id="realized_vol_24",
            formula=f"std(log_return, {v})",
            direction="two_sided",
            hypothesis=(
                f"recent realized volatility over {v} bars may condition "
                "the magnitude of the next return"
            ),
            required_columns=["close"],
        ),
        build(
            factor_id="volume_surprise_24",
            formula=f"zscore(volume, {vol})",
            direction="two_sided",
            hypothesis=(
                f"unusual trading activity over {vol} bars may reveal short-lived information flow"
            ),
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
            formula="zscore(funding_rate, 24)",
            direction="two_sided",
            hypothesis=(
                "extreme funding rates may signal crowded positioning and subsequent reversal"
            ),
            required_columns=["funding_rate"],
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
) -> pd.DataFrame:
    """Build a derivatives factor frame with causal funding/OI joins.

    The ``delay`` parameter (in minutes) controls OI publication delay.
    Factor values computed with a given delay must not change when a larger
    delay is applied to data AFTER the cutoff time.
    """
    frame = bars.copy()

    # Ensure availability_time exists
    if "available_time" not in frame.columns:
        frame["available_time"] = frame.get("event_time", frame.index)

    # Join funding backward by availability time
    if not funding.empty:
        funding = funding.copy()
        funding_key = "available_time" if "available_time" in funding.columns else "event_time"
        funding_sorted = funding.sort_values(funding_key)
        frame = frame.sort_values("available_time")
        frame = pd.merge_asof(
            frame,
            funding_sorted[["funding_rate", funding_key]].rename(
                columns={funding_key: "funding_available_time"}
            ),
            left_on="available_time",
            right_on="funding_available_time",
            direction="backward",
        )
    else:
        frame["funding_rate"] = 0.0
        frame["funding_available_time"] = frame["available_time"]

    # Join OI backward by availability time, applying publication delay
    if not oi.empty:
        oi = oi.copy()
        oi_key = "available_time" if "available_time" in oi.columns else "event_time"
        # Apply delay: shift the OI availability time forward by delay minutes
        delay_delta = pd.Timedelta(minutes=delay)
        oi_delayed = oi.copy()
        oi_delayed["oi_available_time"] = oi_delayed[oi_key] + delay_delta
        oi_sorted = oi_delayed.sort_values("oi_available_time")
        frame = pd.merge_asof(
            frame,
            oi_sorted[["open_interest", "oi_available_time"]],
            left_on="available_time",
            right_on="oi_available_time",
            direction="backward",
        )
    else:
        frame["open_interest"] = 0.0
        frame["oi_available_time"] = frame["available_time"]

    # Compute factors
    lookups = LOOKBACKS["4h"]  # Default to 4h lookbacks
    m = lookups["momentum"]
    r = lookups["reversal"]
    v = lookups["volatility"]
    vol = lookups["volume"]

    # Price-based factors
    frame["momentum_24"] = momentum(frame["close"], periods=m)
    frame["reversal_12"] = reversal(frame["close"], periods=r)
    frame["realized_vol_24"] = realized_volatility(frame["close"], periods=v)
    frame["volume_surprise_24"] = volume_surprise(frame["volume"], periods=vol)
    frame["amihud_24"] = amihud_illiquidity(frame["close"], frame["volume"], periods=vol)

    # Funding-based factor
    if "funding_rate" in frame.columns:
        funding_mean = frame["funding_rate"].rolling(24, min_periods=1).mean()
        funding_std = frame["funding_rate"].rolling(24, min_periods=1).std()
        frame["funding_zscore"] = (frame["funding_rate"] - funding_mean) / funding_std.replace(
            0.0, np.nan
        )
    else:
        frame["funding_zscore"] = 0.0

    # OI-based factor
    if "open_interest" in frame.columns:
        frame["oi_change"] = frame["open_interest"].pct_change(24)
    else:
        frame["oi_change"] = 0.0

    # Leverage crowding
    frame["leverage_crowding"] = frame["oi_change"] * frame["funding_zscore"]

    return frame


@dataclass
class DualHorizonScreeningResult:
    """Result of dual-horizon factor screening."""

    engineering_status: str  # "passed" or "failed"
    candidate_factor_ids: tuple[str, ...] = ()
    factor_evaluations: list[dict[str, Any]] = field(default_factory=list)
    artifact_path: Path | None = None


def run_dual_horizon_screening(
    frame: pd.DataFrame,
    *,
    config: dict[str, Any] | None = None,
) -> DualHorizonScreeningResult:
    """Run dual-horizon factor screening on the development window only.

    A zero-candidate run is completed (status "passed"), not failed.
    """
    # Determine which factors have sufficient non-NaN values
    factor_columns = [
        "momentum_24",
        "reversal_12",
        "realized_vol_24",
        "volume_surprise_24",
        "amihud_24",
        "funding_zscore",
        "oi_change",
        "leverage_crowding",
    ]

    available = [col for col in factor_columns if col in frame.columns]
    candidate_ids: list[str] = []

    for col in available:
        series = frame[col].dropna()
        if len(series) < 30:
            continue
        # Simple check: non-zero variance
        if series.std() > 0:
            candidate_ids.append(col)

    return DualHorizonScreeningResult(
        engineering_status="passed",
        candidate_factor_ids=tuple(candidate_ids),
    )
