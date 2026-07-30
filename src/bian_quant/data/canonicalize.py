"""Canonical parsers for OHLCV, Funding, and Metrics/OI ZIP archives.

Each parser reads a single-CSV ZIP, validates the schema, converts to a
point-in-time DataFrame, and cleans up temporary extraction paths.

All parsers produce frames with at least:
  asset, event_time, available_time, ingested_at, source

Missing values are preserved — never forward-filled or zero-filled.
"""

from __future__ import annotations

import csv
import io
import shutil
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

from bian_quant.data.adapters.binance_derivatives import (
    EXPECTED_FUNDING_COLUMNS,
    EXPECTED_METRICS_COLUMNS,
    _require_exact_schema,
)
from bian_quant.data.hashing import dataframe_content_hash

EXPECTED_OHLCV_COLUMNS = {
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
}


def _extract_single_csv(path: Path, *, temp_root: Path | None = None) -> bytes:
    """Extract and return the single CSV payload from a ZIP archive.

    If *temp_root* is given, extraction happens there and is cleaned up
    in a ``finally`` block.  If extraction fails, ``ARCHIVE_INVALID`` is raised.
    """
    if temp_root is not None:
        temp_root.mkdir(parents=True, exist_ok=True)
        try:
            try:
                with zipfile.ZipFile(path, "r") as zf:
                    names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                    if len(names) != 1:
                        raise ValueError("ARCHIVE_INVALID: expected exactly one CSV member")
                    zf.extract(names[0], temp_root)
                    return (temp_root / names[0]).read_bytes()
            except zipfile.BadZipFile as error:
                raise ValueError("ARCHIVE_INVALID: not a valid ZIP file") from error
        finally:
            if temp_root.exists():
                shutil.rmtree(temp_root, ignore_errors=True)
    else:
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = [n for n in zf.namelist() if n.lower().endswith(".csv")]
                if len(names) != 1:
                    raise ValueError("ARCHIVE_INVALID: expected exactly one CSV member")
                return zf.read(names[0])
        except zipfile.BadZipFile as error:
            raise ValueError("ARCHIVE_INVALID: not a valid ZIP file") from error


_OHLCV_FIELDNAMES = [
    "open_time",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_volume",
    "trades",
    "taker_buy_base",
    "taker_buy_quote",
    "ignore",
]


def _parse_csv_bytes(
    payload: bytes, *, fieldnames: list[str] | None = None
) -> list[dict[str, str]]:
    """Parse CSV bytes into a list of dict rows.

    If *fieldnames* is provided, the CSV is treated as headerless and the
    given names are assigned positionally.  Otherwise the first row is used
    as the header (standard DictReader behaviour).
    """
    text_stream = io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
    if fieldnames is not None:
        reader = csv.DictReader(text_stream, fieldnames=fieldnames)
    else:
        reader = csv.DictReader(text_stream)
    return list(reader)


def canonicalize_ohlcv_zip(
    path: Path,
    *,
    asset: str,
    interval: str,
    ingested_at: datetime,
    temp_root: Path | None = None,
) -> pd.DataFrame:
    """Parse an OHLCV ZIP into a canonical point-in-time DataFrame.

    ``available_time`` is set to the source ``close_time`` (when the bar's
    close and volume become known).  ``event_time`` is the bar's ``open_time``.
    """
    csv_bytes = _extract_single_csv(path, temp_root=temp_root)
    # Binance USD-M klines archives are headerless; test fixtures have headers.
    # Detect headerless by checking if the first row looks like numeric data
    # (12 fields, first field is a millisecond timestamp).
    import csv as _csv
    import io as _io

    _peek = list(_csv.reader(_io.TextIOWrapper(_io.BytesIO(csv_bytes), encoding="utf-8")))
    if _peek and len(_peek[0]) == 12 and _peek[0][0].isdigit():
        rows = _parse_csv_bytes(csv_bytes, fieldnames=_OHLCV_FIELDNAMES)
    else:
        rows = _parse_csv_bytes(csv_bytes)
    if not rows:
        raise ValueError("OHLCV_SCHEMA_CHANGED: archive contains no rows")
    # Normalize Binance column name variants (2022+ renamed some columns)
    _COLUMN_ALIASES = {
        "count": "trades",
        "taker_buy_volume": "taker_buy_base",
        "taker_buy_quote_volume": "taker_buy_quote",
    }
    normalized_rows = []
    for row in rows:
        normalized = {_COLUMN_ALIASES.get(k, k): v for k, v in row.items()}
        normalized_rows.append(normalized)
    rows = normalized_rows
    actual_columns = set(rows[0].keys())
    if actual_columns != EXPECTED_OHLCV_COLUMNS:
        missing = sorted(EXPECTED_OHLCV_COLUMNS - actual_columns)
        unexpected = sorted(actual_columns - EXPECTED_OHLCV_COLUMNS)
        raise ValueError(f"OHLCV_SCHEMA_CHANGED: missing={missing} unexpected={unexpected}")

    records: list[dict[str, Any]] = []
    for row in rows:
        open_time = datetime.fromtimestamp(int(row["open_time"]) / 1000, tz=UTC)
        close_time = datetime.fromtimestamp(int(row["close_time"]) / 1000, tz=UTC)
        records.append(
            {
                "asset": asset,
                "event_time": open_time,
                "available_time": close_time,
                "ingested_at": ingested_at,
                "source": "binance_ohlcv_archive",
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "volume": float(row["volume"]),
                "source_open_time": open_time,
                "source_close_time": close_time,
                "quote_volume": float(row["quote_volume"]),
                "trades": int(row["trades"]),
                "taker_buy_base": float(row["taker_buy_base"]),
                "taker_buy_quote": float(row["taker_buy_quote"]),
                "interval": interval,
            }
        )

    frame = pd.DataFrame(records)
    frame = frame.sort_values(["asset", "event_time"]).reset_index(drop=True)
    return frame


