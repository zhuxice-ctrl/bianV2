"""Tests for repair of current-plan Canonical inputs from verified local Raw data."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceGranularity,
    SourceObject,
    SourcePlanAudit,
    source_plan_hash,
)
from bian_quant.data.adapters.raw import RawSourceManifest, save_source_artifact
from bian_quant.data.canonicalize import write_canonical_partition
from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.evidence_cutoff import canonical_plan_path, canonical_snapshot_id
from bian_quant.data.hashing import dataframe_content_hash
from bian_quant.data.local_availability_repair import (
    LocalAvailabilityRepairStatus,
    repair_verified_local_canonical_inputs,
)

FIXTURE = Path("tests/fixtures/binance/ohlcv-mini.zip")


def _config(tmp_path: Path) -> DualHorizonAcquisition:
    base = DualHorizonAcquisition.from_yaml(
        Path("configs/experiments/dual_horizon_derivatives.yaml")
    )
    return base.model_copy(
        update={
            "as_of": datetime(2026, 8, 1, tzinfo=UTC),
            "raw_root": tmp_path / "raw",
            "canonical_root": tmp_path / "canonical",
            "research_root": tmp_path / "research",
            "artifact_root": tmp_path / "artifacts",
            "catalog_path": tmp_path / "catalog.sqlite",
            "experiment_registry_path": tmp_path / "experiments.sqlite",
            "factor_registry_path": tmp_path / "factors.sqlite",
        }
    )


def _source(asset: str) -> SourceObject:
    return SourceObject(
        dataset=SourceDataset.OHLCV,
        asset=asset,
        interval="1d",
        granularity=SourceGranularity.DAILY,
        period_start=datetime(2026, 7, 29, tzinfo=UTC),
        url="https://example.invalid/ohlcv",
        relative_path=Path("ohlcv") / asset / "1d" / "2026-07-29.zip",
    )


def _save_raw(config: DualHorizonAcquisition, source: SourceObject, *, complete: bool) -> str:
    payload = FIXTURE.read_bytes()
    path = config.raw_root / source.relative_path
    if not complete:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()
    manifest = RawSourceManifest(
        source_url=source.url,
        fetched_at=datetime(2026, 7, 30, tzinfo=UTC),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        upstream_sha256=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
        asset=source.asset,
        dataset=source.dataset.value,
        interval=source.interval,
        source_period=source.raw_identity.source_period,
    )
    save_source_artifact(path, payload, manifest)
    return manifest.content_sha256


def _patch_plan(monkeypatch: pytest.MonkeyPatch, sources: tuple[SourceObject, ...]) -> None:
    from bian_quant.data import local_availability_repair

    monkeypatch.setattr(
        local_availability_repair,
        "build_source_plan_audit",
        lambda config: SourcePlanAudit(sources, None, ()),
    )


def test_repair_publishes_verified_raw_and_blocks_incomplete_raw(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    verified, incomplete = _source("BTCUSDT"), _source("ETHUSDT")
    raw_sha = _save_raw(config, verified, complete=True)
    _save_raw(config, incomplete, complete=False)
    sources = (verified, incomplete)
    _patch_plan(monkeypatch, sources)

    result = repair_verified_local_canonical_inputs(config)

    plan_hash = source_plan_hash(SourcePlanAudit(sources, None, ()))
    expected_path = canonical_plan_path(
        config.canonical_root, plan_hash=plan_hash, relative_path=verified.relative_path
    )
    expected_id = canonical_snapshot_id(
        verified,
        content_sha=dataframe_content_hash(
            pd.read_parquet(expected_path), sort_by=["asset", "event_time"]
        ),
        plan_hash=plan_hash,
    )
    assert result.status is LocalAvailabilityRepairStatus.BLOCKED
    assert result.repaired_snapshot_ids == (expected_id,)
    assert result.blocked_reasons == (f"RAW_ARTIFACT_INCOMPLETE:{incomplete.identity_key}",)
    assert expected_path.is_file()
    assert raw_sha
    expected_bytes = expected_path.read_bytes()
    expected_entry = DatasetCatalog(config.catalog_path).get(expected_id)

    repeated = repair_verified_local_canonical_inputs(config)
    assert repeated.repaired_snapshot_ids == ()
    assert repeated.blocked_reasons == result.blocked_reasons
    assert expected_path.read_bytes() == expected_bytes
    assert DatasetCatalog(config.catalog_path).get(expected_id) == expected_entry


def test_repair_reports_canonical_conflict_without_overwriting_existing_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    source = _source("BTCUSDT")
    _save_raw(config, source, complete=True)
    _patch_plan(monkeypatch, (source,))
    plan_hash = source_plan_hash(SourcePlanAudit((source,), None, ()))
    canonical_path = canonical_plan_path(
        config.canonical_root, plan_hash=plan_hash, relative_path=source.relative_path
    )
    conflicting = pd.DataFrame(
        {
            "asset": ["ETHUSDT"],
            "event_time": [pd.Timestamp("2026-07-29T00:00:00Z")],
            "available_time": [pd.Timestamp("2026-07-29T23:59:59Z")],
        }
    )
    write_canonical_partition(conflicting, canonical_path)
    before = canonical_path.read_bytes()

    result = repair_verified_local_canonical_inputs(config)

    assert result.status is LocalAvailabilityRepairStatus.BLOCKED
    assert result.repaired_snapshot_ids == ()
    assert result.blocked_reasons == (f"CANONICAL_PARTITION_CONFLICT:{source.identity_key}",)
    assert canonical_path.read_bytes() == before


def test_repair_rejects_existing_catalog_entry_with_wrong_raw_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    source = _source("BTCUSDT")
    _save_raw(config, source, complete=True)
    _patch_plan(monkeypatch, (source,))
    initial = repair_verified_local_canonical_inputs(config)
    snapshot_id = initial.repaired_snapshot_ids[0]
    catalog = DatasetCatalog(config.catalog_path)
    entry = catalog.get(snapshot_id)
    wrong_raw_sha256 = "a" * 64
    wrong_manifest = entry.manifest.model_copy(
        update={
            "parent_snapshot_ids": [f"raw-{wrong_raw_sha256}"],
            "config_json": json.dumps(
                {"identity_key": source.identity_key, "raw_sha256": wrong_raw_sha256},
                sort_keys=True,
                separators=(",", ":"),
            ),
        }
    )
    with sqlite3.connect(config.catalog_path) as connection:
        connection.execute(
            "UPDATE datasets SET manifest_json = ? WHERE snapshot_id = ?",
            (wrong_manifest.model_dump_json(), snapshot_id),
        )
    before = entry.path.read_bytes()

    result = repair_verified_local_canonical_inputs(config)

    assert result.status is LocalAvailabilityRepairStatus.BLOCKED
    assert result.repaired_snapshot_ids == ()
    assert result.blocked_reasons == (f"CANONICAL_PARTITION_CONFLICT:{source.identity_key}",)
    assert entry.path.read_bytes() == before
    assert DatasetCatalog(config.catalog_path).get(snapshot_id).manifest == wrong_manifest


@pytest.mark.parametrize(
    ("mutate", "expected_code"),
    [
        ("hash", "RAW_HASH_MISMATCH"),
        ("identity", "RAW_IDENTITY_MISMATCH"),
        ("byte_count", "RAW_HASH_MISMATCH"),
    ],
)
def test_repair_maps_raw_integrity_failures_to_stable_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutate: str,
    expected_code: str,
) -> None:
    config = _config(tmp_path)
    source = _source("BTCUSDT")
    _save_raw(config, source, complete=True)
    _patch_plan(monkeypatch, (source,))
    raw_path = config.raw_root / source.relative_path
    manifest_path = raw_path.with_suffix(f"{raw_path.suffix}.manifest.json")
    if mutate == "hash":
        raw_path.write_bytes(raw_path.read_bytes() + b"tampered")
    else:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if mutate == "identity":
            manifest["asset"] = "ETHUSDT"
        else:
            manifest["byte_count"] += 1
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = repair_verified_local_canonical_inputs(config)

    assert result.status is LocalAvailabilityRepairStatus.BLOCKED
    assert result.repaired_snapshot_ids == ()
    assert result.blocked_reasons == (f"{expected_code}:{source.identity_key}",)
