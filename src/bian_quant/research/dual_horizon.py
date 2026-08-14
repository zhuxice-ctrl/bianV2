"""Development-only dual-horizon factor screening and lifecycle gates."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
import pandas as pd

from bian_quant.factors.dual_horizon import (
    FACTOR_COLUMNS,
    compute_dual_horizon_factor_columns,
    dual_horizon_factor_specs,
)
from bian_quant.factors.evaluate import (
    MIN_INFERENCE_SAMPLES,
    FactorEvaluation,
    evaluate_factor,
)
from bian_quant.factors.generator import CandidateFactor, generate_candidates
from bian_quant.factors.labels import forward_log_return
from bian_quant.factors.multiple_testing import BHDecision, benjamini_hochberg_details
from bian_quant.factors.primitives import evaluate_node
from bian_quant.factors.redundancy import (
    ClusterResult,
    IncrementalResult,
    cluster_redundant_factors,
    evaluate_incremental_contribution,
)
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorSpec, FactorState
from bian_quant.regimes.classifier import REGIME_LABELS, classify_regime, fit_regime_thresholds
from bian_quant.validation.splits import TimeFold, anchored_walk_forward

OI_DELAYS = (5, 10, 15)


@dataclass
class DualHorizonScreeningResult:
    """Immutable-evidence result of development-only factor screening."""

    engineering_status: str
    candidate_factor_ids: tuple[str, ...] = ()
    factor_evaluations: list[dict[str, Any]] = field(default_factory=list)
    artifact_path: Path | None = None
    lifecycle_artifact_path: Path | None = None
    gate_reasons: dict[str, list[str]] = field(default_factory=dict)
    factor_diagnostics: dict[str, dict[str, Any]] = field(default_factory=dict)
    generated_factor_ids: tuple[str, ...] = ()
    lifecycle_states: dict[str, str] = field(default_factory=dict)


@dataclass
class _AssetContext:
    asset: str
    frame: pd.DataFrame
    label: pd.Series
    folds: list[TimeFold]


def run_dual_horizon_screening(
    frame: pd.DataFrame,
    *,
    config: dict[str, Any] | None = None,
    eligibility_frame: pd.DataFrame | None = None,
) -> DualHorizonScreeningResult:
    """Screen factors without exposing alignment-buffer or holdout rows.

    The input is partitioned before factor computation, regime fitting, split
    creation, candidate generation, redundancy analysis, or model calls. A
    zero-candidate result is a successful completed engineering run.
    """
    settings = dict(config or {})
    if not settings.get("development_start") or not settings.get("development_end"):
        return _blocked("DEVELOPMENT_WINDOW_REQUIRED")
    required = {"asset", "available_time", "close", "volume"}
    missing = required - set(frame.columns)
    if missing:
        return _blocked(f"MISSING_COLUMNS:{','.join(sorted(missing))}")

    start = _aware_timestamp(settings["development_start"], "development_start")
    end = _aware_timestamp(settings["development_end"], "development_end")
    if start >= end:
        return _blocked("INVALID_DEVELOPMENT_WINDOW")
    if float(settings.get("bh_alpha", 0.05)) != 0.05:
        return _blocked("BH_ALPHA_MUST_EQUAL_0_05")

    # Reserve immutable stage names before any registry mutation. The actual
    # exclusive create happens only after completed development evidence exists.
    run_id = str(settings.get("run_id") or f"dual-horizon-{uuid4()}")
    artifact_dir_value = settings.get("artifact_dir")
    artifact_dir = Path(str(artifact_dir_value)) if artifact_dir_value else None
    development_path = artifact_dir / f"{run_id}.development.json" if artifact_dir else None
    lifecycle_path = artifact_dir / f"{run_id}.lifecycle.json" if artifact_dir else None
    for path in (development_path, lifecycle_path):
        if path is not None and path.exists():
            raise FileExistsError(f"factor evidence already exists: {path}")
    if settings.get("factor_registry_path") and development_path is None:
        raise ValueError("factor lifecycle transitions require an artifact_dir")

    source = frame.copy()
    source["available_time"] = pd.to_datetime(source["available_time"], utc=True, errors="coerce")
    if source["available_time"].isna().any():
        return _blocked("INVALID_AVAILABLE_TIME")
    development = source.loc[
        (source["available_time"] >= start) & (source["available_time"] < end)
    ].copy()
    if development.empty:
        return _blocked("EMPTY_DEVELOPMENT_WINDOW")

    if eligibility_frame is not None:
        development = _apply_membership_lineage(development, eligibility_frame)
        if development.empty:
            return _blocked("EMPTY_AFTER_MEMBERSHIP_FILTER")

    # Every auxiliary scenario is also cut at the development boundary before
    # any factor or label operation can observe it.
    sensitivity_source = _development_only_frame(settings.get("sensitivity_frame"), start, end)
    delay_sources = _development_delay_frames(settings.get("oi_delay_frames"), start, end)

    if eligibility_frame is not None:
        if sensitivity_source is not None and not sensitivity_source.empty:
            sensitivity_source = _apply_membership_lineage(sensitivity_source, eligibility_frame)
        for delay_key in list(delay_sources):
            filtered = _apply_membership_lineage(delay_sources[delay_key], eligibility_frame)
            if filtered.empty:
                del delay_sources[delay_key]
            else:
                delay_sources[delay_key] = filtered

    interval = str(settings.get("interval", "4h"))
    development = compute_dual_horizon_factor_columns(development, interval=interval)
    contexts = _build_contexts(development, settings)
    base_specs = list(dual_horizon_factor_specs(interval))
    specs_by_id = {spec.factor_id: spec for spec in base_specs}

    # The interpretable family is always evaluated before generator invocation.
    evaluations = _evaluate_factors(contexts, list(FACTOR_COLUMNS))

    generated = _generate_bounded_candidates(settings)
    generated_specs: list[FactorSpec] = []
    generated_ids: list[str] = []
    for candidate in generated:
        if _append_generated_factor(contexts, candidate):
            spec = _generated_spec(candidate, interval)
            generated_specs.append(spec)
            specs_by_id[spec.factor_id] = spec
            generated_ids.append(spec.factor_id)
    evaluations.extend(_evaluate_factors(contexts, generated_ids))

    factor_names = [*FACTOR_COLUMNS, *generated_ids]
    bh = _bh_family(evaluations, alpha=0.05)
    cluster, incrementals = _development_models(
        contexts,
        factor_names,
        evaluations,
        distance=float(settings.get("redundancy_distance", 0.3)),
    )
    sensitivity = _prepare_sensitivity(sensitivity_source, interval, generated, generated_ids)
    delay_frames = _prepare_delay_factors(delay_sources, interval)
    gate_reasons, diagnostics, candidates = _apply_gates(
        factor_names,
        specs_by_id,
        evaluations,
        bh,
        cluster,
        incrementals,
        sensitivity=sensitivity,
        delay_frames=delay_frames,
        primary=development,
        interval=interval,
    )

    completed_ids = set(factor_names) if any(context.folds for context in contexts) else set()
    planned_states = {
        name: (
            FactorState.CANDIDATE.value
            if name in candidates
            else FactorState.OBSERVED.value
            if name in completed_ids
            else FactorState.RESEARCHING.value
        )
        for name in factor_names
    }
    for name, state in planned_states.items():
        diagnostics[name]["lifecycle_decision"] = state

    code_sha = str(settings.get("code_sha", "unknown"))
    registry_path = settings.get("factor_registry_path")
    registry: FactorRegistry | None = None
    if registry_path:
        registry = FactorRegistry(Path(str(registry_path)))
        _register_specs(registry, [*base_specs, *generated_specs], code_sha=code_sha)

    window_counts = _window_counts(source, start, end, settings)
    development_payload: dict[str, Any] = {
        "run_id": run_id,
        "stage": "completed_development_evidence",
        "status": "completed",
        "code_sha": code_sha,
        "interval": interval,
        "development_window": {"start": start.isoformat(), "end_exclusive": end.isoformat()},
        "window_counts": window_counts,
        "holdout_accessed": False,
        "bh_alpha": 0.05,
        "bh_family_size": len(bh),
        "evaluations": [asdict(result) for result in evaluations],
        "multiple_testing": {key: asdict(value) for key, value in bh.items()},
        "redundancy": asdict(cluster),
        "incremental_returns": {
            name: {str(cost): asdict(value) for cost, value in results.items()}
            for name, results in incrementals.items()
        },
        "gates": gate_reasons,
        "factor_diagnostics": diagnostics,
        "planned_lifecycle_states": planned_states,
        "candidate_factor_ids": candidates,
        "generated_factors": [_generated_payload(item) for item in generated],
        "exclusions": _exclusion_counts(development),
    }

    if development_path is not None:
        _write_exclusive_json(development_path, development_payload)

    lifecycle_states: dict[str, str] = {}
    try:
        if registry is not None:
            _transition_after_evidence(
                registry,
                specs_by_id,
                completed_ids,
                set(candidates),
                evidence_run_id=run_id,
            )
            lifecycle_states = {
                name: registry.state(specs_by_id[name].factor_id, specs_by_id[name].version).value
                for name in factor_names
            }
            assert lifecycle_path is not None
            _write_exclusive_json(
                lifecycle_path,
                {
                    "run_id": run_id,
                    "stage": "lifecycle_transitions",
                    "development_evidence": development_path.name if development_path else None,
                    "states": lifecycle_states,
                    "gates": gate_reasons,
                },
            )
    finally:
        if registry is not None:
            registry.close()

    return DualHorizonScreeningResult(
        engineering_status="passed",
        candidate_factor_ids=tuple(candidates),
        factor_evaluations=_json_safe([asdict(result) for result in evaluations]),
        artifact_path=development_path,
        lifecycle_artifact_path=lifecycle_path if lifecycle_states else None,
        gate_reasons=gate_reasons,
        factor_diagnostics=_json_safe(diagnostics),
        generated_factor_ids=tuple(generated_ids),
        lifecycle_states=lifecycle_states,
    )


def _apply_membership_lineage(frame: pd.DataFrame, eligibility: pd.DataFrame) -> pd.DataFrame:
    """Filter bars to those with valid popular-universe membership.

    Joins by asset and UTC day of *available_time*.  Requires membership
    *selection_time* no later than each bar's *available_time*.  Raises on
    duplicate membership entries for the same asset + UTC day.  Bars whose
    asset is absent from the universe on that day are silently dropped.
    """
    required_cols = {"asset", "selection_time", "rank"}
    missing = required_cols - set(eligibility.columns)
    if missing:
        raise ValueError(f"eligibility_frame missing columns: {','.join(sorted(missing))}")

    work = eligibility.copy()
    work["selection_time"] = pd.to_datetime(work["selection_time"], utc=True, errors="coerce")
    if work["selection_time"].isna().any():
        raise ValueError("eligibility_frame has invalid selection_time values")
    work["membership_day"] = work["selection_time"].dt.tz_convert("UTC").dt.normalize()

    # Fail on duplicate membership for the same asset + UTC day.
    dup_counts = work.groupby(["asset", "membership_day"]).size()
    duplicates = dup_counts[dup_counts > 1]
    if not duplicates.empty:
        raise RuntimeError(
            f"DUPLICATE_MEMBERSHIP: {len(duplicates)} asset-day pairs have multiple entries"
        )

    # Build lookup: (asset, day) -> (selection_time, rank)
    membership_map = {
        (str(row["asset"]), pd.Timestamp(row["membership_day"])): (
            pd.Timestamp(row["selection_time"]),
            int(row["rank"]),
        )
        for _, row in work.iterrows()
    }

    dev = frame.copy()
    dev["bar_day"] = pd.to_datetime(dev["available_time"], utc=True).dt.normalize()

    keep_mask = dev.apply(
        lambda row: (
            (row.asset, row.bar_day) in membership_map
            and membership_map[(row.asset, row.bar_day)][0] <= row.available_time
        ),
        axis=1,
    )
    dev = dev.loc[keep_mask].drop(columns=["bar_day"]).reset_index(drop=True)
    return dev


def _blocked(reason: str) -> DualHorizonScreeningResult:
    return DualHorizonScreeningResult(
        engineering_status="blocked", gate_reasons={"__run__": [reason]}
    )


def _aware_timestamp(value: Any, name: str) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return timestamp.tz_convert("UTC")


def _development_only_frame(
    value: object, start: pd.Timestamp, end: pd.Timestamp
) -> pd.DataFrame | None:
    if not isinstance(value, pd.DataFrame):
        return None
    required = {"asset", "available_time", "close", "volume"}
    if required - set(value.columns):
        return None
    frame = value.copy()
    frame["available_time"] = pd.to_datetime(frame["available_time"], utc=True, errors="coerce")
    return frame.loc[(frame["available_time"] >= start) & (frame["available_time"] < end)].copy()


def _development_delay_frames(
    value: object, start: pd.Timestamp, end: pd.Timestamp
) -> dict[int, pd.DataFrame]:
    if not isinstance(value, dict):
        return {}
    result: dict[int, pd.DataFrame] = {}
    for delay in OI_DELAYS:
        source = value.get(delay, value.get(str(delay)))
        prepared = _development_only_frame(source, start, end)
        if prepared is not None:
            result[delay] = prepared
    return result


def _build_contexts(frame: pd.DataFrame, settings: dict[str, Any]) -> list[_AssetContext]:
    contexts: list[_AssetContext] = []
    fold_count = int(settings.get("n_folds", 3))
    for asset, asset_frame in frame.groupby("asset", sort=True):
        work = asset_frame.sort_values("available_time").reset_index(drop=True)
        folds: list[TimeFold] = []
        if len(work) >= 100:
            index = pd.DatetimeIndex(work["available_time"])
            initial_train = max(60, len(index) // (fold_count + 1))
            test_size = max(30, (len(index) - initial_train) // max(fold_count, 1))
            folds = anchored_walk_forward(
                index,
                initial_train=initial_train,
                test_size=test_size,
                step=test_size,
                label_horizon=1,
                embargo=int(settings.get("embargo_bars", 6)),
            )
        contexts.append(
            _AssetContext(
                asset=str(asset),
                frame=work,
                label=forward_log_return(work["close"], periods=1),
                folds=folds,
            )
        )
    return contexts


def _evaluate_factors(
    contexts: list[_AssetContext], factor_names: list[str]
) -> list[FactorEvaluation]:
    evaluations: list[FactorEvaluation] = []
    for context in contexts:
        index = pd.DatetimeIndex(context.frame["available_time"])
        for fold in context.folds:
            train_positions = index.get_indexer(fold.train)
            test_positions = index.get_indexer(fold.test)
            train = context.frame.iloc[train_positions]
            thresholds = fit_regime_thresholds(train[["close", "volume"]])
            regimes = classify_regime(context.frame[["close", "volume"]], thresholds).iloc[
                test_positions
            ]
            metadata = pd.DataFrame(
                {"asset": context.asset, "regime": regimes.to_numpy()}, index=test_positions
            )
            for name in factor_names:
                if name not in context.frame:
                    continue
                series = context.frame[name].rename(name)
                evaluations.extend(
                    evaluate_factor(
                        series.iloc[test_positions],
                        context.label.iloc[test_positions],
                        metadata,
                        fold=f"fold_{fold.number}",
                        train_factor=series.iloc[train_positions],
                    )
                )
    return evaluations


def _generate_bounded_candidates(settings: dict[str, Any]) -> list[CandidateFactor]:
    default_path = Path(__file__).resolve().parents[3] / "configs" / "factors" / "search_space.yaml"
    path = Path(str(settings.get("generator_config_path", default_path)))
    generated = generate_candidates(path, code_sha=str(settings.get("code_sha", "unknown")))
    limit = min(int(settings.get("max_candidates", 20)), 20)
    return generated[:limit]


def _append_generated_factor(contexts: list[_AssetContext], candidate: CandidateFactor) -> bool:
    required = set(candidate.expression_tree.required_columns)
    if any(required - set(context.frame.columns) for context in contexts):
        return False
    for context in contexts:
        context.frame[candidate.factor_id] = evaluate_node(candidate.expression_tree, context.frame)
    return True


def _generated_spec(candidate: CandidateFactor, interval: str) -> FactorSpec:
    return FactorSpec(
        factor_id=candidate.factor_id,
        version="0.1.0",
        formula=candidate.expression_hash,
        direction="two_sided",
        hypothesis=(
            "A bounded development-only expression may add stable incremental return evidence"
        ),
        required_columns=sorted(candidate.expression_tree.required_columns),
        horizon=interval,
        missing_policy="preserve",
        winsor_limits=(0.01, 0.99),
        valid_regimes=list(REGIME_LABELS),
        failure_conditions=["fails one or more locked development promotion gates"],
        parent_factors=list(candidate.parent_factors),
    )


def _bh_family(evaluations: list[FactorEvaluation], *, alpha: float) -> dict[str, BHDecision]:
    p_values = {
        _evaluation_key(result): result.p_value
        for result in evaluations
        if np.isfinite(result.p_value)
    }
    return benjamini_hochberg_details(p_values, alpha=alpha)


def _development_models(
    contexts: list[_AssetContext],
    names: list[str],
    evaluations: list[FactorEvaluation],
    *,
    distance: float,
) -> tuple[ClusterResult, dict[str, dict[int, IncrementalResult]]]:
    train_frames: list[pd.DataFrame] = []
    test_frames: list[pd.DataFrame] = []
    train_labels: list[pd.Series] = []
    test_labels: list[pd.Series] = []
    for context in contexts:
        if not context.folds:
            continue
        index = pd.DatetimeIndex(context.frame["available_time"])
        fold = context.folds[-1]
        train_positions = index.get_indexer(fold.train)
        test_positions = index.get_indexer(fold.test)
        train_frames.append(context.frame[names].iloc[train_positions].reset_index(drop=True))
        test_frames.append(context.frame[names].iloc[test_positions].reset_index(drop=True))
        train_labels.append(context.label.iloc[train_positions].reset_index(drop=True))
        test_labels.append(context.label.iloc[test_positions].reset_index(drop=True))
    if not train_frames:
        return ClusterResult({}, {}, {}), {}
    train = pd.concat(train_frames, ignore_index=True)
    test = pd.concat(test_frames, ignore_index=True)
    train_label = pd.concat(train_labels, ignore_index=True)
    test_label = pd.concat(test_labels, ignore_index=True)
    usable = [name for name in names if train[name].notna().any() and test[name].notna().any()]
    if not usable:
        return ClusterResult({}, {}, {}), {}
    scores: dict[str, float] = {}
    for name in usable:
        values = [
            abs(result.spearman_ic)
            for result in evaluations
            if result.factor_name == name and np.isfinite(result.spearman_ic)
        ]
        if values:
            scores[name] = float(np.mean(values))
    cluster = cluster_redundant_factors(
        train[usable], distance_threshold=distance, inner_validation_scores=scores
    )
    representatives = set(cluster.representatives.values())
    incrementals: dict[str, dict[int, IncrementalResult]] = {}
    for name in usable:
        baseline = sorted(representatives - {name})
        incrementals[name] = {
            cost: evaluate_incremental_contribution(
                train[name],
                train[baseline],
                train_label,
                factor_name=name,
                validation_candidate_factor=test[name],
                validation_baseline_factors=test[baseline],
                validation_label=test_label,
                cost_rate_bps=float(cost),
            )
            for cost in (5, 10)
        }
    return cluster, incrementals


def _prepare_sensitivity(
    source: pd.DataFrame | None,
    primary_interval: str,
    generated: list[CandidateFactor],
    generated_ids: list[str],
) -> pd.DataFrame | None:
    if primary_interval != "4h" or source is None or source.empty:
        return None
    frame = compute_dual_horizon_factor_columns(source, interval="1h")
    generated_by_id = {item.factor_id: item for item in generated}
    for name in generated_ids:
        candidate = generated_by_id[name]
        if set(candidate.expression_tree.required_columns) <= set(frame.columns):
            values: list[pd.DataFrame] = []
            for _asset, asset_frame in frame.groupby("asset", sort=True):
                work = asset_frame.copy()
                work[name] = evaluate_node(candidate.expression_tree, work)
                values.append(work)
            frame = pd.concat(values, ignore_index=True)
    return frame


def _prepare_delay_factors(
    sources: dict[int, pd.DataFrame], interval: str
) -> dict[int, pd.DataFrame]:
    return {
        delay: compute_dual_horizon_factor_columns(frame, interval=interval)
        for delay, frame in sources.items()
    }


def _apply_gates(
    names: list[str],
    specs: dict[str, FactorSpec],
    evaluations: list[FactorEvaluation],
    bh: dict[str, BHDecision],
    cluster: ClusterResult,
    incrementals: dict[str, dict[int, IncrementalResult]],
    *,
    sensitivity: pd.DataFrame | None,
    delay_frames: dict[int, pd.DataFrame],
    primary: pd.DataFrame,
    interval: str,
) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]], list[str]]:
    representatives = set(cluster.representatives.values())
    gates: dict[str, list[str]] = {}
    diagnostics: dict[str, dict[str, Any]] = {}
    candidates: list[str] = []
    for name in names:
        eligible = [
            result
            for result in evaluations
            if result.factor_name == name
            and result.sample_count >= MIN_INFERENCE_SAMPLES
            and np.isfinite(result.spearman_ic)
        ]
        survivors = [
            result
            for result in eligible
            if (decision := bh.get(_evaluation_key(result))) and decision.rejected_null
        ]
        target = _target_direction(specs[name], eligible)
        consistent = [result for result in eligible if np.sign(result.spearman_ic) == target]
        supported = [result for result in survivors if np.sign(result.spearman_ic) == target]
        direction_ratio = len(consistent) / len(eligible) if eligible else 0.0
        asset_share = _max_share([result.asset for result in supported])
        regime_share = _max_share([result.regime for result in supported])
        returns = incrementals.get(name, {})
        return_5 = returns.get(5)
        return_10 = returns.get(10)
        five_value = return_5.delta_cost_adjusted_return if return_5 else float("nan")
        ten_value = return_10.delta_cost_adjusted_return if return_10 else float("nan")
        sensitivity_direction = (
            _factor_direction(sensitivity, name)
            if sensitivity is not None and name in sensitivity
            else 0.0
        )
        delay_directions = _delay_directions(primary, delay_frames, name)

        reasons: list[str] = []
        if len(survivors) < 2:
            reasons.append("BH_SURVIVING_SLICES_LT_2")
        if len({(r.fold, r.asset, r.regime) for r in survivors}) < 2:
            reasons.append("INDEPENDENT_SLICES_LT_2")
        if direction_ratio < 0.6:
            reasons.append("DIRECTION_AGREEMENT_LT_60PCT")
        if len({result.asset for result in survivors}) < 2:
            reasons.append("ASSETS_LT_2")
        if name not in representatives:
            reasons.append("REDUNDANT_NON_REPRESENTATIVE")
        if not np.isfinite(five_value) or five_value <= 0:
            reasons.append("FINAL_FOLD_5BPS_NON_POSITIVE")
        if not np.isfinite(ten_value) or ten_value < 0:
            reasons.append("TEN_BPS_NEGATIVE")
        if asset_share > 0.5:
            reasons.append("ASSET_SUPPORT_CONCENTRATION_GT_50PCT")
        if regime_share > 0.5:
            reasons.append("REGIME_SUPPORT_CONCENTRATION_GT_50PCT")
        if interval == "4h" and sensitivity_direction == 0:
            reasons.append("ONE_HOUR_SENSITIVITY_UNAVAILABLE")
        elif interval == "4h" and sensitivity_direction != target:
            reasons.append("ONE_HOUR_DIRECTION_UNSTABLE")
        if name in {"oi_change", "leverage_crowding"}:
            if set(delay_directions) != set(OI_DELAYS):
                reasons.append("OI_DELAY_STABILITY_UNAVAILABLE")
            elif any(value == 0 or value != target for value in delay_directions.values()):
                reasons.append("OI_DELAY_DIRECTION_UNSTABLE")

        gates[name] = reasons or ["ALL_DEVELOPMENT_GATES_PASSED"]
        diagnostics[name] = {
            "eligible_slice_count": len(eligible),
            "bh_survivors": [_evaluation_key(result) for result in survivors],
            "direction_consistent_slice_count": len(consistent),
            "direction_agreement": direction_ratio,
            "target_direction": target,
            "asset_coverage": sorted({result.asset for result in survivors}),
            "redundancy_representative": name in representatives,
            "final_fold_incremental_return_5bps": five_value,
            "final_fold_incremental_return_10bps": ten_value,
            "asset_support_concentration": asset_share,
            "regime_support_concentration": regime_share,
            "oi_delay_directions": delay_directions,
            "one_hour_direction": sensitivity_direction,
            "exclusion_evidence": _factor_exclusion_counts(primary, name),
            "reason_codes": gates[name],
        }
        if not reasons:
            candidates.append(name)
    return gates, diagnostics, candidates


def _target_direction(spec: FactorSpec, eligible: list[FactorEvaluation]) -> float:
    if spec.direction == "positive":
        return 1.0
    if spec.direction == "negative":
        return -1.0
    signs = [np.sign(result.spearman_ic) for result in eligible if result.spearman_ic != 0]
    if not signs:
        return 0.0
    return 1.0 if sum(sign > 0 for sign in signs) >= len(signs) / 2 else -1.0


def _delay_directions(
    primary: pd.DataFrame, delay_frames: dict[int, pd.DataFrame], name: str
) -> dict[int, float]:
    result: dict[int, float] = {}
    for delay in OI_DELAYS:
        if delay in delay_frames and name in delay_frames[delay]:
            result[delay] = _factor_direction(delay_frames[delay], name)
        elif f"{name}_delay_{delay}" in primary:
            result[delay] = _factor_direction(primary, f"{name}_delay_{delay}")
    return result


def _factor_direction(frame: pd.DataFrame, name: str) -> float:
    correlations: list[float] = []
    for _asset, asset_frame in frame.groupby("asset", sort=True):
        work = asset_frame.sort_values("available_time")
        value = work[name].corr(forward_log_return(work["close"], periods=1))
        if np.isfinite(value):
            correlations.append(float(value))
    return float(np.sign(np.median(correlations))) if correlations else 0.0


def _max_share(values: list[str]) -> float:
    if not values:
        return 1.0
    counts = pd.Series(values).value_counts()
    return float(counts.iloc[0] / len(values))


def _evaluation_key(result: FactorEvaluation) -> str:
    return f"{result.factor_name}@{result.fold}:{result.asset}:{result.regime}"


def _register_specs(registry: FactorRegistry, specs: list[FactorSpec], *, code_sha: str) -> None:
    for spec in specs:
        try:
            registered = registry.get(spec.factor_id, spec.version)
        except KeyError:
            registry.register(spec, code_sha=code_sha)
            continue
        if registered != spec:
            raise ValueError(f"registered spec differs for {spec.factor_id}@{spec.version}")


def _transition_after_evidence(
    registry: FactorRegistry,
    specs: dict[str, FactorSpec],
    completed: set[str],
    candidates: set[str],
    *,
    evidence_run_id: str,
) -> None:
    for name in completed:
        spec = specs[name]
        if registry.state(spec.factor_id, spec.version) == FactorState.RESEARCHING:
            registry.transition(
                spec.factor_id,
                spec.version,
                FactorState.OBSERVED,
                evidence_run_id=evidence_run_id,
            )
        if (
            name in candidates
            and registry.state(spec.factor_id, spec.version) == FactorState.OBSERVED
        ):
            registry.transition(
                spec.factor_id,
                spec.version,
                FactorState.CANDIDATE,
                evidence_run_id=evidence_run_id,
            )


def _window_counts(
    source: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, settings: dict[str, Any]
) -> dict[str, int]:
    times = source["available_time"]
    result = {"input": len(source), "development": int(((times >= start) & (times < end)).sum())}
    holdout_start_value = settings.get("holdout_start")
    holdout_end_value = settings.get("holdout_end")
    if holdout_start_value and holdout_end_value:
        holdout_start = _aware_timestamp(holdout_start_value, "holdout_start")
        holdout_end = _aware_timestamp(holdout_end_value, "holdout_end")
        result["alignment_buffer_excluded"] = int(((times >= end) & (times < holdout_start)).sum())
        result["holdout_excluded"] = int(((times >= holdout_start) & (times <= holdout_end)).sum())
    return result


def _exclusion_counts(frame: pd.DataFrame) -> dict[str, dict[str, int]]:
    result: dict[str, dict[str, int]] = {}
    for column in ("funding_exclusion_reason", "oi_exclusion_reason"):
        if column in frame:
            result[column] = {
                str(reason): int(count)
                for reason, count in frame[column].dropna().value_counts().items()
            }
    return result


def _factor_exclusion_counts(frame: pd.DataFrame, name: str) -> dict[str, dict[str, int]]:
    columns: list[str] = []
    if name in {"funding_zscore", "leverage_crowding"}:
        columns.append("funding_exclusion_reason")
    if name in {"oi_change", "leverage_crowding"}:
        columns.append("oi_exclusion_reason")
    if name == "relative_funding_pressure":
        columns.append("relative_funding_pressure_exclusion_reason")
    return {
        column: {
            str(reason): int(count)
            for reason, count in frame[column].dropna().value_counts().items()
        }
        for column in columns
        if column in frame
    }


def _generated_payload(candidate: CandidateFactor) -> dict[str, Any]:
    return {
        "factor_id": candidate.factor_id,
        "expression_hash": candidate.expression_hash,
        "search_manifest_hash": candidate.search_manifest_hash,
        "generation_rank": candidate.generation_rank,
        "parent_factors": list(candidate.parent_factors),
        "required_lookback": candidate.required_lookback,
        "code_sha": candidate.code_sha,
    }


def _write_exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            json.dump(_json_safe(payload), handle, indent=2, sort_keys=True, allow_nan=False)
    except FileExistsError as error:
        raise FileExistsError(f"factor evidence already exists: {path}") from error


def _json_safe(value: Any) -> Any:
    if isinstance(value, float) and not np.isfinite(value):
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value
