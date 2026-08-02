"""Reporting tests: exclusive cycle directories and 30-day review summary."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from bian_quant.paper.ledger import PaperLedger
from bian_quant.paper.models import PaperCycleStatus, PaperDecision, PaperRunConfig
from bian_quant.paper.reporting import (
    CYCLE_FILES,
    build_review_summary,
    render_review_summary,
    write_cycle_artifacts,
)

T0 = datetime(2026, 8, 3, 8, 0, tzinfo=UTC)


def _config() -> PaperRunConfig:
    return PaperRunConfig.model_validate(
        {
            "run_id": "paper-run-rpt",
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


def _decision(scheduled: datetime, *, trade: bool = False) -> PaperDecision:
    return PaperDecision(
        run_id="paper-run-rpt",
        scheduled_time=scheduled,
        decision_time=scheduled,
        status=PaperCycleStatus.TRADE if trade else PaperCycleStatus.NO_TRADE,
        reason_code="PAPER_TRADE_OPENED" if trade else "PAPER_NO_SIGNAL",
        asset="BTCUSDT" if trade else None,
        side="BUY" if trade else None,
        quantity=Decimal("0.5") if trade else None,
        entry=Decimal("110") if trade else None,
        stop=Decimal("96.8") if trade else None,
        target=Decimal("121") if trade else None,
        notional=Decimal("55") if trade else None,
        stop_risk=Decimal("6.6") if trade else None,
        equity_before=Decimal("100"),
        equity_after=Decimal("100"),
    )


def test_cycle_directory_contains_all_files(tmp_path: Path) -> None:
    decision = _decision(T0, trade=True)
    cycle_dir = write_cycle_artifacts(tmp_path / "artifacts", decision)
    for filename in CYCLE_FILES:
        assert (cycle_dir / filename).exists(), f"missing {filename}"
    payload = json.loads((cycle_dir / "decision.json").read_text(encoding="utf-8"))
    assert payload["status"] == "TRADE"
    orders = json.loads((cycle_dir / "orders.json").read_text(encoding="utf-8"))
    assert orders["orders"][0]["asset"] == "BTCUSDT"


def test_cycle_directory_is_exclusive(tmp_path: Path) -> None:
    decision = _decision(T0)
    write_cycle_artifacts(tmp_path / "artifacts", decision)
    import pytest

    with pytest.raises(FileExistsError):
        write_cycle_artifacts(tmp_path / "artifacts", decision)


def test_review_summary_reports_missing_slots(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    config = _config()
    ledger.record(_decision(T0))
    now = T0 + timedelta(hours=12)
    summary = build_review_summary(ledger, config, now=now)
    assert summary["run_id"] == "paper-run-rpt"
    assert summary["review_ready"] is False
    # Slots at +4h and +8h are overdue relative to now=+12h; +12h is the frontier.
    assert len(summary["missing_slots"]) >= 1
    ledger.close()


def test_review_summary_not_ready_on_timing_violation(tmp_path: Path) -> None:
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    config = _config()
    slot = T0
    end = T0 + timedelta(days=31)
    violated = False
    while slot < end:
        decision = _decision(slot)
        if not violated and slot > T0 + timedelta(days=15):
            decision = decision.model_copy(update={"timing_violation": True})
            violated = True
        ledger.record(decision)
        slot += timedelta(hours=4)
    summary = build_review_summary(ledger, config, now=end)
    assert summary["review_ready"] is False
    markdown = render_review_summary(summary)
    assert "Review ready: NO" in markdown
    ledger.close()