def canonicalize_funding_zip(path: Path, *, asset: str, ingested_at: datetime) -> pd.DataFrame:
    """Parse a Funding ZIP into a canonical point-in-time DataFrame.

    Funding ``available_time`` equals ``event_time`` (the archived calc_time).
    """
    csv_bytes = _extract_single_csv(path)
    rows = _parse_csv_bytes(csv_bytes)
    if not rows:
        raise ValueError("DERIVATIVES_EMPTY: funding archive contains no rows")
    _require_exact_schema(set(rows[0]), EXPECTED_FUNDING_COLUMNS, "funding")

    records: list[dict[str, Any]] = []
    for row in rows:
        event_time = datetime.fromtimestamp(int(row["calc_time"]) / 1000, tz=UTC)
        records.append(
            {
                "asset": asset,
                "event_time": event_time,
                "available_time": event_time,
                "ingested_at": ingested_at,
                "source": "binance_funding_archive",
                "funding_interval_hours": int(row["funding_interval_hours"]),
                "funding_rate": float(row["last_funding_rate"]),
                "source_timestamp": row["calc_time"],
            }
        )

    frame = pd.DataFrame(records)
    frame = frame.sort_values(["asset", "event_time"]).reset_index(drop=True)
    return frame


def canonicalize_metrics_zip(
    path: Path,
    *,
    ingested_at: datetime,
    publication_delay: timedelta,
) -> pd.DataFrame:
    """Parse a Metrics/OI ZIP into a canonical point-in-time DataFrame.

    ``available_time`` is ``event_time + publication_delay``.
    The assumption label (e.g. ``BINANCE_METRICS_DELAY_5M``) is stored
    in every row.
    """
    csv_bytes = _extract_single_csv(path)
    rows = _parse_csv_bytes(csv_bytes)
    if not rows:
        raise ValueError("DERIVATIVES_EMPTY: metrics archive contains no rows")
    _require_exact_schema(set(rows[0]), EXPECTED_METRICS_COLUMNS, "metrics")

    delay_minutes = int(publication_delay.total_seconds() // 60)
    assumption_label = f"BINANCE_METRICS_DELAY_{delay_minutes}M"

    def optional_float(value: str) -> float:
        return float(value) if value.strip() else float("nan")

    records: list[dict[str, Any]] = []
    for row in rows:
        event_time = datetime.strptime(row["create_time"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        records.append(
            {
                "asset": row["symbol"],
                "event_time": event_time,
                "available_time": event_time + publication_delay,
                "ingested_at": ingested_at,
                "source": "binance_metrics_archive",
                "availability_assumption": assumption_label,
                "sum_open_interest": optional_float(row["sum_open_interest"]),
                "sum_open_interest_value": optional_float(row["sum_open_interest_value"]),
                "top_trader_account_long_short_ratio": optional_float(
                    row["count_toptrader_long_short_ratio"]
                ),
                "top_trader_position_long_short_ratio": optional_float(
                    row["sum_toptrader_long_short_ratio"]
                ),
                "global_account_long_short_ratio": optional_float(row["count_long_short_ratio"]),
                "taker_long_short_volume_ratio": optional_float(
                    row["sum_taker_long_short_vol_ratio"]
                ),
                "source_timestamp": row["create_time"],
            }
        )

    frame = pd.DataFrame(records)
    frame = frame.sort_values(["asset", "event_time"]).reset_index(drop=True)
    return frame


def canonical_partition_path(
    root: Path, *, dataset: str, asset: str, year: int, month: int
) -> Path:
    """Return the deterministic partition path for a canonical dataset."""
    return root / dataset / asset / f"year={year}" / f"month={month:02d}" / "data.parquet"


def write_canonical_partition(frame: pd.DataFrame, path: Path) -> str:
    """Write a DataFrame as Zstd Parquet and return its content hash.

    Refuses to overwrite a file with different content.  Writing the same
    content again is idempotent.
    """
    content_hash = dataframe_content_hash(frame, sort_by=["asset", "event_time"])

    if path.exists():
        existing = pd.read_parquet(path)
        existing_hash = dataframe_content_hash(existing, sort_by=["asset", "event_time"])
        if existing_hash != content_hash:
            raise ValueError(
                "CANONICAL_PARTITION_CONFLICT: existing partition has different content"
            )
        return existing_hash

    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(path, engine="pyarrow", compression="zstd", index=False)
    return content_hash
