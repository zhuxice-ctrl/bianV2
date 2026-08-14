from __future__ import annotations

import pandas as pd

from bian_quant.backtest.market_cycle_comparison import (
    comparison_payload,
    run_market_cycle_comparison,
)
from bian_quant.data.funding_alignment import FundingAlignmentRecord


def _popular(days: int) -> pd.DataFrame:
    rows = []
    for index in range(days):
        rows.append(
            {
                "selection_time": pd.Timestamp("2026-01-01", tz="UTC") + pd.Timedelta(days=index),
                "member_count": 12,
                "median_quote_volume": 100.0 + index,
                "median_oi_value": 200.0 + index,
                "top3_share": 0.35,
            }
        )
    return pd.DataFrame(rows)


def test_market_cycle_comparison_is_deterministic() -> None:
    returns = pd.DataFrame(
        {
            "date": pd.date_range("2026-02-01", periods=5, tz="UTC"),
            "BTCUSDT": [0.01, -0.01, 0.02, 0.00, 0.01],
            "ETHUSDT": [0.00, 0.01, -0.01, 0.01, 0.00],
            "BNBUSDT": [0.005, 0.005, 0.005, -0.005, 0.005],
        }
    )

    first = run_market_cycle_comparison(returns, _popular(70))
    second = run_market_cycle_comparison(returns, _popular(70))

    assert first.artifact_sha256 == second.artifact_sha256
    assert first.baseline.final_equity > 0
    assert first.confidence_weighted.final_equity > 0


def test_empty_returns_preserve_initial_equity() -> None:
    result = run_market_cycle_comparison(pd.DataFrame(), _popular(70))

    assert result.baseline.final_equity == 100.0
    assert result.confidence_weighted.final_equity == 100.0
    assert result.baseline.trade_count == 0


def test_outputs_remain_bounded_on_small_returns() -> None:
    returns = pd.DataFrame(
        {
            "date": pd.date_range("2026-02-01", periods=4, tz="UTC"),
            "BTCUSDT": [0.01, 0.01, 0.01, 0.01],
            "ETHUSDT": [0.01, 0.01, 0.01, 0.01],
            "BNBUSDT": [0.01, 0.01, 0.01, 0.01],
        }
    )

    result = run_market_cycle_comparison(returns, _popular(70))

    assert result.baseline.final_equity > 100.0
    assert result.baseline.final_equity < 200.0
    assert result.confidence_weighted.final_equity < 200.0


# ---------------------------------------------------------------------------
# Task 1: Funding alignment propagation tests
# ---------------------------------------------------------------------------


def _make_funding_records(
    n_days: int = 40, start: str = "2026-01-01"
) -> tuple[FundingAlignmentRecord, ...]:
    """Generate synthetic FundingAlignmentRecords available before returns."""
    records: list[FundingAlignmentRecord] = []
    base = pd.Timestamp(start, tz="UTC")
    for i in range(n_days):
        dt = (base + pd.Timedelta(days=i)).to_pydatetime()
        records.append(
            FundingAlignmentRecord(
                decision_time=dt,
                available_time=dt,
                member_count=3,
                positive_rate_share=0.9,
                median_rate=0.0001,
                coverage_ratio=1.0,
                source_sha256="a" * 64,
            )
        )
    return tuple(records)


def _make_future_funding_records(
    n_days: int = 5, start: str = "2026-03-01"
) -> tuple[FundingAlignmentRecord, ...]:
    """Generate funding records available only after the returns period."""
    records: list[FundingAlignmentRecord] = []
    base = pd.Timestamp(start, tz="UTC")
    for i in range(n_days):
        dt = (base + pd.Timedelta(days=i)).to_pydatetime()
        records.append(
            FundingAlignmentRecord(
                decision_time=dt,
                available_time=dt,
                member_count=3,
                positive_rate_share=0.1,
                median_rate=-0.0001,
                coverage_ratio=1.0,
                source_sha256="b" * 64,
            )
        )
    return tuple(records)


def test_funding_alignment_none_is_byte_identical() -> None:
    """Without funding_alignment and with explicit None must be byte-identical."""
    returns = pd.DataFrame(
        {
            "date": pd.date_range("2026-02-01", periods=5, tz="UTC"),
            "BTCUSDT": [0.01, -0.01, 0.02, 0.00, 0.01],
            "ETHUSDT": [0.00, 0.01, -0.01, 0.01, 0.00],
            "BNBUSDT": [0.005, 0.005, 0.005, -0.005, 0.005],
        }
    )
    popular = _popular(70)

    without = run_market_cycle_comparison(returns, popular)
    explicit_none = run_market_cycle_comparison(returns, popular, funding_alignment=None)

    assert comparison_payload(without) == comparison_payload(explicit_none)


def test_funding_alignment_affects_only_weighted() -> None:
    """Funding must only change the weighted variant, never the baseline."""
    returns = pd.DataFrame(
        {
            "date": pd.date_range("2026-02-01", periods=5, tz="UTC"),
            "BTCUSDT": [0.01, -0.01, 0.02, 0.00, 0.01],
            "ETHUSDT": [0.00, 0.01, -0.01, 0.01, 0.00],
            "BNBUSDT": [0.005, 0.005, 0.005, -0.005, 0.005],
        }
    )
    popular = _popular(70)
    funding = _make_funding_records(40, start="2026-01-01")

    without = run_market_cycle_comparison(returns, popular)
    with_funding = run_market_cycle_comparison(returns, popular, funding_alignment=funding)

    # Baseline must be byte-identical — funding never touches it.
    assert without.baseline == with_funding.baseline

    # The artifact hash must differ when funding changes the weighted cycle.
    assert without.artifact_sha256 != with_funding.artifact_sha256

    # Funding audit fields must be populated.
    assert with_funding.funding_alignment_source_sha256 is not None
    assert with_funding.funding_alignment_applied_signal_count is not None
    assert with_funding.funding_alignment_applied_signal_count > 0

    # Without funding, audit fields must be None (byte-identical to pre-funding).
    assert without.funding_alignment_source_sha256 is None
    assert without.funding_alignment_applied_signal_count is None


def test_future_funding_does_not_change_result() -> None:
    """Funding available only after the returns period must not change the result."""
    returns = pd.DataFrame(
        {
            "date": pd.date_range("2026-02-01", periods=5, tz="UTC"),
            "BTCUSDT": [0.01, -0.01, 0.02, 0.00, 0.01],
            "ETHUSDT": [0.00, 0.01, -0.01, 0.01, 0.00],
            "BNBUSDT": [0.005, 0.005, 0.005, -0.005, 0.005],
        }
    )
    popular = _popular(70)
    future_funding = _make_future_funding_records(5, start="2026-03-01")

    without = run_market_cycle_comparison(returns, popular)
    with_future = run_market_cycle_comparison(returns, popular, funding_alignment=future_funding)

    # Future funding cannot affect any decision in the returns period.
    assert comparison_payload(without) == comparison_payload(with_future)


def test_empty_returns_with_funding_preserves_baseline() -> None:
    """Empty returns with funding must not crash and baseline stays at 100U."""
    result = run_market_cycle_comparison(
        pd.DataFrame(), _popular(70), funding_alignment=_make_funding_records(40)
    )
    assert result.baseline.final_equity == 100.0
    assert result.confidence_weighted.final_equity == 100.0
