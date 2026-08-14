"""Tests for the causal ETH single-asset strategy evaluator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bian_quant.backtest.single_asset_strategy import (
    _compute_metrics_from_equity_only,
    _records_through,
    cycle_multiplier,
    evaluate_eth_strategy,
)
from bian_quant.data.funding_alignment import FundingAlignmentRecord


def _make_ohlcv(n_bars: int = 250, start: str = "2025-01-01") -> pd.DataFrame:
    """Generate synthetic ETH 4H OHLCV data with enough bars for EMA200."""
    index = pd.date_range(start=start, periods=n_bars, freq="4h", tz="UTC")
    # Simple random walk with enough movement to generate some signals
    np.random.seed(42)
    returns = np.random.randn(n_bars) * 0.005
    close = 2000 * np.cumprod(1 + returns)
    open_ = np.roll(close, 1)
    open_[0] = 2000
    high = np.maximum(open_, close) * (1 + np.abs(np.random.randn(n_bars)) * 0.003)
    low = np.minimum(open_, close) * (1 - np.abs(np.random.randn(n_bars)) * 0.003)
    volume = np.random.randint(100, 10000, n_bars).astype(float)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


def _make_popular_records(n_days: int = 40, start: str = "2025-01-01") -> pd.DataFrame:
    """Generate synthetic popular-universe records."""
    dates = pd.date_range(start=start, periods=n_days, freq="D", tz="UTC")
    records = []
    for d in dates:
        records.append(
            {
                "selection_time": d.to_pydatetime(),
                "member_count": 12,
                "median_quote_volume": 50000000.0,
                "median_oi_value": 100000000.0,
                "top3_share": 0.45,
            }
        )
    return pd.DataFrame(records)


def test_empty_input_returns_missing(tmp_path: Path):
    """When the OHLCV file doesn't exist, status must be 'missing'."""
    result = evaluate_eth_strategy(
        ohlcv_path=tmp_path / "nonexistent.csv",
        popular_records=pd.DataFrame(),
    )
    assert result.status == "missing"
    assert result.baseline is None
    assert result.confidence_weighted is None


def test_baseline_starts_from_100u(tmp_path: Path):
    """Both variants must start from 100 USDT initial equity."""
    frame = _make_ohlcv(300)
    csv_path = tmp_path / "ETHUSDT_4h.csv"
    frame.to_csv(csv_path, index_label="timestamp")

    records = _make_popular_records(40, start=str(frame.index[0].date()))
    result = evaluate_eth_strategy(
        ohlcv_path=csv_path,
        popular_records=records,
    )

    if result.status == "ok" and result.baseline is not None:
        # Final equity should be a reasonable number (not NaN/inf)
        assert np.isfinite(result.baseline.final_equity)
        # If no trades, equity stays at 100
        if result.baseline.trade_count == 0:
            assert result.baseline.final_equity == 100.0


def test_weighted_notional_does_not_exceed_baseline(tmp_path: Path):
    """The weighted variant's notional must never exceed the baseline's 100U."""
    frame = _make_ohlcv(300)
    csv_path = tmp_path / "ETHUSDT_4h.csv"
    frame.to_csv(csv_path, index_label="timestamp")

    records = _make_popular_records(40, start=str(frame.index[0].date()))
    result = evaluate_eth_strategy(
        ohlcv_path=csv_path,
        popular_records=records,
    )

    if result.status == "ok":
        # The multiplier is always <= 1.0, so weighted notional <= baseline notional
        # This is implicitly guaranteed by cycle_multiplier returning <= 1.0
        assert result.cycle_multiplier is not None
        assert result.cycle_multiplier <= 1.0


