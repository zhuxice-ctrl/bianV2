"""Append-only ledger continuity and review-readiness tests."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from bian_quant.paper.ledger import PaperLedger
from bian_quant.paper.models import (
    PaperCycleStatus,
    PaperDecision,
    PaperRunConfig,
)

START = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


def _config() -> PaperRunConfig:
    return PaperRunConfig.model_validate(
        {
            "run_id": "paper-run-1",
            "approved_factor_id": "momentum-4h-popular-v1",
            "approved_factor_version": "1.0.0",
            "holdout_artifact_path": "var/holdout.json",
            "small_account_artifact_path": "var/backtest.json",
            "universe_artifact_id": "popular-universe-2026-07-26",
            "snapshot_ids": ("micro-4h-popular-2026-07-26",),
            "decision_assets": ("BTCUSDT",),
            "decision_asset": "BTCUSDT",
        }
    )


def _decision(scheduled: datetime, *, equity_after: str = "100") -> PaperDecision:
    return PaperDecision(
        run_id="paper-run-1",
        scheduled_time=scheduled,
        decision_time=scheduled,
        status=PaperCycleStatus.NO_TRADE,
        reason_code="PAPER_NO_SIGNAL",
        equity_before=Decimal("100"),
        equity_after=Decimal(equity_after),
    )


def test_record_is_unique_by_run_and_time(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    decision = _decision(START)
    ledger.record(decision)
    with pytest.raises(sqlite3.IntegrityError):
        ledger.record(decision)
    ledger.close()


def test_update_and_delete_rejected(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    ledger.record(_decision(START))
    with pytest.raises(sqlite3.DatabaseError, match="APPEND_ONLY"):
        ledger._conn.execute("UPDATE paper_decisions SET status = 'TRADE'")  # noqa: SLF001
    with pytest.raises(sqlite3.DatabaseError, match="APPEND_ONLY"):
        ledger._conn.execute("DELETE FROM paper_decisions")  # noqa: SLF001
    ledger.close()


def test_missing_slots_reports_gap(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    ledger.record(_decision(START))
    end = START + timedelta(hours=8)
    assert ledger.missing_slots(START, end, run_id="paper-run-1") == (START + timedelta(hours=4),)
    ledger.close()


def test_missing_slots_none_when_contiguous(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    ledger.record(_decision(START))
    ledger.record(_decision(START + timedelta(hours=4)))
    end = START + timedelta(hours=8)
    assert ledger.missing_slots(START, end, run_id="paper-run-1") == ()
    ledger.close()


def test_review_readiness_false_before_30_days(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    ledger.record(_decision(START))
    config = _config()
    assert not ledger.review_readiness(config, now=START + timedelta(days=10))
    ledger.close()


def test_review_readiness_true_after_clean_30_days(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    config = _config()
    slot = START
    # Fill 30 days of contiguous four-hour slots with no violation.
    end = START + timedelta(days=30, hours=4)
    while slot < end:
        ledger.record(_decision(slot))
        slot += timedelta(hours=4)
    assert ledger.review_readiness(config, now=end)
    ledger.close()


def test_review_readiness_false_on_risk_breach(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    config = _config()
    slot = START
    end = START + timedelta(days=31)
    breached = False
    while slot < end:
        decision = _decision(slot)
        if not breached and slot > START + timedelta(days=15):
            decision = decision.model_copy(
                update={"risk_breach": True, "reason_code": "PAPER_RISK_BREACH"}
            )
            breached = True
        ledger.record(decision)
        slot += timedelta(hours=4)
    assert not ledger.review_readiness(config, now=end)
    ledger.close()


def test_load_state_returns_initial_when_empty(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    config = _config()
    state = ledger.load_state(config)
    assert state.equity == Decimal("100")
    assert state.positions == ()
    assert state.pause_until is None
    ledger.close()
