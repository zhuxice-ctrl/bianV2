"""Deterministic event-driven backtest engine.

Processes ``Bar`` and ``SignalEvent`` sequences with explicit rules for
fill timing, slippage, fees, funding, stop/target conflicts, and
exposure limits.  All monetary arithmetic uses ``Decimal`` to ensure
golden-fixture reproducibility.

Causality rules
---------------
1. A signal decided on bar *t* may only fill on bar *t+1*.
2. The reference (fill) price is the next bar's **open**.
3. Adverse slippage is applied on top of the reference price.
4. Stop and target are checked against the fill bar's high/low.
5. ``STOP_FIRST`` exits at the stop when both are touched in one bar.
6. Funding is applied only when a bar timestamp matches a
   ``FundingEvent`` timestamp.
7. Target notional is capped by ``gross_limit * current_equity``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from .events import Bar, BarConflictPolicy, Fill, FundingEvent, SignalEvent, Trade

_BPS = Decimal("10000")


@dataclass(frozen=True)
class BacktestResult:
    """Result of an event-driven backtest run.

    Attributes
    ----------
    trades:
        Completed round-trip trades.
    fills:
        Individual fill records (entries, exits, funding).
    equity:
        Account equity at the end of each bar.
    returns:
        Per-bar returns (fractional).
    diagnostics:
        Rejected-signal counts and other engine metadata.
    """

    trades: list[Trade]
    fills: list[Fill]
    equity: list[Decimal]
    returns: list[Decimal]
    diagnostics: dict[str, Any] = field(default_factory=dict)


class _Position:
    """Mutable position state used during a single backtest run."""

    __slots__ = (
        "direction",
        "qty",
        "notional",
        "entry_price",
        "entry_time",
        "stop",
        "target",
        "cumulative_funding",
    )

    def __init__(self) -> None:
        self.direction: int = 0
        self.qty: Decimal = Decimal("0")
        self.notional: Decimal = Decimal("0")
        self.entry_price: Decimal = Decimal("0")
        self.entry_time: datetime | None = None
        self.stop: Decimal | None = None
        self.target: Decimal | None = None
        self.cumulative_funding: Decimal = Decimal("0")

    @property
    def is_open(self) -> bool:
        return self.direction != 0

    def open(
        self,
        direction: int,
        qty: Decimal,
        notional: Decimal,
        entry_price: Decimal,
        entry_time: datetime,
        stop: Decimal | None,
        target: Decimal | None,
    ) -> None:
        self.direction = direction
        self.qty = qty
        self.notional = notional
        self.entry_price = entry_price
        self.entry_time = entry_time
        self.stop = stop
        self.target = target

    def close(self) -> None:
        self.direction = 0
        self.qty = Decimal("0")
        self.notional = Decimal("0")
        self.entry_price = Decimal("0")
        self.entry_time = None
        self.stop = None
        self.target = None
        self.cumulative_funding = Decimal("0")


class EventEngine:
    """Deterministic event-driven backtesting engine.

    Parameters
    ----------
    taker_fee_bps:
        Taker fee in basis points (e.g. ``Decimal("4")`` = 4 bps).
    slippage_bps:
        Adverse slippage in basis points (e.g. ``Decimal("10")`` = 10 bps).
    initial_equity:
        Starting account equity.
    gross_limit:
        Maximum gross exposure as a fraction of equity (e.g. ``1.0``).
    close_at_end:
        If ``True``, open positions are closed at the final bar's close.
    bar_conflict_policy:
        Policy for same-bar stop+target conflicts.
    """

    def __init__(
        self,
        *,
        taker_fee_bps: Decimal = Decimal("4"),
        slippage_bps: Decimal = Decimal("10"),
        initial_equity: Decimal = Decimal("10000"),
        gross_limit: Decimal = Decimal("1.0"),
        close_at_end: bool = True,
        bar_conflict_policy: BarConflictPolicy = BarConflictPolicy.STOP_FIRST,
    ) -> None:
        self.taker_fee_bps = taker_fee_bps
        self.slippage_bps = slippage_bps
        self.initial_equity = initial_equity
        self.gross_limit = gross_limit
        self.close_at_end = close_at_end
        self.bar_conflict_policy = bar_conflict_policy

    # -- public API --------------------------------------------------------

    def run(
        self,
        *,
        bars: list[Bar],
        signals: list[SignalEvent],
        funding_events: list[FundingEvent] | None = None,
    ) -> BacktestResult:
        """Execute the backtest and return results."""
        funding_events = funding_events or []
        fee_rate = self.taker_fee_bps / _BPS
        slip_rate = self.slippage_bps / _BPS

        equity: list[Decimal] = []
        returns: list[Decimal] = []
        fills: list[Fill] = []
        trades: list[Trade] = []
        diagnostics: dict[str, Any] = {"rejected_signals": 0}

        cash = self.initial_equity
        pos = _Position()
        prev_equity = self.initial_equity

        # Track which signals were matched to a bar (for rejection counting)
        matched_signals: set[int] = set()
        funding_by_ts: dict[datetime, Decimal] = {}
        for fe in funding_events:
            funding_by_ts[fe.timestamp] = fe.funding_rate

        # Sort signals by timestamp for deterministic processing
        sorted_signals = sorted(signals, key=lambda s: s.timestamp)

        # Pending signal to execute at next bar
        pending_signal: SignalEvent | None = None

        for i, bar in enumerate(bars):
            # 1. Apply funding for this bar's timestamp if there's an open position
            if pos.is_open and bar.timestamp in funding_by_ts:
                rate = funding_by_ts[bar.timestamp]
                funding_cf = -pos.notional * Decimal(pos.direction) * rate
                cash += funding_cf
                pos.cumulative_funding += funding_cf

            # 2. Execute pending signal at this bar's open
            if pending_signal is not None:
                sig = pending_signal
                pending_signal = None

                # Close existing position if signal direction differs
                if pos.is_open and sig.direction != pos.direction:
                    close_ref = bar.open
                    close_exec = self._slippage(close_ref, -pos.direction, slip_rate)
                    close_fee = close_exec * pos.qty * fee_rate
                    pnl = (close_exec - pos.entry_price) * Decimal(pos.direction) * pos.qty
                    cash += pnl - close_fee
                    fills.append(
                        self._make_fill(
                            bar.timestamp,
                            -pos.direction,
                            close_ref,
                            close_exec,
                            pos.notional,
                            close_fee,
                            "exit_signal",
                        )
                    )
                    trades.append(
                        self._make_trade(
                            pos, bar.timestamp, close_exec, pnl - close_fee, "signal", close_fee
                        )
                    )
                    pos.close()

                # Open new position
                if sig.direction != 0 and not pos.is_open:
                    ref_price = bar.open
                    exec_price = self._slippage(ref_price, sig.direction, slip_rate)

                    # Cap notional
                    requested = sig.notional
                    max_notional = self.gross_limit * cash
                    if requested is not None:
                        notional = min(requested, max_notional)
                    else:
                        notional = max_notional

                    if notional > 0 and exec_price > 0:
                        qty = notional / exec_price
                        entry_fee = exec_price * qty * fee_rate
                        cash -= entry_fee

                        fills.append(
                            self._make_fill(
                                bar.timestamp,
                                sig.direction,
                                ref_price,
                                exec_price,
                                notional,
                                entry_fee,
                                "entry",
                            )
                        )

                        pos.open(
                            direction=sig.direction,
                            qty=qty,
                            notional=notional,
                            entry_price=exec_price,
                            entry_time=bar.timestamp,
                            stop=sig.stop,
                            target=sig.target,
                        )

                # Explicit exit (direction=0)
                elif sig.direction == 0 and pos.is_open:
                    close_ref = bar.open
                    close_exec = self._slippage(close_ref, -pos.direction, slip_rate)
                    close_fee = close_exec * pos.qty * fee_rate
                    pnl = (close_exec - pos.entry_price) * Decimal(pos.direction) * pos.qty
                    cash += pnl - close_fee
                    fills.append(
                        self._make_fill(
                            bar.timestamp,
                            -pos.direction,
                            close_ref,
                            close_exec,
                            pos.notional,
                            close_fee,
                            "exit_signal",
                        )
                    )
                    trades.append(
                        self._make_trade(
                            pos, bar.timestamp, close_exec, pnl - close_fee, "signal", close_fee
                        )
                    )
                    pos.close()

            # 3. Check stop/target on the current bar for open positions
            if pos.is_open:
                exit_info = self._check_bar_exit(bar, pos)
                if exit_info is not None:
                    exit_reason, exit_ref = exit_info
                    # Stop/target exits fill at the reference price (no slippage)
                    exit_exec = exit_ref
                    exit_fee = exit_exec * pos.qty * fee_rate
                    pnl = (exit_exec - pos.entry_price) * Decimal(pos.direction) * pos.qty
                    cash += pnl - exit_fee
                    fills.append(
                        self._make_fill(
                            bar.timestamp,
                            -pos.direction,
                            exit_ref,
                            exit_exec,
                            pos.notional,
                            exit_fee,
                            exit_reason,
                        )
                    )
                    trades.append(
                        self._make_trade(
                            pos, bar.timestamp, exit_exec, pnl - exit_fee, exit_reason, exit_fee
                        )
                    )
                    pos.close()

            # 4. Queue signal for this bar (to execute at next bar)
            for sig_idx, sig in enumerate(sorted_signals):
                if sig.timestamp == bar.timestamp:
                    matched_signals.add(sig_idx)
                    # Signal is causal if its timestamp <= this bar's timestamp
                    # and there's a subsequent bar to execute on
                    if i + 1 < len(bars):
                        pending_signal = sig
                    else:
                        # Signal on last bar can't execute (no next bar)
                        diagnostics["rejected_signals"] += 1
                    break

            # 5. Mark-to-market and record equity
            if pos.is_open:
                unrealized = (bar.close - pos.entry_price) * Decimal(pos.direction) * pos.qty
                current_equity = cash + unrealized
            else:
                current_equity = cash

            equity.append(current_equity)
            if prev_equity != 0:
                bar_return = (current_equity - prev_equity) / prev_equity
            else:
                bar_return = Decimal("0")
            returns.append(bar_return)
            prev_equity = current_equity

        # 6. Close at end if needed
        if pos.is_open:
            last_bar = bars[-1]
            if self.close_at_end:
                close_ref = last_bar.close
                # Close at market: ref_price = exec_price = close (no slippage)
                close_exec = close_ref
                exit_fee = close_exec * pos.qty * fee_rate
                pnl = (close_exec - pos.entry_price) * Decimal(pos.direction) * pos.qty
                cash += pnl - exit_fee
                fills.append(
                    self._make_fill(
                        last_bar.timestamp,
                        -pos.direction,
                        close_ref,
                        close_exec,
                        pos.notional,
                        exit_fee,
                        "end_of_data",
                    )
                )
                trades.append(
                    self._make_trade(
                        pos, last_bar.timestamp, close_exec, pnl - exit_fee, "end_of_data", exit_fee
                    )
                )
                pos.close()
                equity[-1] = cash
                if prev_equity != 0:
                    returns[-1] = (cash - prev_equity) / prev_equity
            # If close_at_end=False, position stays open; equity already marked at close

        # 7. Count unmatched signals as rejected (future signals)
        for sig_idx in range(len(sorted_signals)):
            if sig_idx not in matched_signals:
                diagnostics["rejected_signals"] += 1

        return BacktestResult(
            trades=trades,
            fills=fills,
            equity=equity,
            returns=returns,
            diagnostics=diagnostics,
        )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _slippage(price: Decimal, direction: int, slip_rate: Decimal) -> Decimal:
        """Apply adverse slippage: longs pay more, shorts receive less."""
        if direction > 0:
            return price * (Decimal("1") + slip_rate)
        elif direction < 0:
            return price * (Decimal("1") - slip_rate)
        return price

    def _check_bar_exit(self, bar: Bar, pos: _Position) -> tuple[str, Decimal] | None:
        """Check if stop or target is hit on this bar.

        Returns (reason, ref_price) or None.  The execution price equals
        the reference price for stop/target exits (the stop order fills
        at its trigger level).
        """
        direction = pos.direction
        stop = pos.stop
        target = pos.target

        if direction > 0:  # long
            stop_hit = stop is not None and bar.low <= stop
            target_hit = target is not None and bar.high >= target

            if stop_hit and target_hit:
                if self.bar_conflict_policy == BarConflictPolicy.STOP_FIRST:
                    return ("stop", stop)  # type: ignore[return-value]
                else:
                    return ("target", target)  # type: ignore[return-value]
            elif stop_hit:
                return ("stop", stop)  # type: ignore[return-value]
            elif target_hit:
                return ("target", target)  # type: ignore[return-value]
        else:  # short
            stop_hit = stop is not None and bar.high >= stop
            target_hit = target is not None and bar.low <= target

            if stop_hit and target_hit:
                if self.bar_conflict_policy == BarConflictPolicy.STOP_FIRST:
                    return ("stop", stop)  # type: ignore[return-value]
                else:
                    return ("target", target)  # type: ignore[return-value]
            elif stop_hit:
                return ("stop", stop)  # type: ignore[return-value]
            elif target_hit:
                return ("target", target)  # type: ignore[return-value]

        return None

    @staticmethod
    def _make_fill(
        ts: datetime,
        direction: int,
        ref: Decimal,
        exec_: Decimal,
        notional: Decimal,
        fee: Decimal,
        reason: str,
    ) -> Fill:
        return Fill(
            timestamp=ts,
            direction=direction,
            ref_price=ref,
            exec_price=exec_,
            notional=notional,
            fee=fee,
            reason=reason,
        )

    @staticmethod
    def _make_trade(
        pos: _Position,
        exit_time: datetime,
        exit_price: Decimal,
        pnl: Decimal,
        exit_reason: str,
        fee_paid: Decimal,
    ) -> Trade:
        return Trade(
            entry_time=pos.entry_time or exit_time,
            exit_time=exit_time,
            direction=pos.direction,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            notional=pos.notional,
            pnl=pnl,
            exit_reason=exit_reason,
            fee_paid=fee_paid,
            funding_paid=pos.cumulative_funding,
        )
