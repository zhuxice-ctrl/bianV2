"""Binance USD-M futures derivatives (funding rate and metrics/OI) adapters."""

from __future__ import annotations

import csv
import io
import zipfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from bian_quant.data.adapters.binance_archive import download_verified
from bian_quant.data.adapters.raw import AcquisitionObjectResult, RawSourceIdentity

FUNDING_BASE = "https://data.binance.vision/data/futures/um/monthly/fundingRate"
DAILY_FUNDING_BASE = "https://data.binance.vision/data/futures/um/daily/fundingRate"
METRICS_BASE = "https://data.binance.vision/data/futures/um/daily/metrics"

OI_PUBLICATION_DELAY = timedelta(minutes=5)
OI_PUBLICATION_ASSUMPTION = "BINANCE_METRICS_MAX_PUBLICATION_DELAY_5M"

EXPECTED_FUNDING_COLUMNS = {"calc_time", "funding_interval_hours", "last_funding_rate"}
EXPECTED_METRICS_COLUMNS = {
    "create_time",
    "symbol",
    "sum_open_interest",
    "sum_open_interest_value",
    "count_toptrader_long_short_ratio",
    "sum_toptrader_long_short_ratio",
    "count_long_short_ratio",
    "sum_taker_long_short_vol_ratio",
}


def funding_url(asset: str, year: int, month: int) -> str:
    filename = f"{asset}-fundingRate-{year:04d}-{month:02d}.zip"
    return f"{FUNDING_BASE}/{asset}/{filename}"


def daily_funding_url(asset: str, day: date) -> str:
    stamp = day.isoformat()
    filename = f"{asset}-fundingRate-{stamp}.zip"
    return f"{DAILY_FUNDING_BASE}/{asset}/{filename}"


def metrics_url(asset: str, date: datetime) -> str:
    date_str = date.strftime("%Y-%m-%d")
    filename = f"{asset}-metrics-{date_str}.zip"
    return f"{METRICS_BASE}/{asset}/{filename}"


def _read_zip_csv(payload: bytes) -> list[dict[str, str]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        if len(names) != 1:
            raise ValueError("DERIVATIVES_ARCHIVE_INVALID: expected exactly one CSV")
        with zf.open(names[0]) as f:
            reader = csv.DictReader(io.TextIOWrapper(f, encoding="utf-8"))
            return list(reader)


def _require_exact_schema(actual: set[str], expected: set[str], dataset: str) -> None:
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise ValueError(
            f"DERIVATIVES_SCHEMA_CHANGED: {dataset} missing={missing} unexpected={unexpected}"
        )


def parse_funding(payload: bytes, *, asset: str) -> list[dict[str, Any]]:
    rows = _read_zip_csv(payload)
    if not rows:
        raise ValueError("DERIVATIVES_EMPTY: funding archive contains no rows")
    _require_exact_schema(set(rows[0]), EXPECTED_FUNDING_COLUMNS, "funding")
    result = []
    for row in rows:
        event_time = datetime.fromtimestamp(int(row["calc_time"]) / 1000, tz=UTC)
        result.append(
            {
                "asset": asset,
                "event_time": event_time,
                "available_time": event_time,
                "funding_interval_hours": int(row["funding_interval_hours"]),
                "funding_rate": float(row["last_funding_rate"]),
                "source_timestamp": row["calc_time"],
                "source": "binance_funding_archive",
            }
        )
    return result


def parse_metrics(
    payload: bytes, *, publication_delay: timedelta = OI_PUBLICATION_DELAY
) -> list[dict[str, Any]]:
    rows = _read_zip_csv(payload)
    if not rows:
        raise ValueError("DERIVATIVES_EMPTY: metrics archive contains no rows")
    _require_exact_schema(set(rows[0]), EXPECTED_METRICS_COLUMNS, "metrics")
    delay_minutes = int(publication_delay.total_seconds() // 60)
    assumption_label = f"BINANCE_METRICS_DELAY_{delay_minutes}M"
    result = []
    for row in rows:
        event_time = datetime.strptime(row["create_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        result.append(
            {
                "asset": row["symbol"],
                "event_time": event_time,
                "available_time": event_time + publication_delay,
                "availability_assumption": assumption_label,
                "sum_open_interest": float(row["sum_open_interest"]),
                "sum_open_interest_value": float(row["sum_open_interest_value"]),
                "top_trader_account_long_short_ratio": float(
                    row["count_toptrader_long_short_ratio"]
                ),
                "top_trader_position_long_short_ratio": float(
                    row["sum_toptrader_long_short_ratio"]
                ),
                "global_account_long_short_ratio": float(row["count_long_short_ratio"]),
                "taker_long_short_volume_ratio": float(row["sum_taker_long_short_vol_ratio"]),
                "source_timestamp": row["create_time"],
                "source": "binance_metrics_archive",
            }
        )
    return result


def download_funding(path: Path, *, asset: str, year: int, month: int) -> AcquisitionObjectResult:
    identity = RawSourceIdentity(
        asset=asset, dataset="funding", interval="native", source_period=f"{year:04d}-{month:02d}"
    )
    return download_verified(path, url=funding_url(asset, year, month), identity=identity)


def download_metrics(path: Path, *, asset: str, date: datetime) -> AcquisitionObjectResult:
    identity = RawSourceIdentity(
        asset=asset,
        dataset="metrics_oi",
        interval="native",
        source_period=date.strftime("%Y-%m-%d"),
    )
    return download_verified(path, url=metrics_url(asset, date), identity=identity)
