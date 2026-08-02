"""Deterministic ranked small-account portfolio replay.

Consumes ranked Approved signals and immutable bars/funding events and replays
them as a two-position portfolio under the 100 USDT risk policy.  Fills honour
the same next-bar, adverse-slippage, taker-fee, funding, and ``STOP_FIRST``
semantics as the single-position :class:`~bian_quant.backtest.engine.EventEngine`,
but sizing and admission are governed by
:func:`~bian_quant.backtest.small_account.size_order`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from bian_quant.backtest.events import (
    Bar,
    BarConflictPolicy,
    Fill,
    FundingEvent,
    SignalEvent,
    Trade,
)
from bian_quant.backtest.small_account import (
    ContractRules,
    RejectedOrder,
    SmallAccountLimits,
    size_order,
)

_BPS = Decimal("10000")


@dataclass
class _PortfolioPosition:
    asset: str
    direction: int
    qty: Decimal
    notional: Decimal
    entry_price: Decimal
    entry_time: datetime
    stop: Decimal | None
    target: Decimal | None
    entry_fee: Decimal
    stop_risk: Decimal
    cumulative_funding: Decimal = Decimal("0")


@dataclass
class PortfolioReplayResult:
    """Result of a ranked portfolio replay."""

    fills: list[Fill]
    trades: list[Trade]
    equity: list[Decimal]
    daily_attribution: dict[str, Decimal]
    rejections: list[dict[str, Any]] = field(default_factory=list)
    maximum_gross: Decimal = Decimal("0")
    pause_events: list[dict[str, Any]] = field(default_factory=list)


def _portfolio_budget(open_risks: tuple[Decimal, ...], limits: SmallAccountLimits) -> Decimal:
    """Per-position risk budget for the ranked portfolio.

    A single-position portfolio (``max_positions == 1``) sizes at the full
    10 USDT budget.  A two-position portfolio sizes each leg at 5 USDT (capped
    by the 10 USDT aggregate) so both legs can coexist.
    """
    if limits.max_positions <= 1:
        return limits.single_position_risk_usdt
    remaining = limits.single_position_risk_usdt - sum(open_risks, Decimal("0"))
    if remaining <= 0:
        return Decimal("0")
    return min(limits.two_position_risk_usdt, remaining)


def _slippage(price: Decimal, direction: int, slip_rate: Decimal) -> Decimal:
    if direction > 0:
        return price * (Decimal("1") + slip_rate)
    if direction < 0:
        return price * (Decimal("1") - slip_rate)
    return price


def _resolve_stop(signal: SignalEvent, exec_price: Decimal) -> Decimal | None:
    if signal.stop is not None:
        return signal.stop
    if signal.stop_distance is not None:
        return exec_price - Decimal(signal.direction) * signal.stop_distance
    return None


def _resolve_target(signal: SignalEvent, exec_price: Decimal) -> Decimal | None:
    if signal.target is not None:
        return signal.target
    if signal.target_distance is not None:
        return exec_price + Decimal(signal.direction) * signal.target_distance
    return None


def _bar_exit(
    bar: Bar, pos: _PortfolioPosition, policy: BarConflictPolicy
) -> tuple[str, Decimal] | None:
    direction = pos.direction
    stop = pos.stop
    target = pos.target
    if direction > 0:
        stop_hit = stop is not None and bar.low <= stop
        target_hit = target is not None and bar.high >= target
    else:
        stop_hit = stop is not None and bar.high >= stop
        target_hit = target is not None and bar.low <= target
    if stop_hit and target_hit:
        if policy == BarConflictPolicy.STOP_FIRST:
            return "stop", stop if stop is not None else Decimal("0")
        return "target", target if target is not None else Decimal("0")
    if stop_hit:
        return "stop", stop if stop is not None else Decimal("0")
    if target_hit:
        return "target", target if target is not None else Decimal("0")
    return None


def _close_position(
    pos: _PortfolioPosition,
    exit_time: datetime,
    exit_price: Decimal,
    exit_reason: str,
    fee_rate: Decimal,
    fills: list[Fill],
    trades: list[Trade],
    cash: Decimal,
) -> Decimal:
    exit_fee = exit_price * pos.qty * fee_rate
    pnl = (exit_price - pos.entry_price) * Decimal(pos.direction) * pos.qty
    pnl_net = pnl - pos.entry_fee - exit_fee + pos.cumulative_funding
    fills.append(
        Fill(
            timestamp=exit_time,
            direction=-pos.direction,
            ref_price=exit_price,
            exec_price=exit_price,
            notional=pos.notional,
            fee=exit_fee,
            reason=exit_reason,
        )
    )
    trades.append(
        Trade(
            entry_time=pos.entry_time,
            exit_time=exit_time,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            notional=pos.notional,
            pnl=pnl_net,
            exit_reason=exit_reason,
            fee_paid=pos.entry_fee + exit_fee,
            funding_paid=pos.cumulative_funding,
        )
    )
    return cash + pnl - exit_fee


def replay_ranked_portfolio(
    *,
    bars: list[Bar],
    signals: list[SignalEvent],
    limits: SmallAccountLimits,
    contract_rules: dict[str, ContractRules],
    funding_events: list[FundingEvent] | None = None,
    bar_conflict_policy: BarConflictPolicy = BarConflictPolicy.STOP_FIRST,
) -> PortfolioReplayResult:
    """Replay ranked signals as a two-position 100 USDT portfolio."""
    funding_events = funding_events or []
    if not bars:
        return PortfolioReplayResult([], [], [], {})
    bar_timestamps = [bar.timestamp for bar in bars]
    if bar_timestamps != sorted(bar_timestamps) or len(set(bar_timestamps)) != len(bars):
        raise ValueError("bars must be sorted with unique timestamps")

    fee_rate = limits.taker_fee_bps / _BPS
    slip_rate = limits.slippage_bps / _BPS
    funding_by_ts: dict[datetime, Decimal] = {}
    for event in funding_events:
        if event.timestamp in funding_by_ts:
            raise ValueError("duplicate funding timestamp")
        funding_by_ts[event.timestamp] = event.funding_rate

    signals_by_ts: dict[datetime, list[SignalEvent]] = {}
    for signal in signals:
        signals_by_ts.setdefault(signal.timestamp, []).append(signal)

    positions: list[_PortfolioPosition] = []
    pending: list[SignalEvent] = []
    fills: list[Fill] = []
    trades: list[Trade] = []
    rejections: list[dict[str, Any]] = []
    equity: list[Decimal] = []
    maximum_gross = Decimal("0")
    pause_events: list[dict[str, Any]] = []
    daily_realized: dict[str, Decimal] = {}
    high_water = limits.initial_equity_usdt
    cash = limits.initial_equity_usdt

    for i, bar in enumerate(bars):
        # 1. Funding on open positions.
        if bar.timestamp in funding_by_ts:
            rate = funding_by_ts[bar.timestamp]
            for pos in positions:
                cf = -pos.notional * Decimal(pos.direction) * rate
                cash += cf
                pos.cumulative_funding += cf
                fills.append(
                    Fill(
                        timestamp=bar.timestamp,
                        direction=0,
                        ref_price=bar.close,
                        exec_price=bar.close,
                        notional=pos.notional,
                        fee=cf,
                        reason="funding",
                    )
                )

        # 2. Execute pending signals at this bar's open.
        if pending:
            ordered = sorted(pending, key=lambda sig: (sig.rank, sig.asset))
            pending = []
            for signal in ordered:
                available_time = signal.available_time or signal.timestamp
                if available_time > bar.timestamp:
                    rejections.append(
                        {"asset": signal.asset, "reason": "FUTURE_AVAILABLE", "rank": signal.rank}
                    )
                    continue
                if len(positions) >= limits.max_positions:
                    rejections.append(
                        {
                            "asset": signal.asset,
                            "reason": "MAX_POSITIONS_REACHED",
                            "rank": signal.rank,
                        }
                    )
                    continue
                if signal.direction == 0:
                    continue
                rules = contract_rules.get(signal.asset)
                if rules is None:
                    rejections.append(
                        {
                            "asset": signal.asset,
                            "reason": "CONTRACT_RULES_MISSING",
                            "rank": signal.rank,
                        }
                    )
                    continue
                entry_ref = bar.open
                entry_exec = _slippage(entry_ref, signal.direction, slip_rate)
                stop = _resolve_stop(signal, entry_exec)
                if stop is None:
                    rejections.append(
                        {"asset": signal.asset, "reason": "STOP_MISSING", "rank": signal.rank}
                    )
                    continue
                open_risks = tuple(pos.stop_risk for pos in positions)
                open_notionals = tuple(pos.notional for pos in positions)
                budget = _portfolio_budget(open_risks, limits)
                sized = size_order(
                    entry_ref,
                    stop,
                    entry_ref,
                    open_risks,
                    open_notionals,
                    rules,
                    limits,
                    risk_budget=budget,
                )
                if isinstance(sized, RejectedOrder):
                    rejections.append(
                        {"asset": signal.asset, "reason": sized.reason, "rank": signal.rank}
                    )
                    continue
                entry_fee = entry_exec * sized.quantity * fee_rate
                cash -= entry_fee
                fills.append(
                    Fill(
                        timestamp=bar.timestamp,
                        direction=signal.direction,
                        ref_price=entry_ref,
                        exec_price=entry_exec,
                        notional=sized.notional,
                        fee=entry_fee,
                        reason="entry",
                    )
                )
                positions.append(
                    _PortfolioPosition(
                        asset=signal.asset,
                        direction=signal.direction,
                        qty=sized.quantity,
                        notional=sized.notional,
                        entry_price=entry_exec,
                        entry_time=bar.timestamp,
                        stop=stop,
                        target=_resolve_target(signal, entry_exec),
                        entry_fee=entry_fee,
                        stop_risk=sized.stop_risk,
                    )
                )

        # 3. Check stop/target exits on open positions.
        still_open: list[_PortfolioPosition] = []
        for pos in positions:
            exit_info = _bar_exit(bar, pos, bar_conflict_policy)
            if exit_info is not None:
                exit_reason, exit_price = exit_info
                cash = _close_position(
                    pos, bar.timestamp, exit_price, exit_reason, fee_rate, fills, trades, cash
                )
                day = bar.timestamp.astimezone(UTC).date().isoformat()
                daily_realized[day] = daily_realized.get(day, Decimal("0")) + (
                    (exit_price - pos.entry_price) * Decimal(pos.direction) * pos.qty
                )
            else:
                still_open.append(pos)
        positions = still_open

        # 4. Queue signals decided at this bar for the next bar.
        decided = signals_by_ts.pop(bar.timestamp, [])
        if decided:
            if i + 1 < len(bars):
                pending.extend(decided)
            else:
                for signal in decided:
                    rejections.append(
                        {"asset": signal.asset, "reason": "NO_NEXT_BAR", "rank": signal.rank}
                    )

        # 5. Mark-to-market and record equity / gross / pauses.
        unrealized = sum(
            ((bar.close - pos.entry_price) * Decimal(pos.direction) * pos.qty for pos in positions),
            Decimal("0"),
        )
        current_equity = cash + unrealized
        equity.append(current_equity)
        gross = sum((pos.notional for pos in positions), Decimal("0"))
        if gross > maximum_gross:
            maximum_gross = gross
        if current_equity > high_water:
            high_water = current_equity
        drawdown = high_water - current_equity
        if drawdown >= limits.drawdown_pause_usdt:
            pause_events.append(
                {
                    "timestamp": bar.timestamp.isoformat(),
                    "reason": "DRAWDOWN_REVIEW_REQUIRED",
                    "drawdown": str(drawdown),
                }
            )
        for day, realized in daily_realized.items():
            if -realized >= limits.daily_loss_pause_usdt:
                pause_events.append(
                    {
                        "timestamp": bar.timestamp.isoformat(),
                        "reason": "DAILY_LOSS_PAUSE",
                        "day": day,
                        "loss": str(-realized),
                    }
                )

    # 6. Close any remaining positions at the final bar's close.
    last_bar = bars[-1]
    for pos in positions:
        cash = _close_position(
            pos, last_bar.timestamp, last_bar.close, "end_of_data", fee_rate, fills, trades, cash
        )
    if positions:
        equity[-1] = cash

    return PortfolioReplayResult(
        fills=fills,
        trades=trades,
        equity=equity,
        daily_attribution=daily_realized,
        rejections=rejections,
        maximum_gross=maximum_gross,
        pause_events=pause_events,
    )
