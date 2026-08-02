"""Unit tests for ranked two-position 100 USDT portfolio replay."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from bian_quant.backtest.events import Bar, SignalEvent
from bian_quant.backtest.portfolio import replay_ranked_portfolio
from bian_quant.backtest.small_account import ContractRules, SmallAccountLimits

PORTFOLIO = Path("configs/backtests/popular_universe_100u.yaml")


def _bar(timestamp: datetime, price: Decimal) -> Bar:
    return Bar(
        timestamp=timestamp,
        open=price,
        high=price + Decimal("5"),
        low=price - Decimal("5"),
        close=price,
        volume=Decimal("1000"),
    )


def _rules(asset: str) -> ContractRules:
    return ContractRules(asset, Decimal("0.01"), Decimal("0.01"), Decimal("0.1"), Decimal("5"))


def _signal(asset: str, rank: int, timestamp: datetime, stop: Decimal) -> SignalEvent:
    return SignalEvent(
        timestamp=timestamp,
        direction=1,
        stop=stop,
        asset=asset,
        rank=rank,
    )


def test_ranked_portfolio_admits_two_legs_and_rejects_third() -> None:
    limits = SmallAccountLimits.from_yaml(PORTFOLIO)
    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=4)
    t2 = t0 + timedelta(hours=8)
    t3 = t0 + timedelta(hours=12)
    bars = [
        _bar(t0, Decimal("100")),
        _bar(t1, Decimal("100")),
        _bar(t2, Decimal("101")),
        _bar(t3, Decimal("102")),
    ]
    signals = [
        _signal("ALPHAUSDT", 1, t0, Decimal("80")),
        _signal("BETAUSDT", 2, t0, Decimal("80")),
        _signal("GAMMAUSDT", 3, t0, Decimal("80")),
    ]
    result = replay_ranked_portfolio(
        bars=bars,
        signals=signals,
        limits=limits,
        contract_rules={
            "ALPHAUSDT": _rules("ALPHAUSDT"),
            "BETAUSDT": _rules("BETAUSDT"),
            "GAMMAUSDT": _rules("GAMMAUSDT"),
        },
    )
    entries = [fill for fill in result.fills if fill.reason == "entry"]
    assert [fill.timestamp for fill in entries] == [t1, t1]
    assert [fill.direction for fill in entries] == [1, 1]
    # Both legs sized at 5 USDT risk: notional 25 with a 20 USDT stop distance.
    assert all(fill.notional == Decimal("25") for fill in entries)
    assert result.maximum_gross <= Decimal("90")
    reasons = {rejection["reason"] for rejection in result.rejections}
    assert "MAX_POSITIONS_REACHED" in reasons


def test_future_signal_without_next_bar_is_rejected() -> None:
    limits = SmallAccountLimits.from_yaml(PORTFOLIO)
    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=4)
    bars = [_bar(t0, Decimal("100")), _bar(t1, Decimal("100"))]
    # Signal decided at the final bar has no subsequent bar to fill on.
    signals = [_signal("ALPHAUSDT", 1, t1, Decimal("80"))]
    result = replay_ranked_portfolio(
        bars=bars,
        signals=signals,
        limits=limits,
        contract_rules={"ALPHAUSDT": _rules("ALPHAUSDT")},
    )
    reasons = {rejection["reason"] for rejection in result.rejections}
    assert "NO_NEXT_BAR" in reasons
    assert not any(fill.reason == "entry" for fill in result.fills)


def test_stop_exit_closes_position_with_stop_first_semantics() -> None:
    limits = SmallAccountLimits.from_yaml(PORTFOLIO)
    t0 = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)
    t1 = t0 + timedelta(hours=4)
    t2 = t0 + timedelta(hours=8)
    # The fill bar opens at 100; the next bar breaches the 80 stop.
    bars = [
        _bar(t0, Decimal("100")),
        Bar(t1, Decimal("100"), Decimal("105"), Decimal("95"), Decimal("101"), Decimal("1000")),
        Bar(t2, Decimal("101"), Decimal("106"), Decimal("79"), Decimal("80"), Decimal("1000")),
    ]
    signals = [_signal("ALPHAUSDT", 1, t0, Decimal("80"))]
    result = replay_ranked_portfolio(
        bars=bars,
        signals=signals,
        limits=limits,
        contract_rules={"ALPHAUSDT": _rules("ALPHAUSDT")},
    )
    exit_fills = [fill for fill in result.fills if fill.reason == "stop"]
    assert exit_fills
    assert result.trades
    assert result.trades[0].exit_reason == "stop"
