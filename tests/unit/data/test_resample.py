import pandas as pd

from bian_quant.data.resample import resample_ohlcv


def test_resample_1h_to_4h_preserves_causal_availability() -> None:
    frame = pd.DataFrame(
        {
            "asset": ["BTCUSDT"] * 4,
            "event_time": pd.to_datetime(
                [
                    "2026-01-01T00:00:00Z",
                    "2026-01-01T01:00:00Z",
                    "2026-01-01T02:00:00Z",
                    "2026-01-01T03:00:00Z",
                ]
            ),
            "open": [100.0, 101.0, 102.0, 103.0],
            "high": [105.0, 106.0, 107.0, 108.0],
            "low": [99.0, 100.0, 101.0, 102.0],
            "close": [101.0, 102.0, 103.0, 104.0],
            "volume": [10.0, 20.0, 30.0, 40.0],
            "available_time": pd.to_datetime(
                [
                    "2026-01-01T01:00:00Z",
                    "2026-01-01T02:00:00Z",
                    "2026-01-01T03:00:00Z",
                    "2026-01-01T04:00:00Z",
                ]
            ),
            "ingested_at": pd.to_datetime(
                [
                    "2026-01-01T01:00:00Z",
                    "2026-01-01T02:00:00Z",
                    "2026-01-01T03:00:00Z",
                    "2026-01-01T04:00:00Z",
                ]
            ),
            "source": ["test"] * 4,
        }
    )

    result = resample_ohlcv(frame, rule="4h")

    assert len(result) == 1
    row = result.iloc[0]
    assert row["open"] == 100.0
    assert row["high"] == 108.0
    assert row["low"] == 99.0
    assert row["close"] == 104.0
    assert row["volume"] == 100.0
    assert row["available_time"] == pd.Timestamp("2026-01-01T04:00:00Z")


def test_resample_never_combines_different_assets() -> None:
    timestamps = pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"])
    frame = pd.DataFrame(
        {
            "asset": ["BTCUSDT", "BTCUSDT", "ETHUSDT", "ETHUSDT"],
            "event_time": [*timestamps, *timestamps],
            "open": [100.0, 101.0, 200.0, 201.0],
            "high": [102.0, 103.0, 202.0, 203.0],
            "low": [99.0, 100.0, 199.0, 200.0],
            "close": [101.0, 102.0, 201.0, 202.0],
            "volume": [1.0, 1.0, 2.0, 2.0],
            "available_time": [
                *pd.to_datetime(["2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"]),
                *pd.to_datetime(["2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"]),
            ],
            "ingested_at": pd.to_datetime(["2026-01-02T00:00:00Z"] * 4),
            "source": ["test"] * 4,
        }
    )

    result = resample_ohlcv(frame, rule="4h")

    assert result["asset"].tolist() == ["BTCUSDT", "ETHUSDT"]
    assert result["open"].tolist() == [100.0, 200.0]
    assert result["close"].tolist() == [102.0, 202.0]
