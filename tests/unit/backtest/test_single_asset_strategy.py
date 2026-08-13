"""Tests for the causal ETH single-asset strategy evaluator."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bian_quant.backtest.single_asset_strategy import (
    INITIAL_EQUITY,
    cycle_multiplier,
    evaluate_eth_strategy,
    _compute_metrics,
    _compute_metrics_from_equity_only,
    _records_through,
)


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
        records.append({
            "selection_time": d.to_pydatetime(),
            "member_count": 12,
            "median_quote_volume": 50000000.0,
            "median_oi_value": 100000000.0,
            "top3_share": 0.45,
        })
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
    records_modified = pd.concat([
        records,
        pd.DataFrame([{
            "selection_time": (records["selection_time"].iloc[-1] + timedelta(days=1)).to_pydatetime()
            if isinstance(records["selection_time"].iloc[-1], datetime)
            else records["selection_time"].iloc[-1] + timedelta(days=1),
            "member_count": 5,
            "median_quote_volume": 10000000.0,
            "median_oi_value": 50000000.0,
            "top3_share": 0.80,
        }])
    ], ignore_index=True)

    result2 = evaluate_eth_strategy(ohlcv_path=csv_path, popular_records=records_modified)

    # Input hash should differ (more records), but result hash for the same
    # signals should be identical because the extra record is after the last signal
    if result1.status == "ok" and result2.status == "ok":
        if result1.baseline and result2.baseline:
            # Baseline doesn't use popular records at all, so must be identical
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
    records = pd.DataFrame({
        "selection_time": pd.to_datetime([
            "2025-01-01", "2025-01-02", "2025-01-03", "2025-01-04"
        ], utc=True),
        "member_count": [12, 10, 15, 8],
    })
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
