"""Offline integration test for the dual-horizon pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.dual_horizon import (
    FixtureDownloader,
    DualHorizonStatus,
    prepare_dual_horizon,
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "binance"


def test_offline_pipeline_builds_cataloged_macro_and_micro_snapshots(tmp_path: Path) -> None:
    config = DualHorizonAcquisition(
        assets=("BTCUSDT", "ETHUSDT", "BNBUSDT"),
        macro_start=datetime(2026, 7, 1, tzinfo=UTC),
        micro_start=datetime(2026, 7, 1, tzinfo=UTC),
        as_of=datetime(2026, 7, 3, 12, tzinfo=UTC),
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
        coverage={"ohlcv": 0.999, "funding": 0.99, "metrics_oi": 0.98},
        factor_protocol={
            "primary_interval": "4h",
            "sensitivity_interval": "1h",
            "development_months": 18,
            "holdout_months": 6,
            "development_start": "2026-07-01T00:00:00Z",
            "development_end_exclusive": "2026-07-02T00:00:00Z",
            "holdout_start": "2026-07-02T20:00:00Z",
            "holdout_end": "2026-07-03T12:00:00Z",
            "bh_alpha": 0.05,
            "minimum_inference_samples": 30,
            "max_candidates": 20,
            "cost_bps": [5, 10],
        },
    )
    result = prepare_dual_horizon(
        config,
        code_sha="a" * 40,
        downloader=FixtureDownloader(FIXTURES),
    )
    assert result.status in (DualHorizonStatus.PASSED, DualHorizonStatus.BLOCKED)
    assert result.acquisition_artifact.exists()
    assert result.quality_artifact.exists()
