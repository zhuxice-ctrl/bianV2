"""End-to-end paper-cycle integration tests with injected fixtures."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from bian_quant.paper.ledger import PaperLedger
from bian_quant.paper.market_data import (
    PublicPaperMarketDataClient,
    RawResponse,
)
from bian_quant.paper.models import PaperFactorState, PaperRunConfig
from bian_quant.paper.runner import run_paper_cycle

# 2026-08-03 00:00 UTC — five 4h slots (00, 04, 08, 12, 16) fit inside one
# calendar day so the daily-loss pause is observable before the UTC reset.
T0 = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)


def _bar(open_time_ms: int, *, high: str, low: str, close: str) -> list:
    close_time = open_time_ms + 4 * 3600 * 1000
    return [open_time_ms, "100.0", high, low, close, "10.0", close_time, "1000.0", 10, "0.5", "0"]


def _klines_bytes(
    last_close_time: datetime,
    *,
    closes: list[str] | None = None,
    last_low: str = "99.0",
    last_high: str = "101.0",
    bars: int = 25,
) -> bytes:
    """Build a klines payload ending at *last_close_time*."""
    close_ms = int(last_close_time.timestamp() * 1000)
    if closes is None:
        closes = ["100.0"] * bars
    rows: list[list] = []
    base_open = close_ms - bars * 4 * 3600 * 1000
    for i in range(bars):
        open_ms = base_open + i * 4 * 3600 * 1000
        rows.append(_bar(open_ms, high=last_high, low=last_low, close=closes[i]))
    return json.dumps(rows).encode("utf-8")


class _FixtureClient(PublicPaperMarketDataClient):
    """Paper client whose byte_reader returns a queued payload per call."""

    def __init__(self, payloads: Iterator[bytes]) -> None:
        self._queue = payloads
        super().__init__(byte_reader=self._next)  # type: ignore[arg-type]

    def _next(self, url: str) -> RawResponse:
        return RawResponse(status=200, body=next(self._queue))


def _config(
    tmp_path: Path,
    *,
    stop_distance_pct: str = "0.02",
    state: PaperFactorState = PaperFactorState.APPROVED,
) -> PaperRunConfig:
    holdout = tmp_path / "holdout.json"
    backtest = tmp_path / "backtest.json"
    holdout.write_text("{}", encoding="utf-8")
    backtest.write_text("{}", encoding="utf-8")
    return PaperRunConfig.model_validate(
        {
            "run_id": "paper-run-it",
            "approved_factor_id": "momentum-4h-popular-v1",
            "approved_factor_version": "1.0.0",
            "approved_factor_state": state.value,
            "holdout_artifact_path": str(holdout),
            "small_account_artifact_path": str(backtest),
            "universe_artifact_id": "popular-universe-2026-07-26",
            "snapshot_ids": ("micro-4h-popular-2026-07-26",),
            "decision_assets": ("BTCUSDT",),
            "decision_asset": "BTCUSDT",
            "stop_distance_pct": stop_distance_pct,
            "artifact_root": str(tmp_path / "artifacts"),
        }
    )


RISING = ["100.0"] * 24 + ["110.0"]
FLAT = ["110.0"] * 25


def test_on_time_cycle_records_trade(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    client = _FixtureClient(iter([_klines_bytes(T0, closes=RISING)]))
    decision = run_paper_cycle(config, scheduled_time=T0, client=client, ledger=ledger)
    assert decision.status.value == "TRADE"
    assert decision.asset == "BTCUSDT"
    assert decision.side == "BUY"
    assert ledger.decision_count(config.run_id) == 1
    ledger.close()


def test_stale_klines_record_no_trade(tmp_path: Path) -> None:
    config = _config(tmp_path)
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    stale_close = T0 - timedelta(hours=8)
    client = _FixtureClient(iter([_klines_bytes(stale_close)]))
    decision = run_paper_cycle(config, scheduled_time=T0, client=client, ledger=ledger)
    assert decision.status.value == "NO_TRADE"
    assert decision.reason_code == "PAPER_DATA_STALE"
    ledger.close()


def test_observed_factor_lineage_raises(tmp_path: Path) -> None:
    config = _config(tmp_path, state=PaperFactorState.OBSERVED)
    ledger = PaperLedger(tmp_path / "paper.sqlite")
    client = _FixtureClient(iter([_klines_bytes(T0)]))
    with pytest.raises(PermissionError, match="PAPER_APPROVAL_REQUIRED"):
        run_paper_cycle(config, scheduled_time=T0, client=client, ledger=ledger)
    ledger.close()


def test_ten_usdt_stop_pauses_later_decisions(tmp_path: Path) -> None:
    # A 12% stop sizes each position near the 10 USDT risk budget. Two stops
    # inside one UTC day accumulate > 10 USDT of daily loss, triggering the
    # daily-loss pause on the following slot.
    config = _config(tmp_path, stop_distance_pct="0.12")
    ledger = PaperLedger(tmp_path / "paper.sqlite")

    slots = [T0 + timedelta(hours=4 * i) for i in range(5)]
    payloads = [
        _klines_bytes(slots[0], closes=RISING, last_low="99.0"),  # open long
        _klines_bytes(slots[1], closes=FLAT, last_low="95.0"),  # stop filled
        _klines_bytes(slots[2], closes=RISING, last_low="99.0"),  # open long
        _klines_bytes(slots[3], closes=FLAT, last_low="95.0"),  # stop filled
        _klines_bytes(slots[4], closes=FLAT, last_low="99.0"),  # paused
    ]
    client = _FixtureClient(iter(payloads))

    first = run_paper_cycle(config, scheduled_time=slots[0], client=client, ledger=ledger)
    assert first.status.value == "TRADE"
    assert first.stop_risk is not None and first.stop_risk >= Decimal("9.5")

    second = run_paper_cycle(config, scheduled_time=slots[1], client=client, ledger=ledger)
    assert second.status.value == "NO_TRADE"  # stop realised, no new signal

    third = run_paper_cycle(config, scheduled_time=slots[2], client=client, ledger=ledger)
    assert third.status.value == "TRADE"

    fourth = run_paper_cycle(config, scheduled_time=slots[3], client=client, ledger=ledger)
    assert fourth.status.value == "NO_TRADE"
    assert fourth.risk_breach is True

    fifth = run_paper_cycle(config, scheduled_time=slots[4], client=client, ledger=ledger)
    assert fifth.status.value == "NO_TRADE"
    assert fifth.reason_code == "PAPER_RISK_PAUSED"
    ledger.close()
