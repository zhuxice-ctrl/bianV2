"""Regression tests for real Binance archive boundary conventions."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd

from bian_quant.data.acquisition import DualHorizonAcquisition, build_source_plan
from bian_quant.data.dual_horizon import _quality_report

CONFIG = Path("configs/experiments/dual_horizon_derivatives.yaml")


def test_shifted_daily_metrics_grid_accepts_next_midnight_endpoint() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = next(
        item
        for item in build_source_plan(config)
        if item.identity_key == "metrics_oi|BTCUSDT|native|daily|2025-04-23T00:00:00+00:00"
    )
    times = pd.date_range(
        source.period_start + timedelta(minutes=5),
        periods=288,
        freq="5min",
    )
    frame = pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": times,
            "available_time": times + timedelta(minutes=5),
            "sum_open_interest": 100.0,
            "sum_open_interest_value": 200.0,
        }
    )

    report = _quality_report(source, frame, config)

    assert report.observed_rows == 288
    assert report.expected_rows == 288
    assert report.findings == ()


def test_shifted_daily_metrics_grid_accepts_one_second_endpoint_drift() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = next(
        item
        for item in build_source_plan(config)
        if item.identity_key == "metrics_oi|BTCUSDT|native|daily|2025-06-14T00:00:00+00:00"
    )
    times = pd.date_range(
        source.period_start + timedelta(minutes=5),
        periods=288,
        freq="5min",
    )
    times = times.to_series(index=range(len(times)))
    times.iloc[-1] += timedelta(seconds=1)
    frame = pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": times,
            "available_time": times + timedelta(minutes=5),
            "sum_open_interest": 100.0,
            "sum_open_interest_value": 200.0,
        }
    )

    report = _quality_report(source, frame, config)

    assert report.observed_rows == 288
    assert report.expected_rows == 288
    assert report.findings == ()


def test_cutoff_day_ignores_expected_archive_tail_after_cutoff() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = next(
        item
        for item in build_source_plan(config)
        if item.identity_key == "ohlcv|BTCUSDT|1h|daily|2026-07-26T00:00:00+00:00"
    )
    times = pd.date_range(source.period_start, periods=24, freq="1h")
    frame = pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": times,
            "available_time": times + timedelta(hours=1) - timedelta(milliseconds=1),
            "open": 100.0,
            "high": 101.0,
            "low": 99.0,
            "close": 100.0,
            "volume": 1.0,
        }
    )

    report = _quality_report(source, frame, config)

    assert report.observed_rows == 20
    assert report.expected_rows == 20
    assert report.findings == ()


def test_metrics_row_unavailable_at_cutoff_is_not_observed() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = next(
        item
        for item in build_source_plan(config)
        if item.identity_key == "metrics_oi|BTCUSDT|native|daily|2026-07-26T00:00:00+00:00"
    )
    times = pd.date_range(source.period_start, periods=240, freq="5min")
    frame = pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": times,
            "available_time": times + timedelta(minutes=5),
            "sum_open_interest": 100.0,
            "sum_open_interest_value": 200.0,
        }
    )
    report = _quality_report(source, frame, config)
    assert report.observed_rows == 239
    assert report.expected_rows == 239
    assert report.findings == ()
