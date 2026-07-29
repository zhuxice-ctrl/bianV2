"""Factor batch runner: register → compute → evaluate → lifecycle transition.

The runner never infers parameters from the current clock or latest files.
On failure it transitions the run to ``failed``; on blocking data quality
it transitions to ``blocked``.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from bian_quant.factors.evaluate import FactorEvaluation, evaluate_factor
from bian_quant.factors.multiple_testing import benjamini_hochberg
from bian_quant.factors.redundancy import (
    cluster_redundant_factors,
    evaluate_incremental_contribution,
)
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorSpec, FactorState


@dataclass
class FactorRunConfig:
    """Configuration for a factor evaluation run."""

    dataset_snapshot_id: str
    factor_specs: list[FactorSpec]
    split_config: dict[str, Any]
    seed: int = 42
    artifact_dir: Path = Path("var/factor_runs")


@dataclass
class FactorRunResult:
    """Result of a factor evaluation run."""

    run_id: str
    status: str  # "completed", "failed", "blocked"
    evaluations: list[FactorEvaluation] = field(default_factory=list)
    multiple_testing: dict[str, bool] = field(default_factory=dict)
    cluster_result: Any = None
    artifact_path: Path | None = None
    error: str | None = None


def run_factor_pipeline(
    config: FactorRunConfig,
    data: pd.DataFrame,
    *,
    registry: FactorRegistry,
    factor_functions: dict[str, Any],
) -> FactorRunResult:
    """Run the full factor evaluation pipeline.

    Parameters
    ----------
    config
        Run configuration including dataset snapshot ID, factor specs,
        split config, and seed.
    data
        Point-in-time DataFrame with columns: timestamp, asset, close,
        volume, available_time.
    registry
        Factor registry for lifecycle management.
    factor_functions
        Mapping of factor_id to callable that computes the factor from
        the data.
    """
    run_id = f"factor-run-{uuid.uuid4().hex[:12]}"
    artifact_dir = Path(config.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Validate data
        required_cols = {"timestamp", "asset", "close", "volume"}
        if not required_cols.issubset(data.columns):
            raise ValueError(f"data missing required columns: {required_cols - set(data.columns)}")

        if len(data) < 100:
            raise ValueError("insufficient data for factor evaluation (need >= 100 rows)")

        # Create walk-forward splits
        splits = _create_splits(data, config.split_config, config.seed)

        all_evaluations: list[FactorEvaluation] = []

        for fold_name, (train_idx, test_idx) in splits.items():
            train_data = data.iloc[train_idx]
            test_data = data.iloc[test_idx]

            for spec in config.factor_specs:
                # Register factor if not already
                try:
                    registry.register(spec, code_sha=run_id)
                except ValueError:
                    pass  # already registered

                # Compute factor on test data
                fn = factor_functions.get(spec.factor_id)
                if fn is None:
                    continue

                factor_values = fn(test_data)
                train_factor_values = fn(train_data)

                # Build label (forward log return, isolated)
                from bian_quant.factors.labels import forward_log_return

                label = forward_log_return(test_data["close"], periods=1)

                # Build metadata
                metadata = pd.DataFrame(
                    {
                        "asset": test_data["asset"].values,
                        "regime": _assign_regimes(test_data),
                    },
                    index=test_data.index,
                )

                # Evaluate
                evals = evaluate_factor(
                    factor_values,
                    label,
                    metadata,
                    fold=fold_name,
                    winsor_limits=spec.winsor_limits,
                    train_factor=train_factor_values,
                )
                all_evaluations.extend(evals)

        # Multiple testing correction
        p_values: dict[str, float] = {}
        for ev in all_evaluations:
            # Approximate p-value from IC and sample count
            if ev.sample_count > 2 and not np.isnan(ev.spearman_ic):
                # Fisher transform for p-value
                z = 0.5 * np.log((1 + ev.spearman_ic) / (1 - ev.spearman_ic))
                p = 2 * (1 - _standard_normal_cdf(abs(z) * np.sqrt(ev.sample_count - 3)))
                p_values[ev.factor_name + f"@{ev.fold}:{ev.asset}:{ev.regime}"] = max(min(p, 1.0), 0.0)

        mt_result = benjamini_hochberg(p_values, alpha=0.05)

        # Redundancy clustering (on train data)
        train_factor_df = pd.DataFrame()
        for spec in config.factor_specs:
            fn = factor_functions.get(spec.factor_id)
            if fn is not None:
                train_data = data.iloc[splits[list(splits.keys())[0]][0]]
                train_factor_df[spec.factor_id] = fn(train_data)

        cluster_result = None
        if train_factor_df.shape[1] > 0:
            # Use mean IC as inner validation score
            scores = {}
            for ev in all_evaluations:
                scores[ev.factor_name] = abs(ev.spearman_ic)
            cluster_result = cluster_redundant_factors(
                train_factor_df.dropna(),
                distance_threshold=0.3,
                inner_validation_scores=scores if scores else None,
            )

        # Persist results
        result = FactorRunResult(
            run_id=run_id,
            status="completed",
            evaluations=all_evaluations,
            multiple_testing=mt_result,
            cluster_result=cluster_result,
        )

        # Save artifacts
        artifact_path = artifact_dir / f"{run_id}.json"
        artifact_data = {
            "run_id": run_id,
            "status": "completed",
            "dataset_snapshot_id": config.dataset_snapshot_id,
            "seed": config.seed,
            "evaluations": [
                {
                    "factor_name": ev.factor_name,
                    "fold": ev.fold,
                    "asset": ev.asset,
                    "regime": ev.regime,
                    "pearson_ic": ev.pearson_ic,
                    "spearman_ic": ev.spearman_ic,
                    "coverage": ev.coverage,
                    "turnover": ev.turnover,
                    "sample_count": ev.sample_count,
                    "ci_lower": ev.ci_lower,
                    "ci_upper": ev.ci_upper,
                }
                for ev in all_evaluations
            ],
            "multiple_testing": mt_result,
        }
        artifact_path.write_text(json.dumps(artifact_data, indent=2, default=str))
        result.artifact_path = artifact_path

        return result

    except Exception as e:
        result = FactorRunResult(
            run_id=run_id,
            status="blocked" if "insufficient" in str(e).lower() else "failed",
            error=str(e),
        )
        artifact_path = artifact_dir / f"{run_id}.json"
        artifact_data = {
            "run_id": run_id,
            "status": result.status,
            "error": str(e),
            "dataset_snapshot_id": config.dataset_snapshot_id,
            "seed": config.seed,
        }
        artifact_path.write_text(json.dumps(artifact_data, indent=2))
        result.artifact_path = artifact_path
        return result


def _create_splits(
    data: pd.DataFrame, split_config: dict[str, Any], seed: int
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    """Create walk-forward splits from config."""
    n = len(data)
    n_folds = split_config.get("n_folds", 3)
    train_ratio = split_config.get("train_ratio", 0.6)
    purge_bars = split_config.get("purge_bars", 6)

    fold_size = n // (n_folds + 1)
    splits: dict[str, tuple[np.ndarray, np.ndarray]] = {}

    for i in range(n_folds):
        train_end = fold_size * (i + 1)
        test_start = train_end + purge_bars
        test_end = min(test_start + fold_size, n)

        if test_start >= n or test_end <= test_start:
            continue

        train_idx = np.arange(0, train_end)
        test_idx = np.arange(test_start, test_end)
        splits[f"fold_{i}"] = (train_idx, test_idx)

    if not splits:
        # Fallback: single split
        mid = int(n * train_ratio)
        splits["fold_0"] = (np.arange(0, mid), np.arange(mid, n))

    return splits


def _assign_regimes(data: pd.DataFrame) -> list[str]:
    """Simple regime assignment based on volatility (placeholder)."""
    close = data["close"]
    returns = np.log(close / close.shift(1))
    vol = returns.rolling(48, min_periods=10).std()
    median_vol = vol.median()
    if np.isnan(median_vol):
        return ["range_low_vol"] * len(data)
    high_vol = vol > median_vol
    return ["trend_high_vol" if hv else "trend_low_vol" if not np.isnan(hv) else "range_low_vol" for hv in high_vol.fillna(False)]


def _standard_normal_cdf(x: float) -> float:
    """Standard normal CDF approximation."""
    from math import erf, sqrt

    return 0.5 * (1 + erf(x / sqrt(2)))
