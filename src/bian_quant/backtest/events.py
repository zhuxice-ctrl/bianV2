from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


def _require_aware(timestamp: datetime, name: str) -> None:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


class BarConflictPolicy(StrEnum):
    STOP_FIRST = "stop_first"
    TARGET_FIRST = "target_first"


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        _require_aware(self.timestamp, "bar timestamp")
        if self.high < max(self.open, self.close, self.low):
            raise ValueError("bar high violates OHLC ordering")
        if self.low > min(self.open, self.close, self.high):
            raise ValueError("bar low violates OHLC ordering")
        if self.volume < 0:
            raise ValueError("bar volume must be non-negative")


@dataclass(frozen=True)
class SignalEvent:
    timestamp: datetime
    direction: int
    available_time: datetime | None = None
    notional: Decimal | None = None
    stop: Decimal | None = None
    target: Decimal | None = None
    stop_distance: Decimal | None = None
    target_distance: Decimal | None = None
    asset: str = ""
    rank: int = 0

    def __post_init__(self) -> None:
        _require_aware(self.timestamp, "signal decision timestamp")
        available_time = self.available_time or self.timestamp
        object.__setattr__(self, "available_time", available_time)
        _require_aware(available_time, "signal available_time")
        if available_time > self.timestamp:
            raise ValueError("signal was not available at decision time")
        if self.direction not in (-1, 0, 1):
            raise ValueError("signal direction must be -1, 0, or 1")
        if self.notional is not None and self.notional < 0:
            raise ValueError("signal notional must be non-negative")
        if self.stop is not None and self.stop_distance is not None:
            raise ValueError("use either stop or stop_distance")
        if self.target is not None and self.target_distance is not None:
            raise ValueError("use either target or target_distance")
        for distance in (self.stop_distance, self.target_distance):
            if distance is not None and distance <= 0:
                raise ValueError("stop and target distances must be positive")


@dataclass(frozen=True)
class FundingEvent:
    timestamp: datetime
    funding_rate: Decimal

    def __post_init__(self) -> None:
        _require_aware(self.timestamp, "funding timestamp")


@dataclass(frozen=True)
class Fill:
    timestamp: datetime
    direction: int
    ref_price: Decimal
    exec_price: Decimal
    notional: Decimal
    fee: Decimal
    reason: str


@dataclass(frozen=True)
class Trade:
    entry_time: datetime
    exit_time: datetime
    direction: int
    entry_price: Decimal
    exit_price: Decimal
    notional: Decimal
    pnl: Decimal
    exit_reason: str
    fee_paid: Decimal
    funding_paid: Decimal
