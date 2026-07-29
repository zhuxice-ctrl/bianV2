"""End-to-end factor pipeline integration test."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from bian_quant.factors.labels import forward_log_return
from bian_quant.factors.price import momentum
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.runner import FactorRunConfig, run_factor_pipeline
from bian_quant.factors.spec import FactorSpec, FactorState


def _make_deterministic_data(n: int = 500, seed: int = 42) -> pd.DataFrame:
    """Create deterministic BTC-like 4h data."""
    rng = np.random.default_rng(seed)
    close = 40000.0 * np.cumprod(1.0 + rng.normal(0.0005, 0.02, n))
    volume = rng.uniform(100, 1000, n)
    timestamps = pd.date_range("2024-01-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "available_time": timestamps,
            "asset": "BTC",
            "close": close,
            "volume": volume,
        }
    )


def _momentum_fn(frame: pd.DataFrame) -> pd.Series:
    return momentum(frame["close"], periods=24)


def test_factor_pipeline_e2e(tmp_path: Path) -> None:
    """Register → compute → evaluate → lifecycle transition with evidence."""
    registry = FactorRegistry(tmp_path / "registry.sqlite")

    spec = FactorSpec(
        factor_id="price.momentum",
        version="1.0.0",
        formula="close / close.shift(24) - 1",
        direction="positive",
        hypothesis="persistent price movement may continue over the next horizon",
        required_columns=["close"],
        horizon="4h",
        missing_policy="preserve",
        winsor_limits=(0.01, 0.99),
        valid_regimes=["all"],
        failure_conditions=["cost-adjusted OOS IC lower bound <= 0"],
        parent_factors=[],
    )

    config = FactorRunConfig(
        dataset_snapshot_id="test-snapshot-v1",
        factor_specs=[spec],
        split_config={"n_folds": 3, "train_ratio": 0.6, "purge_bars": 6},
        seed=7,
        artifact_dir=tmp_path / "artifacts",
    )

    data = _make_deterministic_data(500)
    result = run_factor_pipeline(
        config,
        data,
        registry=registry,
        factor_functions={"price.momentum": _momentum_fn},
    )

    # Run should complete
    assert result.status == "completed"
    assert result.run_id is not None

    # Should have evaluations with fold/asset/regime breakdown
    assert len(result.evaluations) > 0
    for ev in result.evaluations:
        assert ev.fold is not None
        assert ev.asset is not None
        assert ev.regime is not None

    # Multiple testing should be applied
    assert len(result.multiple_testing) > 0

    # Artifacts should be persisted
    assert result.artifact_path is not None
    assert result.artifact_path.exists()

    # Lifecycle transition should cite the run_id
    # Factor should be registered as RESEARCHING
    assert registry.state("price.momentum", "1.0.0") == FactorState.RESEARCHING

    # If we transition to OBSERVED, it must use evidence_run_id
    registry.transition(
        "price.momentum",
        "1.0.0",
        FactorState.OBSERVED,
        evidence_run_id=result.run_id,
    )
    assert registry.state("price.momentum", "1.0.0") == FactorState.OBSERVED

    # Verify the transition history cites the run_id
    history = registry.history("price.momentum", "1.0.0")
    transition = [h for h in history if h["to_state"] == "observed"][0]
    assert transition["evidence_run_id"] == result.run_id


def test_factor_pipeline_blocked_on_insufficient_data(tmp_path: Path) -> None:
    """Pipeline should be blocked on insufficient data."""
    registry = FactorRegistry(tmp_path / "registry.sqlite")

    spec = FactorSpec(
        factor_id="price.momentum",
        version="1.0.0",
        formula="close / close.shift(24) - 1",
        direction="positive",
        hypothesis="persistent price movement may continue over the next horizon",
        required_columns=["close"],
        horizon="4h",
        missing_policy="preserve",
        winsor_limits=(0.01, 0.99),
        valid_regimes=["all"],
        failure_conditions=["cost-adjusted OOS IC lower bound <= 0"],
        parent_factors=[],
    )

    config = FactorRunConfig(
        dataset_snapshot_id="test-snapshot-v1",
        factor_specs=[spec],
        split_config={"n_folds": 3, "train_ratio": 0.6, "purge_bars": 6},
        seed=7,
        artifact_dir=tmp_path / "artifacts",
    )

    # Only 50 rows — insufficient
    data = _make_deterministic_data(50)
    result = run_factor_pipeline(
        config,
        data,
        registry=registry,
        factor_functions={"price.momentum": _momentum_fn},
    )

    assert result.status == "blocked"
    assert result.error is not None
    assert result.artifact_path is not None
    assert result.artifact_path.exists()
