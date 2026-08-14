"""Operator boundaries for cataloged analysis and one-time holdout access."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.catalog import CatalogEntry, DatasetCatalog
from bian_quant.data.contracts import DatasetLayer
from bian_quant.experiments.holdout import HoldoutLedger
from bian_quant.experiments.models import LockedHoldout, RunManifest, RunStatus
from bian_quant.experiments.registry import ExperimentRegistry
from bian_quant.factors.dual_horizon import compute_dual_horizon_factor_columns
from bian_quant.factors.labels import forward_log_return
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorSpec, FactorState
from bian_quant.regimes.macro import (
    classify_macro_history,
    macro_evidence_payload,
    render_macro_evidence_markdown,
)
from bian_quant.reporting.decision import DecisionEvidence, write_decision_packet
from bian_quant.research.dual_horizon import run_dual_horizon_screening

REQUIRED_SNAPSHOTS = ("macro-1d", "macro-4h", "micro-1h", "micro-4h")
SNAPSHOT_COLUMNS = (
    "asset",
    "event_time",
    "available_time",
    "open",
    "close",
    "high",
    "low",
    "volume",
    "quote_volume",
    "funding_rate",
    "funding_available_time",
    "funding_interval_hours",
    "sum_open_interest",
    "sum_open_interest_value",
    "oi_available_time",
    "availability_assumption",
)


class AnalysisBlocked(RuntimeError):
    """Stable fail-closed analysis boundary."""


@dataclass(frozen=True)
class CatalogedSnapshots:
    entries: dict[str, CatalogEntry]
    oi_delay_entries: dict[int, CatalogEntry]

    @property
    def snapshot_ids(self) -> tuple[str, ...]:
        return tuple(self.entries[name].manifest.snapshot_id for name in REQUIRED_SNAPSHOTS)


@dataclass(frozen=True)
class CatalogedAnalysisResult:
    run_id: str
    status: str
    artifact_dir: Path
    snapshot_ids: tuple[str, ...]
    candidate_factor_ids: tuple[str, ...]
    error_code: str | None = None


@dataclass(frozen=True)
class HoldoutEvaluationResult:
    run_id: str
    status: str
    factor_state: FactorState
    artifact_path: Path
    reason_codes: tuple[str, ...]


def resolve_dual_horizon_snapshots(
    config: DualHorizonAcquisition, *, code_sha: str
) -> CatalogedSnapshots:
    """Resolve exactly one immutable snapshot for each locked horizon/interval."""
    catalog = DatasetCatalog(config.catalog_path)
    entries: dict[str, CatalogEntry] = {}
    expected = {
        "assets": list(config.assets),
        "macro_start": config.macro_start.isoformat(),
        "micro_start": config.micro_start.isoformat(),
        "as_of": config.as_of.isoformat(),
        "code_sha": code_sha,
    }
    for name in REQUIRED_SNAPSHOTS:
        matches: list[CatalogEntry] = []
        for entry in catalog.find_by_name(name):
            try:
                identity = json.loads(entry.manifest.config_json)
            except json.JSONDecodeError as error:
                raise AnalysisBlocked(f"SNAPSHOT_CONFIG_INVALID:{name}") from error
            if all(identity.get(key) == value for key, value in expected.items()):
                matches.append(entry)
        if not matches:
            raise AnalysisBlocked(f"SNAPSHOT_MISSING:{name}")
        if len(matches) != 1:
            raise AnalysisBlocked(f"SNAPSHOT_AMBIGUOUS:{name}")
        entry = matches[0]
        if entry.manifest.layer != DatasetLayer.RESEARCH:
            raise AnalysisBlocked(f"SNAPSHOT_LAYER_INVALID:{name}")
        if not entry.path.is_file():
            raise AnalysisBlocked(f"SNAPSHOT_FILE_MISSING:{name}")
        entries[name] = entry

    parent_sets = {tuple(entry.manifest.parent_snapshot_ids) for entry in entries.values()}
    if len(parent_sets) != 1 or not next(iter(parent_sets)):
        raise AnalysisBlocked("SNAPSHOT_LINEAGE_INVALID")
    delay_entries = _resolve_delay_entries(
        config,
        required_parent_ids={entry.manifest.snapshot_id for entry in entries.values()},
    )
    return CatalogedSnapshots(entries=entries, oi_delay_entries=delay_entries)


def analyze_cataloged_dual_horizon(
    config: DualHorizonAcquisition, *, code_sha: str
) -> CatalogedAnalysisResult:
    """Run Macro and development screening from validated catalog snapshots."""
    snapshots: CatalogedSnapshots | None = None
    manifest: RunManifest | None = None
    acquisition: dict[str, Any] = {}
    quality: dict[str, Any] = {}
    try:
        snapshots = resolve_dual_horizon_snapshots(config, code_sha=code_sha)
        acquisition, quality = _load_acquisition_evidence(
            config,
            code_sha=code_sha,
            required_snapshot_ids=snapshots.snapshot_ids,
        )
        if acquisition.get("status") != "passed" or quality.get("status") != "passed":
            raise AnalysisBlocked("SOURCE_RUN_BLOCKED")
        eligibility_frame, universe_artifact_ids = _load_popular_universe_eligibility(
            snapshots, config
        )
        manifest = RunManifest.create(
            strategy_name="dual_horizon_analysis",
            code_sha=code_sha,
            dataset_snapshot_ids=list(snapshots.snapshot_ids),
            config={
                "as_of": config.as_of.isoformat(),
                "snapshot_names": REQUIRED_SNAPSHOTS,
                "popular_universe_artifact_ids": universe_artifact_ids,
            },
            seed=0,
            locked_holdout=LockedHoldout(
                start=config.factor_protocol.holdout_start,
                end=config.factor_protocol.holdout_end,
            ),
        )
        _start_run(config, manifest)

        frames = {name: _read_snapshot(entry) for name, entry in snapshots.entries.items()}
        if any(frame.empty for frame in frames.values()):
            raise AnalysisBlocked("SNAPSHOT_EMPTY")

        macro_source = frames["macro-4h"].copy()
        macro_source["event_time"] = pd.to_datetime(macro_source["event_time"], utc=True)
        macro_frame = (
            macro_source.groupby("event_time", as_index=False)
            .agg(close=("close", "mean"), volume=("volume", "sum"))
            .sort_values("event_time")
            .reset_index(drop=True)
        )
        initial_train = max(60, min(365, len(macro_frame) // 3))
        if len(macro_frame) <= initial_train:
            raise AnalysisBlocked("MACRO_INSUFFICIENT_ROWS")
        macro = classify_macro_history(macro_frame, initial_train=initial_train, refit_every=30)
        macro_payload = macro_evidence_payload(macro)
        macro_payload["snapshot_ids"] = [
            snapshots.entries["macro-1d"].manifest.snapshot_id,
            snapshots.entries["macro-4h"].manifest.snapshot_id,
        ]

        stage_dir = config.artifact_root / "factor-stages"
        screening = run_dual_horizon_screening(
            frames["micro-4h"],
            eligibility_frame=eligibility_frame,
            config={
                "run_id": manifest.run_id,
                "artifact_dir": stage_dir,
                "factor_registry_path": config.factor_registry_path,
                "code_sha": code_sha,
                "development_start": config.factor_protocol.development_start,
                "development_end": config.factor_protocol.development_end_exclusive,
                "holdout_start": config.factor_protocol.holdout_start,
                "holdout_end": config.factor_protocol.holdout_end,
                "interval": "4h",
                "sensitivity_frame": frames["micro-1h"],
                "oi_delay_frames": _build_delay_factor_frames(
                    frames["micro-4h"], snapshots.oi_delay_entries
                ),
                "bh_alpha": config.factor_protocol.bh_alpha,
                "max_candidates": config.factor_protocol.max_candidates,
            },
        )
        if screening.engineering_status != "passed" or screening.artifact_path is None:
            raise AnalysisBlocked("FACTOR_SCREENING_BLOCKED")
        screening_payload = json.loads(screening.artifact_path.read_text(encoding="utf-8"))
        screening_payload["snapshot_ids"] = [
            snapshots.entries["micro-1h"].manifest.snapshot_id,
            snapshots.entries["micro-4h"].manifest.snapshot_id,
        ]
        candidates = screening.candidate_factor_ids
        states = screening.lifecycle_states
        evidence = DecisionEvidence(
            acquisition=acquisition,
            quality=quality,
            macro_regime=macro_payload,
            macro_regime_md=render_macro_evidence_markdown(macro),
            factor_screening=screening_payload,
            factor_screening_md=_render_factor_screening(screening_payload),
            engineering_status="PASSED",
            data_status="COMPLETE",
            factor_status="CANDIDATES_PENDING_HOLDOUT" if candidates else "NO_PROMOTION",
            human_decision="REVIEW_CANDIDATES" if candidates else "NONE_REQUIRED",
            candidate_factor_ids=candidates,
            current_regime=macro.current.label,
            passed_factors=list(candidates),
            failed_factors=sorted(
                name
                for name, reasons in screening.gate_reasons.items()
                if reasons != ["ALL_DEVELOPMENT_GATES_PASSED"]
            ),
            observed_factors=sorted(
                name for name, state in states.items() if state == FactorState.OBSERVED.value
            ),
        )
        run_dir = config.artifact_root / manifest.run_id
        write_decision_packet(evidence, run_dir)
        _finish_run(config, manifest.run_id, RunStatus.PASSED)
        return CatalogedAnalysisResult(
            run_id=manifest.run_id,
            status="passed",
            artifact_dir=run_dir,
            snapshot_ids=snapshots.snapshot_ids,
            candidate_factor_ids=candidates,
        )
    except Exception as error:
        reason = str(error) if isinstance(error, AnalysisBlocked) else f"ANALYSIS_FAILED:{error}"
        if manifest is None:
            snapshot_ids = list(snapshots.snapshot_ids) if snapshots is not None else []
            manifest = _blocked_manifest(config, code_sha=code_sha, snapshot_ids=snapshot_ids)
            _start_run(config, manifest)
        run_dir = config.artifact_root / manifest.run_id
        if not run_dir.exists():
            write_decision_packet(
                DecisionEvidence(
                    acquisition=acquisition or {"status": "blocked", "reason": reason},
                    quality=quality or {"status": "blocked", "findings": [reason]},
                    macro_regime={"status": "blocked", "reason": reason},
                    macro_regime_md=f"# Macro Regime\n\nBlocked: {reason}",
                    factor_screening={"status": "blocked", "reason": reason},
                    factor_screening_md=f"# Factor Screening\n\nBlocked: {reason}",
                    engineering_status="BLOCKED",
                    data_status="BLOCKED",
                    factor_status="NOT_RUN",
                    human_decision="RESOLVE_BLOCKING_INPUTS",
                ),
                run_dir,
            )
        _finish_run(config, manifest.run_id, RunStatus.BLOCKED)
        return CatalogedAnalysisResult(
            run_id=manifest.run_id,
            status="blocked",
            artifact_dir=run_dir,
            snapshot_ids=tuple(snapshots.snapshot_ids) if snapshots else (),
            candidate_factor_ids=(),
            error_code=reason,
        )


def evaluate_candidate_holdout(
    config: DualHorizonAcquisition,
    *,
    run_id: str,
    factor_id: str,
    factor_version: str,
    snapshot_id: str,
    reader: Callable[[CatalogEntry], pd.DataFrame] | None = None,
    evaluator: Callable[[pd.DataFrame, FactorSpec], tuple[bool, list[str], dict[str, Any]]]
    | None = None,
) -> HoldoutEvaluationResult:
    """Authorize once, then read and evaluate only the locked Micro holdout."""
    reader = reader or _read_snapshot
    evaluator = evaluator or _default_holdout_evaluator
    artifact_path = config.artifact_root / "holdout" / f"{run_id}-{factor_id}-{factor_version}.json"
    if artifact_path.exists():
        raise FileExistsError(f"holdout evidence already exists: {artifact_path}")

    with FactorRegistry(config.factor_registry_path) as factors:
        spec = factors.get(factor_id, factor_version)
        state = factors.state(factor_id, factor_version)
        if state != FactorState.CANDIDATE:
            raise PermissionError("HOLDOUT_ACCESS_DENIED: factor is not Candidate")
        with ExperimentRegistry(config.experiment_registry_path) as experiments:
            parent_run = experiments.get(run_id)
        if (
            parent_run.status != RunStatus.PASSED
            or snapshot_id not in parent_run.dataset_snapshot_ids
        ):
            raise PermissionError("HOLDOUT_ACCESS_DENIED: invalid experiment lineage")
        entry = DatasetCatalog(config.catalog_path).get(snapshot_id)
        if entry.manifest.name != "micro-4h" or entry.manifest.layer != DatasetLayer.RESEARCH:
            raise PermissionError("HOLDOUT_ACCESS_DENIED: snapshot is not locked Micro 4h")
        if not entry.path.is_file():
            raise PermissionError("HOLDOUT_ACCESS_DENIED: snapshot file is missing")
        delay_entries = _resolve_delay_entries(
            config,
            required_parent_ids=set(parent_run.dataset_snapshot_ids),
        )

        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        with HoldoutLedger(config.artifact_root / "holdout-access.sqlite") as ledger:
            access = ledger.authorize(
                snapshot_id=snapshot_id,
                factor_id=factor_id,
                factor_version=factor_version,
                factor_state=state,
                access_run_id=run_id,
            )
        try:
            frame = reader(entry)
            times = pd.to_datetime(frame["available_time"], utc=True, errors="coerce")
            holdout = frame.loc[
                (times >= config.factor_protocol.holdout_start)
                & (times <= config.factor_protocol.holdout_end)
            ].copy()
            if holdout.empty:
                raise AnalysisBlocked("HOLDOUT_EMPTY")
            if factor_id in {"oi_change", "leverage_crowding"}:
                delay_frames = _build_delay_factor_frames(frame, delay_entries)
                for delay, delay_frame in delay_frames.items():
                    delay_times = pd.to_datetime(
                        delay_frame["available_time"], utc=True, errors="coerce"
                    )
                    delay_holdout = delay_frame.loc[
                        (delay_times >= config.factor_protocol.holdout_start)
                        & (delay_times <= config.factor_protocol.holdout_end)
                    ].copy()
                    computed = compute_dual_horizon_factor_columns(delay_holdout, interval="4h")
                    values = computed[["asset", "available_time", factor_id]].rename(
                        columns={factor_id: f"{factor_id}_delay_{delay}"}
                    )
                    holdout = holdout.merge(
                        values, on=["asset", "available_time"], how="left", validate="one_to_one"
                    )
            passed, reasons, metrics = evaluator(holdout, spec)
            if not passed and "FACTOR_PROMOTION_REJECTED" not in reasons:
                reasons.insert(0, "FACTOR_PROMOTION_REJECTED")
            holdout_artifact_ids: list[str] = []
            try:
                snapshot_identity = json.loads(entry.manifest.config_json)
                holdout_artifact_ids = snapshot_identity.get("popular_universe_artifact_ids", [])
            except json.JSONDecodeError:
                pass
            payload = {
                "run_id": run_id,
                "snapshot_id": snapshot_id,
                "factor_id": factor_id,
                "factor_version": factor_version,
                "access": access,
                "status": "passed" if passed else "rejected",
                "reason_codes": reasons,
                "metrics": metrics,
                "popular_universe_artifact_ids": holdout_artifact_ids,
            }
            _write_exclusive_json(artifact_path, payload)
            if passed:
                factors.transition(
                    factor_id,
                    factor_version,
                    FactorState.APPROVED,
                    evidence_run_id=run_id,
                )
                final_state = FactorState.APPROVED
            else:
                final_state = FactorState.CANDIDATE
            return HoldoutEvaluationResult(
                run_id=run_id,
                status="passed" if passed else "rejected",
                factor_state=final_state,
                artifact_path=artifact_path,
                reason_codes=tuple(reasons),
            )
        except Exception as error:
            failure_path = (
                artifact_path
                if not artifact_path.exists()
                else artifact_path.with_name(f"{artifact_path.stem}.failure.json")
            )
            _write_exclusive_json(
                failure_path,
                {
                    "run_id": run_id,
                    "snapshot_id": snapshot_id,
                    "factor_id": factor_id,
                    "factor_version": factor_version,
                    "access": access,
                    "status": "failed",
                    "reason_codes": [f"HOLDOUT_EVALUATION_FAILED:{error}"],
                },
            )
            raise


def _load_popular_universe_eligibility(
    snapshots: CatalogedSnapshots, config: DualHorizonAcquisition
) -> tuple[pd.DataFrame | None, list[str]]:
    """Load popular-universe artifacts referenced by snapshot config.

    Returns (eligibility_frame, artifact_ids).  When no artifacts are
    referenced, returns (None, []).
    """
    artifact_ids: list[str] = []
    for entry in snapshots.entries.values():
        try:
            identity = json.loads(entry.manifest.config_json)
        except json.JSONDecodeError:
            continue
        ids = identity.get("popular_universe_artifact_ids", [])
        if ids:
            artifact_ids = ids
            break

    if not artifact_ids:
        return None, []

    artifacts_dir = config.artifact_root / "popular-universe"
    if not artifacts_dir.is_dir():
        raise AnalysisBlocked("POPULAR_UNIVERSE_DIR_MISSING")

    rows: list[dict[str, Any]] = []
    found_ids: set[str] = set()
    for path in sorted(artifacts_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if payload.get("artifact_id") not in artifact_ids:
            continue
        found_ids.add(payload["artifact_id"])
        selection_time = payload["selection_time"]
        for member in payload.get("members", []):
            rows.append(
                {
                    "asset": member["asset"],
                    "selection_time": selection_time,
                    "rank": member["rank"],
                }
            )

    missing = set(artifact_ids) - found_ids
    if missing:
        raise AnalysisBlocked(f"POPULAR_UNIVERSE_ARTIFACT_MISSING:{','.join(sorted(missing))}")

    if not rows:
        return None, artifact_ids
    return pd.DataFrame(rows), artifact_ids


def _read_snapshot(entry: CatalogEntry) -> pd.DataFrame:
    schema = set(pq.ParquetFile(entry.path).schema.names)
    columns = [column for column in SNAPSHOT_COLUMNS if column in schema]
    required = {"asset", "event_time", "available_time", "close", "volume"}
    if not required <= set(columns):
        raise AnalysisBlocked(f"SNAPSHOT_SCHEMA_INVALID:{entry.manifest.name}")
    return pd.read_parquet(entry.path, columns=columns)


def _resolve_delay_entries(
    config: DualHorizonAcquisition,
    *,
    required_parent_ids: set[str],
) -> dict[int, CatalogEntry]:
    catalog_path = config.research_root / "delay_catalog.sqlite"
    if not catalog_path.is_file():
        raise AnalysisBlocked("OI_DELAY_CATALOG_MISSING")
    catalog = DatasetCatalog(catalog_path)
    result: dict[int, CatalogEntry] = {}
    for delay in config.oi_delay_minutes:
        name = f"metrics-oi-delay-{delay}m"
        matches = catalog.find_by_name(name)
        if not matches:
            raise AnalysisBlocked(f"OI_DELAY_SNAPSHOT_MISSING:{delay}")
        lineage_matches = [
            entry
            for entry in matches
            if entry.manifest.layer == DatasetLayer.RESEARCH
            and set(entry.manifest.parent_snapshot_ids) == required_parent_ids
            and entry.path.is_file()
        ]
        if len(lineage_matches) != 1:
            raise AnalysisBlocked(f"OI_DELAY_SNAPSHOT_AMBIGUOUS:{delay}")
        entry = lineage_matches[0]
        result[delay] = entry
    return result


def _build_delay_factor_frames(
    primary: pd.DataFrame,
    entries: dict[int, CatalogEntry],
) -> dict[int, pd.DataFrame]:
    result: dict[int, pd.DataFrame] = {}
    oi_columns = {
        "sum_open_interest",
        "sum_open_interest_value",
        "oi_available_time",
        "availability_assumption",
    }
    for delay, entry in entries.items():
        schema = set(pq.ParquetFile(entry.path).schema.names)
        required = {
            "asset",
            "event_time",
            "available_time",
            "sum_open_interest",
            "sum_open_interest_value",
            "availability_assumption",
        }
        if not required <= schema:
            raise AnalysisBlocked(f"OI_DELAY_SCHEMA_INVALID:{delay}")
        metrics = pd.read_parquet(entry.path, columns=sorted(required))
        assets: list[pd.DataFrame] = []
        for asset, bars in primary.groupby("asset", sort=True):
            left = bars.drop(columns=list(oi_columns), errors="ignore").sort_values(
                "available_time"
            )
            right = metrics.loc[metrics["asset"] == asset].sort_values("available_time")
            if right.empty:
                raise AnalysisBlocked(f"OI_DELAY_ASSET_MISSING:{delay}:{asset}")
            right = right.drop(columns=["asset", "event_time"]).rename(
                columns={"available_time": "oi_available_time"}
            )
            assets.append(
                pd.merge_asof(
                    left,
                    right,
                    left_on="available_time",
                    right_on="oi_available_time",
                    direction="backward",
                    allow_exact_matches=True,
                )
            )
        result[delay] = pd.concat(assets, ignore_index=True).sort_values(
            ["asset", "available_time"]
        )
    return result


def _load_acquisition_evidence(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    required_snapshot_ids: tuple[str, ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        runs = [
            run
            for run in registry.list_runs()
            if run.strategy_name == "dual_horizon_derivatives"
            and run.code_sha == code_sha
            and run.status == RunStatus.PASSED
        ]
    for run in reversed(runs):
        acquisition_path = config.artifact_root / run.run_id / "data-acquisition.json"
        quality_path = config.artifact_root / run.run_id / "data-quality.json"
        if acquisition_path.is_file() and quality_path.is_file():
            acquisition = json.loads(acquisition_path.read_text(encoding="utf-8"))
            quality = json.loads(quality_path.read_text(encoding="utf-8"))
            snapshot_ids = acquisition.get("snapshot_ids", [])
            if (
                isinstance(snapshot_ids, list)
                and len(snapshot_ids) == len(required_snapshot_ids)
                and set(snapshot_ids) == set(required_snapshot_ids)
            ):
                return acquisition, quality
    raise AnalysisBlocked("SOURCE_EVIDENCE_MISSING")


def _start_run(config: DualHorizonAcquisition, manifest: RunManifest) -> None:
    config.experiment_registry_path.parent.mkdir(parents=True, exist_ok=True)
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        registry.create(manifest)
        registry.transition(manifest.run_id, RunStatus.RUNNING)


def _finish_run(config: DualHorizonAcquisition, run_id: str, status: RunStatus) -> None:
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        current = registry.get(run_id)
        if current.status == RunStatus.RUNNING:
            registry.transition(run_id, status)


def _blocked_manifest(
    config: DualHorizonAcquisition, *, code_sha: str, snapshot_ids: list[str]
) -> RunManifest:
    identity = hashlib.sha256(
        json.dumps(
            {"code_sha": code_sha, "snapshot_ids": snapshot_ids, "status": "blocked"},
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    created = RunManifest.create(
        strategy_name="dual_horizon_analysis",
        code_sha=code_sha,
        dataset_snapshot_ids=snapshot_ids or [f"catalog-resolution-{identity[:16]}"],
        config={"as_of": config.as_of.isoformat(), "status": "blocked"},
        seed=0,
        locked_holdout=LockedHoldout(
            start=config.factor_protocol.holdout_start,
            end=config.factor_protocol.holdout_end,
        ),
    )
    return created


def _render_factor_screening(payload: dict[str, Any]) -> str:
    candidates = payload.get("candidate_factor_ids", [])
    lines = [
        "# Factor Screening",
        "",
        f"Engineering status: {payload.get('status', 'unknown')}",
        f"Candidate factors: {len(candidates)}",
        "",
        "## Gate decisions",
        "",
    ]
    for factor, reasons in sorted(payload.get("gates", {}).items()):
        lines.append(f"- **{factor}**: {', '.join(reasons)}")
    return "\n".join(lines)


def _default_holdout_evaluator(
    frame: pd.DataFrame, spec: FactorSpec
) -> tuple[bool, list[str], dict[str, Any]]:
    work = compute_dual_horizon_factor_columns(frame, interval="4h")
    if spec.factor_id not in work:
        return False, ["FACTOR_PROMOTION_REJECTED", "FACTOR_COLUMN_MISSING"], {}
    correlations: dict[str, float] = {}
    returns: dict[str, float] = {}
    for asset, asset_frame in work.groupby("asset", sort=True):
        label = forward_log_return(asset_frame["close"], periods=1)
        correlation = asset_frame[spec.factor_id].corr(label, method="spearman")
        if np.isfinite(correlation):
            correlations[str(asset)] = float(correlation)
            direction = np.sign(correlation)
            returns[str(asset)] = float((direction * label).dropna().mean())
    reasons: list[str] = []
    if len(correlations) < 2:
        reasons.append("HOLDOUT_ASSET_COVERAGE_LT_2")
    target = 1.0 if spec.direction == "positive" else -1.0 if spec.direction == "negative" else 0.0
    if target and any(np.sign(value) != target for value in correlations.values()):
        reasons.append("HOLDOUT_DIRECTION_UNSTABLE")
    support = [asset for asset, value in returns.items() if value > 0]
    if support and 1 / len(support) > 0.5:
        reasons.append("HOLDOUT_ASSET_CONCENTRATION_GT_50PCT")
    mean_return = float(np.mean(list(returns.values()))) if returns else float("nan")
    five_bps = mean_return - 0.0005
    ten_bps = mean_return - 0.001
    if not np.isfinite(five_bps) or five_bps <= 0:
        reasons.append("HOLDOUT_5BPS_NON_POSITIVE")
    if not np.isfinite(ten_bps) or ten_bps < 0:
        reasons.append("HOLDOUT_10BPS_NEGATIVE")
    if spec.factor_id in {"oi_change", "leverage_crowding"}:
        delay_directions: dict[int, float] = {}
        for delay in (5, 10, 15):
            column = f"{spec.factor_id}_delay_{delay}"
            if column not in work:
                continue
            delay_correlations: list[float] = []
            for _asset, asset_frame in work.groupby("asset", sort=True):
                value = asset_frame[column].corr(
                    forward_log_return(asset_frame["close"], periods=1),
                    method="spearman",
                )
                if np.isfinite(value):
                    delay_correlations.append(float(value))
            if delay_correlations:
                delay_directions[delay] = float(np.sign(np.median(delay_correlations)))
        if set(delay_directions) != {5, 10, 15}:
            reasons.append("HOLDOUT_OI_DELAY_STRESS_UNAVAILABLE")
        elif target and any(value != target for value in delay_directions.values()):
            reasons.append("HOLDOUT_OI_DELAY_DIRECTION_UNSTABLE")
    return (
        not reasons,
        reasons or ["ALL_HOLDOUT_GATES_PASSED"],
        {
            "asset_spearman_ic": correlations,
            "asset_mean_return": returns,
            "cost_adjusted_return_5bps": five_bps,
            "cost_adjusted_return_10bps": ten_bps,
        },
    )


def _write_exclusive_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False, default=str)


@dataclass(frozen=True)
class SmallAccountBacktestResult:
    """Result of a 100 USDT portfolio backtest gated on Approved factor."""

    run_id: str
    status: str
    factor_id: str
    factor_version: str
    artifact_path: Path
    trade_count: int
    final_equity: str
    maximum_gross: str
    reason_codes: tuple[str, ...] = ()


def run_small_account_backtest(
    config: DualHorizonAcquisition,
    *,
    factor_id: str,
    factor_version: str,
    snapshot_id: str,
    backtest_config_path: Path,
    run_id: str | None = None,
) -> SmallAccountBacktestResult:
    """Run a 100 USDT portfolio backtest gated on an Approved factor.

    Raises PermissionError if the factor is not in APPROVED state.
    """
    from decimal import Decimal

    from bian_quant.backtest.events import Bar, SignalEvent
    from bian_quant.backtest.portfolio import replay_ranked_portfolio
    from bian_quant.backtest.small_account import ContractRules, SmallAccountLimits

    # Gate: factor must be APPROVED.
    with FactorRegistry(config.factor_registry_path) as factors:
        factors.get(factor_id, factor_version)
        state = factors.state(factor_id, factor_version)
        if state != FactorState.APPROVED:
            raise PermissionError(
                f"BACKTEST_ACCESS_DENIED: factor {factor_id}@{factor_version} "
                f"is {state.value}, not APPROVED"
            )

    # Load locked Micro-4h snapshot.
    entry = DatasetCatalog(config.catalog_path).get(snapshot_id)
    if entry.manifest.name != "micro-4h" or entry.manifest.layer != DatasetLayer.RESEARCH:
        raise PermissionError("BACKTEST_ACCESS_DENIED: snapshot is not locked Micro 4h")
    if not entry.path.is_file():
        raise PermissionError("BACKTEST_ACCESS_DENIED: snapshot file is missing")

    frame = _read_snapshot(entry)
    computed = compute_dual_horizon_factor_columns(frame, interval="4h")
    if factor_id not in computed.columns:
        raise AnalysisBlocked(f"FACTOR_COLUMN_MISSING:{factor_id}")

    limits = SmallAccountLimits.from_yaml(backtest_config_path)

    # Derive per-asset contract rules with conservative defaults.
    contract_rules: dict[str, ContractRules] = {}
    for asset in computed["asset"].unique():
        contract_rules[str(asset)] = ContractRules(
            asset=str(asset),
            min_qty=Decimal("0.001"),
            step_size=Decimal("0.001"),
            min_notional=Decimal("5"),
            tick_size=Decimal("0.01"),
        )

    # Build a single-timeline bar list (one bar per unique timestamp).
    # Use the average close across assets as the representative price.
    timeline = (
        computed.groupby("available_time", as_index=False)
        .agg(
            open=("open", "mean"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "mean"),
            volume=("volume", "sum"),
        )
        .sort_values("available_time")
        .reset_index(drop=True)
    )
    bars: list[Bar] = []
    for row in timeline.to_dict(orient="records"):
        timestamp = pd.Timestamp(row["available_time"]).to_pydatetime()
        bars.append(
            Bar(
                timestamp=timestamp,
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row["volume"])),
            )
        )

    # Generate ranked signals from factor values.
    signals: list[SignalEvent] = []
    for _timestamp, group in computed.groupby("available_time"):
        factor_values = group[[factor_id, "asset", "available_time"]].dropna(subset=[factor_id])
        if factor_values.empty:
            continue
        ranked = factor_values.assign(_abs=factor_values[factor_id].abs()).sort_values(
            "_abs", ascending=False
        )
        for rank, row in enumerate(ranked.to_dict(orient="records"), start=1):
            value = row[factor_id]
            if value == 0:
                continue
            direction = 1 if value > 0 else -1
            timestamp = pd.Timestamp(row["available_time"]).to_pydatetime()
            signals.append(
                SignalEvent(
                    timestamp=timestamp,
                    direction=direction,
                    available_time=timestamp,
                    asset=str(row["asset"]),
                    rank=rank,
                    stop_distance=Decimal("0.02"),
                    target_distance=Decimal("0.04"),
                )
            )

    bt_run_id = run_id or f"backtest-{factor_id}-{factor_version}"
    result = replay_ranked_portfolio(
        bars=bars,
        signals=signals,
        limits=limits,
        contract_rules=contract_rules,
    )

    final_equity = result.equity[-1] if result.equity else limits.initial_equity_usdt
    artifact_path = config.artifact_root / "backtest" / f"{bt_run_id}.json"
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": bt_run_id,
        "factor_id": factor_id,
        "factor_version": factor_version,
        "snapshot_id": snapshot_id,
        "status": "completed",
        "trade_count": len(result.trades),
        "final_equity": str(final_equity),
        "maximum_gross": str(result.maximum_gross),
        "fills": [
            {
                "timestamp": fill.timestamp.isoformat(),
                "direction": fill.direction,
                "exec_price": str(fill.exec_price),
                "notional": str(fill.notional),
                "reason": fill.reason,
            }
            for fill in result.fills
        ],
        "trades": [
            {
                "entry_time": t.entry_time.isoformat(),
                "exit_time": t.exit_time.isoformat(),
                "direction": t.direction,
                "entry_price": str(t.entry_price),
                "exit_price": str(t.exit_price),
                "pnl": str(t.pnl),
                "exit_reason": t.exit_reason,
            }
            for t in result.trades
        ],
        "rejections": result.rejections,
        "pause_events": result.pause_events,
        "daily_attribution": {k: str(v) for k, v in result.daily_attribution.items()},
    }
    with artifact_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, allow_nan=False, default=str)

    return SmallAccountBacktestResult(
        run_id=bt_run_id,
        status="completed",
        factor_id=factor_id,
        factor_version=factor_version,
        artifact_path=artifact_path,
        trade_count=len(result.trades),
        final_equity=str(final_equity),
        maximum_gross=str(result.maximum_gross),
    )
