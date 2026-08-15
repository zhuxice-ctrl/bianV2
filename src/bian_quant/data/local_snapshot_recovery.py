"""Read-only preflight for rebuilding research snapshots from local Canonical data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from pathlib import Path

import pandas as pd

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceObject,
    SourcePlanAudit,
    build_source_plan_audit,
    canonical_input_sources,
    source_plan_hash,
)
from bian_quant.data.catalog import CatalogEntry
from bian_quant.data.contracts import DatasetLayer, DatasetManifest
from bian_quant.data.evidence_cutoff import (
    CutoffEvidence,
    canonical_plan_path,
    clip_to_evidence_cutoff,
)
from bian_quant.data.hashing import dataframe_content_hash
from bian_quant.data.popular_universe_artifacts import (
    PopularUniverseBuildResult,
    build_popular_universe_artifacts,
)
from bian_quant.data.snapshots import (
    build_delay_views,
    build_macro_snapshots,
    build_micro_snapshots,
)
from bian_quant.experiments.models import RunManifest, RunStatus
from bian_quant.experiments.registry import ExperimentRegistry


class LocalSnapshotRecoveryStatus(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    RECOVERED = "recovered"


@dataclass(frozen=True)
class CanonicalRecoveryInput:
    source: SourceObject
    entry: CatalogEntry
    frame: pd.DataFrame
    cutoff: CutoffEvidence


@dataclass(frozen=True)
class LocalSnapshotRecoveryPreflight:
    status: LocalSnapshotRecoveryStatus
    inputs: tuple[CanonicalRecoveryInput, ...]
    parent_snapshot_ids: tuple[str, ...]
    input_set_sha256: str | None
    blocked_reasons: tuple[str, ...]
    excluded_source_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class LocalSnapshotRecoveryResult:
    run_id: str
    status: LocalSnapshotRecoveryStatus
    snapshots: tuple[DatasetManifest, ...]
    delay_snapshot_ids: dict[int, str]
    acquisition_artifact: Path
    quality_artifact: Path
    blocked_reasons: tuple[str, ...]
    excluded_source_ids: tuple[str, ...] = ()

    @property
    def snapshot_ids(self) -> tuple[str, ...]:
        return tuple(item.snapshot_id for item in self.snapshots)


_REQUIRED_COLUMNS: dict[SourceDataset, frozenset[str]] = {
    SourceDataset.OHLCV: frozenset(
        {"asset", "event_time", "available_time", "open", "high", "low", "close", "volume"}
    ),
    SourceDataset.FUNDING: frozenset(
        {
            "asset",
            "event_time",
            "available_time",
            "funding_rate",
            "funding_interval_hours",
        }
    ),
    SourceDataset.METRICS_OI: frozenset(
        {
            "asset",
            "event_time",
            "available_time",
            "sum_open_interest",
            "sum_open_interest_value",
            "availability_assumption",
        }
    ),
}


def _entries_by_name_read_only(path: Path, names: set[str]) -> dict[str, tuple[CatalogEntry, ...]]:
    if not path.is_file():
        return {}
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    placeholders = ",".join("?" for _ in names)
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute(
                "SELECT name, path, manifest_json FROM datasets "
                f"WHERE name IN ({placeholders}) ORDER BY rowid",
                tuple(sorted(names)),
            ).fetchall()
    except sqlite3.Error:
        return {}
    entries: dict[str, list[CatalogEntry]] = {}
    for name, stored_path, manifest_json in rows:
        try:
            manifest = DatasetManifest.model_validate_json(manifest_json)
        except ValueError:
            continue
        entries.setdefault(name, []).append(CatalogEntry(manifest=manifest, path=Path(stored_path)))
    return {name: tuple(value) for name, value in entries.items()}


def _identity(entry: CatalogEntry) -> str | None:
    try:
        payload = json.loads(entry.manifest.config_json)
    except (TypeError, json.JSONDecodeError):
        return None
    value = payload.get("identity_key") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


def _raw_sha256(entry: CatalogEntry) -> str | None:
    try:
        payload = json.loads(entry.manifest.config_json)
    except (TypeError, json.JSONDecodeError):
        return None
    value = payload.get("raw_sha256") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


def _raw_manifest_sha256(config: DualHorizonAcquisition, source: SourceObject) -> str | None:
    manifest_path = config.raw_root / source.relative_path
    manifest_path = manifest_path.with_suffix(f"{manifest_path.suffix}.manifest.json")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    value = payload.get("content_sha256") if isinstance(payload, dict) else None
    return value if isinstance(value, str) else None


def _canonical_input_set_sha(inputs: tuple[CanonicalRecoveryInput, ...]) -> str:
    payload = [
        {
            "content_sha256": item.entry.manifest.content_sha256,
            "identity_key": item.source.identity_key,
            "snapshot_id": item.entry.manifest.snapshot_id,
        }
        for item in inputs
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validate_frame(
    source: SourceObject,
    entry: CatalogEntry,
    frame: pd.DataFrame,
    config: DualHorizonAcquisition,
) -> tuple[CutoffEvidence | None, tuple[str, ...]]:
    reasons: list[str] = []
    required = _REQUIRED_COLUMNS[source.dataset]
    missing = sorted(required - set(frame.columns))
    if missing:
        reasons.append(f"CANONICAL_SCHEMA_INVALID:{source.identity_key}")
        return None, tuple(reasons)
    try:
        content_sha = dataframe_content_hash(frame, sort_by=["asset", "event_time"])
    except (KeyError, TypeError, ValueError):
        content_sha = ""
    if content_sha != entry.manifest.content_sha256:
        reasons.append(f"CANONICAL_CONTENT_HASH_MISMATCH:{entry.manifest.snapshot_id}")
    event_time = pd.to_datetime(frame["event_time"], utc=True, errors="coerce")
    available_time = pd.to_datetime(frame["available_time"], utc=True, errors="coerce")
    if event_time.isna().any() or available_time.isna().any():
        reasons.append(f"CANONICAL_TIME_INVALID:{source.identity_key}")
    elif (available_time < event_time).any():
        reasons.append(f"CANONICAL_CAUSALITY_INVALID:{source.identity_key}")
    cutoff = clip_to_evidence_cutoff(source, frame, as_of=config.as_of).evidence
    if cutoff.post_cutoff_rows_excluded:
        reasons.append(f"CANONICAL_CUTOFF_VIOLATION:{source.identity_key}")
    if not (frame["asset"].astype(str) == source.asset).all():
        reasons.append(f"CANONICAL_ASSET_INVALID:{source.identity_key}")
    if source.granularity.value == "daily":
        period_end = source.period_start + timedelta(days=1)
    elif source.period_start.month == 12:
        period_end = source.period_start.replace(year=source.period_start.year + 1, month=1)
    else:
        period_end = source.period_start.replace(month=source.period_start.month + 1)
    if source.dataset == SourceDataset.METRICS_OI and source.granularity.value == "daily":
        in_period = (event_time >= source.period_start) & (
            event_time <= period_end + timedelta(seconds=1)
        )
    else:
        in_period = (event_time >= source.period_start) & (event_time < period_end)
    if (~in_period).any():
        reasons.append(f"CANONICAL_SOURCE_PERIOD_MISMATCH:{source.identity_key}")
    if frame.duplicated(["asset", "event_time"]).any():
        reasons.append(f"CANONICAL_DUPLICATE:{source.identity_key}")
    if source.dataset == SourceDataset.OHLCV:
        invalid_prices = (
            (frame[["open", "high", "low", "close"]] <= 0).any(axis=1)
            | (frame["volume"] < 0)
            | (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        )
        if invalid_prices.any():
            reasons.append(f"CANONICAL_VALUE_INVALID:{source.identity_key}")
    elif source.dataset == SourceDataset.FUNDING:
        interval = pd.to_numeric(frame["funding_interval_hours"], errors="coerce")
        if interval.isna().any() or not interval.isin([1, 4, 8]).all():
            reasons.append(f"CANONICAL_INTERVAL_INVALID:{source.identity_key}")
    elif (frame["sum_open_interest"] < 0).any() or (frame["sum_open_interest_value"] < 0).any():
        reasons.append(f"CANONICAL_NEGATIVE_OI:{source.identity_key}")
    return cutoff, tuple(reasons)


def _preflight_plan(config: DualHorizonAcquisition) -> SourcePlanAudit:
    return build_source_plan_audit(config)


def _load_canonical_input(
    source: SourceObject,
    entry: CatalogEntry,
    config: DualHorizonAcquisition,
) -> tuple[CanonicalRecoveryInput | None, tuple[str, ...]]:
    if entry.manifest.layer != DatasetLayer.CANONICAL:
        return None, (f"CANONICAL_LAYER_INVALID:{entry.manifest.snapshot_id}",)
    if not entry.path.is_file():
        return None, (f"CANONICAL_FILE_MISSING:{entry.manifest.snapshot_id}",)
    try:
        frame = pd.read_parquet(entry.path)
    except (OSError, ValueError, ImportError) as error:
        return None, (f"CANONICAL_READ_FAILED:{entry.manifest.snapshot_id}:{error}",)
    cutoff, frame_reasons = _validate_frame(source, entry, frame, config)
    if cutoff is None:
        return None, frame_reasons
    return CanonicalRecoveryInput(source, entry, frame, cutoff), frame_reasons


def preflight_local_snapshot_recovery(
    config: DualHorizonAcquisition,
) -> LocalSnapshotRecoveryPreflight:
    """Inspect local Canonical inputs without creating or changing any file."""
    plan = _preflight_plan(config)
    plan_hash = source_plan_hash(plan)
    sources = canonical_input_sources(plan, as_of=config.as_of)
    excluded_source_ids = tuple(sorted(item.identity_key for item in plan.permanent_exclusions))
    reasons: list[str] = []
    inputs: list[CanonicalRecoveryInput] = []
    names = {f"canonical-{source.dataset.value}-{source.interval}" for source in sources}
    entries_by_name = _entries_by_name_read_only(config.catalog_path, names)
    entries_by_identity: dict[tuple[str, str | None, str | None, Path], list[CatalogEntry]] = {}
    for name, entries in entries_by_name.items():
        for entry in entries:
            key = (name, _identity(entry), _raw_sha256(entry), entry.path.resolve())
            entries_by_identity.setdefault(key, []).append(entry)
    selected: list[tuple[SourceObject, CatalogEntry]] = []
    for source in sources:
        name = f"canonical-{source.dataset.value}-{source.interval}"
        raw_sha256 = _raw_manifest_sha256(config, source)
        if raw_sha256 is None:
            reasons.append(f"RAW_LINEAGE_MISSING:{source.identity_key}")
            continue
        expected_path = canonical_plan_path(
            config.canonical_root,
            plan_hash=plan_hash,
            relative_path=source.relative_path,
        ).resolve()
        matches = entries_by_identity.get(
            (name, source.identity_key, raw_sha256, expected_path), []
        )
        if not matches:
            reasons.append(f"CANONICAL_INPUT_MISSING:{source.identity_key}")
            continue
        if len(matches) != 1:
            reasons.append(f"CANONICAL_INPUT_AMBIGUOUS:{source.identity_key}")
            continue
        selected.append((source, matches[0]))
    for source, entry in selected:
        item, item_reasons = _load_canonical_input(source, entry, config)
        reasons.extend(item_reasons)
        if item is not None:
            inputs.append(item)

    ordered_inputs = tuple(sorted(inputs, key=lambda item: item.source.identity_key))
    if reasons:
        return LocalSnapshotRecoveryPreflight(
            status=LocalSnapshotRecoveryStatus.BLOCKED,
            inputs=ordered_inputs,
            parent_snapshot_ids=(),
            input_set_sha256=None,
            blocked_reasons=tuple(sorted(set(reasons))),
            excluded_source_ids=excluded_source_ids,
        )
    parent_ids = tuple(sorted(item.entry.manifest.snapshot_id for item in ordered_inputs))
    if not parent_ids:
        reasons.append("CANONICAL_INPUTS_EMPTY")
        return LocalSnapshotRecoveryPreflight(
            status=LocalSnapshotRecoveryStatus.BLOCKED,
            inputs=(),
            parent_snapshot_ids=(),
            input_set_sha256=None,
            blocked_reasons=tuple(reasons),
            excluded_source_ids=excluded_source_ids,
        )
    return LocalSnapshotRecoveryPreflight(
        status=LocalSnapshotRecoveryStatus.READY,
        inputs=ordered_inputs,
        parent_snapshot_ids=parent_ids,
        input_set_sha256=_canonical_input_set_sha(ordered_inputs),
        blocked_reasons=(),
        excluded_source_ids=excluded_source_ids,
    )


def _write_exclusive_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, sort_keys=True, separators=(",", ":"), default=str)


def _start_recovery_run(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    parent_snapshot_ids: tuple[str, ...],
    input_set_sha256: str | None,
    excluded_source_ids: tuple[str, ...],
) -> RunManifest:
    manifest = RunManifest.create(
        strategy_name="dual_horizon_derivatives",
        code_sha=code_sha,
        dataset_snapshot_ids=list(parent_snapshot_ids)
        or [f"local-canonical-input-set-{input_set_sha256 or 'blocked'}"],
        config={
            "source_mode": "local-canonical-recovery-v1",
            "canonical_input_set_sha256": input_set_sha256,
            "excluded_source_ids": list(excluded_source_ids),
            "as_of": config.as_of.isoformat(),
        },
        seed=0,
    )
    config.experiment_registry_path.parent.mkdir(parents=True, exist_ok=True)
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        registry.create(manifest)
        registry.transition(manifest.run_id, RunStatus.RUNNING)
    return manifest


def _finish_recovery_run(config: DualHorizonAcquisition, run_id: str, status: RunStatus) -> None:
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        registry.transition(run_id, status)


def _blocked_recovery_result(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    preflight: LocalSnapshotRecoveryPreflight,
) -> LocalSnapshotRecoveryResult:
    run = _start_recovery_run(
        config,
        code_sha=code_sha,
        parent_snapshot_ids=preflight.parent_snapshot_ids,
        input_set_sha256=preflight.input_set_sha256,
        excluded_source_ids=preflight.excluded_source_ids,
    )
    acquisition_path = config.artifact_root / run.run_id / "data-acquisition.json"
    quality_path = config.artifact_root / run.run_id / "data-quality.json"
    payload = {
        "run_id": run.run_id,
        "status": "blocked",
        "source_mode": "local-canonical-recovery-v1",
        "snapshot_ids": [],
        "delay_snapshot_ids": {},
        "blocked_reasons": list(preflight.blocked_reasons),
        "excluded_source_ids": list(preflight.excluded_source_ids),
        "holdout_accessed": False,
    }
    _write_exclusive_json(acquisition_path, payload)
    _write_exclusive_json(quality_path, payload)
    _finish_recovery_run(config, run.run_id, RunStatus.BLOCKED)
    return LocalSnapshotRecoveryResult(
        run_id=run.run_id,
        status=LocalSnapshotRecoveryStatus.BLOCKED,
        snapshots=(),
        delay_snapshot_ids={},
        acquisition_artifact=acquisition_path,
        quality_artifact=quality_path,
        blocked_reasons=preflight.blocked_reasons,
        excluded_source_ids=preflight.excluded_source_ids,
    )


def _combine_inputs(
    inputs: tuple[CanonicalRecoveryInput, ...], dataset: SourceDataset
) -> pd.DataFrame:
    frames = [item.frame for item in inputs if item.source.dataset == dataset]
    if not frames:
        return pd.DataFrame()
    return (
        pd.concat(frames, ignore_index=True)
        .sort_values(["asset", "event_time"])
        .reset_index(drop=True)
    )


def recover_local_dual_horizon_snapshots(
    config: DualHorizonAcquisition, *, code_sha: str
) -> LocalSnapshotRecoveryResult:
    """Rebuild research snapshots from verified local Canonical inputs only."""
    preflight = preflight_local_snapshot_recovery(config)
    if preflight.status is not LocalSnapshotRecoveryStatus.READY:
        return _blocked_recovery_result(config, code_sha=code_sha, preflight=preflight)

    run = _start_recovery_run(
        config,
        code_sha=code_sha,
        parent_snapshot_ids=preflight.parent_snapshot_ids,
        input_set_sha256=preflight.input_set_sha256,
        excluded_source_ids=preflight.excluded_source_ids,
    )
    acquisition_path = config.artifact_root / run.run_id / "data-acquisition.json"
    quality_path = config.artifact_root / run.run_id / "data-quality.json"
    ohlcv = _combine_inputs(preflight.inputs, SourceDataset.OHLCV)
    funding = _combine_inputs(preflight.inputs, SourceDataset.FUNDING)
    metrics = _combine_inputs(preflight.inputs, SourceDataset.METRICS_OI)
    macro_ohlcv = ohlcv.loc[ohlcv["event_time"] >= config.macro_start].copy()
    micro_ohlcv = ohlcv.loc[ohlcv["event_time"] >= config.micro_start].copy()

    popular_build = PopularUniverseBuildResult([], [], config.micro_start, config.micro_start, None)
    if config.universe_policy is not None:
        popular_build = build_popular_universe_artifacts(config, ohlcv, funding, metrics)
        if popular_build.shortages:
            preflight = LocalSnapshotRecoveryPreflight(
                status=LocalSnapshotRecoveryStatus.BLOCKED,
                inputs=preflight.inputs,
                parent_snapshot_ids=preflight.parent_snapshot_ids,
                input_set_sha256=preflight.input_set_sha256,
                blocked_reasons=tuple(
                    sorted(item["identity_key"] for item in popular_build.shortages)
                ),
                excluded_source_ids=preflight.excluded_source_ids,
            )
            _finish_recovery_run(config, run.run_id, RunStatus.BLOCKED)
            payload = {
                "run_id": run.run_id,
                "status": "blocked",
                "source_mode": "local-canonical-recovery-v1",
                "snapshot_ids": [],
                "delay_snapshot_ids": {},
                "blocked_reasons": list(preflight.blocked_reasons),
                "excluded_source_ids": list(preflight.excluded_source_ids),
                "holdout_accessed": False,
            }
            _write_exclusive_json(acquisition_path, payload)
            _write_exclusive_json(quality_path, payload)
            return LocalSnapshotRecoveryResult(
                run_id=run.run_id,
                status=LocalSnapshotRecoveryStatus.BLOCKED,
                snapshots=(),
                delay_snapshot_ids={},
                acquisition_artifact=acquisition_path,
                quality_artifact=quality_path,
                blocked_reasons=preflight.blocked_reasons,
                excluded_source_ids=preflight.excluded_source_ids,
            )

    snapshot_config = json.dumps(
        {
            "assets": list(config.assets),
            "macro_start": config.macro_start.isoformat(),
            "micro_start": config.micro_start.isoformat(),
            "as_of": config.as_of.isoformat(),
            "code_sha": code_sha,
            "source_mode": "local-canonical-recovery-v1",
            "canonical_input_snapshot_ids": list(preflight.parent_snapshot_ids),
            "canonical_input_set_sha256": preflight.input_set_sha256,
            "excluded_source_ids": list(preflight.excluded_source_ids),
            "popular_universe_artifact_ids": [
                str(item["artifact_id"]) for item in popular_build.artifacts
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    from bian_quant.data.catalog import DatasetCatalog

    catalog = DatasetCatalog(config.catalog_path)
    snapshots = [
        *build_macro_snapshots(
            macro_ohlcv,
            funding,
            intervals=config.macro_intervals,
            root=config.research_root,
            catalog=catalog,
            parent_snapshot_ids=preflight.parent_snapshot_ids,
            config_json=snapshot_config,
        ),
        *build_micro_snapshots(
            micro_ohlcv,
            funding,
            metrics,
            intervals=config.micro_intervals,
            root=config.research_root,
            catalog=catalog,
            parent_snapshot_ids=preflight.parent_snapshot_ids,
            config_json=snapshot_config,
        ),
    ]
    delay_snapshot_ids = build_delay_views(
        metrics,
        delays=config.oi_delay_minutes,
        root=config.research_root,
        parent_snapshot_ids=tuple(item.snapshot_id for item in snapshots),
        as_of=config.as_of,
    )
    snapshot_ids = [item.snapshot_id for item in snapshots]
    payload = {
        "run_id": run.run_id,
        "status": "passed",
        "source_mode": "local-canonical-recovery-v1",
        "snapshot_ids": snapshot_ids,
        "delay_snapshot_ids": delay_snapshot_ids,
        "canonical_input_snapshot_ids": list(preflight.parent_snapshot_ids),
        "canonical_input_set_sha256": preflight.input_set_sha256,
        "excluded_source_ids": list(preflight.excluded_source_ids),
        "popular_universe_artifacts": popular_build.artifacts,
        "holdout_accessed": False,
    }
    _write_exclusive_json(acquisition_path, payload)
    _write_exclusive_json(quality_path, payload)
    _finish_recovery_run(config, run.run_id, RunStatus.PASSED)
    return LocalSnapshotRecoveryResult(
        run_id=run.run_id,
        status=LocalSnapshotRecoveryStatus.RECOVERED,
        snapshots=tuple(snapshots),
        delay_snapshot_ids=delay_snapshot_ids,
        acquisition_artifact=acquisition_path,
        quality_artifact=quality_path,
        blocked_reasons=(),
        excluded_source_ids=preflight.excluded_source_ids,
    )
