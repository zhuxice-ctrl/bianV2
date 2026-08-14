"""Offline integration tests for Canonical-to-research snapshot recovery."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceGranularity,
    SourceObject,
)
from bian_quant.data.catalog import CatalogEntry
from bian_quant.data.contracts import DatasetLayer, DatasetManifest
from bian_quant.data.evidence_cutoff import CutoffEvidence
from bian_quant.data.local_snapshot_recovery import (
    CanonicalRecoveryInput,
    LocalSnapshotRecoveryPreflight,
    LocalSnapshotRecoveryStatus,
    recover_local_dual_horizon_snapshots,
)
from bian_quant.research.operations import resolve_dual_horizon_snapshots

CODE_SHA = "c" * 40


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


def _source(dataset: SourceDataset, interval: str) -> SourceObject:
    return SourceObject(
        dataset=dataset,
        asset="BTCUSDT",
        interval=interval,
        granularity=SourceGranularity.DAILY,
        period_start=datetime(2026, 7, 1, tzinfo=UTC),
        url="https://example.invalid/local",
        relative_path=Path(f"{dataset.value}-{interval}.zip"),
    )


def _bars(interval: str) -> pd.DataFrame:
    event_time = pd.Timestamp("2026-07-01T00:00:00Z")
    return pd.DataFrame(
        {
            "asset": ["BTCUSDT"],
            "interval": [interval],
            "event_time": [event_time],
            "available_time": [event_time + pd.Timedelta(minutes=5)],
            "open": [100.0],
            "high": [101.0],
            "low": [99.0],
            "close": [100.5],
            "volume": [10.0],
            "quote_volume": [1005.0],
        }
    )


def _funding() -> pd.DataFrame:
    event_time = pd.Timestamp("2026-07-01T00:00:00Z")
    return pd.DataFrame(
        {
            "asset": ["BTCUSDT"],
            "event_time": [event_time],
            "available_time": [event_time + pd.Timedelta(minutes=5)],
            "funding_rate": [0.0001],
            "funding_interval_hours": [8],
        }
    )


def _metrics() -> pd.DataFrame:
    event_time = pd.Timestamp("2026-07-01T00:00:00Z")
    return pd.DataFrame(
        {
            "asset": ["BTCUSDT"],
            "event_time": [event_time],
            "available_time": [event_time + pd.Timedelta(minutes=5)],
            "sum_open_interest": [1000.0],
            "sum_open_interest_value": [100500.0],
            "availability_assumption": ["BINANCE_METRICS_DELAY_5M"],
        }
    )


def _preflight() -> LocalSnapshotRecoveryPreflight:
    sources = (
        _source(SourceDataset.OHLCV, "1d"),
        _source(SourceDataset.OHLCV, "4h"),
        _source(SourceDataset.OHLCV, "1h"),
        _source(SourceDataset.FUNDING, "native"),
        _source(SourceDataset.METRICS_OI, "native"),
    )
    frames = {
        sources[0].identity_key: _bars("1d"),
        sources[1].identity_key: _bars("4h"),
        sources[2].identity_key: _bars("1h"),
        sources[3].identity_key: _funding(),
        sources[4].identity_key: _metrics(),
    }
    inputs: list[CanonicalRecoveryInput] = []
    for index, source in enumerate(sources):
        frame = frames[source.identity_key]
        manifest = DatasetManifest(
            snapshot_id=f"canonical-input-{index}",
            layer=DatasetLayer.CANONICAL,
            name=f"canonical-{source.dataset.value}-{source.interval}",
            content_sha256="a" * 64,
            row_count=len(frame),
            min_event_time=datetime(2026, 7, 1, tzinfo=UTC),
            max_event_time=datetime(2026, 7, 1, tzinfo=UTC),
            parent_snapshot_ids=["raw-parent"],
            config_json="{}",
        )
        cutoff = CutoffEvidence(
            identity_key=source.identity_key,
            dataset=source.dataset.value,
            eligible_rows=len(frame),
            post_cutoff_rows_excluded=0,
            earliest_excluded_event_time=None,
            latest_excluded_event_time=None,
            earliest_excluded_available_time=None,
            latest_excluded_available_time=None,
        )
        inputs.append(
            CanonicalRecoveryInput(source, CatalogEntry(manifest, Path("unused")), frame, cutoff)
        )
    return LocalSnapshotRecoveryPreflight(
        status=LocalSnapshotRecoveryStatus.READY,
        inputs=tuple(inputs),
        parent_snapshot_ids=tuple(item.entry.manifest.snapshot_id for item in inputs),
        input_set_sha256="f" * 64,
        blocked_reasons=(),
    )


def test_local_recovery_publishes_resolvable_snapshots_idempotently(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(tmp_path)
    preflight = _preflight()
    monkeypatch.setattr(
        "bian_quant.data.local_snapshot_recovery.preflight_local_snapshot_recovery",
        lambda config: preflight,
    )

    first = recover_local_dual_horizon_snapshots(config, code_sha=CODE_SHA)
    first_bytes = {path: path.read_bytes() for path in config.research_root.rglob("*.parquet")}
    second = recover_local_dual_horizon_snapshots(config, code_sha=CODE_SHA)

    assert first.status is LocalSnapshotRecoveryStatus.RECOVERED
    assert second.status is LocalSnapshotRecoveryStatus.RECOVERED
    assert first.snapshot_ids == second.snapshot_ids
    assert first.delay_snapshot_ids == second.delay_snapshot_ids
    assert first_bytes == {
        path: path.read_bytes() for path in config.research_root.rglob("*.parquet")
    }
    resolved = resolve_dual_horizon_snapshots(config, code_sha=CODE_SHA)
    assert resolved.snapshot_ids == first.snapshot_ids
    assert set(resolved.entries) == {"macro-1d", "macro-4h", "micro-1h", "micro-4h"}
    assert not (config.artifact_root / "holdout-access.sqlite").exists()
