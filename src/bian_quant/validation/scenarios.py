"""Stress scenarios for robustness testing.

Each scenario produces an immutable copy of a base experiment config
with specific parameters perturbed.  Scenarios are used to verify that
a strategy survives realistic adverse conditions, not just the ideal
case.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(frozen=True)
class ExperimentConfig:
    """Base experiment configuration.

    Attributes
    ----------
    assets:
        List of trading symbols.
    interval:
        Bar interval (e.g. ``"4h"``).
    initial_train_size:
        Number of bars in the initial training window.
    test_size:
        Number of bars in each walk-forward test window.
    step:
        Number of bars to advance between folds.
    horizon:
        Signal horizon (e.g. ``"4h"``).
    embargo:
        Purge/embargo bars between train and test.
    locked_holdout_size:
        Number of trailing bars reserved as locked holdout.
    seed:
        Random seed for reproducibility.
    taker_fee_bps:
        Normal taker fee in basis points.
    slippage_bps:
        Normal slippage in basis points.
    stress_taker_fee_bps:
        Stress-scenario taker fee.
    stress_slippage_bps:
        Stress-scenario slippage.
    gross_limit:
        Maximum gross exposure as a fraction of equity.
    """

    assets: list[str]
    interval: str
    initial_train_size: int
    test_size: int
    step: int
    horizon: str
    embargo: int
    locked_holdout_size: int
    seed: int
    taker_fee_bps: float
    slippage_bps: float
    stress_taker_fee_bps: float
    stress_slippage_bps: float
    gross_limit: float


def base_config() -> ExperimentConfig:
    """Return the default base experiment configuration."""
    return ExperimentConfig(
        assets=["BTCUSDT", "ETHUSDT", "BNBUSDT"],
        interval="4h",
        initial_train_size=2000,
        test_size=500,
        step=500,
        horizon="4h",
        embargo=6,
        locked_holdout_size=500,
        seed=42,
        taker_fee_bps=4.0,
        slippage_bps=5.0,
        stress_taker_fee_bps=8.0,
        stress_slippage_bps=10.0,
        gross_limit=1.0,
    )


def _scenario(base: ExperimentConfig, **changes: Any) -> ExperimentConfig:
    """Create a scenario by applying changes to the base config."""
    return replace(base, **changes)


def ideal(base: ExperimentConfig | None = None) -> ExperimentConfig:
    """Ideal conditions: zero costs, no delays."""
    b = base or base_config()
    return _scenario(b, taker_fee_bps=0.0, slippage_bps=0.0)


def normal(base: ExperimentConfig | None = None) -> ExperimentConfig:
    """Normal conditions: realistic costs."""
    b = base or base_config()
    return _scenario(b)


def double_cost(base: ExperimentConfig | None = None) -> ExperimentConfig:
    """Double the normal fees and slippage."""
    b = base or base_config()
    return _scenario(b, taker_fee_bps=b.taker_fee_bps * 2, slippage_bps=b.slippage_bps * 2)


def one_bar_delay(base: ExperimentConfig | None = None) -> ExperimentConfig:
    """Signal delayed by one additional bar (extra execution lag)."""
    b = base or base_config()
    return _scenario(b, embargo=b.embargo + 1)


def parameter_down(base: ExperimentConfig | None = None) -> ExperimentConfig:
    """Conservative parameter set: smaller position size."""
    b = base or base_config()
    return _scenario(b, gross_limit=b.gross_limit * 0.5)


def parameter_up(base: ExperimentConfig | None = None) -> ExperimentConfig:
    """Aggressive parameter set: larger position size."""
    b = base or base_config()
    return _scenario(b, gross_limit=min(b.gross_limit * 2.0, 2.0))


def data_gap(base: ExperimentConfig | None = None) -> ExperimentConfig:
    """Simulate a data gap: larger test windows to span potential gaps."""
    b = base or base_config()
    return _scenario(b, test_size=b.test_size + 100)


def price_spike(base: ExperimentConfig | None = None) -> ExperimentConfig:
    """Price spike scenario: higher slippage to simulate adverse selection."""
    b = base or base_config()
    return _scenario(b, slippage_bps=b.slippage_bps * 3)


def all_scenarios(base: ExperimentConfig | None = None) -> dict[str, ExperimentConfig]:
    """Return all named scenarios as a dictionary."""
    b = base or base_config()
    return {
        "ideal": ideal(b),
        "normal": normal(b),
        "double_cost": double_cost(b),
        "one_bar_delay": one_bar_delay(b),
        "parameter_down": parameter_down(b),
        "parameter_up": parameter_up(b),
        "data_gap": data_gap(b),
        "price_spike": price_spike(b),
    }
