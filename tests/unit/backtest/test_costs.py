"""Tests for cost and funding models."""

from __future__ import annotations

import pytest

from bian_quant.backtest.costs import CostModel


class TestCostModel:
    def test_one_way_fraction(self):
        cm = CostModel(fee_rate=0.0004, slippage_rate=0.001)
        assert cm.one_way_fraction() == pytest.approx(0.0014)

    def test_round_trip_fraction(self):
        cm = CostModel(fee_rate=0.0004, slippage_rate=0.001)
        assert cm.round_trip_fraction() == pytest.approx(0.0028)

    def test_round_trip_equals_double_one_way(self):
        cm = CostModel(fee_rate=0.001, slippage_rate=0.002)
        assert cm.round_trip_fraction() == pytest.approx(2 * cm.one_way_fraction())

    def test_default_funding_zero(self):
        cm = CostModel(fee_rate=0.0, slippage_rate=0.0)
        assert cm.funding_rate == 0.0

    def test_frozen(self):
        cm = CostModel(fee_rate=0.001, slippage_rate=0.0)
        with pytest.raises(Exception):
            cm.fee_rate = 0.002  # type: ignore[misc]


class TestFundingCashflow:
    def test_long_pays_positive_funding(self):
        cm = CostModel(fee_rate=0.0, slippage_rate=0.0, funding_rate=0.0001)
        cf = cm.funding_cashflow(notional=10_000.0, direction=1)
        assert cf == pytest.approx(-1.0)  # long pays

    def test_short_receives_positive_funding(self):
        cm = CostModel(fee_rate=0.0, slippage_rate=0.0, funding_rate=0.0001)
        cf = cm.funding_cashflow(notional=10_000.0, direction=-1)
        assert cf == pytest.approx(1.0)  # short receives

    def test_long_receives_negative_funding(self):
        cm = CostModel(fee_rate=0.0, slippage_rate=0.0, funding_rate=-0.0001)
        cf = cm.funding_cashflow(notional=10_000.0, direction=1)
        assert cf == pytest.approx(1.0)  # long receives

    def test_multiple_periods(self):
        cm = CostModel(fee_rate=0.0, slippage_rate=0.0, funding_rate=0.0001)
        cf1 = cm.funding_cashflow(notional=10_000.0, direction=1, periods=1)
        cf3 = cm.funding_cashflow(notional=10_000.0, direction=1, periods=3)
        assert cf3 == pytest.approx(3 * cf1)

    def test_zero_funding_rate(self):
        cm = CostModel(fee_rate=0.0, slippage_rate=0.0, funding_rate=0.0)
        cf = cm.funding_cashflow(notional=10_000.0, direction=1)
        assert cf == 0.0

    def test_zero_notional(self):
        cm = CostModel(fee_rate=0.0, slippage_rate=0.0, funding_rate=0.0001)
        cf = cm.funding_cashflow(notional=0.0, direction=1)
        assert cf == 0.0
