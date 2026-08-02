"""100 USDT small-account risk sizing, exchange filters, and pause rules.

All monetary arithmetic uses :class:`~decimal.Decimal` so that golden
fixtures are reproducible.  Sizing never rounds upward: the raw quantity is
floored to the contract step size before any notional check.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import yaml


@dataclass(frozen=True)
class ContractRules:
    """Exchange contract filters for one symbol."""

    asset: str
    min_qty: Decimal
    step_size: Decimal
    min_notional: Decimal
    tick_size: Decimal


@dataclass(frozen=True)
class SmallAccountLimits:
    """Locked 100 USDT portfolio and cost policy."""

    initial_equity_usdt: Decimal
    max_gross_notional_usdt: Decimal
    max_positions: int
    single_position_risk_usdt: Decimal
    two_position_risk_usdt: Decimal
    daily_loss_pause_usdt: Decimal
    drawdown_pause_usdt: Decimal
    taker_fee_bps: Decimal
    slippage_bps: Decimal
    interval: str

    @classmethod
    def from_yaml(cls, path: Path) -> SmallAccountLimits:
        """Load the locked policy from a YAML file."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("small-account config must be a YAML mapping")
        return cls(
            initial_equity_usdt=Decimal(str(data["initial_equity_usdt"])),
            max_gross_notional_usdt=Decimal(str(data["max_gross_notional_usdt"])),
            max_positions=int(data["max_positions"]),
            single_position_risk_usdt=Decimal(str(data["single_position_risk_usdt"])),
            two_position_risk_usdt=Decimal(str(data["two_position_risk_usdt"])),
            daily_loss_pause_usdt=Decimal(str(data["daily_loss_pause_usdt"])),
            drawdown_pause_usdt=Decimal(str(data["drawdown_pause_usdt"])),
            taker_fee_bps=Decimal(str(data["taker_fee_bps"])),
            slippage_bps=Decimal(str(data["slippage_bps"])),
            interval=str(data["interval"]),
        )


@dataclass(frozen=True)
class SizedOrder:
    """An order that satisfied every risk and filter constraint."""

    asset: str
    quantity: Decimal
    notional: Decimal
    entry: Decimal
    stop: Decimal
    stop_risk: Decimal
    gross_remaining: Decimal


@dataclass(frozen=True)
class RejectedOrder:
    """An order rejected by a filter or risk constraint."""

    asset: str
    reason: str


@dataclass(frozen=True)
class RiskPauseState:
    """Daily-loss and drawdown pause policy."""

    daily_loss_pause_usdt: Decimal
    drawdown_pause_usdt: Decimal

    def daily_loss_paused(self, daily_loss: Decimal) -> bool:
        """True when the realized daily loss reaches the pause threshold."""
        return daily_loss >= self.daily_loss_pause_usdt

    def drawdown_review_required(self, drawdown: Decimal) -> bool:
        """True when the high-water-mark drawdown requires human review."""
        return drawdown >= self.drawdown_pause_usdt

    @staticmethod
    def next_utc_midnight(now: datetime) -> datetime:
        """Return the next UTC midnight strictly after *now*."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        midnight = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        if midnight <= now.astimezone(UTC):
            midnight += timedelta(days=1)
        return midnight


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    """Floor *value* to the nearest multiple of *step* (never rounds up)."""
    if step <= 0:
        raise ValueError("step_size must be positive")
    return (value // step) * step


def _risk_budget(open_risks: tuple[Decimal, ...], limits: SmallAccountLimits) -> Decimal:
    """Permit 10 USDT for the first position; 5 USDT (or the remaining
    aggregate) for each subsequent position."""
    if not open_risks:
        return limits.single_position_risk_usdt
    aggregate_used = sum(open_risks, Decimal("0"))
    remaining_aggregate = limits.single_position_risk_usdt - aggregate_used
    if remaining_aggregate <= 0:
        return Decimal("0")
    return min(limits.two_position_risk_usdt, remaining_aggregate)


def size_order(
    entry: Decimal,
    stop: Decimal,
    ref_price: Decimal,
    open_risks: tuple[Decimal, ...],
    open_notionals: tuple[Decimal, ...],
    rules: ContractRules,
    limits: SmallAccountLimits,
    risk_budget: Decimal | None = None,
) -> SizedOrder | RejectedOrder:
    """Size an order against the 100 USDT risk and gross-notional limits.

    The risk budget is converted to a notional via ``budget * entry / distance``
    and then capped by the remaining 90 USDT gross capacity.  The quantity is
    floored to the contract step size; anything below ``min_qty`` or
    ``min_notional`` is rejected.  When *risk_budget* is given it overrides the
    default per-position budget (used by the two-position portfolio to size each
    leg at 5 USDT so both can coexist under the 10 USDT aggregate cap).
    """
    distance = abs(entry - stop)
    if distance <= 0:
        return RejectedOrder(rules.asset, "INVALID_STOP_DISTANCE")
    if ref_price <= 0:
        return RejectedOrder(rules.asset, "INVALID_REF_PRICE")

    budget = risk_budget if risk_budget is not None else _risk_budget(open_risks, limits)
    if budget <= 0:
        return RejectedOrder(rules.asset, "RISK_BUDGET_EXHAUSTED")

    notional_by_risk = budget * entry / distance
    gross_used = sum(open_notionals, Decimal("0"))
    gross_remaining = limits.max_gross_notional_usdt - gross_used
    if gross_remaining <= 0:
        return RejectedOrder(rules.asset, "GROSS_CAPACITY_EXHAUSTED")

    notional = min(notional_by_risk, gross_remaining)
    quantity = _floor_to_step(notional / ref_price, rules.step_size)
    notional = quantity * ref_price

    if quantity < rules.min_qty or notional < rules.min_notional:
        return RejectedOrder(rules.asset, "MIN_NOTIONAL_OR_STEP_CONFLICT")

    stop_risk = notional * distance / entry
    return SizedOrder(
        asset=rules.asset,
        quantity=quantity,
        notional=notional,
        entry=entry,
        stop=stop,
        stop_risk=stop_risk,
        gross_remaining=limits.max_gross_notional_usdt - gross_used - notional,
    )
