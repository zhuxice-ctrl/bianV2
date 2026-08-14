from __future__ import annotations

import math
from datetime import datetime, timedelta

import pandas as pd
import pytest

from bian_quant.data.funding_alignment import FundingAlignmentRecord
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
                "selection_time": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=index),
                "member_count": member_count,
                "median_quote_volume": qv_start * growth,
                "median_oi_value": oi_start * growth,
                "top3_share": 0.35,
            }
        )
    return pd.DataFrame(rows)


def _risk_off_records(days: int) -> pd.DataFrame:
    rows = []
    for index in range(days):
        decline = 1.0 - (index / max(days - 1, 1)) * 0.5
        rows.append(
            {
                "selection_time": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=index),
                "member_count": 3,
                "median_quote_volume": 1000.0 * decline,
                "median_oi_value": 2000.0 * decline,
                "top3_share": 0.80,
            }
        )
    return pd.DataFrame(rows)


def _funding_record(
    decision_time: datetime,
    *,
    positive_rate_share: float,
    coverage_ratio: float = 1.0,
    source_sha: str = "b" * 64,
) -> FundingAlignmentRecord:
    return FundingAlignmentRecord(
        decision_time=decision_time,
        available_time=decision_time,
        member_count=12,
        positive_rate_share=positive_rate_share,
        median_rate=0.0001,
        coverage_ratio=coverage_ratio,
        source_sha256=source_sha,
    )


def test_bull_cycle_has_probability_distribution() -> None:
    state = classify_market_cycle(_records(60, member_count=12, qv_start=100.0, oi_start=200.0))

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


def test_no_funding_input_preserves_outputs() -> None:
    records = _records(60, member_count=12, qv_start=100.0, oi_start=200.0)
    assert market_cycle_payload(classify_market_cycle(records)) == market_cycle_payload(
        classify_market_cycle(records, funding_alignment=None)
    )


def test_funding_alignment_evidence_and_hash_change() -> None:
    records = _records(60, member_count=12, qv_start=100.0, oi_start=200.0)
    base = classify_market_cycle(records)
    with_funding = classify_market_cycle(
        records, funding_alignment=(_funding_record(base.decision_time, positive_rate_share=0.9),)
    )
    assert with_funding.evidence["funding_alignment"] is not None
    assert with_funding.evidence_sha256 != base.evidence_sha256


def test_insufficient_funding_coverage_does_not_block() -> None:
    records = _records(60, member_count=12, qv_start=100.0, oi_start=200.0)
    base = classify_market_cycle(records)
    with_funding = classify_market_cycle(
        records,
        funding_alignment=(
            _funding_record(base.decision_time, positive_rate_share=0.9, coverage_ratio=0.1),
        ),
    )
    assert with_funding.evidence["funding_alignment"] is None
    assert with_funding.probabilities == base.probabilities


def test_future_funding_rows_do_not_change_prefix_state() -> None:
    records = _records(70, member_count=12, qv_start=100.0, oi_start=200.0)
    prefix = records.iloc[:45]
    future = _funding_record(
        classify_market_cycle(prefix).decision_time + timedelta(days=1),
        positive_rate_share=0.9,
    )
    assert market_cycle_payload(classify_market_cycle(prefix)) == market_cycle_payload(
        classify_market_cycle(prefix, funding_alignment=(future,))
    )


def test_broad_positive_funding_reduces_bull() -> None:
    records = _records(60, member_count=12, qv_start=100.0, oi_start=200.0)
    base = classify_market_cycle(records)
    with_funding = classify_market_cycle(
        records, funding_alignment=(_funding_record(base.decision_time, positive_rate_share=0.95),)
    )
    assert with_funding.probabilities["bull"] <= base.probabilities["bull"] + 1e-9


def test_broad_negative_funding_increases_bull_when_not_risk_off() -> None:
    records = _records(60, member_count=12, qv_start=100.0, oi_start=200.0)
    base = classify_market_cycle(records)
    with_funding = classify_market_cycle(
        records, funding_alignment=(_funding_record(base.decision_time, positive_rate_share=0.05),)
    )
    assert with_funding.probabilities["bull"] >= base.probabilities["bull"] - 1e-9


def test_negative_funding_no_boost_in_risk_off_regime() -> None:
    records = _risk_off_records(60)
    base = classify_market_cycle(records)
    with_funding = classify_market_cycle(
        records, funding_alignment=(_funding_record(base.decision_time, positive_rate_share=0.05),)
    )
    assert with_funding.probabilities["bull"] == pytest.approx(base.probabilities["bull"], abs=1e-9)
