from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    taker_fee_bps: float
    slippage_bps: float

    def __post_init__(self) -> None:
        if self.taker_fee_bps < 0 or self.slippage_bps < 0:
            raise ValueError("cost inputs must be non-negative")

    def one_way_fraction(self) -> float:
        return (self.taker_fee_bps + self.slippage_bps) / 10_000.0

    def round_trip_fraction(self) -> float:
        return 2.0 * self.one_way_fraction()

    def funding_cashflow(
        self, *, notional: float, position_sign: int, funding_rate: float
    ) -> float:
        if position_sign not in (-1, 1):
            raise ValueError("position_sign must be -1 or 1")
        if notional < 0:
            raise ValueError("notional must be non-negative")
        return -notional * position_sign * funding_rate
