"""Causal Funding-alignment read model.

A narrow, read-only adapter that turns already-published canonical Funding
Parquet artifacts into immutable daily ``FundingAlignmentRecord`` rows.

The adapter owns disk reads and never imports the dashboard, strategy,
exchange, or network modules.  Every record is point-in-time: a record is only
eligible for a decision at time *t* when ``available_time <= t``.  Later
Funding observations can never change an earlier aggregate.

This module produces *evidence*, not trading signals.
"""

from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pyarrow.parquet as pq  # type: ignore[import-untyped]

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_MIN_COVERAGE_RATIO = 0.5

# Cache complete alignment results per (root, assets, as_of) so repeated API
# requests do not re-scan the canonical lake.  Results are deterministic.
_ALIGNMENT_CACHE: dict[tuple[str, tuple[str, ...], str], tuple[FundingAlignmentRecord, ...]] = {}


@dataclass(frozen=True)
class FundingAlignmentRecord:
    """Immutable daily Funding-alignment aggregate.

    ``decision_time`` is the moment the daily aggregate becomes available
    (the latest Funding event time of the day).  ``available_time`` equals
    ``decision_time``: the aggregate cannot be known before its last input.
    """

    decision_time: datetime
    available_time: datetime
    member_count: int
    positive_rate_share: float
    median_rate: float
    coverage_ratio: float
    source_sha256: str

    def __post_init__(self) -> None:
        for name, value in (
            ("decision_time", self.decision_time),
            ("available_time", self.available_time),
        ):
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone-aware")
        if self.available_time > self.decision_time:
            raise ValueError("available_time must not follow decision_time")
        if self.member_count < 0:
            raise ValueError("member_count must be non-negative")
        for metric_name, metric_value in (
            ("positive_rate_share", self.positive_rate_share),
            ("coverage_ratio", self.coverage_ratio),
        ):
            if not (0.0 <= metric_value <= 1.0):
                raise ValueError(f"{metric_name} must lie within [0, 1]")
        if not _SHA256_RE.match(self.source_sha256):
            raise ValueError("source_sha256 must be 64 lowercase hexadecimal characters")


def build_daily_funding_alignment(
    canonical_root: Path,
    *,
    assets: tuple[str, ...],
    as_of: datetime,
) -> tuple[FundingAlignmentRecord, ...]:
    """Build immutable daily Funding-alignment records from canonical Parquet.

    Reads only local canonical Funding Parquet under ``canonical_root`` using
    the layout ``plan=<id>/funding/<ASSET>/native/YYYY-MM.parquet``.  Records
    with ``available_time > as_of`` are discarded.  Rows are grouped by UTC
    date; for each date the aggregate becomes available at the latest Funding
    event time of that day.
    """
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    if not assets:
        return ()
    canonical_root = Path(canonical_root)
    cache_key = (str(canonical_root), tuple(assets), as_of.astimezone(UTC).isoformat())
    cached = _ALIGNMENT_CACHE.get(cache_key)
    if cached is not None:
        return cached
    if not canonical_root.is_dir():
        _ALIGNMENT_CACHE[cache_key] = ()
        return ()

    as_of_utc = _to_utc(as_of)
    frames: list[pd.DataFrame] = []
    file_hashes_by_date: dict[Any, set[str]] = {}

    for asset in assets:
        pattern = f"plan=*/funding/{asset}/native/*.parquet"
        for path in sorted(canonical_root.glob(pattern)):
            try:
                raw = path.read_bytes()
                content_sha = hashlib.sha256(raw).hexdigest()
                table = pq.read_table(io.BytesIO(raw))
            except (OSError, ValueError):
                continue
            frame = table.to_pandas()
            if frame.empty:
                continue
            required = {"asset", "event_time", "available_time", "funding_rate"}
            if not required.issubset(frame.columns):
                continue
            frame = frame[list(required)].copy()
            frame["asset"] = frame["asset"].astype(str)
            frame["event_time"] = pd.to_datetime(frame["event_time"], utc=True)
            frame["available_time"] = pd.to_datetime(frame["available_time"], utc=True)
            frame["funding_rate"] = pd.to_numeric(frame["funding_rate"], errors="coerce")
            frame = frame.dropna(subset=["funding_rate"])
            # Point-in-time gate: only Funding available by as_of may influence.
            frame = frame.loc[frame["available_time"] <= as_of_utc]
            if frame.empty:
                continue
            frame["__date"] = frame["available_time"].dt.tz_convert("UTC").dt.date
            for date_value, _ in frame.groupby("__date"):
                file_hashes_by_date.setdefault(date_value, set()).add(content_sha)
            frames.append(frame)

    if not frames:
        return ()

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.sort_values("available_time").reset_index(drop=True)

    asset_count = len(assets)
    records: list[FundingAlignmentRecord] = []
    for date_value, group in combined.groupby("__date", sort=True):
        decision_time = group["available_time"].max().to_pydatetime()
        member_count = int(group["asset"].nunique())
        rates = group["funding_rate"].astype(float)
        positive_rate_share = float((rates > 0).mean()) if len(rates) else 0.0
        median_rate = float(rates.median()) if len(rates) else 0.0
        coverage_ratio = member_count / asset_count if asset_count else 0.0
        contributing = sorted(file_hashes_by_date.get(date_value, set()))
        source_sha256 = hashlib.sha256("".join(contributing).encode("utf-8")).hexdigest()
        records.append(
            FundingAlignmentRecord(
                decision_time=decision_time,
                available_time=decision_time,
                member_count=member_count,
                positive_rate_share=round(positive_rate_share, 8),
                median_rate=round(median_rate, 12),
                coverage_ratio=round(coverage_ratio, 8),
                source_sha256=source_sha256,
            )
        )
    result = tuple(records)
    _ALIGNMENT_CACHE[cache_key] = result
    return result


def latest_alignment_through(
    records: tuple[FundingAlignmentRecord, ...] | None,
    decision_time: datetime | None,
) -> FundingAlignmentRecord | None:
    """Return the most recent alignment record available by *decision_time*."""
    if not records or decision_time is None:
        return None
    cutoff = _to_utc(decision_time) if decision_time.tzinfo is not None else decision_time
    eligible = [r for r in records if r.available_time <= cutoff]
    if not eligible:
        return None
    return max(eligible, key=lambda r: r.available_time)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


# Sentinel used by callers that need a stable "no data" hash.
EMPTY_FUNDING_SOURCE_SHA256 = hashlib.sha256(b"").hexdigest()
