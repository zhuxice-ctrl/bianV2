from datetime import datetime
from pathlib import Path

import pandas as pd

INTERVALS = {"1h": pd.Timedelta(hours=1), "4h": pd.Timedelta(hours=4), "1d": pd.Timedelta(days=1)}


def import_legacy_ohlcv(
    path: Path, *, asset: str, interval: str, ingested_at: datetime
) -> pd.DataFrame:
    if interval not in INTERVALS:
        raise ValueError(f"unsupported interval: {interval}")
    if ingested_at.tzinfo is None:
        raise ValueError("ingested_at must be timezone-aware")
    frame = pd.read_csv(path)
    required = {"datetime", "open", "high", "low", "close", "volume"}
    if not required <= set(frame.columns):
        missing = sorted(required - set(frame.columns))
        raise ValueError(f"legacy OHLCV columns are missing: {missing}")
    event_time = pd.to_datetime(frame.pop("datetime"), utc=True)
    frame.insert(0, "asset", asset)
    frame.insert(1, "interval", interval)
    frame.insert(2, "event_time", event_time)
    frame.insert(3, "available_time", event_time + INTERVALS[interval])
    frame.insert(4, "ingested_at", pd.Timestamp(ingested_at))
    frame.insert(5, "source", "legacy_csv")
    if (frame["available_time"] > frame["ingested_at"]).any():
        raise ValueError("ingested_at must not precede available_time")
    return frame.sort_values(["asset", "event_time"]).reset_index(drop=True)
