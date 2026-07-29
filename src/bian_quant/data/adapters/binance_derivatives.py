import csv
import io
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.request import urlopen

from bian_quant.data.adapters.binance_archive import save_raw_bytes

FUNDING_BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
METRICS_BASE = "https://data.binance.vision/data/futures/um/daily/metrics"

OI_PUBLICATION_DELAY = timedelta(minutes=5)
OI_PUBLICATION_ASSUMPTION = "BINANCE_METRICS_MAX_PUBLICATION_DELAY_5M"

EXPECTED_FUNDING_COLUMNS = {"calc_time", "funding_rate", "symbol"}
EXPECTED_METRICS_COLUMNS = {
    "sum_open_interest",
    "sum_open_interest_value",
    "count",
    "sum_open_interest_cost",
    "sum_open_interest_cost_value",
    "long_short_ratio",
    "long_account",
    "short_account",
    "long_position",
    "short_position",
    "timestamp",
}


def funding_url(asset: str, year: int, month: int) -> str:
    filename = f"{asset}-fundingRate-{year:04d}-{month:02d}.zip"
    return f"{FUNDING_BASE}/{asset}/{filename}"


def metrics_url(asset: str, date: datetime) -> str:
    date_str = date.strftime("%Y-%m-%d")
    filename = f"{asset}-metrics-{date_str}.zip"
    return f"{METRICS_BASE}/{asset}/{filename}"


def _read_zip_csv(payload: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = zf.namelist()
        if not names:
            return []
        with zf.open(names[0]) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
            return list(reader)


def parse_funding(payload: bytes) -> list[dict[str, Any]]:
    rows = _read_zip_csv(payload)
    if not rows:
        return []
    actual_cols = set(rows[0].keys())
    missing = EXPECTED_FUNDING_COLUMNS - actual_cols
    if missing:
        raise ValueError(f"DERIVATIVES_SCHEMA_CHANGED: missing funding columns: {missing}")
    result = []
    for row in rows:
        event_time = datetime.fromtimestamp(int(row["calc_time"]) / 1000, tz=UTC)
        result.append(
            {
                "asset": row["symbol"],
                "event_time": event_time,
                "available_time": event_time,
                "funding_rate": float(row["funding_rate"]),
                "source": "binance_funding_archive",
            }
        )
    return result


def parse_metrics(payload: bytes) -> list[dict[str, Any]]:
    rows = _read_zip_csv(payload)
    if not rows:
        return []
    actual_cols = set(rows[0].keys())
    unexpected = actual_cols - EXPECTED_METRICS_COLUMNS
    if unexpected:
        raise ValueError(f"DERIVATIVES_SCHEMA_CHANGED: unexpected metrics columns: {unexpected}")
    result = []
    for row in rows:
        event_time = datetime.fromtimestamp(int(row["timestamp"]) / 1000, tz=UTC)
        result.append(
            {
                "asset": row.get("symbol", ""),
                "event_time": event_time,
                "available_time": event_time + OI_PUBLICATION_DELAY,
                "available_assumption": OI_PUBLICATION_ASSUMPTION,
                "sum_open_interest": float(row["sum_open_interest"]),
                "sum_open_interest_value": float(row["sum_open_interest_value"]),
                "long_short_ratio": float(row.get("long_short_ratio", 0)),
                "source": "binance_metrics_archive",
            }
        )
    return result


def download_funding(path: Path, *, asset: str, year: int, month: int) -> None:
    with urlopen(funding_url(asset, year, month), timeout=60) as response:
        save_raw_bytes(path, response.read())


def download_metrics(path: Path, *, asset: str, date: datetime) -> None:
    with urlopen(metrics_url(asset, date), timeout=60) as response:
        save_raw_bytes(path, response.read())
