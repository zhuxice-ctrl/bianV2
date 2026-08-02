"""One deterministic four-hour paper cycle.

The runner captures public market data, enforces the Approved Plan-A lineage,
reuses the small-account risk sizer, and appends exactly one paper decision to
the ledger.  It has no exchange trading client and never imports a private
endpoint, a trading adapter, or urllib request headers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from bian_quant.backtest.small_account import (
    ContractRules,
    RejectedOrder,
    SizedOrder,
    SmallAccountLimits,
    size_order,
)
from bian_quant.paper.ledger import PaperLedger
from bian_quant.paper.market_data import PaperDataBlocked, PublicPaperMarketDataClient
from bian_quant.paper.models import (
    MarketDataCapture,
    PaperCycleStatus,
    PaperDecision,
    PaperPortfolioState,
    PaperPosition,
    PaperRunConfig,
)

#: Conservative default contract filters when no exchange filter is configured.
DEFAULT_RULES = ContractRules(
    asset="BTCUSDT",
    min_qty=Decimal("0.001"),
    step_size=Decimal("0.001"),
    min_notional=Decimal("5"),
    tick_size=Decimal("0.01"),
)

_SIGNAL_LOOKBACK = 20


def run_paper_cycle(
    config: PaperRunConfig,
    *,
    scheduled_time: datetime,
    client: PublicPaperMarketDataClient,
    ledger: PaperLedger,
) -> PaperDecision:
    """Run one guarded four-hour paper cycle and append its decision."""
    decision_time = scheduled_time

    # 1. Four-hour UTC alignment.
    _require_aligned(scheduled_time)

    # 2. Approved Plan-A lineage gate.
    _require_approved(config)

    ledger.register_run(config)
    state = ledger.load_state(config)

    equity_before = state.equity
    open_positions = list(state.positions)

    # 3. Risk pause: a prior stop / drawdown pauses new entries.
    if state.is_paused(scheduled_time):
        return _persist(
            ledger,
            config,
            scheduled_time,
            decision_time,
            PaperCycleStatus.NO_TRADE,
            "PAPER_RISK_PAUSED",
            equity_before=equity_before,
            equity_after=equity_before,
            captures=(),
            positions=tuple(open_positions),
        )

    # 4. Capture public klines for the decision asset.
    try:
        capture = client.capture_klines(config.decision_asset, scheduled_time)
    except PaperDataBlocked as blocked:
        return _persist(
            ledger,
            config,
            scheduled_time,
            decision_time,
            PaperCycleStatus.NO_TRADE,
            blocked.code,
            equity_before=equity_before,
            equity_after=equity_before,
            captures=(),
            positions=tuple(open_positions),
        )

    bars = _klines(capture.parsed)
    if not bars:
        return _persist(
            ledger,
            config,
            scheduled_time,
            decision_time,
            PaperCycleStatus.NO_TRADE,
            "PAPER_DATA_MALFORMED",
            equity_before=equity_before,
            equity_after=equity_before,
            captures=(capture,),
            positions=tuple(open_positions),
        )

    # 5. Freshness: the most recent closed bar must close within one interval.
    last_close_time = bars[-1].close_time
    if scheduled_time - last_close_time > config.interval:
        return _persist(
            ledger,
            config,
            scheduled_time,
            decision_time,
            PaperCycleStatus.NO_TRADE,
            "PAPER_DATA_STALE",
            equity_before=equity_before,
            equity_after=equity_before,
            captures=(capture,),
            positions=tuple(open_positions),
        )

    # 6. Evaluate open positions against the latest bar (stop / target).
    realized = Decimal("0")
    survivors: list[PaperPosition] = []
    for position in open_positions:
        outcome = _evaluate(position, bars[-1])
        if outcome is None:
            survivors.append(position)
        else:
            realized += outcome
    equity_after = equity_before + realized
    risk_breach = _is_risk_breach(config, state, equity_after)

    # 7. Generate a new signal only when flat and not breached.
    signal = _momentum_signal(bars, stop_distance_pct=config.stop_distance_pct)
    new_position: PaperPosition | None = None
    if not survivors and not risk_breach and signal is not None:
        sized = _size(config, signal, open_positions=())
        if isinstance(sized, SizedOrder):
            new_position = PaperPosition(
                run_id=config.run_id,
                scheduled_time=scheduled_time,
                asset=config.decision_asset,
                side=signal.side,
                quantity=sized.quantity,
                entry=sized.entry,
                stop=sized.stop,
                target=_target_price(sized.entry, signal.side, config),
                notional=sized.notional,
                stop_risk=sized.stop_risk,
            )
            survivors.append(new_position)

    if new_position is not None:
        status = PaperCycleStatus.TRADE
        reason_code = "PAPER_TRADE_OPENED"
        decision = _build_decision(
            config,
            scheduled_time,
            decision_time,
            status,
            reason_code,
            equity_before=equity_before,
            equity_after=equity_after,
            capture=capture,
            position=new_position,
            risk_breach=risk_breach,
        )
    else:
        status = PaperCycleStatus.NO_TRADE
        reason_code = "PAPER_NO_SIGNAL"
        decision = _build_decision(
            config,
            scheduled_time,
            decision_time,
            status,
            reason_code,
            equity_before=equity_before,
            equity_after=equity_after,
            capture=capture,
            position=None,
            risk_breach=risk_breach,
        )

    ledger.record(decision, captures=(capture,), positions=tuple(survivors))
    return decision


# -- helpers -----------------------------------------------------------------


def _require_aligned(scheduled_time: datetime) -> None:
    aware = scheduled_time.astimezone(UTC)
    if aware.minute or aware.second or aware.microsecond or aware.hour % 4 != 0:
        raise ValueError("PAPER_CYCLE_NOT_ALIGNED: scheduled_time must be a 4h UTC boundary")


def _require_approved(config: PaperRunConfig) -> None:
    from bian_quant.paper.models import PaperFactorState

    if config.approved_factor_state != PaperFactorState.APPROVED:
        raise PermissionError(
            f"PAPER_APPROVAL_REQUIRED: factor state is {config.approved_factor_state.value}"
        )
    for artifact in (config.holdout_artifact_path, config.small_account_artifact_path):
        if not Path(artifact).exists():
            raise PermissionError(f"PAPER_APPROVAL_REQUIRED: missing artifact {artifact}")


def _is_risk_breach(
    config: PaperRunConfig, state: PaperPortfolioState, equity_after: Decimal
) -> bool:
    daily_loss = max(Decimal("0"), state.equity - equity_after) + state.daily_loss
    if daily_loss >= config.daily_loss_pause_usdt:
        return True
    return (state.high_water_mark - equity_after) >= config.drawdown_pause_usdt


def _persist(
    ledger: PaperLedger,
    config: PaperRunConfig,
    scheduled_time: datetime,
    decision_time: datetime,
    status: PaperCycleStatus,
    reason_code: str,
    *,
    equity_before: Decimal,
    equity_after: Decimal,
    captures: tuple[MarketDataCapture, ...],
    positions: tuple[PaperPosition, ...],
) -> PaperDecision:
    decision = PaperDecision(
        run_id=config.run_id,
        scheduled_time=scheduled_time,
        decision_time=decision_time,
        status=status,
        reason_code=reason_code,
        equity_before=equity_before,
        equity_after=equity_after,
        risk_breach=_is_risk_breach(
            config,
            PaperPortfolioState(
                run_id=config.run_id,
                equity=equity_before,
                high_water_mark=equity_before,
            ),
            equity_after,
        ),
    )
    ledger.record(decision, captures=captures, positions=positions)
    return decision


def _build_decision(
    config: PaperRunConfig,
    scheduled_time: datetime,
    decision_time: datetime,
    status: PaperCycleStatus,
    reason_code: str,
    *,
    equity_before: Decimal,
    equity_after: Decimal,
    capture: MarketDataCapture,
    position: PaperPosition | None,
    risk_breach: bool,
) -> PaperDecision:
    return PaperDecision(
        run_id=config.run_id,
        scheduled_time=scheduled_time,
        decision_time=decision_time,
        status=status,
        reason_code=reason_code,
        asset=position.asset if position else None,
        side=position.side if position else None,
        quantity=position.quantity if position else None,
        entry=position.entry if position else None,
        stop=position.stop if position else None,
        target=position.target if position else None,
        notional=position.notional if position else None,
        stop_risk=position.stop_risk if position else None,
        equity_before=equity_before,
        equity_after=equity_after,
        captures=(capture,),
        risk_breach=risk_breach,
    )


# -- kline parsing & signals -------------------------------------------------


@dataclass(frozen=True)
class _Bar:
    open_time: datetime
    high: Decimal
    low: Decimal
    close: Decimal
    close_time: datetime


def _klines(parsed: object) -> list[_Bar]:
    if not isinstance(parsed, list):
        return []
    bars: list[_Bar] = []
    for row in parsed:
        if not isinstance(row, list) or len(row) < 7:
            continue
        try:
            bars.append(
                _Bar(
                    open_time=_from_ms(row[0]),
                    high=Decimal(str(row[2])),
                    low=Decimal(str(row[3])),
                    close=Decimal(str(row[4])),
                    close_time=_from_ms(row[6]),
                )
            )
        except (TypeError, ValueError, OSError):
            continue
    return bars


@dataclass(frozen=True)
class _Signal:
    side: str
    entry: Decimal
    stop: Decimal


def _momentum_signal(bars: list[_Bar], *, stop_distance_pct: Decimal) -> _Signal | None:
    if len(bars) < _SIGNAL_LOOKBACK + 1:
        return None
    last = bars[-1].close
    reference = bars[-1 - _SIGNAL_LOOKBACK].close
    if last == reference:
        return None
    return _signal_from(last, reference, stop_distance_pct=stop_distance_pct)


def _signal_from(entry: Decimal, reference: Decimal, *, stop_distance_pct: Decimal) -> _Signal:
    if entry > reference:
        return _Signal(side="BUY", entry=entry, stop=_move(entry, -1, stop_distance_pct))
    return _Signal(side="SELL", entry=entry, stop=_move(entry, 1, stop_distance_pct))


def _move(price: Decimal, direction: int, distance_pct: Decimal) -> Decimal:
    return price * (Decimal(1) + Decimal(direction) * distance_pct)


def _target_price(entry: Decimal, side: str, config: PaperRunConfig) -> Decimal:
    if side == "BUY":
        return entry * (Decimal(1) + config.target_distance_pct)
    return entry * (Decimal(1) - config.target_distance_pct)


def _size(
    config: PaperRunConfig,
    signal: _Signal,
    *,
    open_positions: tuple[PaperPosition, ...],
) -> SizedOrder | RejectedOrder:
    limits = _limits(config)
    rules = ContractRules(
        asset=config.decision_asset,
        min_qty=DEFAULT_RULES.min_qty,
        step_size=DEFAULT_RULES.step_size,
        min_notional=DEFAULT_RULES.min_notional,
        tick_size=DEFAULT_RULES.tick_size,
    )
    open_risks = tuple(p.stop_risk for p in open_positions)
    open_notionals = tuple(p.notional for p in open_positions)
    budget = (
        limits.single_position_risk_usdt if not open_positions else limits.two_position_risk_usdt
    )
    return size_order(
        entry=signal.entry,
        stop=signal.stop,
        ref_price=signal.entry,
        open_risks=open_risks,
        open_notionals=open_notionals,
        rules=rules,
        limits=limits,
        risk_budget=budget,
    )


def _limits(config: PaperRunConfig) -> SmallAccountLimits:
    return SmallAccountLimits(
        initial_equity_usdt=config.initial_equity_usdt,
        max_gross_notional_usdt=config.max_gross_notional_usdt,
        max_positions=config.max_positions,
        single_position_risk_usdt=config.single_position_risk_usdt,
        two_position_risk_usdt=config.two_position_risk_usdt,
        daily_loss_pause_usdt=config.daily_loss_pause_usdt,
        drawdown_pause_usdt=config.drawdown_pause_usdt,
        taker_fee_bps=Decimal("4"),
        slippage_bps=Decimal("10"),
        interval="4h",
    )


def _evaluate(position: PaperPosition, bar: _Bar) -> Decimal | None:
    """Return realized PnL if *position* was stopped / targeted by *bar*, else None."""
    if position.side == "BUY":
        if bar.low <= position.stop:
            return -position.stop_risk
        if bar.high >= position.target:
            gain = position.notional * (position.target - position.entry) / position.entry
            return gain
        return None
    # short
    if bar.high >= position.stop:
        return -position.stop_risk
    if bar.low <= position.target:
        gain = position.notional * (position.entry - position.target) / position.entry
        return gain
    return None


def _from_ms(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, bytes, bytearray)):
        raise ValueError("millisecond epoch is invalid")
    return datetime.fromtimestamp(int(value) / 1000, tz=UTC)


__all__ = ["run_paper_cycle", "DEFAULT_RULES"]
