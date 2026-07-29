"""Evidence-driven factor batch runner.

The runner binds every evaluation to an explicit dataset snapshot, code SHA,
split configuration, and seed. Labels are built per asset, regime thresholds
are fit on training folds only, and all lifecycle transitions cite a registered
experiment run.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from bian_quant.experiments.models import RunManifest, RunStatus
from bian_quant.experiments.registry import ExperimentRegistry
from bian_quant.factors.evaluate import FactorEvaluation, evaluate_factor
from bian_quant.factors.labels import forward_log_return
from bian_quant.factors.multiple_testing import (
    BHDecision,
    benjamini_hochberg_details,
)
from bian_quant.factors.redundancy import (
    ClusterResult,
    IncrementalResult,
    cluster_redundant_factors,
    evaluate_incremental_contribution,
)
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorSpec, FactorState
from bian_quant.regimes.classifier import classify_regime, fit_regime_thresholds

FactorCallable = Callable[[pd.DataFrame], pd.Series]


class FactorDataBlockedError(ValueError):
    """A blocking point-in-time or data-quality defect."""


@dataclass(frozen=True)
class FactorRunConfig:
    """Explicit, reproducible configuration for a factor evaluation run."""

    dataset_snapshot_id: str
    factor_specs: list[FactorSpec]
    split_config: dict[str, Any]
    code_sha: str = "uncommitted"
    seed: int = 42
    artifact_dir: Path = Path("var/factor_runs")
    experiment_registry_path: Path | str = ":memory:"
    bh_alpha: float = 0.05
    redundancy_distance: float = 0.3
    incremental_cost_bps: float = 5.0


@dataclass
class FactorRunResult:
    """Structured result persisted by :func:`run_factor_pipeline`."""

    run_id: str
    status: str
    evaluations: list[FactorEvaluation] = field(default_factory=list)
    multiple_testing: dict[str, bool] = field(default_factory=dict)
    multiple_testing_details: dict[str, BHDecision] = field(default_factory=dict)
    cluster_result: ClusterResult | None = None
    incremental_results: list[IncrementalResult] = field(default_factory=list)
    lifecycle_states: dict[str, str] = field(default_factory=dict)
    artifact_path: Path | None = None
    error: str | None = None


def run_factor_pipeline(
    config: FactorRunConfig,
    data: pd.DataFrame,
    *,
    registry: FactorRegistry,
    factor_functions: dict[str, FactorCallable],
    experiment_registry: ExperimentRegistry | None = None,
) -> FactorRunResult:
    """Run causal factor evaluation and persist auditable evidence."""
    artifact_dir = Path(config.artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    owns_experiment_registry = experiment_registry is None
    runs = experiment_registry or ExperimentRegistry(config.experiment_registry_path)

    manifest = RunManifest.create(
        strategy_name="factor_screening",
        code_sha=config.code_sha,
        dataset_snapshot_ids=[config.dataset_snapshot_id],
        config=_manifest_config(config),
        seed=config.seed,
    )
    runs.create(manifest)
    runs.transition(manifest.run_id, RunStatus.RUNNING)

    try:
        result = _execute_pipeline(
            config,
            data,
            registry=registry,
            factor_functions=factor_functions,
            run_id=manifest.run_id,
        )
        # Persist evidence before allowing factor lifecycle transitions.
        result.artifact_path = _persist_result(config, result)
        _transition_completed_factors(registry, config.factor_specs, result)
        result.lifecycle_states = {
            spec.factor_id: registry.state(spec.factor_id, spec.version).value
            for spec in config.factor_specs
        }
        result.artifact_path = _persist_result(config, result)
        runs.transition(manifest.run_id, RunStatus.PASSED)
        return result
    except FactorDataBlockedError as error:
        result = FactorRunResult(run_id=manifest.run_id, status="blocked", error=str(error))
        result.artifact_path = _persist_result(config, result)
        runs.transition(manifest.run_id, RunStatus.BLOCKED)
        return result
    except Exception as error:
        result = FactorRunResult(run_id=manifest.run_id, status="failed", error=str(error))
        result.artifact_path = _persist_result(config, result)
        runs.transition(manifest.run_id, RunStatus.FAILED)
        return result
    finally:
        if owns_experiment_registry:
            runs.close()


def _execute_pipeline(
    config: FactorRunConfig,
    data: pd.DataFrame,
    *,
    registry: FactorRegistry,
    factor_functions: dict[str, FactorCallable],
    run_id: str,
) -> FactorRunResult:
    frame = _validate_frame(config, data, factor_functions)
    _register_specs(registry, config.factor_specs, code_sha=config.code_sha)

    evaluations: list[FactorEvaluation] = []
    final_train_factors: list[pd.DataFrame] = []
    final_validation_factors: list[pd.DataFrame] = []
    final_train_labels: list[pd.Series] = []
    final_validation_labels: list[pd.Series] = []

    for _asset, asset_frame in frame.groupby("asset", sort=True):
        asset_frame = asset_frame.sort_values("available_time").reset_index(drop=True)
        if len(asset_frame) < 100:
            raise FactorDataBlockedError(
                f"insufficient data for asset {asset_frame['asset'].iloc[0]}: need >= 100 rows"
            )

        splits = _create_splits(len(asset_frame), config.split_config)
        label = forward_log_return(asset_frame["close"], periods=1)
        factor_values = _compute_factors(asset_frame, config.factor_specs, factor_functions)

        for fold_name, (train_idx, test_idx) in splits.items():
            train = asset_frame.iloc[train_idx]
            thresholds = fit_regime_thresholds(train[["close", "volume"]])
            regimes = classify_regime(asset_frame[["close", "volume"]], thresholds).iloc[test_idx]
            metadata = pd.DataFrame(
                {
                    "asset": asset_frame.iloc[test_idx]["asset"].to_numpy(),
                    "regime": regimes.to_numpy(),
                },
                index=test_idx,
            )

            for spec in config.factor_specs:
                values = factor_values[spec.factor_id]
                fold_evaluations = evaluate_factor(
                    values.iloc[test_idx],
                    label.iloc[test_idx],
                    metadata,
                    fold=fold_name,
                    winsor_limits=spec.winsor_limits,
                    train_factor=values.iloc[train_idx],
                )
                evaluations.extend(fold_evaluations)

        _final_fold_frames(
            splits,
            factor_values,
            label,
            final_train_factors,
            final_validation_factors,
            final_train_labels,
            final_validation_labels,
        )

    if not evaluations:
        raise FactorDataBlockedError("no evaluable factor slices were produced")

    p_values = {
        _evaluation_key(evaluation): evaluation.p_value
        for evaluation in evaluations
        if np.isfinite(evaluation.p_value)
    }
    bh_details = benjamini_hochberg_details(p_values, alpha=config.bh_alpha)
    bh_decisions = {name: decision.rejected_null for name, decision in bh_details.items()}

    train_factor_frame = pd.concat(final_train_factors, ignore_index=True)
    validation_factor_frame = pd.concat(final_validation_factors, ignore_index=True)
    train_label = pd.concat(final_train_labels, ignore_index=True)
    validation_label = pd.concat(final_validation_labels, ignore_index=True)
    scores = _inner_validation_scores(evaluations)
    cluster_result = cluster_redundant_factors(
        train_factor_frame,
        distance_threshold=config.redundancy_distance,
        inner_validation_scores=scores,
    )
    incremental_results = _evaluate_incremental_results(
        train_factor_frame,
        validation_factor_frame,
        train_label,
        validation_label,
        cluster_result,
        cost_rate_bps=config.incremental_cost_bps,
    )

    return FactorRunResult(
        run_id=run_id,
        status="completed",
        evaluations=evaluations,
        multiple_testing=bh_decisions,
        multiple_testing_details=bh_details,
        cluster_result=cluster_result,
        incremental_results=incremental_results,
    )


def _validate_frame(
    config: FactorRunConfig,
    data: pd.DataFrame,
    factor_functions: dict[str, FactorCallable],
) -> pd.DataFrame:
    if not config.dataset_snapshot_id.strip():
        raise FactorDataBlockedError("dataset_snapshot_id must be explicit")
    if not config.code_sha.strip():
        raise FactorDataBlockedError("code_sha must be explicit")
    if not config.factor_specs:
        raise FactorDataBlockedError("at least one factor spec is required")

    required = {"timestamp", "available_time", "asset", "close", "volume"}
    missing = required - set(data.columns)
    if missing:
        raise FactorDataBlockedError(f"data missing required columns: {sorted(missing)}")
    missing_functions = {
        spec.factor_id for spec in config.factor_specs if spec.factor_id not in factor_functions
    }
    if missing_functions:
        raise FactorDataBlockedError(f"factor functions missing: {sorted(missing_functions)}")

    frame = data.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame["available_time"] = pd.to_datetime(frame["available_time"], utc=True, errors="coerce")
    if frame[["timestamp", "available_time"]].isna().any().any():
        raise FactorDataBlockedError("timestamps must be valid and timezone-aware")
    if (frame["available_time"] > frame["timestamp"]).any():
        raise FactorDataBlockedError("available_time cannot follow the factor decision timestamp")
    if frame.duplicated(["asset", "available_time"]).any():
        raise FactorDataBlockedError("duplicate asset/available_time rows")
    if (pd.to_numeric(frame["close"], errors="coerce") <= 0).any():
        raise FactorDataBlockedError("close must be positive")
    if (pd.to_numeric(frame["volume"], errors="coerce") < 0).any():
        raise FactorDataBlockedError("volume must be non-negative")
    frame["close"] = pd.to_numeric(frame["close"], errors="raise")
    frame["volume"] = pd.to_numeric(frame["volume"], errors="raise")
    return frame.sort_values(["asset", "available_time"]).reset_index(drop=True)


def _register_specs(registry: FactorRegistry, specs: list[FactorSpec], *, code_sha: str) -> None:
    for spec in specs:
        try:
            registered = registry.get(spec.factor_id, spec.version)
        except KeyError:
            registry.register(spec, code_sha=code_sha)
            continue
        if registered != spec:
            raise ValueError(f"registered spec differs for {spec.factor_id}@{spec.version}")


def _compute_factors(
    frame: pd.DataFrame,
    specs: list[FactorSpec],
    factor_functions: dict[str, FactorCallable],
) -> pd.DataFrame:
    computed = pd.DataFrame(index=frame.index)
    for spec in specs:
        values = factor_functions[spec.factor_id](frame)
        if len(values) != len(frame) or not values.index.equals(frame.index):
            raise ValueError(f"factor {spec.factor_id} did not preserve input index alignment")
        computed[spec.factor_id] = values.astype(float)
    return computed


def _create_splits(
    row_count: int, split_config: dict[str, Any]
) -> dict[str, tuple[NDArray[np.int_], NDArray[np.int_]]]:
    n_folds = int(split_config.get("n_folds", 3))
    train_ratio = float(split_config.get("train_ratio", 0.6))
    purge_bars = int(split_config.get("purge_bars", 6))
    if n_folds <= 0 or not 0.0 < train_ratio < 1.0 or purge_bars < 0:
        raise ValueError("invalid split configuration")

    fold_size = row_count // (n_folds + 1)
    splits: dict[str, tuple[NDArray[np.int_], NDArray[np.int_]]] = {}
    for fold_number in range(n_folds):
        train_end = fold_size * (fold_number + 1)
        test_start = train_end + purge_bars
        test_end = min(test_start + fold_size, row_count)
        if test_start < row_count and test_end > test_start:
            splits[f"fold_{fold_number}"] = (
                np.arange(0, train_end, dtype=np.int_),
                np.arange(test_start, test_end, dtype=np.int_),
            )
    if not splits:
        split_at = int(row_count * train_ratio)
        test_start = split_at + purge_bars
        if test_start >= row_count:
            raise FactorDataBlockedError("split leaves no validation rows")
        splits["fold_0"] = (
            np.arange(0, split_at, dtype=np.int_),
            np.arange(test_start, row_count, dtype=np.int_),
        )
    return splits


def _final_fold_frames(
    splits: dict[str, tuple[NDArray[np.int_], NDArray[np.int_]]],
    factor_values: pd.DataFrame,
    label: pd.Series,
    train_frames: list[pd.DataFrame],
    validation_frames: list[pd.DataFrame],
    train_labels: list[pd.Series],
    validation_labels: list[pd.Series],
) -> None:
    final_fold = list(splits.values())[-1]
    train_idx, validation_idx = final_fold
    train_frames.append(factor_values.iloc[train_idx].reset_index(drop=True))
    validation_frames.append(factor_values.iloc[validation_idx].reset_index(drop=True))
    train_labels.append(label.iloc[train_idx].reset_index(drop=True))
    validation_labels.append(label.iloc[validation_idx].reset_index(drop=True))


def _inner_validation_scores(
    evaluations: list[FactorEvaluation],
) -> dict[str, float]:
    scores: dict[str, list[float]] = {}
    for evaluation in evaluations:
        if np.isfinite(evaluation.spearman_ic):
            scores.setdefault(evaluation.factor_name, []).append(abs(evaluation.spearman_ic))
    return {name: float(np.mean(values)) for name, values in scores.items() if values}


def _evaluate_incremental_results(
    train_factors: pd.DataFrame,
    validation_factors: pd.DataFrame,
    train_label: pd.Series,
    validation_label: pd.Series,
    cluster_result: ClusterResult,
    *,
    cost_rate_bps: float,
) -> list[IncrementalResult]:
    representatives = set(cluster_result.representatives.values())
    results: list[IncrementalResult] = []
    for factor_name in train_factors.columns:
        baseline_names = sorted(representatives - {str(factor_name)})
        results.append(
            evaluate_incremental_contribution(
                train_factors[str(factor_name)],
                train_factors[baseline_names],
                train_label,
                factor_name=str(factor_name),
                validation_candidate_factor=validation_factors[str(factor_name)],
                validation_baseline_factors=validation_factors[baseline_names],
                validation_label=validation_label,
                cost_rate_bps=cost_rate_bps,
            )
        )
    return results


def _transition_completed_factors(
    registry: FactorRegistry,
    specs: list[FactorSpec],
    result: FactorRunResult,
) -> None:
    evaluated = {evaluation.factor_name for evaluation in result.evaluations}
    for spec in specs:
        if (
            spec.factor_id in evaluated
            and registry.state(spec.factor_id, spec.version) == FactorState.RESEARCHING
        ):
            registry.transition(
                spec.factor_id,
                spec.version,
                FactorState.OBSERVED,
                evidence_run_id=result.run_id,
            )


def _evaluation_key(evaluation: FactorEvaluation) -> str:
    return f"{evaluation.factor_name}@{evaluation.fold}:{evaluation.asset}:{evaluation.regime}"


def _manifest_config(config: FactorRunConfig) -> dict[str, Any]:
    return {
        "factor_specs": [spec.model_dump(mode="json") for spec in config.factor_specs],
        "split_config": config.split_config,
        "bh_alpha": config.bh_alpha,
        "redundancy_distance": config.redundancy_distance,
        "incremental_cost_bps": config.incremental_cost_bps,
    }


def _persist_result(config: FactorRunConfig, result: FactorRunResult) -> Path:
    artifact_path = Path(config.artifact_dir) / f"{result.run_id}.json"
    payload: dict[str, Any] = {
        "run_id": result.run_id,
        "status": result.status,
        "dataset_snapshot_id": config.dataset_snapshot_id,
        "code_sha": config.code_sha,
        "seed": config.seed,
        "split_config": config.split_config,
        "error": result.error,
        "evaluations": [asdict(evaluation) for evaluation in result.evaluations],
        "multiple_testing": {
            name: asdict(decision) for name, decision in result.multiple_testing_details.items()
        },
        "redundancy": (
            asdict(result.cluster_result) if result.cluster_result is not None else None
        ),
        "incremental_contribution": [
            asdict(incremental) for incremental in result.incremental_results
        ],
        "lifecycle_states": result.lifecycle_states,
    }
    artifact_path.write_text(
        json.dumps(_json_safe(payload), indent=2, sort_keys=True, allow_nan=False),
        encoding="utf-8",
    )
    return artifact_path


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
