import pytest

from bian_quant.backtest.costs import CostModel


def test_round_trip_cost_contains_fee_and_slippage_twice() -> None:
    model = CostModel(taker_fee_bps=4.0, slippage_bps=5.0)
    assert model.round_trip_fraction() == 0.0018


def test_long_position_pays_positive_funding() -> None:
    model = CostModel(taker_fee_bps=4.0, slippage_bps=5.0)
    assert (
        model.funding_cashflow(notional=10_000, position_sign=1, funding_rate=0.0001)
        == -1.0
    )


def test_costs_must_be_non_negative() -> None:
    with pytest.raises(ValueError):
        CostModel(taker_fee_bps=-1.0, slippage_bps=5.0)
