"""Unit tests for the append-only holdout ledger and window partitioning."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from bian_quant.data.acquisition import FactorProtocolConfig
from bian_quant.experiments.holdout import (
    DualHorizonWindows,
    HoldoutLedger,
    partition_dual_horizon_windows,
)
from bian_quant.factors.spec import FactorState


def locked_factor_protocol() -> FactorProtocolConfig:
    """Return the locked factor protocol from the dual-horizon config."""
    return FactorProtocolConfig(
        primary_interval="4h",
        sensitivity_interval="1h",
        development_months=18,
        holdout_months=6,
        development_start=datetime(2024, 7, 1, tzinfo=UTC),
        development_end_exclusive=datetime(2026, 1, 1, tzinfo=UTC),
        holdout_start=datetime(2026, 1, 26, 20, tzinfo=UTC),
        holdout_end=datetime(2026, 7, 26, 19, 59, 59, 999000, tzinfo=UTC),
        bh_alpha=0.05,
        minimum_inference_samples=30,
        max_candidates=20,
        cost_bps=(5, 10),
    )


class TestHoldoutLedger:
    def test_researching_or_observed_factor_cannot_open_holdout(self, tmp_path: Path) -> None:
        ledger = HoldoutLedger(tmp_path / "holdout.sqlite")
        with pytest.raises(PermissionError, match="HOLDOUT_ACCESS_DENIED"):
            ledger.authorize(
                snapshot_id="micro-4h",
                factor_id="momentum_24",
                factor_version="1.0.0",
                factor_state=FactorState.OBSERVED,
                access_run_id="run-1",
            )

    def test_candidate_factor_can_open_holdout(self, tmp_path: Path) -> None:
        ledger = HoldoutLedger(tmp_path / "holdout.sqlite")
        record = ledger.authorize(
            snapshot_id="micro-4h",
            factor_id="momentum_24",
            factor_version="1.0.0",
            factor_state=FactorState.CANDIDATE,
            access_run_id="run-1",
        )
        assert record["factor_id"] == "momentum_24"
        assert record["access_run_id"] == "run-1"

    def test_same_snapshot_factor_version_can_be_opened_only_once(self, tmp_path: Path) -> None:
        ledger = HoldoutLedger(tmp_path / "holdout.sqlite")
        ledger.authorize(
            snapshot_id="micro-4h",
            factor_id="momentum_24",
            factor_version="1.0.0",
            factor_state=FactorState.CANDIDATE,
            access_run_id="run-1",
        )
        with pytest.raises(PermissionError, match="HOLDOUT_ACCESS_DENIED"):
            ledger.authorize(
                snapshot_id="micro-4h",
                factor_id="momentum_24",
                factor_version="1.0.0",
                factor_state=FactorState.CANDIDATE,
                access_run_id="run-2",
            )

    def test_different_version_can_open_separately(self, tmp_path: Path) -> None:
        ledger = HoldoutLedger(tmp_path / "holdout.sqlite")
        ledger.authorize(
            snapshot_id="micro-4h",
            factor_id="momentum_24",
            factor_version="1.0.0",
            factor_state=FactorState.CANDIDATE,
            access_run_id="run-1",
        )
        record = ledger.authorize(
            snapshot_id="micro-4h",
            factor_id="momentum_24",
            factor_version="1.1.0",
            factor_state=FactorState.CANDIDATE,
            access_run_id="run-2",
        )
        assert record["factor_version"] == "1.1.0"

    def test_history_returns_all_records(self, tmp_path: Path) -> None:
        ledger = HoldoutLedger(tmp_path / "holdout.sqlite")
        ledger.authorize(
            snapshot_id="micro-4h",
            factor_id="momentum_24",
            factor_version="1.0.0",
            factor_state=FactorState.CANDIDATE,
            access_run_id="run-1",
        )
        ledger.authorize(
            snapshot_id="micro-4h",
            factor_id="reversal_12",
            factor_version="1.0.0",
            factor_state=FactorState.CANDIDATE,
            access_run_id="run-2",
        )
        history = ledger.history()
        assert len(history) == 2

    def test_researching_state_also_rejected(self, tmp_path: Path) -> None:
        ledger = HoldoutLedger(tmp_path / "holdout.sqlite")
        with pytest.raises(PermissionError, match="HOLDOUT_ACCESS_DENIED"):
            ledger.authorize(
                snapshot_id="micro-4h",
                factor_id="momentum_24",
                factor_version="1.0.0",
                factor_state=FactorState.RESEARCHING,
                access_run_id="run-1",
            )


class TestPartitionDualHorizonWindows:
    def test_alignment_buffer_is_neither_development_nor_holdout(self) -> None:
        index = pd.DatetimeIndex(
            [
                "2025-12-31T20:00:00Z",
                "2026-01-01T00:00:00Z",
                "2026-01-26T16:00:00Z",
                "2026-01-26T20:00:00Z",
            ]
        )
        windows = partition_dual_horizon_windows(index, locked_factor_protocol())
        assert isinstance(windows, DualHorizonWindows)
        assert list(windows.development) == [pd.Timestamp("2025-12-31T20:00:00Z")]
        assert list(windows.alignment_buffer) == [
            pd.Timestamp("2026-01-01T00:00:00Z"),
            pd.Timestamp("2026-01-26T16:00:00Z"),
        ]
        assert list(windows.holdout) == [pd.Timestamp("2026-01-26T20:00:00Z")]

    def test_development_is_start_inclusive_end_exclusive(self) -> None:
        index = pd.DatetimeIndex(
            [
                "2024-07-01T00:00:00Z",
                "2025-12-31T20:00:00Z",
                "2026-01-01T00:00:00Z",
            ]
        )
        windows = partition_dual_horizon_windows(index, locked_factor_protocol())
        assert pd.Timestamp("2024-07-01T00:00:00Z") in windows.development
        assert pd.Timestamp("2025-12-31T20:00:00Z") in windows.development
        # development_end_exclusive is NOT in development
        assert pd.Timestamp("2026-01-01T00:00:00Z") not in windows.development

    def test_holdout_is_start_inclusive_end_inclusive(self) -> None:
        index = pd.DatetimeIndex(
            [
                "2026-01-26T20:00:00Z",
                "2026-07-26T19:59:59.999000Z",
            ]
        )
        windows = partition_dual_horizon_windows(index, locked_factor_protocol())
        assert len(windows.holdout) == 2

    def test_empty_index_returns_empty_windows(self) -> None:
        index = pd.DatetimeIndex([])
        windows = partition_dual_horizon_windows(index, locked_factor_protocol())
        assert len(windows.development) == 0
        assert len(windows.alignment_buffer) == 0
        assert len(windows.holdout) == 0

    def test_no_overlap_between_windows(self) -> None:
        index = pd.date_range("2025-12-30", "2026-02-01", freq="4h", tz="UTC")
        windows = partition_dual_horizon_windows(index, locked_factor_protocol())
        all_indices = (
            list(windows.development) + list(windows.alignment_buffer) + list(windows.holdout)
        )
        assert len(all_indices) == len(set(all_indices))
