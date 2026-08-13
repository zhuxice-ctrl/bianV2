from __future__ import annotations

import math

import pandas as pd

from bian_quant.regimes.market_cycle import (
    MarketCycleLabel,
    classify_market_cycle,
    market_cycle_payload,
)


def _records(days: int, *, member_count: int, qv_start: float, oi_start: float) -> pd.DataFrame:
    rows = []
    for index in range(days):
        growth = 1.0 + index / max(days - 1, 1)
        rows.append(
            {
                "selection_time": pd.Timestamp("2026-01-01", tz="UTC")
                + pd.Timedelta(days=index),
                "member_count": member_count,
                "median_quote_volume": qv_start * growth,
                "median_oi_value": oi_start * growth,
                "top3_share": 0.35,
            }
        )
    return pd.DataFrame(rows)


def test_bull_cycle_has_probability_distribution() -> None:
    state = classify_market_cycle(
        _records(60, member_count=12, qv_start=100.0, oi_start=200.0)
    )

    assert state.label in {MarketCycleLabel.BULL, MarketCycleLabel.NEUTRAL}
    assert 0.0 <= state.confidence <= 1.0
    assert math.isclose(sum(state.probabilities.values()), 1.0, abs_tol=1e-5)
    assert len(state.evidence_sha256) == 64


def test_insufficient_evidence_returns_zero_confidence() -> None:
    state = classify_market_cycle(_records(12, member_count=12, qv_start=100.0, oi_start=200.0))

    assert state.label == MarketCycleLabel.INSUFFICIENT_EVIDENCE
    assert state.confidence == 0.0
    assert state.sample_count == 12


def test_prefix_state_uses_only_prefix_records() -> None:
    records = _records(70, member_count=12, qv_start=100.0, oi_start=200.0)

    prefix_state = classify_market_cycle(records.iloc[:45])
    extended_prefix_state = classify_market_cycle(records.iloc[:45])
    classify_market_cycle(records)

    assert market_cycle_payload(prefix_state) == market_cycle_payload(extended_prefix_state)
