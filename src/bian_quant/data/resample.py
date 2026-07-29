import pandas as pd


def resample_ohlcv(frame: pd.DataFrame, *, rule: str) -> pd.DataFrame:
    indexed = frame.set_index(pd.to_datetime(frame["event_time"], utc=True))
    result = indexed.resample(rule, label="left", closed="left").agg(
        {
            "asset": "first",
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
            "available_time": "max",
            "ingested_at": "max",
            "source": "first",
        }
    )
    return result.dropna(subset=["open", "high", "low", "close"]).rename_axis("event_time").reset_index()
