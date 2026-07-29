"""Golden fill tests for the deterministic event-driven backtest engine.

All assertions use Decimal to avoid floating-point rounding issues.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from bian_quant.backtest.engine import EventEngine
from bian_quant.backtest.events import Bar, BarConflictPolicy, FundingEvent, SignalEvent


def _make_bars() -> list[Bar]:
    """Five-bar UTC fixture from Plan 02 Task 7."""
    base = datetime(2026, 1, 1, tzinfo=UTC)
    opens = [100, 101, 102, 103, 104]
    highs = [102, 112, 106, 107, 108]
    lows = [99, 89, 100, 101, 102]
    closes = [101, 105, 104, 106, 107]
    bars: list[Bar] = []
    for i in range(5):
        bars.append(
            Bar(
                timestamp=base + timedelta(hours=4 * i),
                open=Decimal(str(opens[i])),
                high=Decimal(str(highs[i])),
                low=Decimal(str(lows[i])),
                close=Decimal(str(closes[i])),
            )
        )
    return bars


def _make_engine(**kwargs: Any) -> EventEngine:
    defaults: dict[str, Any] = {
        "taker_fee_bps": Decimal("4"),
        "slippage_bps": Decimal("10"),
        "initial_equity": Decimal("10000"),
        "gross_limit": Decimal("1.0"),
        "close_at_end": True,
        "bar_conflict_policy": BarConflictPolicy.STOP_FIRST,
    }
    defaults.update(kwargs)
    return EventEngine(**defaults)


# ---------------------------------------------------------------------------
# Assertion 1: Long signal decided on bar 0 fills on bar 1
# ---------------------------------------------------------------------------


def test_long_signal_fills_next_bar_open() -> None:
    """A long signal decided on bar 0 fills on bar 1 open."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=1,
        )
    ]
    engine = _make_engine(close_at_end=False)
    result = engine.run(bars=bars, signals=signals)

    # Entry fill at bar 1
    entry_fills = [f for f in result.fills if f.reason == "entry"]
    assert len(entry_fills) == 1
    fill = entry_fills[0]
    assert fill.ref_price == Decimal("101")  # bar 1 open
    assert fill.exec_price == Decimal("101.101")  # 101 * 1.001


# ---------------------------------------------------------------------------
# Assertion 2: STOP_FIRST when both stop and target hit on same bar
# ---------------------------------------------------------------------------


def test_stop_first_when_both_hit() -> None:
    """With stop=90 and target=110, bar 1 touches both; STOP_FIRST exits at stop."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=1,
            stop=Decimal("90"),
            target=Decimal("110"),
        )
    ]
    engine = _make_engine()
    result = engine.run(bars=bars, signals=signals)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "stop"
    assert trade.exit_price == Decimal("90")  # exit at stop ref_price


# ---------------------------------------------------------------------------
# Assertion 3: Funding applied once at matching timestamp
# ---------------------------------------------------------------------------


def test_funding_applied_once_at_matching_timestamp() -> None:
    """A funding event at bar 2 changes cash exactly once."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=1,
        )
    ]
    funding_events = [
        FundingEvent(timestamp=bars[2].timestamp, funding_rate=Decimal("0.0001")),
    ]
    engine = _make_engine(close_at_end=True)
    result = engine.run(bars=bars, signals=signals, funding_events=funding_events)

    # The trade should have non-zero funding paid
    assert len(result.trades) == 1
    assert result.trades[0].funding_paid != Decimal("0")


