import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from bian_quant.cli import app
from bian_quant.data.legacy import import_legacy_ohlcv
from bian_quant.data.writer import write_parquet


def test_legacy_import_sets_bar_close_as_available_time(tmp_path: Path) -> None:
    source = tmp_path / "BTCUSDT_4h.csv"
    pd.DataFrame(
        [
            {
                "datetime": "2026-01-01T00:00:00Z",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 3,
            }
        ]
    ).to_csv(source, index=False)

    frame = import_legacy_ohlcv(
        source,
        asset="BTCUSDT",
        interval="4h",
        ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
    )

    assert frame.loc[0, "event_time"] == pd.Timestamp("2026-01-01T00:00:00Z")
    assert frame.loc[0, "available_time"] == pd.Timestamp("2026-01-01T04:00:00Z")


def test_legacy_import_is_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "BTCUSDT_4h.csv"
    pd.DataFrame(
        [
            {
                "datetime": "2026-01-01T00:00:00Z",
                "open": 1,
                "high": 2,
                "low": 1,
                "close": 2,
                "volume": 3,
            },
            {
                "datetime": "2026-01-01T04:00:00Z",
                "open": 2,
                "high": 3,
                "low": 2,
                "close": 3,
                "volume": 5,
            },
        ]
    ).to_csv(source, index=False)

    ingested_at = datetime(2026, 1, 2, tzinfo=UTC)
    frame1 = import_legacy_ohlcv(source, asset="BTCUSDT", interval="4h", ingested_at=ingested_at)
    frame2 = import_legacy_ohlcv(source, asset="BTCUSDT", interval="4h", ingested_at=ingested_at)

    pd.testing.assert_frame_equal(frame1, frame2)


def test_legacy_import_rejects_naive_ingestion_time(tmp_path: Path) -> None:
    source = tmp_path / "BTCUSDT_1h.csv"
    pd.DataFrame(
        [
            {
                "datetime": "2026-01-01T00:00:00Z",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            }
        ]
    ).to_csv(source, index=False)

    with pytest.raises(ValueError, match="timezone-aware"):
        import_legacy_ohlcv(
            source,
            asset="BTCUSDT",
            interval="1h",
            ingested_at=datetime(2026, 1, 2),
        )


def test_legacy_parquet_bytes_are_deterministic(tmp_path: Path) -> None:
    source = tmp_path / "BTCUSDT_1h.csv"
    pd.DataFrame(
        [
            {
                "datetime": "2026-01-01T00:00:00Z",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            }
        ]
    ).to_csv(source, index=False)
    frame = import_legacy_ohlcv(
        source,
        asset="BTCUSDT",
        interval="1h",
        ingested_at=datetime(2026, 1, 2, tzinfo=UTC),
    )
    first = tmp_path / "first.parquet"
    second = tmp_path / "second.parquet"

    write_parquet(frame, first)
    write_parquet(frame, second)

    first_hash = hashlib.sha256(first.read_bytes()).digest()
    second_hash = hashlib.sha256(second.read_bytes()).digest()
    assert first_hash == second_hash


def test_legacy_cli_accepts_timezone_aware_iso_timestamp(tmp_path: Path) -> None:
    source = tmp_path / "BTCUSDT_1h.csv"
    output = tmp_path / "BTCUSDT_1h.parquet"
    pd.DataFrame(
        [
            {
                "datetime": "2026-01-01T00:00:00Z",
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
            }
        ]
    ).to_csv(source, index=False)

    result = CliRunner().invoke(
        app,
        [
            "import-legacy",
            str(source),
            "BTCUSDT",
            "1h",
            str(output),
            "--ingested-at",
            "2026-07-29T00:00:00+00:00",
        ],
    )

    assert result.exit_code == 0, result.output
    assert output.exists()
