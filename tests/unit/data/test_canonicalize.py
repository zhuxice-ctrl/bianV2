"""Tests for canonical partition parsers and writers."""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from bian_quant.data.canonicalize import (
    canonical_partition_path,
    canonicalize_funding_zip,
    canonicalize_metrics_zip,
    canonicalize_ohlcv_zip,
    write_canonical_partition,
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "binance"


def test_ohlcv_close_is_available_at_source_close_time() -> None:
    frame = canonicalize_ohlcv_zip(
        FIXTURES / "ohlcv-mini.zip",
        asset="BTCUSDT",
        interval="1h",
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    assert frame.loc[0, "available_time"] == frame.loc[0, "source_close_time"]
    assert frame.loc[0, "available_time"] > frame.loc[0, "event_time"]


def test_ohlcv_frame_has_required_columns() -> None:
    frame = canonicalize_ohlcv_zip(
        FIXTURES / "ohlcv-mini.zip",
        asset="BTCUSDT",
        interval="1h",
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    required = {
        "asset",
        "event_time",
        "available_time",
        "ingested_at",
        "source",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "source_open_time",
        "source_close_time",
        "quote_volume",
        "trades",
        "taker_buy_base",
        "taker_buy_quote",
    }
    assert required <= set(frame.columns)


def test_funding_available_time_equals_event_time() -> None:
    frame = canonicalize_funding_zip(
        FIXTURES / "funding-mini.zip",
        asset="BTCUSDT",
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    assert (frame["available_time"] == frame["event_time"]).all()
    assert "funding_rate" in frame.columns
    assert "funding_interval_hours" in frame.columns


def test_metrics_delay_is_explicit() -> None:
    frame = canonicalize_metrics_zip(
        FIXTURES / "metrics-mini.zip",
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
        publication_delay=timedelta(minutes=10),
    )
    assert (frame["available_time"] - frame["event_time"]).unique() == [pd.Timedelta(minutes=10)]
    assert set(frame["availability_assumption"]) == {"BINANCE_METRICS_DELAY_10M"}


def test_metrics_default_delay_is_5m() -> None:
    frame = canonicalize_metrics_zip(
        FIXTURES / "metrics-mini.zip",
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
        publication_delay=timedelta(minutes=5),
    )
    assert set(frame["availability_assumption"]) == {"BINANCE_METRICS_DELAY_5M"}


def test_metrics_blank_ratios_remain_missing(tmp_path: Path) -> None:
    csv_bytes = (
        b"create_time,symbol,sum_open_interest,sum_open_interest_value,"
        b"count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        b"count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
        b"2024-08-12 09:00:00,BTCUSDT,100,200,,,,1.2\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("BTCUSDT-metrics-2024-08-12.csv", csv_bytes)
    path = tmp_path / "metrics-with-blanks.zip"
    path.write_bytes(buffer.getvalue())

    frame = canonicalize_metrics_zip(
        path,
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
        publication_delay=timedelta(minutes=5),
    )

    assert pd.isna(frame.loc[0, "top_trader_account_long_short_ratio"])
    assert pd.isna(frame.loc[0, "top_trader_position_long_short_ratio"])
    assert pd.isna(frame.loc[0, "global_account_long_short_ratio"])
    assert frame.loc[0, "taker_long_short_volume_ratio"] == 1.2


def test_partition_path_is_dataset_asset_year_month() -> None:
    path = canonical_partition_path(
        Path("var/canonical"),
        dataset="funding",
        asset="ETHUSDT",
        year=2026,
        month=7,
    )
    assert path.as_posix().endswith("funding/ETHUSDT/year=2026/month=07/data.parquet")


def test_temporary_extraction_is_removed_after_parser_failure(tmp_path: Path) -> None:
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not-a-zip")
    with pytest.raises(ValueError, match="ARCHIVE_INVALID"):
        canonicalize_ohlcv_zip(
            broken,
            asset="BTCUSDT",
            interval="1h",
            ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
            temp_root=tmp_path / "temp",
        )
    assert not (tmp_path / "temp").exists()


def test_write_canonical_partition_returns_hash(tmp_path: Path) -> None:
    frame = canonicalize_ohlcv_zip(
        FIXTURES / "ohlcv-mini.zip",
        asset="BTCUSDT",
        interval="1h",
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    path = tmp_path / "data.parquet"
    content_hash = write_canonical_partition(frame, path)
    assert len(content_hash) == 64
    assert path.exists()


def test_write_canonical_partition_refuses_overwrite_different(tmp_path: Path) -> None:
    frame = canonicalize_ohlcv_zip(
        FIXTURES / "ohlcv-mini.zip",
        asset="BTCUSDT",
        interval="1h",
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    path = tmp_path / "data.parquet"
    write_canonical_partition(frame, path)
    # Writing the same content again should be idempotent
    result = write_canonical_partition(frame, path)
    assert len(result) == 64
    changed = frame.copy()
    changed.loc[0, "close"] += 1.0
    with pytest.raises(ValueError, match="CANONICAL_PARTITION_CONFLICT"):
        write_canonical_partition(changed, path)


def test_ohlcv_schema_change_rejected(tmp_path: Path) -> None:
    """A ZIP with wrong columns must raise OHLCV_SCHEMA_CHANGED."""
    csv_bytes = b"wrong_header,open\n1753756800000,50000.0\n"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("BTCUSDT-1h-2026-07-29.csv", csv_bytes)
    bad_zip = tmp_path / "bad.zip"
    bad_zip.write_bytes(buf.getvalue())
    with pytest.raises(ValueError, match="OHLCV_SCHEMA_CHANGED"):
        canonicalize_ohlcv_zip(
            bad_zip,
            asset="BTCUSDT",
            interval="1h",
            ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
        )


def test_available_time_never_precedes_event_time() -> None:
    """All canonicalized frames must satisfy available_time >= event_time."""
    frame = canonicalize_ohlcv_zip(
        FIXTURES / "ohlcv-mini.zip",
        asset="BTCUSDT",
        interval="1h",
        ingested_at=datetime(2026, 7, 30, tzinfo=UTC),
    )
    assert (frame["available_time"] >= frame["event_time"]).all()
