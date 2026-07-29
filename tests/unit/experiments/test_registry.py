from datetime import UTC, datetime
from pathlib import Path

import pytest

from bian_quant.experiments.models import LockedHoldout, RunManifest, RunStatus
from bian_quant.experiments.registry import ExperimentRegistry


def _manifest() -> RunManifest:
    return RunManifest.create(
        strategy_name="pa_baseline",
        code_sha="a" * 40,
        dataset_snapshot_ids=["ohlcv-v1"],
        config={"factor": "legacy.pa"},
        seed=7,
        locked_holdout=LockedHoldout(
            start=datetime(2025, 11, 1, tzinfo=UTC),
            end=datetime(2026, 1, 1, tzinfo=UTC),
        ),
    )


def test_repeated_identity_gets_new_run_id() -> None:
    first = _manifest()
    second = _manifest()
    assert first.identity_sha256 == second.identity_sha256
    assert first.run_id != second.run_id


def test_registry_allows_repeated_experiment_as_new_run(tmp_path: Path) -> None:
    first = _manifest()
    second = _manifest()
    with ExperimentRegistry(tmp_path / "runs.sqlite") as registry:
        registry.create(first)
        registry.create(second)
        assert len(registry.list_runs()) == 2


@pytest.mark.parametrize("terminal", [RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED])
def test_terminal_run_cannot_reopen(tmp_path: Path, terminal: RunStatus) -> None:
    manifest = _manifest()
    with ExperimentRegistry(tmp_path / "runs.sqlite") as registry:
        registry.create(manifest)
        if terminal == RunStatus.BLOCKED:
            registry.transition(manifest.run_id, terminal)
        else:
            registry.transition(manifest.run_id, RunStatus.RUNNING)
            registry.transition(manifest.run_id, terminal)
        with pytest.raises(ValueError, match="invalid run transition"):
            registry.transition(manifest.run_id, RunStatus.RUNNING)


def test_locked_holdout_boundary_round_trips(tmp_path: Path) -> None:
    manifest = _manifest()
    with ExperimentRegistry(tmp_path / "runs.sqlite") as registry:
        registry.create(manifest)
        restored = registry.get(manifest.run_id)
    assert restored.locked_holdout == manifest.locked_holdout
    assert len(restored.dataset_snapshot_ids) == 1
