"""Repair current-plan Canonical inputs from verified local Raw artifacts only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path

import pandas as pd

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceObject,
    build_source_plan_audit,
    source_plan_hash,
)
from bian_quant.data.adapters.raw import reuse_verified_artifact
from bian_quant.data.canonicalize import (
    canonicalize_funding_zip,
    canonicalize_metrics_zip,
    canonicalize_ohlcv_zip,
    write_canonical_partition,
)
from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import DatasetLayer, DatasetManifest
from bian_quant.data.evidence_cutoff import (
    CutoffEvidence,
    canonical_plan_path,
    canonical_snapshot_id,
    clip_to_evidence_cutoff,
)
from bian_quant.data.hashing import dataframe_content_hash

_RAW_ERROR_CODES = frozenset(
    {
        "RAW_ARTIFACT_INCOMPLETE",
        "RAW_HASH_MISMATCH",
        "RAW_IDENTITY_MISMATCH",
    }
)


class LocalAvailabilityRepairStatus(StrEnum):
    REPAIRED = "repaired"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class LocalAvailabilityRepairResult:
    status: LocalAvailabilityRepairStatus
    repaired_snapshot_ids: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    cutoff_evidence: tuple[CutoffEvidence, ...]


def _canonicalize(source: SourceObject, *, raw_path: Path, ingested_at: datetime) -> pd.DataFrame:
    if source.dataset == SourceDataset.OHLCV:
        return canonicalize_ohlcv_zip(
            raw_path,
            asset=source.asset,
            interval=source.interval,
            ingested_at=ingested_at,
        )
    if source.dataset == SourceDataset.FUNDING:
        return canonicalize_funding_zip(raw_path, asset=source.asset, ingested_at=ingested_at)
    return canonicalize_metrics_zip(
        raw_path,
        ingested_at=ingested_at,
        publication_delay=timedelta(minutes=5),
    )


def _existing_snapshot_id(
    catalog: DatasetCatalog,
    path: Path,
    *,
    plan_hash: str,
    raw_sha256: str,
    source: SourceObject,
) -> str | None:
    if not path.is_file():
        return None
    frame = pd.read_parquet(path)
    content_sha = dataframe_content_hash(frame, sort_by=["asset", "event_time"])
    snapshot_id = canonical_snapshot_id(source, content_sha=content_sha, plan_hash=plan_hash)
    try:
        entry = catalog.get(snapshot_id)
    except KeyError:
        return None
    expected_manifest = DatasetManifest(
        snapshot_id=snapshot_id,
        layer=DatasetLayer.CANONICAL,
        name=f"canonical-{source.dataset.value}-{source.interval}",
        content_sha256=content_sha,
        row_count=len(frame),
        min_event_time=frame["event_time"].min(),
        max_event_time=frame["event_time"].max(),
        min_available_time=frame["available_time"].min(),
        max_available_time=frame["available_time"].max(),
        parent_snapshot_ids=[f"raw-{raw_sha256}"],
        config_json=json.dumps(
            {"identity_key": source.identity_key, "raw_sha256": raw_sha256},
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    if entry.path.resolve() != path.resolve() or entry.manifest != expected_manifest:
        return None
    return snapshot_id


def repair_verified_local_canonical_inputs(
    config: DualHorizonAcquisition,
) -> LocalAvailabilityRepairResult:
    """Publish missing current-plan Canonical inputs without network access."""
    plan = build_source_plan_audit(config)
    plan_hash = source_plan_hash(plan)
    catalog = DatasetCatalog(config.catalog_path)
    repaired: list[str] = []
    blocked: list[str] = []
    cutoff_evidence: list[CutoffEvidence] = []
    for source in sorted(plan.objects, key=lambda item: item.identity_key):
        canonical_path = canonical_plan_path(
            config.canonical_root,
            plan_hash=plan_hash,
            relative_path=source.relative_path,
        )
        raw_path = config.raw_root / source.relative_path
        try:
            verified = reuse_verified_artifact(raw_path, expected=source.raw_identity)
        except ValueError as error:
            code = str(error).split(":", maxsplit=1)[0]
            if code not in _RAW_ERROR_CODES:
                code = "RAW_ARTIFACT_INCOMPLETE"
            blocked.append(f"{code}:{source.identity_key}")
            continue
        if verified.manifest.byte_count != verified.path.stat().st_size:
            blocked.append(f"RAW_HASH_MISMATCH:{source.identity_key}")
            continue
        if (
            _existing_snapshot_id(
                catalog,
                canonical_path,
                plan_hash=plan_hash,
                raw_sha256=verified.manifest.content_sha256,
                source=source,
            )
            is not None
        ):
            continue
        frame = _canonicalize(
            source,
            raw_path=verified.path,
            ingested_at=verified.manifest.fetched_at.astimezone(UTC),
        )
        cutoff = clip_to_evidence_cutoff(source, frame, as_of=config.as_of)
        cutoff_evidence.append(cutoff.evidence)
        if cutoff.eligible.empty:
            blocked.append(f"EVIDENCE_CUTOFF_VIOLATION:{source.identity_key}")
            continue
        content_sha = dataframe_content_hash(cutoff.eligible, sort_by=["asset", "event_time"])
        snapshot_id = canonical_snapshot_id(source, content_sha=content_sha, plan_hash=plan_hash)
        manifest = DatasetManifest(
            snapshot_id=snapshot_id,
            layer=DatasetLayer.CANONICAL,
            name=f"canonical-{source.dataset.value}-{source.interval}",
            content_sha256=content_sha,
            row_count=len(cutoff.eligible),
            min_event_time=cutoff.eligible["event_time"].min(),
            max_event_time=cutoff.eligible["event_time"].max(),
            min_available_time=cutoff.eligible["available_time"].min(),
            max_available_time=cutoff.eligible["available_time"].max(),
            parent_snapshot_ids=[f"raw-{verified.manifest.content_sha256}"],
            config_json=json.dumps(
                {
                    "identity_key": source.identity_key,
                    "raw_sha256": verified.manifest.content_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            ),
        )
        try:
            existing_entry = catalog.get(snapshot_id)
        except KeyError:
            existing_entry = None
        if existing_entry is not None:
            blocked.append(f"CANONICAL_PARTITION_CONFLICT:{source.identity_key}")
            continue
        try:
            written_content_sha = write_canonical_partition(cutoff.eligible, canonical_path)
        except ValueError as error:
            if str(error).startswith("CANONICAL_PARTITION_CONFLICT:"):
                blocked.append(f"CANONICAL_PARTITION_CONFLICT:{source.identity_key}")
                continue
            raise
        if written_content_sha != content_sha:
            raise RuntimeError("canonical partition writer returned an unexpected content hash")
        catalog.register(manifest, path=canonical_path)
        repaired.append(snapshot_id)
    return LocalAvailabilityRepairResult(
        status=(
            LocalAvailabilityRepairStatus.BLOCKED
            if blocked
            else LocalAvailabilityRepairStatus.REPAIRED
        ),
        repaired_snapshot_ids=tuple(sorted(repaired)),
        blocked_reasons=tuple(sorted(set(blocked))),
        cutoff_evidence=tuple(sorted(cutoff_evidence, key=lambda item: item.identity_key)),
    )
