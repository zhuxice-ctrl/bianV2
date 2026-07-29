"""Cost and funding models for realistic backtesting.

All models are immutable (frozen dataclasses) so they can be safely
shared across backtest runs without risk of mutation.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    """Trading cost model combining fees, slippage, and funding.

    Attributes
    ----------
    fee_rate:
        Per-side fee as a fraction of notional (e.g. 0.0004 = 4 bps).
    slippage_rate:
        Per-side slippage as a fraction of reference price.
    funding_rate:
        Per-period funding rate for perpetual positions
        (positive = longs pay shorts).
    """

    fee_rate: float
    slippage_rate: float
    funding_rate: float = 0.0

    def one_way_fraction(self) -> float:
        """Total cost fraction for a single entry or exit.

        = fee + slippage
        """
        return self.fee_rate + self.slippage_rate

    def round_trip_fraction(self) -> float:
        """Total cost fraction for a complete round-trip (entry + exit).

        = 2 × (fee + slippage)
        """
        return 2.0 * self.one_way_fraction()

    def funding_cashflow(
        self,
        notional: float,
        direction: int,
        periods: int = 1,
    ) -> float:
        """Funding cash-flow for holding a position.

        Parameters
        ----------
        notional:
            Absolute notional value of the position.
        direction:
            ``+1`` for long, ``-1`` for short.
        periods:
            Number of funding periods held.

        Returns
        -------
        float
            Cash-flow from funding.  Positive = received, negative = paid.
            Longs pay when ``funding_rate > 0``, shorts receive.
        """
        return -direction * notional * self.funding_rate * periods