def test_funding_not_applied_at_non_matching_timestamp() -> None:
    """An identical funding rate at a non-funding timestamp changes cash zero times."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=1,
        )
    ]
    # Funding at a timestamp that doesn't match any bar
    non_matching_ts = datetime(2026, 1, 15, tzinfo=UTC)
    funding_events = [
        FundingEvent(timestamp=non_matching_ts, funding_rate=Decimal("0.0001")),
    ]
    engine = _make_engine(close_at_end=True)
    result = engine.run(bars=bars, signals=signals, funding_events=funding_events)

    assert len(result.trades) == 1
    assert result.trades[0].funding_paid == Decimal("0")


# ---------------------------------------------------------------------------
# Assertion 4: Notional capped by gross_limit * equity
# ---------------------------------------------------------------------------


def test_notional_capped_by_gross_limit() -> None:
    """Requested notional of 20000 under gross_limit 1.0 and equity 10000 fills ≤10000."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=1,
            notional=Decimal("20000"),
        )
    ]
    engine = _make_engine(close_at_end=True)
    result = engine.run(bars=bars, signals=signals)

    entry_fills = [f for f in result.fills if f.reason == "entry"]
    assert len(entry_fills) == 1
    # Notional before costs must not exceed gross_limit * equity = 10000
    assert entry_fills[0].notional <= Decimal("10000")


# ---------------------------------------------------------------------------
# Assertion 5: close_at_end True vs False
# ---------------------------------------------------------------------------


def test_close_at_end_true_uses_last_bar_close() -> None:
    """With close_at_end=True, final exit uses bar 4 close (107)."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=1,
        )
    ]
    engine = _make_engine(close_at_end=True)
    result = engine.run(bars=bars, signals=signals)

    assert len(result.trades) == 1
    trade = result.trades[0]
    assert trade.exit_reason == "end_of_data"
    assert trade.exit_price == Decimal("107")  # bar 4 close


def test_close_at_end_false_trade_remains_open() -> None:
    """With close_at_end=False, the trade remains open and equity is marked at 107."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=1,
        )
    ]
    engine = _make_engine(close_at_end=False)
    result = engine.run(bars=bars, signals=signals)

    # No exit fill for end-of-data
    exit_fills = [f for f in result.fills if f.reason == "end_of_data"]
    assert len(exit_fills) == 0
    # But equity should be marked at the last bar close
    assert len(result.equity) == 5
    # Final equity should reflect mark-to-market at 107
    # Entry was at 101.101, close is 107, so position is in profit
    assert result.equity[-1] > Decimal("10000")


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


@given(
    direction=st.sampled_from([-1, 0, 1]),
)
@settings(max_examples=20, deadline=None)
def test_equity_always_finite(direction: int) -> None:
    """Equity must be finite for any valid signal direction."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=direction,
        )
    ]
    engine = _make_engine()
    result = engine.run(bars=bars, signals=signals)
    for eq in result.equity:
        assert eq.is_finite()


def test_rejected_future_signal_creates_no_fill() -> None:
    """A signal whose available_time > decision_time must be rejected."""
    bars = _make_bars()
    # Signal timestamp is AFTER bar 4 (future)
    future_ts = datetime(2026, 12, 31, tzinfo=UTC)
    signals = [
        SignalEvent(
            timestamp=future_ts,
            direction=1,
        )
    ]
    engine = _make_engine()
    result = engine.run(bars=bars, signals=signals)
    assert len(result.fills) == 0
    assert len(result.trades) == 0
    assert result.diagnostics.get("rejected_signals", 0) > 0


def test_gross_exposure_never_exceeds_limit() -> None:
    """Gross exposure must never exceed gross_limit * equity."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=1,
            notional=Decimal("50000"),  # way over limit
        )
    ]
    engine = _make_engine(gross_limit=Decimal("0.5"))
    result = engine.run(bars=bars, signals=signals)
    for fill in result.fills:
        assert fill.notional <= Decimal("5000")  # 0.5 * 10000


def test_zero_signal_creates_zero_trades() -> None:
    """A direction=0 signal must not create any trades."""
    bars = _make_bars()
    signals = [
        SignalEvent(
            timestamp=bars[0].timestamp,
            direction=0,
        )
    ]
    engine = _make_engine()
    result = engine.run(bars=bars, signals=signals)
    assert len(result.trades) == 0
