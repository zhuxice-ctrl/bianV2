"""Offline integration tests for the dual-horizon pipeline."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.dual_horizon import (
    DualHorizonStatus,
    FixtureDownloader,
    prepare_dual_horizon,
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "binance"


def _miniature_config(tmp_path: Path) -> DualHorizonAcquisition:
    return DualHorizonAcquisition(
        assets=("BTCUSDT", "ETHUSDT", "BNBUSDT"),
        macro_start=datetime(2026, 7, 1, tzinfo=UTC),
        micro_start=datetime(2026, 7, 1, tzinfo=UTC),
        as_of=datetime(2026, 7, 3, 23, 59, 59, 999000, tzinfo=UTC),
        macro_intervals=("1d", "4h"),
        micro_intervals=("1h", "4h"),
        oi_delay_minutes=(5, 10, 15),
        parent_snapshot_ids=(),
        raw_root=tmp_path / "raw",
        canonical_root=tmp_path / "canonical",
        research_root=tmp_path / "research",
        artifact_root=tmp_path / "artifacts",
        catalog_path=tmp_path / "catalog.sqlite",
        experiment_registry_path=tmp_path / "experiments.sqlite",
        factor_registry_path=tmp_path / "factors.sqlite",
        download_attempts=1,
        max_workers=1,
        disk_warn_gb=10,
        disk_block_gb=5,
        coverage={"ohlcv": 0.01, "funding": 0.01, "metrics_oi": 0.01},
        factor_protocol={
            "primary_interval": "4h",
            "sensitivity_interval": "1h",
            "development_months": 18,
            "holdout_months": 6,
            "development_start": "2026-07-01T00:00:00Z",
            "development_end_exclusive": "2026-07-02T00:00:00Z",
            "holdout_start": "2026-07-03T00:00:00Z",
            "holdout_end": "2026-07-03T23:59:59.999Z",
            "bh_alpha": 0.05,
            "minimum_inference_samples": 30,
            "max_candidates": 20,
            "cost_bps": [5, 10],
        },
    )


def test_offline_pipeline_builds_cataloged_macro_and_micro_snapshots(tmp_path: Path) -> None:
    config = _miniature_config(tmp_path)
    result = prepare_dual_horizon(
        config,
        code_sha="a" * 40,
        downloader=FixtureDownloader(FIXTURES),
    )
    assert result.status == DualHorizonStatus.PASSED
    assert result.blocked_periods == ()
    assert {snapshot.name for snapshot in result.snapshots} == {
        "macro-1d",
        "macro-4h",
        "micro-1h",
        "micro-4h",
    }
    quality = json.loads(result.quality_artifact.read_text(encoding="utf-8"))
    assert quality["coverage_reports"]

    resumed = prepare_dual_horizon(
        config,
        code_sha="a" * 40,
        downloader=FixtureDownloader(FIXTURES),
    )
    assert resumed.status == DualHorizonStatus.PASSED
    assert [snapshot.snapshot_id for snapshot in resumed.snapshots] == [
        snapshot.snapshot_id for snapshot in result.snapshots
    ]
    acquisition = json.loads(resumed.acquisition_artifact.read_text(encoding="utf-8"))
    assert {item["status"] for item in acquisition["results"]} == {"skipped"}


def test_local_only_pipeline_blocks_with_exact_missing_objects(tmp_path: Path) -> None:
    config = _miniature_config(tmp_path)
    result = prepare_dual_horizon(config, code_sha="b" * 40)
    assert result.status == DualHorizonStatus.BLOCKED
    assert result.snapshots == ()
    assert len(result.blocked_periods) == 45
    payload = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    assert payload["planned_objects"] == 45
    assert len([item for item in payload["results"] if item["status"] == "failed"]) == 45
