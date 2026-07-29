"""Tests for the append-only experiment registry."""

from __future__ import annotations

import pytest

from bian_quant.experiments.models import RunManifest, RunStatus
from bian_quant.experiments.registry import LEGAL_TRANSITIONS, ExperimentRegistry


def _make_manifest(
    *,
    strategy_name: str = "pa_baseline",
    data_snapshot_id: str = "snap_001",
    code_sha256: str = "a" * 64,
) -> RunManifest:
    return RunManifest.create(
        strategy_name=strategy_name,
        config={" timeframe": "4h", "universe": ["BTCUSDT"]},
        code_sha256=code_sha256,
        data_snapshot_id=data_snapshot_id,
    )


class TestRunManifest:
    def test_create_produces_sha256_id(self):
        m = _make_manifest()
        assert len(m.run_id) == 64
        assert all(c in "0123456789abcdef" for c in m.run_id)

    def test_create_deterministic(self):
        m1 = RunManifest.create(
            strategy_name="s",
            config={"a": 1},
            code_sha256="b" * 64,
            data_snapshot_id="d",
        )
        m2 = RunManifest.create(
            strategy_name="s",
            config={"a": 1},
            code_sha256="b" * 64,
            data_snapshot_id="d",
        )
        assert m1.run_id == m2.run_id

    def test_different_config_different_id(self):
        m1 = RunManifest.create(
            strategy_name="s",
            config={"a": 1},
            code_sha256="b" * 64,
            data_snapshot_id="d",
        )
        m2 = RunManifest.create(
            strategy_name="s",
            config={"a": 2},
            code_sha256="b" * 64,
            data_snapshot_id="d",
        )
        assert m1.run_id != m2.run_id

    def test_default_status_pending(self):
        m = _make_manifest()
        assert m.status == RunStatus.PENDING

    def test_frozen(self):
        m = _make_manifest()
        with pytest.raises(Exception):
            m.status = RunStatus.RUNNING  # type: ignore[misc]


class TestRegistryCreate:
    def test_create_and_get(self):
        with ExperimentRegistry() as reg:
            m = _make_manifest()
            reg.create(m)
            fetched = reg.get(m.run_id)
            assert fetched.run_id == m.run_id
            assert fetched.status == RunStatus.PENDING

    def test_duplicate_run_id_rejected(self):
        with ExperimentRegistry() as reg:
            m = _make_manifest()
            reg.create(m)
            with pytest.raises(ValueError, match="already exists"):
                reg.create(m)

    def test_get_missing_raises(self):
        with ExperimentRegistry() as reg:
            with pytest.raises(KeyError):
                reg.get("nonexistent")


class TestRegistryTransition:
    def test_legal_transition(self):
        with ExperimentRegistry() as reg:
            m = _make_manifest()
            reg.create(m)
            updated = reg.transition(m.run_id, RunStatus.RUNNING)
            assert updated.status == RunStatus.RUNNING

    def test_illegal_transition_rejected(self):
        with ExperimentRegistry() as reg:
            m = _make_manifest()
            reg.create(m)
            # PENDING -> COMPLETED is illegal
            with pytest.raises(ValueError, match="illegal transition"):
                reg.transition(m.run_id, RunStatus.COMPLETED)

    def test_full_happy_path(self):
        with ExperimentRegistry() as reg:
            m = _make_manifest()
            reg.create(m)
            reg.transition(m.run_id, RunStatus.RUNNING)
            reg.transition(m.run_id, RunStatus.COMPLETED)
            assert reg.get(m.run_id).status == RunStatus.COMPLETED

    def test_cancelled_can_reopen(self):
        with ExperimentRegistry() as reg:
            m = _make_manifest()
            reg.create(m)
            reg.transition(m.run_id, RunStatus.CANCELLED)
            reg.transition(m.run_id, RunStatus.PENDING)
            assert reg.get(m.run_id).status == RunStatus.PENDING

    def test_failed_can_retry(self):
        with ExperimentRegistry() as reg:
            m = _make_manifest()
            reg.create(m)
            reg.transition(m.run_id, RunStatus.RUNNING)
            reg.transition(m.run_id, RunStatus.FAILED)
            reg.transition(m.run_id, RunStatus.PENDING)
            assert reg.get(m.run_id).status == RunStatus.PENDING

    def test_completed_is_terminal(self):
        with ExperimentRegistry() as reg:
            m = _make_manifest()
            reg.create(m)
            reg.transition(m.run_id, RunStatus.RUNNING)
            reg.transition(m.run_id, RunStatus.COMPLETED)
            with pytest.raises(ValueError, match="illegal transition"):
                reg.transition(m.run_id, RunStatus.RUNNING)

    def test_transition_missing_run_raises(self):
        with ExperimentRegistry() as reg:
            with pytest.raises(KeyError):
                reg.transition("nonexistent", RunStatus.RUNNING)


class TestTransitionHistory:
    def test_history_records_all_transitions(self):
        with ExperimentRegistry() as reg:
            m = _make_manifest()
            reg.create(m)
            reg.transition(m.run_id, RunStatus.RUNNING)
            reg.transition(m.run_id, RunStatus.COMPLETED)

            history = reg.transition_history(m.run_id)
            assert len(history) == 3  # create + 2 transitions
            assert history[0]["from_status"] is None
            assert history[0]["to_status"] == "pending"
            assert history[1]["from_status"] == "pending"
            assert history[1]["to_status"] == "running"
            assert history[2]["from_status"] == "running"
            assert history[2]["to_status"] == "completed"


class TestLegalTransitionsMap:
    def test_completed_has_no_outgoing(self):
        assert len(LEGAL_TRANSITIONS[RunStatus.COMPLETED]) == 0

    def test_pending_can_start_or_cancel(self):
        allowed = LEGAL_TRANSITIONS[RunStatus.PENDING]
        assert RunStatus.RUNNING in allowed
        assert RunStatus.CANCELLED in allowed
