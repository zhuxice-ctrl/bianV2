from pathlib import Path

import pandas as pd

from bian_quant.factors.screening import load_legacy_screening_data


def test_legacy_screening_uses_close_time_as_availability(tmp_path: Path) -> None:
    source = pd.DataFrame(
        {
            "open_time": [0, 14_400_000],
            "close_time": [14_399_999, 28_799_999],
            "close": [100.0, 101.0],
            "volume": [10.0, 11.0],
        }
    )
    source.to_csv(tmp_path / "BTCUSDT_4h.csv", index=False)

    frame, snapshot_id = load_legacy_screening_data(tmp_path, assets=["BTCUSDT"], interval="4h")

    assert frame.loc[0, "available_time"] == pd.Timestamp("1970-01-01T03:59:59.999Z")
    assert frame.loc[0, "timestamp"] == frame.loc[0, "available_time"]
    assert frame.loc[0, "available_time"] > frame.loc[0, "event_time"]
    assert snapshot_id.startswith("legacy-ohlcv-4h-")
