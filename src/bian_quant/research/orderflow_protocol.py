"""Dollar-neutral portfolio diagnostics for orderflow research.

This module is isolated from production factor modules.  It provides
deterministic target-weight construction, open-to-open drift, L1 turnover
and fee diagnostics — all research-only.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

_FLAT_REASON = "PORTFOLIO_INSUFFICIENT_COVERAGE"
_OK_REASON = ""


@dataclass(frozen=True)
class TargetResult:
    """Outcome of target-weight construction."""

    weights: pd.Series
    long_count: int
    short_count: int
    reason: str


def build_orderflow_targets(
    signals: pd.DataFrame,
    *,
    q: float = 0.2,
    k_min: int = 3,
) -> TargetResult:
    """Build deterministic dollar-neutral target weights.

    Parameters
    ----------
    signals
        DataFrame with columns ``asset`` and ``signal``.
        Only valid (non-NaN) signals should be passed.
    q
        Quantile leg fraction.  Must be in (0, 1).
    k_min
        Minimum leg size.  At least ``2 * k_min`` assets are required.

    Returns
    -------
    TargetResult
        Weights sum to zero, ``abs`` sum to one — or all-flat with reason.
        Ties in signal are broken by asset name in ascending alphabetical
        order.
    """
    if q <= 0 or q >= 1:
        raise ValueError("q must be in (0, 1)")
    if k_min < 1:
        raise ValueError("k_min must be positive")

    required = {"asset", "signal"}
    missing = required - set(signals.columns)
    if missing:
        raise ValueError(f"missing required columns: {sorted(missing)}")

    n_valid = len(signals)
    if n_valid < 2 * k_min:
        weights = pd.Series(
            0.0,
            index=signals["asset"].values,
            dtype=float,
        )
        weights.name = "target_weight"
        return TargetResult(
            weights=weights,
            long_count=0,
            short_count=0,
            reason=_FLAT_REASON,
        )

    n = max(k_min, int(np.floor(q * n_valid)))

    sorted_signals = signals.sort_values(
        by=["signal", "asset"],
        ascending=[False, True],
    ).reset_index(drop=True)

    top_assets = sorted_signals.head(n)["asset"].tolist()
    bottom_assets = sorted_signals.tail(n)["asset"].tolist()

    weights = pd.Series(
        0.0,
        index=signals["asset"].values,
        dtype=float,
    )
    weights.name = "target_weight"

    long_w = 0.5 / n
    short_w = -0.5 / n

    for asset in top_assets:
        weights.loc[asset] = long_w
    for asset in bottom_assets:
        weights.loc[asset] = short_w

    return TargetResult(
        weights=weights,
        long_count=n,
        short_count=n,
        reason=_OK_REASON,
    )


def drift_weights_open_to_open(
    target: pd.Series,
    open_returns: pd.Series,
) -> pd.Series:
    """Drift weights using open-to-open returns.

    Parameters
    ----------
    target
        Target weights indexed by asset.
    open_returns
        Per-asset open-to-open returns for the holding period.

    Returns
    -------
    pd.Series
        Drifted weights that preserve the dollar-neutral constraint.

    Raises
    ------
    ValueError
        If ``1 + portfolio_return <= 0`` (nonpositive denominator).
    """
    aligned = pd.DataFrame({"target": target, "ret": open_returns}).fillna(0.0)
    portfolio_return = float((aligned["target"] * aligned["ret"]).sum())
    denominator = 1.0 + portfolio_return
    if denominator <= 0:
        raise ValueError(
            f"nonpositive drift denominator: 1 + {portfolio_return} = {denominator}",
        )
    drifted = aligned["target"] * (1.0 + aligned["ret"]) / denominator
    drifted.name = "drifted_weight"
    return drifted


def compute_turnover_l1(
    target: pd.Series,
    held: pd.Series,
) -> float:
    """L1 turnover between held and target weights.

    Assets present in one series but not the other are treated as zero.
    """
    aligned = pd.DataFrame({"target": target, "held": held}).fillna(0.0)
    return float((aligned["target"] - aligned["held"]).abs().sum())


def compute_fee(turnover_l1: float, taker_fee_bps: float) -> float:
    """Fee = ``turnover_l1 * taker_fee_bps / 10000``."""
    return turnover_l1 * taker_fee_bps / 10000.0
