from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from bian_quant.backtest.confidence_allocation import allocate_confidence_cap
from bian_quant.regimes.market_cycle import MarketCycleLabel, MarketCycleState


def _state(label: MarketCycleLabel, confidence: float) -> MarketCycleState:
    return MarketCycleState(
        label=label,
        confidence=confidence,
        probabilities={"bull": confidence, "neutral": 0.0, "risk_off": 0.0},
        decision_time=datetime(2026, 1, 1, tzinfo=UTC),
        sample_count=30,
        evidence={},
        evidence_sha256="a" * 64,
    )


def test_confidence_thresholds_map_to_shared_cap() -> None:
    weights = {"BTCUSDT": 1.0, "ETHUSDT": 1.0, "BNBUSDT": 1.0}

    high = allocate_confidence_cap(_state(MarketCycleLabel.BULL, 0.80), weights)
    medium = allocate_confidence_cap(_state(MarketCycleLabel.BULL, 0.65), weights)
    low = allocate_confidence_cap(_state(MarketCycleLabel.BULL, 0.50), weights)
    closed = allocate_confidence_cap(_state(MarketCycleLabel.BULL, 0.49), weights)

    assert high.total_cap_usdt == Decimal("100")
    assert medium.total_cap_usdt == Decimal("70.00")
    assert low.total_cap_usdt == Decimal("40.00")
    assert closed.total_cap_usdt == Decimal("0")


def test_three_coin_weights_are_normalized_under_cap() -> None:
    decision = allocate_confidence_cap(
        _state(MarketCycleLabel.BULL, 0.80),
        {"BTCUSDT": 2.0, "ETHUSDT": 1.0, "BNBUSDT": 1.0, "SOLUSDT": 99.0},
    )

    assert decision.selected_assets == ("BTCUSDT", "ETHUSDT", "BNBUSDT")
    assert sum(decision.per_asset_caps_usdt.values(), Decimal("0")) == Decimal("100")
    assert decision.per_asset_caps_usdt["BTCUSDT"] == Decimal("50")


def test_risk_off_opens_no_new_exposure() -> None:
    decision = allocate_confidence_cap(
        _state(MarketCycleLabel.RISK_OFF, 0.99),
        {"BTCUSDT": 1.0, "ETHUSDT": 1.0, "BNBUSDT": 1.0},
    )

    assert decision.total_cap_usdt == Decimal("0")
    assert decision.selected_assets == ()