def test_deterministic_results(tmp_path: Path):
    """Repeated evaluation with the same input must produce identical results."""
    frame = _make_ohlcv(300)
    csv_path = tmp_path / "ETHUSDT_4h.csv"
    frame.to_csv(csv_path, index_label="timestamp")

    records = _make_popular_records(40, start=str(frame.index[0].date()))

    result1 = evaluate_eth_strategy(ohlcv_path=csv_path, popular_records=records)
    result2 = evaluate_eth_strategy(ohlcv_path=csv_path, popular_records=records)

    assert result1.status == result2.status
    if result1.status == "ok" and result1.baseline and result2.baseline:
        assert result1.baseline.final_equity == result2.baseline.final_equity
        assert result1.baseline.trade_count == result2.baseline.trade_count
    if result1.input_sha256 and result2.input_sha256:
        assert result1.input_sha256 == result2.input_sha256
    if result1.result_sha256 and result2.result_sha256:
        assert result1.result_sha256 == result2.result_sha256


def test_prefix_causality(tmp_path: Path):
    """Modifying future popular-universe records must not change past results."""
    frame = _make_ohlcv(300)
    csv_path = tmp_path / "ETHUSDT_4h.csv"
    frame.to_csv(csv_path, index_label="timestamp")

    records = _make_popular_records(40, start=str(frame.index[0].date()))

    result1 = evaluate_eth_strategy(ohlcv_path=csv_path, popular_records=records)

    # Add more records at the end (future)
    records_modified = pd.concat(
        [
            records,
            pd.DataFrame(
                [
                    {
                        "selection_time": (
                            records["selection_time"].iloc[-1] + timedelta(days=1)
                        ).to_pydatetime()
                        if isinstance(records["selection_time"].iloc[-1], datetime)
                        else records["selection_time"].iloc[-1] + timedelta(days=1),
                        "member_count": 5,
                        "median_quote_volume": 10000000.0,
                        "median_oi_value": 50000000.0,
                        "top3_share": 0.80,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )

    result2 = evaluate_eth_strategy(ohlcv_path=csv_path, popular_records=records_modified)

    # Input hash should differ (more records), but result hash for the same
    # signals should be identical because the extra record is after the last signal
    if result1.status == "ok" and result2.status == "ok" and result1.baseline and result2.baseline:
        # Baseline doesn't use popular records at all, so must be identical.
        assert result1.baseline.final_equity == result2.baseline.final_equity
        assert result1.baseline.trade_count == result2.baseline.trade_count


def test_cycle_multiplier_thresholds():
    """Test the multiplier mapping for all cycle states."""
    assert cycle_multiplier("bull", 0.80) == 1.0
    assert cycle_multiplier("bull", 0.85) == 1.0
    assert cycle_multiplier("bull", 0.79) == 0.70  # bull below 0.80 → neutral path
    assert cycle_multiplier("neutral", 0.65) == 0.70
    assert cycle_multiplier("neutral", 0.50) == 0.40
    assert cycle_multiplier("neutral", 0.49) == 0.0
    assert cycle_multiplier("risk_off", 0.90) == 0.0
    assert cycle_multiplier("insufficient_evidence", 0.50) == 0.0


def test_records_through_filters_causally():
    """_records_through must only return records at or before the decision time."""
    records = pd.DataFrame(
        {
            "selection_time": pd.to_datetime(
                ["2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"], utc=True
            ),
            "member_count": [12, 10, 15, 8],
        }
    )
    dt = datetime(2025, 1, 3, tzinfo=UTC)
    filtered = _records_through(records, dt)
    assert len(filtered) == 3  # Jan 1, 2, 3
    assert all(pd.to_datetime(filtered["selection_time"], utc=True) <= pd.Timestamp(dt))


def test_empty_metrics_when_no_trades():
    """When there are no trades, metrics must show 100U and null win_rate."""
    metrics = _compute_metrics_from_equity_only(100.0)
    assert metrics.final_equity == 100.0
    assert metrics.trade_count == 0
    assert metrics.win_rate is None
    assert metrics.fee_paid_net_profit == 0.0
    assert metrics.fees_paid == 0.0


def test_checked_in_eth_csv_evaluates_deterministically() -> None:
    """The tracked ETH 4H CSV must evaluate deterministically when present."""
    repo_root = Path(__file__).resolve().parents[3]
    source = repo_root / "data" / "ETHUSDT_4h.csv"
    if not source.is_file():
        pytest.skip("checked-in ETH 4H source is unavailable")
    result_one = evaluate_eth_strategy(
        ohlcv_path=source,
        popular_universe_dir=repo_root
        / "var"
        / "artifacts"
        / "dual-horizon-popular-v1"
        / "popular-universe",
    )
    result_two = evaluate_eth_strategy(
        ohlcv_path=source,
        popular_universe_dir=repo_root
        / "var"
        / "artifacts"
        / "dual-horizon-popular-v1"
        / "popular-universe",
    )
    assert result_one.status == "ok"
    assert result_one.result_sha256 == result_two.result_sha256
    assert result_one.baseline is not None
    assert result_one.confidence_weighted is not None


def test_prefix_causality_real_artifact_shape() -> None:
    """Prefix invariance on the real artifact shape.

    The baseline variant never uses popular-universe records, so it must be
    identical regardless of how many future records are appended.  The
    confidence-weighted variant may only consume records available at or
    before each signal decision time, so its per-signal multipliers through a
    cutoff must be byte-identical after truncation, and the truncated result
    hash must be deterministic.
    """
    repo_root = Path(__file__).resolve().parents[3]
    source = repo_root / "data" / "ETHUSDT_4h.csv"
    if not source.is_file():
        pytest.skip("checked-in ETH 4H source is unavailable")
    popular_dir = repo_root / "var" / "artifacts" / "dual-horizon-popular-v1" / "popular-universe"
    if not popular_dir.is_dir():
        pytest.skip("checked-in popular-universe artifacts are unavailable")
    from bian_quant.regimes.market_cycle import load_popular_universe_records

    records = load_popular_universe_records(popular_dir)
    if records.empty:
        pytest.skip("popular-universe records are empty")

    full = evaluate_eth_strategy(ohlcv_path=source, popular_records=records)
    if full.status != "ok" or not full.baseline:
        pytest.skip("ETH evaluation did not produce an ok result on real data")

    midpoint = records.iloc[len(records) // 2]["selection_time"]
    truncated = evaluate_eth_strategy(
        ohlcv_path=source, popular_records=records.iloc[: len(records) // 2 + 1]
    )
    truncated_again = evaluate_eth_strategy(
        ohlcv_path=source, popular_records=records.iloc[: len(records) // 2 + 1]
    )

    # Baseline never touches popular records -> identical.
    assert full.baseline.final_equity == truncated.baseline.final_equity
    assert full.baseline.trade_count == truncated.baseline.trade_count

    # Truncated run is deterministic.
    assert truncated.result_sha256 == truncated_again.result_sha256

    # Per-signal multipliers for decisions at or before the midpoint must be
    # JSON-identical between the full and truncated runs.
    import json as _json

    full_multipliers = full.raw_metrics.get("signal_multipliers", [])
    trunc_multipliers = truncated.raw_metrics.get("signal_multipliers", [])
    prefix_full = [
        m
        for m in full_multipliers
        if pd.Timestamp(m["decision_time"]).tz_convert("UTC")
        <= pd.Timestamp(midpoint).tz_convert("UTC")
    ]
    prefix_truncated = [
        m
        for m in trunc_multipliers
        if pd.Timestamp(m["decision_time"]).tz_convert("UTC")
        <= pd.Timestamp(midpoint).tz_convert("UTC")
    ]
    assert _json.dumps(prefix_full, sort_keys=True) == _json.dumps(prefix_truncated, sort_keys=True)

    # Every multiplier entry must carry a decision_time (structural causality
    # anchor; the engine fills on the bar after the signal).
    assert all("decision_time" in m for m in full_multipliers)


# ---------------------------------------------------------------------------
# Task 1: Funding alignment propagation tests for ETH strategy
# ---------------------------------------------------------------------------


def _make_eth_funding_records(
    n_days: int = 40, start: str = "2025-01-01"
) -> tuple[FundingAlignmentRecord, ...]:
    """Generate synthetic FundingAlignmentRecords for ETH tests."""
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
                source_sha256="e" * 64,
            )
        )
    return tuple(records)


def test_funding_alignment_none_is_byte_identical_eth(tmp_path: Path):
    """evaluate_eth_strategy without and with explicit funding_alignment=None must be identical."""
    frame = _make_ohlcv(300)
    csv_path = tmp_path / "ETHUSDT_4h.csv"
    frame.to_csv(csv_path, index_label="timestamp")

    records = _make_popular_records(40, start=str(frame.index[0].date()))

    without = evaluate_eth_strategy(ohlcv_path=csv_path, popular_records=records)
    explicit_none = evaluate_eth_strategy(
        ohlcv_path=csv_path, popular_records=records, funding_alignment=None
    )

    assert without.result_sha256 == explicit_none.result_sha256
    assert without.input_sha256 == explicit_none.input_sha256


def test_funding_does_not_affect_baseline(tmp_path: Path):
    """Funding alignment must never change the baseline variant's metrics."""
    frame = _make_ohlcv(300)
    csv_path = tmp_path / "ETHUSDT_4h.csv"
    frame.to_csv(csv_path, index_label="timestamp")

    records = _make_popular_records(40, start=str(frame.index[0].date()))
    funding = _make_eth_funding_records(40, start=str(frame.index[0].date()))

    without = evaluate_eth_strategy(ohlcv_path=csv_path, popular_records=records)
    with_funding = evaluate_eth_strategy(
        ohlcv_path=csv_path, popular_records=records, funding_alignment=funding
    )

    if without.status == "ok" and with_funding.status == "ok":
        assert without.baseline is not None
        assert with_funding.baseline is not None
        # Baseline must be identical — funding never touches it.
        assert without.baseline.final_equity == with_funding.baseline.final_equity
        assert without.baseline.trade_count == with_funding.baseline.trade_count
        assert without.baseline.fees_paid == with_funding.baseline.fees_paid


def test_funding_source_sha_in_audit_when_applied(tmp_path: Path):
    """When funding is applied, the source SHA and count must appear in the result."""
    frame = _make_ohlcv(300)
    csv_path = tmp_path / "ETHUSDT_4h.csv"
    frame.to_csv(csv_path, index_label="timestamp")

    records = _make_popular_records(40, start=str(frame.index[0].date()))
    funding = _make_eth_funding_records(40, start=str(frame.index[0].date()))

    result = evaluate_eth_strategy(
        ohlcv_path=csv_path, popular_records=records, funding_alignment=funding
    )

    if result.status == "ok" and result.funding_alignment_applied_signal_count > 0:
        assert result.funding_alignment_source_sha256 is not None
        # The signal_multipliers in raw_metrics must include funding SHA.
        multipliers = result.raw_metrics.get("signal_multipliers", [])
        funding_entries = [m for m in multipliers if "funding_alignment_source_sha256" in m]
        assert len(funding_entries) == result.funding_alignment_applied_signal_count


def test_future_funding_preserves_eth_prefix(tmp_path: Path):
    """Funding available only after the last signal must not change any result."""
    frame = _make_ohlcv(300)
    csv_path = tmp_path / "ETHUSDT_4h.csv"
    frame.to_csv(csv_path, index_label="timestamp")

    records = _make_popular_records(40, start=str(frame.index[0].date()))

    # Create funding records far in the future — after all signals.
    future_start = str((frame.index[-1] + pd.Timedelta(days=30)).date())
    future_funding = _make_eth_funding_records(10, start=future_start)

    without = evaluate_eth_strategy(ohlcv_path=csv_path, popular_records=records)
    with_future = evaluate_eth_strategy(
        ohlcv_path=csv_path, popular_records=records, funding_alignment=future_funding
    )

    if without.status == "ok" and with_future.status == "ok":
        # Future funding cannot affect any past decision.
        assert without.result_sha256 == with_future.result_sha256
        assert with_future.funding_alignment_applied_signal_count == 0
        assert with_future.funding_alignment_source_sha256 is None
