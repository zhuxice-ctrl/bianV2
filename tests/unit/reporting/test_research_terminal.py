"""Unit tests for the research terminal response aggregator."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from bian_quant.experiments.models import RunManifest, RunStatus
from bian_quant.experiments.registry import ExperimentRegistry
from bian_quant.reporting.research_protocol import (
    PartialExclusionReason,
    TerminalState,
)
from bian_quant.reporting.research_terminal import build_research_terminal_response


def _write_config(tmp_path: Path) -> Path:
    config_data = {
        "assets": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
        "macro_start": "2026-07-01T00:00:00Z",
        "micro_start": "2026-07-01T00:00:00Z",
        "as_of": "2026-07-03T23:59:59.999Z",
        "macro_intervals": ["1d", "4h"],
        "micro_intervals": ["1h", "4h"],
        "oi_delay_minutes": [5, 10, 15],
        "funding_tail_strategy": "monthly_archive_after_period_close",
        "parent_snapshot_ids": [],
        "raw_root": str(tmp_path / "raw"),
        "canonical_root": str(tmp_path / "canonical"),
        "research_root": str(tmp_path / "research"),
        "artifact_root": str(tmp_path / "artifacts"),
        "catalog_path": str(tmp_path / "catalog.sqlite"),
        "experiment_registry_path": str(tmp_path / "experiments.sqlite"),
        "factor_registry_path": str(tmp_path / "factors.sqlite"),
        "download_attempts": 1,
        "max_workers": 1,
        "disk_warn_gb": 10,
        "disk_block_gb": 5,
        "coverage": {"ohlcv": 0.01, "funding": 0.01, "metrics_oi": 0.01},
        "factor_protocol": {
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
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config_data), encoding="utf-8")
    return config_path


def _create_passed_run(tmp_path: Path) -> str:
    """Create a passed derivatives run in the experiment registry and return run_id."""
    registry_path = tmp_path / "experiments.sqlite"
    run_manifest = RunManifest.create(
        strategy_name="dual_horizon_derivatives",
        code_sha="a" * 40,
        dataset_snapshot_ids=["source-plan-test"],
        config={"plan_hash": "test", "as_of": "2026-07-03T23:59:59.999Z"},
        seed=0,
    )
    with ExperimentRegistry(registry_path) as registry:
        registry.create(run_manifest)
        registry.transition(run_manifest.run_id, RunStatus.RUNNING)
        registry.transition(run_manifest.run_id, RunStatus.PASSED)
    return run_manifest.run_id


def _write_artifacts(tmp_path: Path, run_id: str, *, partial: bool) -> None:
    run_dir = tmp_path / "artifacts" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if partial:
        partial_exclusions = [
            {
                "identity_key": "funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00",
                "asset": "TONUSDT",
                "dataset": "funding",
                "granularity": "monthly",
                "period": "2026-07",
                "reason": "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE",
                "error_code": "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE",
                "temporary": True,
            }
        ]
        partial_impact = {
            "affected_assets": ["TONUSDT"],
            "affected_periods": 2,
            "affected_selection_days": 31,
        }
        partial_sha = "abc123"
    else:
        partial_exclusions = []
        partial_impact = {
            "affected_assets": [],
            "affected_periods": 0,
            "affected_selection_days": 0,
        }
        partial_sha = None

    acquisition = {
        "run_id": run_id,
        "status": "passed",
        "plan_hash": "test",
        "planned_objects": 39,
        "results": (
            [
                {
                    "identity_key": partial_exclusions[0]["identity_key"],
                    "status": "failed",
                    "error_code": partial_exclusions[0]["error_code"],
                    "message": "HTTP Error 404: Not Found",
                    "temporary": True,
                }
            ]
            if partial
            else []
        ),
        "blocked_periods": [],
        "persistent_bytes": 0,
        "peak_working_bytes": 0,
        "funding_tail_strategy": "monthly_archive_after_period_close",
        "cutoff_evidence": [],
        "snapshot_ids": [],
        "delay_snapshot_ids": {},
        "popular_universe_artifacts": [],
        "availability_manifest_sha256": None,
        "pre_listing_exclusions": [],
        "partial_availability_exclusions": partial_exclusions,
        "partial_availability_impact": partial_impact,
        "partial_availability_exclusion_sha256": partial_sha,
    }
    quality = {
        "run_id": run_id,
        "status": "passed",
        "coverage_reports": [],
        "blocked_periods": [],
        "funding_tail_strategy": "monthly_archive_after_period_close",
        "cutoff_evidence": [],
        "popular_universe_artifacts": [],
        "availability_manifest_sha256": None,
        "pre_listing_exclusions": [],
        "partial_availability_exclusions": partial_exclusions,
        "partial_availability_impact": partial_impact,
        "partial_availability_exclusion_sha256": partial_sha,
    }

    (run_dir / "data-acquisition.json").write_text(
        json.dumps(acquisition, indent=2, sort_keys=True), encoding="utf-8"
    )
    (run_dir / "data-quality.json").write_text(
        json.dumps(quality, indent=2, sort_keys=True), encoding="utf-8"
    )


def test_partial_availability_exclusion_mapped(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    run_id = _create_passed_run(tmp_path)
    _write_artifacts(tmp_path, run_id, partial=True)

    response = build_research_terminal_response(config_path, repo_root=tmp_path)

    assert response.state == TerminalState.PASSED
    assert response.blockers == []

    assert len(response.partial_availability_exclusions) == 1
    exclusion = response.partial_availability_exclusions[0]
    assert exclusion.asset == "TONUSDT"
    assert exclusion.dataset.value == "funding"
    assert exclusion.granularity.value == "monthly"
    assert exclusion.period == "2026-07"
    assert exclusion.reason == PartialExclusionReason.TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE
    assert exclusion.error_code == "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
    assert exclusion.temporary is True

    assert response.partial_availability_impact.affected_assets == ["TONUSDT"]
    assert response.partial_availability_impact.affected_periods == 2
    assert response.partial_availability_impact.affected_selection_days == 31
    assert response.market_cycle.label == "insufficient_evidence"
    assert response.allocation.total_cap_usdt == 0.0
    assert response.backtest_comparison.baseline.final_equity == 100.0


def test_no_partial_artifact_returns_empty(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)
    run_id = _create_passed_run(tmp_path)
    _write_artifacts(tmp_path, run_id, partial=False)

    response = build_research_terminal_response(config_path, repo_root=tmp_path)

    assert response.state == TerminalState.PASSED
    assert response.partial_availability_exclusions == []
    assert response.partial_availability_impact.affected_assets == []
    assert response.partial_availability_impact.affected_periods == 0
    assert response.partial_availability_impact.affected_selection_days == 0
    assert response.market_cycle.status in {"missing", "insufficient_evidence"}
    assert response.backtest_comparison.status in {"missing", "missing_returns"}


def test_empty_response_when_no_run(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path)

    response = build_research_terminal_response(config_path, repo_root=tmp_path)

    assert response.state == TerminalState.EMPTY
    assert response.partial_availability_exclusions == []
    assert response.partial_availability_impact.affected_assets == []
    assert response.partial_availability_impact.affected_periods == 0
    assert response.partial_availability_impact.affected_selection_days == 0
    assert response.market_cycle.status == "missing"
    assert response.allocation.selected_assets == []
