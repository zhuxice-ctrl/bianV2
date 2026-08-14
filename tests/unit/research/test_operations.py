"""Operator-boundary tests for catalog analysis and holdout access."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import DatasetLayer
from bian_quant.data.snapshots import SnapshotSpec, publish_snapshot
from bian_quant.experiments.holdout import HoldoutLedger
from bian_quant.experiments.models import RunManifest, RunStatus
from bian_quant.experiments.registry import ExperimentRegistry
from bian_quant.factors.dual_horizon import dual_horizon_factor_specs
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorState
from bian_quant.reporting.decision import (
    REQUIRED_ARTIFACTS,
    write_decision_packet,
    zero_candidate_evidence,
)
from bian_quant.research.operations import (
    analyze_cataloged_dual_horizon,
    evaluate_candidate_holdout,
    resolve_dual_horizon_snapshots,
)

CODE_SHA = "a" * 40


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


def _frame(start: str, *, periods: int, frequency: str) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for asset_index, asset in enumerate(("BTCUSDT", "ETHUSDT", "BNBUSDT")):
        times = pd.date_range(start, periods=periods, freq=frequency, tz="UTC")
        sequence = pd.Series(range(periods), dtype="float64")
        phase = np.arange(periods, dtype=float) / 7.0 + asset_index
        close = 100.0 + asset_index * 20.0 + sequence * 0.03 + np.sin(phase) * 2.0
        volume = 1000.0 + sequence + np.cos(phase) * 25.0
        frames.append(
            pd.DataFrame(
                {
                    "asset": asset,
                    "event_time": times,
                    "available_time": times,
                    "close": close,
                    "high": close + 1.0,
                    "low": close - 1.0,
                    "volume": volume,
                    "quote_volume": volume * close,
                    "funding_rate": 0.0001 + sequence * 0.0000001,
                    "funding_available_time": times,
                    "funding_interval_hours": 8,
                    "sum_open_interest": 10000.0 + sequence * 2.0,
                    "sum_open_interest_value": (10000.0 + sequence * 2.0) * close,
                    "oi_available_time": times,
                    "availability_assumption": "BINANCE_METRICS_DELAY_5M",
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


def _snapshot_config(config: DualHorizonAcquisition) -> str:
    return json.dumps(
        {
            "assets": list(config.assets),
            "macro_start": config.macro_start.isoformat(),
            "micro_start": config.micro_start.isoformat(),
            "as_of": config.as_of.isoformat(),
            "code_sha": CODE_SHA,
        },
        sort_keys=True,
    )


def _publish_required(config: DualHorizonAcquisition) -> dict[str, str]:
    catalog = DatasetCatalog(config.catalog_path)
    parents = ("raw-set-" + "b" * 64,)
    inputs = {
        "macro-1d": (_frame("2021-07-01", periods=180, frequency="1D"), "1d"),
        "macro-4h": (_frame("2021-07-01", periods=240, frequency="4h"), "4h"),
        "micro-1h": (_frame("2024-07-01", periods=500, frequency="1h"), "1h"),
        "micro-4h": (_frame("2024-07-01", periods=450, frequency="4h"), "4h"),
    }
    result: dict[str, str] = {}
    for name, (frame, interval) in inputs.items():
        manifest = publish_snapshot(
            frame,
            SnapshotSpec(
                name=name,
                layer=DatasetLayer.RESEARCH,
                interval=interval,
                horizon=name.split("-")[0],
                parent_snapshot_ids=parents,
                config_json=_snapshot_config(config),
            ),
            config.research_root,
            catalog,
        )
        result[name] = manifest.snapshot_id
    delay_catalog = DatasetCatalog(config.research_root / "delay_catalog.sqlite")
    for delay in config.oi_delay_minutes:
        metrics = _frame("2024-07-01", periods=500, frequency="1h")
        metrics["available_time"] = metrics["event_time"] + pd.Timedelta(minutes=delay)
        metrics["availability_assumption"] = f"BINANCE_METRICS_DELAY_{delay}M"
        publish_snapshot(
            metrics,
            SnapshotSpec(
                name=f"metrics-oi-delay-{delay}m",
                layer=DatasetLayer.RESEARCH,
                interval="1h",
                horizon="micro",
                parent_snapshot_ids=tuple(result.values()),
                config_json=json.dumps({"delay_minutes": delay}),
            ),
            config.research_root,
            delay_catalog,
        )
    return result


def _passed_source_run(config: DualHorizonAcquisition) -> str:
    manifest = RunManifest.create(
        strategy_name="dual_horizon_derivatives",
        code_sha=CODE_SHA,
        dataset_snapshot_ids=["source-plan-test"],
        config={"as_of": config.as_of.isoformat()},
        seed=0,
    )
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        registry.create(manifest)
        registry.transition(manifest.run_id, RunStatus.RUNNING)
        registry.transition(manifest.run_id, RunStatus.PASSED)
    run_dir = config.artifact_root / manifest.run_id
    run_dir.mkdir(parents=True)
    (run_dir / "data-acquisition.json").write_text(
        json.dumps({"run_id": manifest.run_id, "status": "passed"}), encoding="utf-8"
    )
    (run_dir / "data-quality.json").write_text(
        json.dumps({"run_id": manifest.run_id, "status": "passed"}), encoding="utf-8"
    )
    return manifest.run_id


def test_missing_catalog_inputs_create_terminal_blocked_packet(tmp_path: Path) -> None:
    config = _config(tmp_path)
    result = analyze_cataloged_dual_horizon(config, code_sha=CODE_SHA)
    assert result.status == "blocked"
    assert "SNAPSHOT_MISSING" in (result.error_code or "")
    assert {path.name for path in result.artifact_dir.iterdir()} == REQUIRED_ARTIFACTS
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        assert registry.get(result.run_id).status == RunStatus.BLOCKED


def test_cataloged_analysis_uses_actual_snapshots_and_packet(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ids = _publish_required(config)
    _passed_source_run(config)
    resolved = resolve_dual_horizon_snapshots(config, code_sha=CODE_SHA)
    assert set(resolved.snapshot_ids) == set(ids.values())

    result = analyze_cataloged_dual_horizon(config, code_sha=CODE_SHA)
    assert result.status == "passed"
    assert set(result.snapshot_ids) == set(ids.values())
    assert {path.name for path in result.artifact_dir.iterdir()} == REQUIRED_ARTIFACTS
    factor_payload = json.loads(
        (result.artifact_dir / "factor-screening.json").read_text(encoding="utf-8")
    )
    assert factor_payload["snapshot_ids"] == [ids["micro-1h"], ids["micro-4h"]]
    summary = (result.artifact_dir / "decision-summary.md").read_text(encoding="utf-8")
    assert "Engineering status: PASSED" in summary
    expected_status = (
        "CANDIDATES_PENDING_HOLDOUT" if result.candidate_factor_ids else "NO_PROMOTION"
    )
    assert f"Factor status: {expected_status}" in summary
    assert not (config.artifact_root / "holdout-access.sqlite").exists()


def test_cataloged_analysis_factor_screening_includes_relative_funding_pressure(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    _publish_required(config)
    _passed_source_run(config)

    result = analyze_cataloged_dual_horizon(config, code_sha=CODE_SHA)
    assert result.status == "passed"

    factor_payload = json.loads(
        (result.artifact_dir / "factor-screening.json").read_text(encoding="utf-8")
    )
    assert "relative_funding_pressure" in factor_payload["gates"]
    assert "relative_funding_pressure" in factor_payload["factor_diagnostics"]
    assert "relative_funding_pressure" in factor_payload["planned_lifecycle_states"]
    assert not (config.artifact_root / "holdout-access.sqlite").exists()


def test_decision_packet_rejects_precreated_or_reused_run_directory(tmp_path: Path) -> None:
    run_dir = tmp_path / "run-1"
    run_dir.mkdir()
    with pytest.raises(FileExistsError):
        write_decision_packet(zero_candidate_evidence(), run_dir)
    run_dir.rmdir()
    write_decision_packet(zero_candidate_evidence(), run_dir)
    with pytest.raises(FileExistsError):
        write_decision_packet(zero_candidate_evidence(), run_dir)


def _candidate_and_run(
    config: DualHorizonAcquisition, snapshot_ids: dict[str, str]
) -> tuple[str, str]:
    spec = dual_horizon_factor_specs("4h")[0]
    with FactorRegistry(config.factor_registry_path) as factors:
        factors.register(spec, code_sha=CODE_SHA)
        factors.transition(
            spec.factor_id, spec.version, FactorState.OBSERVED, evidence_run_id="development"
        )
        factors.transition(
            spec.factor_id, spec.version, FactorState.CANDIDATE, evidence_run_id="development"
        )
    manifest = RunManifest.create(
        strategy_name="dual_horizon_analysis",
        code_sha=CODE_SHA,
        dataset_snapshot_ids=list(snapshot_ids.values()),
        config={},
        seed=0,
    )
    with ExperimentRegistry(config.experiment_registry_path) as registry:
        registry.create(manifest)
        registry.transition(manifest.run_id, RunStatus.RUNNING)
        registry.transition(manifest.run_id, RunStatus.PASSED)
    return manifest.run_id, spec.factor_id


def test_holdout_authorizes_before_read_and_rejection_preserves_candidate(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    ids = _publish_required(config)
    run_id, factor_id = _candidate_and_run(config, ids)

    def ordered_reader(entry):
        with HoldoutLedger(config.artifact_root / "holdout-access.sqlite") as ledger:
            assert len(ledger.history()) == 1
        return _frame("2026-01-26T20:00:00Z", periods=60, frequency="4h")

    result = evaluate_candidate_holdout(
        config,
        run_id=run_id,
        factor_id=factor_id,
        factor_version="1.0.0",
        snapshot_id=ids["micro-4h"],
        reader=ordered_reader,
        evaluator=lambda frame, spec: (False, ["HOLDOUT_5BPS_NON_POSITIVE"], {}),
    )
    assert result.status == "rejected"
    assert result.factor_state == FactorState.CANDIDATE
    payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
    assert payload["reason_codes"][0] == "FACTOR_PROMOTION_REJECTED"


def test_post_authorization_failure_keeps_access_and_failed_evidence(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ids = _publish_required(config)
    run_id, factor_id = _candidate_and_run(config, ids)

    def fail_after_authorization(entry):
        raise RuntimeError("reader failed")

    with pytest.raises(RuntimeError, match="reader failed"):
        evaluate_candidate_holdout(
            config,
            run_id=run_id,
            factor_id=factor_id,
            factor_version="1.0.0",
            snapshot_id=ids["micro-4h"],
            reader=fail_after_authorization,
        )
    with HoldoutLedger(config.artifact_root / "holdout-access.sqlite") as ledger:
        assert len(ledger.history()) == 1
    artifact = config.artifact_root / "holdout" / f"{run_id}-{factor_id}-1.0.0.json"
    assert json.loads(artifact.read_text(encoding="utf-8"))["status"] == "failed"


def test_observed_factor_leaves_holdout_ledger_untouched(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ids = _publish_required(config)
    spec = dual_horizon_factor_specs("4h")[0]
    with FactorRegistry(config.factor_registry_path) as factors:
        factors.register(spec, code_sha=CODE_SHA)
        factors.transition(
            spec.factor_id, spec.version, FactorState.OBSERVED, evidence_run_id="development"
        )
    with pytest.raises(PermissionError, match="not Candidate"):
        evaluate_candidate_holdout(
            config,
            run_id="not-opened",
            factor_id=spec.factor_id,
            factor_version=spec.version,
            snapshot_id=ids["micro-4h"],
        )
    assert not (config.artifact_root / "holdout-access.sqlite").exists()
