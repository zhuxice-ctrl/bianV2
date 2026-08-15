"""Tests for read-only local Canonical snapshot preflight."""

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
from bian_quant.data.canonicalize import write_canonical_partition
from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import DatasetLayer, DatasetManifest
from bian_quant.data.evidence_cutoff import canonical_plan_path
from bian_quant.data.local_snapshot_recovery import (
    LocalSnapshotRecoveryStatus,
    preflight_local_snapshot_recovery,
)


def _config(tmp_path: Path) -> DualHorizonAcquisition:
    base = DualHorizonAcquisition.from_yaml(
        Path("configs/experiments/dual_horizon_derivatives.yaml")
    )
    return base.model_copy(
        update={
            "raw_root": tmp_path / "raw",
            "canonical_root": tmp_path / "canonical",
            "research_root": tmp_path / "research",
            "artifact_root": tmp_path / "artifacts",
            "catalog_path": tmp_path / "catalog.sqlite",
            "experiment_registry_path": tmp_path / "experiments.sqlite",
            "factor_registry_path": tmp_path / "factors.sqlite",
        }
    )


def _sources() -> tuple[SourceObject, ...]:
    start = datetime(2026, 7, 1, tzinfo=UTC)
    return (
        SourceObject(
            dataset=SourceDataset.OHLCV,
            asset="BTCUSDT",
            interval="4h",
            granularity=SourceGranularity.DAILY,
            period_start=start,
            url="https://example.invalid/ohlcv",
            relative_path=Path("ohlcv.parquet"),
        ),
        SourceObject(
            dataset=SourceDataset.FUNDING,
            asset="BTCUSDT",
            interval="native",
            granularity=SourceGranularity.DAILY,
            period_start=start,
            url="https://example.invalid/funding",
            relative_path=Path("funding.parquet"),
        ),
        SourceObject(
            dataset=SourceDataset.METRICS_OI,
            asset="BTCUSDT",
            interval="native",
            granularity=SourceGranularity.DAILY,
            period_start=start,
            url="https://example.invalid/metrics",
            relative_path=Path("metrics.parquet"),
        ),
    )


def _frames(sources: tuple[SourceObject, ...]) -> dict[str, pd.DataFrame]:
    event_time = pd.Timestamp("2026-07-01T00:00:00Z")
    available_time = pd.Timestamp("2026-07-01T00:05:00Z")
    return {
        sources[0].identity_key: pd.DataFrame(
            {
                "asset": ["BTCUSDT"],
                "event_time": [event_time],
                "available_time": [available_time],
                "ingested_at": [pd.Timestamp("2026-07-02T00:00:00Z")],
                "open": [100.0],
                "high": [101.0],
                "low": [99.0],
                "close": [100.5],
                "volume": [10.0],
                "quote_volume": [1005.0],
            }
        ),
        sources[1].identity_key: pd.DataFrame(
            {
                "asset": ["BTCUSDT"],
                "event_time": [event_time],
                "available_time": [available_time],
                "ingested_at": [pd.Timestamp("2026-07-02T00:00:00Z")],
                "funding_rate": [0.0001],
                "funding_interval_hours": [8],
            }
        ),
        sources[2].identity_key: pd.DataFrame(
            {
                "asset": ["BTCUSDT"],
                "event_time": [event_time],
                "available_time": [available_time],
                "ingested_at": [pd.Timestamp("2026-07-02T00:00:00Z")],
                "sum_open_interest": [1000.0],
                "sum_open_interest_value": [100500.0],
                "availability_assumption": ["BINANCE_METRICS_DELAY_5M"],
            }
        ),
    }


def _publish_inputs(
    config: DualHorizonAcquisition,
    sources: tuple[SourceObject, ...],
    frames: dict[str, pd.DataFrame],
    *,
    duplicate_identity: bool = False,
) -> None:
    catalog = DatasetCatalog(config.catalog_path)
    plan_hash = source_plan_hash(SourcePlanAudit(sources, None, ()))
    for index, source in enumerate(sources):
        frame = frames[source.identity_key]
        path = canonical_plan_path(
            config.canonical_root,
            plan_hash=plan_hash,
            relative_path=source.relative_path,
        )
        content_sha = write_canonical_partition(frame, path)
        raw_sha256 = "b" * 64
        raw_path = config.raw_root / source.relative_path
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.with_suffix(f"{raw_path.suffix}.manifest.json").write_text(
            json.dumps({"content_sha256": raw_sha256}), encoding="utf-8"
        )
        manifest = DatasetManifest(
            snapshot_id=f"canonical-{index}-{content_sha[:16]}",
            layer=DatasetLayer.CANONICAL,
            name=f"canonical-{source.dataset.value}-{source.interval}",
            content_sha256=content_sha,
            row_count=len(frame),
            min_event_time=frame["event_time"].min().to_pydatetime(),
            max_event_time=frame["event_time"].max().to_pydatetime(),
            min_available_time=frame["available_time"].min().to_pydatetime(),
            max_available_time=frame["available_time"].max().to_pydatetime(),
            parent_snapshot_ids=["raw-parent"],
            config_json=json.dumps(
                {"identity_key": source.identity_key, "raw_sha256": raw_sha256},
                sort_keys=True,
            ),
        )
        catalog.register(manifest, path=path)
        if duplicate_identity and index == 0:
            duplicate = manifest.model_copy(
                update={
                    "snapshot_id": f"canonical-duplicate-{content_sha[:16]}",
                }
            )
            catalog.register(duplicate, path=path)


