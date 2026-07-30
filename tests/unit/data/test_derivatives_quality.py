"""Tests for derivatives-specific data quality gates."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from bian_quant.data.derivatives_quality import (
    inspect_coverage,
    inspect_funding,
    inspect_metrics,
)


def test_ohlcv_coverage_below_999_per_thousand_blocks() -> None:
    report = inspect_coverage(
        observed=998,
        expected=1000,
        threshold=0.999,
        dataset="ohlcv",
        source_period="2026-06",
    )
    assert report.blocking
    assert report.findings[0].code == "DATA_COVERAGE_BLOCKED"


def test_metrics_month_below_98_percent_is_excluded_not_filled() -> None:
    report = inspect_coverage(
        observed=97,
        expected=100,
        threshold=0.98,
        dataset="metrics_oi",
        source_period="2026-06",
    )
    assert report.excluded_periods == ("2026-06",)


def test_funding_expected_count_uses_archived_interval() -> None:
    frame = funding_fixture(interval_hours=4, rows=6)
    day_start = datetime(2026, 7, 1, tzinfo=UTC)
    day_end = datetime(2026, 7, 1, 23, 59, 59, tzinfo=UTC)
    report = inspect_funding(frame, period_start=day_start, period_end=day_end, threshold=0.99)
    assert report.expected_rows == 6
    assert not report.blocking


def test_funding_duplicates_block() -> None:
    frame = funding_fixture(interval_hours=8, rows=3)
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    day_start = datetime(2026, 7, 1, tzinfo=UTC)
    day_end = datetime(2026, 7, 2, tzinfo=UTC)
    report = inspect_funding(frame, period_start=day_start, period_end=day_end, threshold=0.99)
    assert report.blocking


def test_metrics_negative_oi_blocks() -> None:
    frame = metrics_fixture(negative_oi=True)
    report = inspect_metrics(
        frame,
        period_start=datetime(2026, 7, 1, tzinfo=UTC),
        period_end=datetime(2026, 7, 1, 3, tzinfo=UTC),
        threshold=0.98,
    )
    assert report.blocking


def test_coverage_passing_threshold() -> None:
    report = inspect_coverage(
        observed=999,
        expected=1000,
        threshold=0.999,
        dataset="ohlcv",
        source_period="2026-06",
    )
    assert not report.blocking
    assert report.excluded_periods == ()


def funding_fixture(interval_hours: int = 8, rows: int = 3) -> pd.DataFrame:
    base = datetime(2026, 7, 1, tzinfo=UTC)
    records = []
    for i in range(rows):
        t = base + timedelta(hours=interval_hours * i)
        records.append(
            {
                "asset": "BTCUSDT",
                "event_time": t,
                "available_time": t,
                "funding_interval_hours": interval_hours,
                "funding_rate": 0.0001,
            }
        )
    return pd.DataFrame(records)


def metrics_fixture(negative_oi: bool = False) -> pd.DataFrame:
    base = datetime(2026, 7, 1, tzinfo=UTC)
    records = []
    for i in range(3):
        t = base + timedelta(hours=i)
        records.append(
            {
                "asset": "BTCUSDT",
                "event_time": t,
                "available_time": t + timedelta(minutes=5),
                "sum_open_interest": -1.0 if negative_oi else 100000.0,
                "sum_open_interest_value": 5000000000.0,
            }
        )
    return pd.DataFrame(records)
