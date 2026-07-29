from pathlib import Path

import pandas as pd
import pytest

from bian_quant.data.quality import inspect_ohlcv
from bian_quant.data.writer import DataQualityError, write_canonical_ohlcv


def test_impossible_ohlc_is_blocking() -> None:
    frame = pd.DataFrame(
        [
            {
                "open": 10,
                "high": 9,
                "low": 8,
                "close": 10,
                "volume": 1,
                "event_time": "2026-01-01T00:00:00Z",
            }
        ]
    )

    report = inspect_ohlcv(frame, expected_frequency="1h")

    assert report.blocking
    assert "OHLC_RELATION" in {finding.code for finding in report.findings}


def test_missing_bar_is_reported() -> None:
    frame = pd.DataFrame(
        [
            {
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
                "event_time": "2026-01-01T00:00:00Z",
            },
            {
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
                "event_time": "2026-01-01T02:00:00Z",
            },
        ]
    )

    report = inspect_ohlcv(frame, expected_frequency="1h")

    assert "TIME_GAP" in {finding.code for finding in report.findings}


def test_negative_volume_is_blocking() -> None:
    frame = pd.DataFrame(
        [
            {
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": -5,
                "event_time": "2026-01-01T00:00:00Z",
            }
        ]
    )

    report = inspect_ohlcv(frame, expected_frequency="1h")

    assert report.blocking
    assert "NEGATIVE_VOLUME" in {finding.code for finding in report.findings}


def test_clean_data_has_no_findings() -> None:
    frame = pd.DataFrame(
        [
            {
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 5,
                "event_time": "2026-01-01T00:00:00Z",
            },
            {
                "open": 2,
                "high": 3,
                "low": 2,
                "close": 3,
                "volume": 6,
                "event_time": "2026-01-01T01:00:00Z",
            },
        ]
    )

    report = inspect_ohlcv(frame, expected_frequency="1h")

    assert not report.blocking


def test_gap_checks_do_not_mix_assets() -> None:
    frame = pd.DataFrame(
        [
            {
                "asset": asset,
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
                "event_time": timestamp,
            }
            for asset in ("BTCUSDT", "ETHUSDT")
            for timestamp in ("2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z")
        ]
    )

    report = inspect_ohlcv(frame, expected_frequency="1h")

    assert "TIME_GAP" not in {finding.code for finding in report.findings}
    assert "DUPLICATE_BAR" not in {finding.code for finding in report.findings}


def test_blocking_finding_prevents_publication(tmp_path: Path) -> None:
    frame = pd.DataFrame(
        [
            {
                "asset": "BTCUSDT",
                "open": 10,
                "high": 9,
                "low": 8,
                "close": 10,
                "volume": 1,
                "event_time": "2026-01-01T00:00:00Z",
            }
        ]
    )
    output = tmp_path / "invalid.parquet"

    with pytest.raises(DataQualityError, match="OHLC_RELATION"):
        write_canonical_ohlcv(frame, output, expected_frequency="1h")

    assert not output.exists()
