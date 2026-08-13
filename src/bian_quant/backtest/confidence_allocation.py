"""Shared BTC/ETH/BNB exposure cap from market-cycle confidence."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal

from bian_quant.regimes.market_cycle import MarketCycleLabel, MarketCycleState

THREE_COIN_UNIVERSE = ("BTCUSDT", "ETHUSDT", "BNBUSDT")


@dataclass(frozen=True)
class AllocationDecision:
    """Read-only exposure budget; this is not an order request."""

    total_cap_usdt: Decimal
    per_asset_caps_usdt: dict[str, Decimal]
    selected_assets: tuple[str, ...]
    confidence: float
    label: str
    reason: str


def confidence_cap_fraction(confidence: float) -> Decimal:
    """Map confidence to the shared portfolio cap fraction."""
    if confidence >= 0.80:
        return Decimal("1.0")
    if confidence >= 0.65:
        return Decimal("0.70")
    if confidence >= 0.50:
        return Decimal("0.40")
    return Decimal("0")


def allocate_confidence_cap(
    state: MarketCycleState,
    signal_weights: Mapping[str, float],
    *,
    capital_usdt: Decimal = Decimal("100"),
) -> AllocationDecision:
    """Allocate one shared cap across BTC/ETH/BNB positive signal weights."""
    if state.label in {
        MarketCycleLabel.RISK_OFF,
        MarketCycleLabel.INSUFFICIENT_EVIDENCE,
    }:
        return AllocationDecision(
            total_cap_usdt=Decimal("0"),
            per_asset_caps_usdt={asset: Decimal("0") for asset in THREE_COIN_UNIVERSE},
            selected_assets=(),
            confidence=state.confidence,
            label=state.label.value,
            reason=f"{state.label.value.upper()}_NO_NEW_EXPOSURE",
        )

    cap = capital_usdt * confidence_cap_fraction(state.confidence)
    positive = {
        asset: Decimal(str(weight))
        for asset, weight in signal_weights.items()
        if asset in THREE_COIN_UNIVERSE and weight > 0
    }
    if cap <= 0 or not positive:
        return AllocationDecision(
            total_cap_usdt=Decimal("0"),
            per_asset_caps_usdt={asset: Decimal("0") for asset in THREE_COIN_UNIVERSE},
            selected_assets=(),
            confidence=state.confidence,
            label=state.label.value,
            reason="CONFIDENCE_OR_SIGNAL_BELOW_THRESHOLD",
        )
    weight_sum = sum(positive.values(), Decimal("0"))
    per_asset = {asset: Decimal("0") for asset in THREE_COIN_UNIVERSE}
    allocated = Decimal("0")
    ordered_assets = [asset for asset in THREE_COIN_UNIVERSE if asset in positive]
    for asset in ordered_assets[:-1]:
        weight = positive[asset]
        per_asset[asset] = cap * weight / weight_sum
        allocated += per_asset[asset]
    per_asset[ordered_assets[-1]] = cap - allocated
    return AllocationDecision(
        total_cap_usdt=cap,
        per_asset_caps_usdt=per_asset,
        selected_assets=tuple(asset for asset in THREE_COIN_UNIVERSE if per_asset[asset] > 0),
        confidence=state.confidence,
        label=state.label.value,
        reason="CONFIDENCE_WEIGHTED_SHARED_CAP",
    )


def allocation_payload(decision: AllocationDecision) -> dict[str, object]:
    return {
        "total_cap_usdt": float(decision.total_cap_usdt),
        "per_asset_caps_usdt": {
            asset: float(value) for asset, value in decision.per_asset_caps_usdt.items()
        },
        "selected_assets": list(decision.selected_assets),
        "confidence": decision.confidence,
        "label": decision.label,
        "reason": decision.reason,
    }