def _patch_plan(monkeypatch: pytest.MonkeyPatch, sources: tuple[SourceObject, ...]) -> None:
    from bian_quant.data import local_snapshot_recovery

    monkeypatch.setattr(
        local_snapshot_recovery,
        "build_source_plan_audit",
        lambda config: SourcePlanAudit(sources, None, ()),
    )


def test_source_plan_hash_is_stable_and_shared() -> None:
    sources = _sources()
    source_a, source_b = sources[0], sources[1]
    plan = SourcePlanAudit((source_a, source_b), "a" * 64, ())
    payload = {
        "availability_manifest_sha256": plan.availability_manifest_sha256,
        "object_identity_keys": [source_a.identity_key, source_b.identity_key],
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert source_plan_hash(plan) == expected


def test_preflight_accepts_unique_hashed_canonical_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    sources = _sources()
    _publish_inputs(config, sources, _frames(sources))
    _patch_plan(monkeypatch, sources)

    result = preflight_local_snapshot_recovery(config)

    assert result.status is LocalSnapshotRecoveryStatus.READY
    assert len(result.inputs) == len(sources)
    assert result.parent_snapshot_ids == tuple(
        sorted(item.entry.manifest.snapshot_id for item in result.inputs)
    )
    assert result.input_set_sha256
    assert result.blocked_reasons == ()


def test_preflight_blocks_missing_and_ambiguous_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    sources = _sources()
    _publish_inputs(config, sources, _frames(sources))
    _patch_plan(monkeypatch, sources)
    with sqlite3.connect(config.catalog_path) as connection:
        connection.execute("DELETE FROM datasets WHERE name = ?", ("canonical-metrics_oi-native",))

    missing = preflight_local_snapshot_recovery(config)
    assert f"CANONICAL_INPUT_MISSING:{sources[-1].identity_key}" in missing.blocked_reasons

    _publish_inputs(config, sources, _frames(sources), duplicate_identity=True)
    ambiguous = preflight_local_snapshot_recovery(config)
    assert f"CANONICAL_INPUT_AMBIGUOUS:{sources[0].identity_key}" in ambiguous.blocked_reasons


def test_preflight_excludes_unclosed_daily_1d_source_from_canonical_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    unclosed = SourceObject(
        dataset=SourceDataset.OHLCV,
        asset="BTCUSDT",
        interval="1d",
        granularity=SourceGranularity.DAILY,
        period_start=config.as_of.replace(hour=0, minute=0, second=0, microsecond=0),
        url="https://example.invalid/ohlcv",
        relative_path=Path("ohlcv") / "BTCUSDT" / "1d" / "2026-07-26.zip",
    )
    _patch_plan(monkeypatch, (unclosed,))

    result = preflight_local_snapshot_recovery(config)

    assert result.status is LocalSnapshotRecoveryStatus.BLOCKED
    assert result.inputs == ()
    assert result.blocked_reasons == ("CANONICAL_INPUTS_EMPTY",)


def test_preflight_blocks_hash_tampering_and_cutoff_violation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    sources = _sources()
    frames = _frames(sources)
    _publish_inputs(config, sources, frames)
    _patch_plan(monkeypatch, sources)

    tampered_path = next(config.canonical_root.rglob("*.parquet"))
    tampered = pd.read_parquet(tampered_path)
    tampered.loc[0, "asset"] = "ETHUSDT"
    tampered.to_parquet(tampered_path, index=False)
    tampered_result = preflight_local_snapshot_recovery(config)
    assert any(
        reason.startswith("CANONICAL_CONTENT_HASH_MISMATCH:")
        for reason in tampered_result.blocked_reasons
    )

    config = _config(tmp_path / "future")
    future_frames = _frames(sources)
    future_frames[sources[0].identity_key].loc[0, "available_time"] = pd.Timestamp(
        "2026-07-27T00:00:00Z"
    )
    _publish_inputs(config, sources, future_frames)
    _patch_plan(monkeypatch, sources)
    future_result = preflight_local_snapshot_recovery(config)
    assert f"CANONICAL_CUTOFF_VIOLATION:{sources[0].identity_key}" in future_result.blocked_reasons


def test_preflight_does_not_write_catalog_or_snapshot_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = _config(tmp_path)
    sources = _sources()
    _publish_inputs(config, sources, _frames(sources))
    _patch_plan(monkeypatch, sources)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    preflight_local_snapshot_recovery(config)

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert before == after
