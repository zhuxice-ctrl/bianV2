"""Read-only preflight for rebuilding research snapshots from local Canonical data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import pandas as pd

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceObject,
    SourcePlanAudit,
    build_source_plan_audit,
)
from bian_quant.data.catalog import CatalogEntry
from bian_quant.data.contracts import DatasetLayer, DatasetManifest
from bian_quant.data.evidence_cutoff import CutoffEvidence, clip_to_evidence_cutoff
from bian_quant.data.hashing import dataframe_content_hash


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


def _find_by_name_read_only(path: Path, name: str) -> tuple[CatalogEntry, ...]:
    if not path.is_file():
        return ()
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    try:
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute(
                "SELECT path, manifest_json FROM datasets WHERE name = ? ORDER BY rowid",
                (name,),
            ).fetchall()
    except sqlite3.Error:
        return ()
    return tuple(
        CatalogEntry(
            manifest=DatasetManifest.model_validate_json(manifest_json),
            path=Path(stored_path),
        )
        for stored_path, manifest_json in rows
    )


def _identity(entry: CatalogEntry) -> str | None:
    try:
        payload = json.loads(entry.manifest.config_json)
    except (TypeError, json.JSONDecodeError):
        return None
    value = payload.get("identity_key") if isinstance(payload, dict) else None
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
    return cutoff, tuple(reasons)


def _preflight_plan(config: DualHorizonAcquisition) -> SourcePlanAudit:
    return build_source_plan_audit(config)


def preflight_local_snapshot_recovery(
    config: DualHorizonAcquisition,
) -> LocalSnapshotRecoveryPreflight:
    """Inspect local Canonical inputs without creating or changing any file."""
    plan = _preflight_plan(config)
    reasons: list[str] = []
    inputs: list[CanonicalRecoveryInput] = []
    for source in plan.objects:
        name = f"canonical-{source.dataset.value}-{source.interval}"
        matches = [
            entry
            for entry in _find_by_name_read_only(config.catalog_path, name)
            if _identity(entry) == source.identity_key
        ]
        if not matches:
            reasons.append(f"CANONICAL_INPUT_MISSING:{source.identity_key}")
            continue
        if len(matches) != 1:
            reasons.append(f"CANONICAL_INPUT_AMBIGUOUS:{source.identity_key}")
            continue
        entry = matches[0]
        if entry.manifest.layer != DatasetLayer.CANONICAL:
            reasons.append(f"CANONICAL_LAYER_INVALID:{entry.manifest.snapshot_id}")
            continue
        if not entry.path.is_file():
            reasons.append(f"CANONICAL_FILE_MISSING:{entry.manifest.snapshot_id}")
            continue
        try:
            frame = pd.read_parquet(entry.path)
        except (OSError, ValueError, ImportError) as error:
            reasons.append(f"CANONICAL_READ_FAILED:{entry.manifest.snapshot_id}:{error}")
            continue
        cutoff, frame_reasons = _validate_frame(source, entry, frame, config)
        reasons.extend(frame_reasons)
        if cutoff is not None:
            inputs.append(CanonicalRecoveryInput(source, entry, frame, cutoff))

    ordered_inputs = tuple(sorted(inputs, key=lambda item: item.source.identity_key))
    if reasons:
        return LocalSnapshotRecoveryPreflight(
            status=LocalSnapshotRecoveryStatus.BLOCKED,
            inputs=ordered_inputs,
            parent_snapshot_ids=(),
            input_set_sha256=None,
            blocked_reasons=tuple(sorted(set(reasons))),
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
        )
    return LocalSnapshotRecoveryPreflight(
        status=LocalSnapshotRecoveryStatus.READY,
        inputs=ordered_inputs,
        parent_snapshot_ids=parent_ids,
        input_set_sha256=_canonical_input_set_sha(ordered_inputs),
        blocked_reasons=(),
    )
