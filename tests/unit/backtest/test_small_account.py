"""Unit tests for 100 USDT small-account risk sizing and pause rules."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from bian_quant.backtest.small_account import (
    ContractRules,
    RiskPauseState,
    SmallAccountLimits,
    size_order,
)

PORTFOLIO = Path("configs/backtests/popular_universe_100u.yaml")

RULES = ContractRules(
    "ALPHAUSDT",
    Decimal("0.01"),
    Decimal("0.1"),
    Decimal("0.1"),
    Decimal("5"),
)


def _limits() -> SmallAccountLimits:
    return SmallAccountLimits.from_yaml(PORTFOLIO)


def test_first_order_capped_at_gross_notional_and_risk_below_budget() -> None:
    limits = _limits()
    order = size_order(Decimal("20"), Decimal("18"), Decimal("100"), (), (), RULES, limits)
    assert order.notional == Decimal("90")
    assert order.stop_risk == Decimal("9.0")


def test_second_order_risk_capped_at_five_usdt() -> None:
    limits = _limits()
    second = size_order(
        Decimal("20"),
        Decimal("18"),
        Decimal("100"),
        (Decimal("5"),),
        (),
        RULES,
        limits,
    )
    assert second.stop_risk <= Decimal("5")


def test_min_notional_conflict_is_rejected() -> None:
    limits = _limits()
    reject = size_order(
        Decimal("20"),
        Decimal("18"),
        Decimal("100"),
        (Decimal("5"),),
        (Decimal("89.95"),),
        RULES,
        limits,
    )
    assert reject.reason == "MIN_NOTIONAL_OR_STEP_CONFLICT"


def test_invalid_stop_distance_rejected() -> None:
    limits = _limits()
    reject = size_order(
        Decimal("20"),
        Decimal("20"),
        Decimal("100"),
        (),
        (),
        RULES,
        limits,
    )
    assert reject.reason == "INVALID_STOP_DISTANCE"


def test_daily_loss_pause_until_next_utc_day() -> None:
    state = RiskPauseState(
        daily_loss_pause_usdt=Decimal("10"),
        drawdown_pause_usdt=Decimal("20"),
    )
    assert state.daily_loss_paused(Decimal("10"))
    assert not state.daily_loss_paused(Decimal("9.5"))
    now = datetime(2026, 8, 3, 13, 30, tzinfo=UTC)
    assert state.next_utc_midnight(now) == datetime(2026, 8, 4, 0, 0, tzinfo=UTC)


def test_drawdown_requires_human_review() -> None:
    state = RiskPauseState(
        daily_loss_pause_usdt=Decimal("10"),
        drawdown_pause_usdt=Decimal("20"),
    )
    assert state.drawdown_review_required(Decimal("20"))
    assert not state.drawdown_review_required(Decimal("19.99"))


def test_risk_budget_exhausted_with_two_open_positions() -> None:
    limits = _limits()
    reject = size_order(
        Decimal("20"),
        Decimal("18"),
        Decimal("100"),
        (Decimal("5"), Decimal("5")),
        (Decimal("45"), Decimal("45")),
        RULES,
        limits,
    )
    assert reject.reason == "RISK_BUDGET_EXHAUSTED"
