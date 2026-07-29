from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from bian_quant.data.legacy import import_legacy_ohlcv


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
