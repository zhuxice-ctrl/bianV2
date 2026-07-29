import pandas as pd


def resample_ohlcv(frame: pd.DataFrame, *, rule: str) -> pd.DataFrame:
    required = {
        "asset",
        "event_time",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "available_time",
        "ingested_at",
        "source",
    }
    if not required <= set(frame.columns):
        raise ValueError(f"OHLCV columns are missing: {sorted(required - set(frame.columns))}")

    results = []
    for asset, group in frame.groupby("asset", sort=True):
        indexed = group.copy()
        indexed.index = pd.to_datetime(indexed.pop("event_time"), utc=True)
        result = indexed.resample(rule, label="left", closed="left").agg(
            {
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
        result.insert(0, "asset", asset)
        results.append(
            result.dropna(subset=["open", "high", "low", "close"])
            .rename_axis("event_time")
            .reset_index()
        )
    if not results:
        return pd.DataFrame(columns=["event_time", *sorted(required - {"event_time"})])
    return pd.concat(results, ignore_index=True).sort_values(["asset", "event_time"])
