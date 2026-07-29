import pandas as pd

_REQUIRED_AUDIT_COLUMNS = {"asset", "event_time", "available_time", "ingested_at", "source"}


def resample_point_in_time(
    frame: pd.DataFrame,
    *,
    rule: str,
    aggregations: dict[str, str],
) -> pd.DataFrame:
    """Causal point-in-time resampling.

    Groups by asset, indexes by event time, applies only named aggregations,
    and always aggregates ``available_time=max``, ``ingested_at=max``,
    ``source=first``.  Rejects unsupported aggregation names, missing audit
    columns, or output rows whose availability precedes any contributing record.
    Does not fill missing values.
    """
    missing = _REQUIRED_AUDIT_COLUMNS - set(frame.columns)
    if missing:
        raise ValueError(f"audit columns are missing: {sorted(missing)}")

    valid_aggs = {"first", "last", "max", "min", "sum", "mean"}
    bad_aggs = set(aggregations.values()) - valid_aggs
    if bad_aggs:
        raise ValueError(f"unsupported aggregation names: {sorted(bad_aggs)}")

    all_aggs = dict(aggregations)
    all_aggs["available_time"] = "max"
    all_aggs["ingested_at"] = "max"
    all_aggs["source"] = "first"

    # Only include columns that exist in the frame
    all_aggs = {k: v for k, v in all_aggs.items() if k in frame.columns}

    results = []
    for asset, group in frame.groupby("asset", sort=True):
        indexed = group.copy()
        indexed.index = pd.to_datetime(indexed.pop("event_time"), utc=True)
        result = indexed.resample(rule, label="left", closed="left").agg(all_aggs)
        result.insert(0, "asset", asset)
        results.append(
            result.dropna(subset=["available_time"])
            .rename_axis("event_time")
            .reset_index()
        )
    if not results:
        return pd.DataFrame(columns=["event_time", *sorted(_REQUIRED_AUDIT_COLUMNS - {"event_time"})])
    return pd.concat(results, ignore_index=True).sort_values(["asset", "event_time"])


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
