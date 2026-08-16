"""Tests for the archive availability manifest and offline bootstrap."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

import bian_quant.data.archive_availability as archive_availability
from bian_quant.data.acquisition import SourceDataset, SourceGranularity
from bian_quant.data.archive_availability import (
    ArchiveAvailabilityEntry,
    ArchiveAvailabilityManifest,
    bootstrap_archive_availability,
)

ENTRY: dict[str, str] = {
    "asset": "APTUSDT",
    "dataset": "ohlcv",
    "granularity": "monthly",
    "first_available_period": "2022-10-01T00:00:00+00:00",
    "evidence_identity_key": "ohlcv|APTUSDT|1d|monthly|2022-10-01T00:00:00+00:00",
    "evidence_url": "https://example.com/APTUSDT-1d-2022-10.zip",
    "evidence_content_sha256": "a" * 64,
    "first_event_time": "2022-10-19T00:00:00+00:00",
}


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


def test_duplicate_availability_key_is_rejected() -> None:
    with pytest.raises(ValueError, match="duplicate availability entry"):
        ArchiveAvailabilityManifest.model_validate(
            {"rule_version": "popular-universe-availability-v1", "entries": [ENTRY, ENTRY]}
        )


def _load_written_manifest(tmp_path: Path, *, ordered: bool) -> ArchiveAvailabilityManifest:
    entry = dict(ENTRY)
    if not ordered:
        entry = dict(reversed(list(entry.items())))
    data = (
        {"entries": [entry], "rule_version": "popular-universe-availability-v1"}
        if not ordered
        else {"rule_version": "popular-universe-availability-v1", "entries": [entry]}
    )
    path = tmp_path / ("manifest_ordered.yaml" if ordered else "manifest_unordered.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return ArchiveAvailabilityManifest.from_yaml(path)


def test_hash_is_stable_when_yaml_key_order_changes(tmp_path: Path) -> None:
    assert _load_written_manifest(tmp_path, ordered=False).content_sha256 == (
        _load_written_manifest(tmp_path, ordered=True).content_sha256
    )


def test_first_available_period_is_normalized_to_utc() -> None:
    entry = ArchiveAvailabilityEntry.model_validate(
        {**ENTRY, "first_available_period": "2022-09-30T20:00:00-04:00"}
    )
    assert entry.first_available_period == datetime(2022, 10, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    "period",
    ("2022-10-01T00:01:00+00:00", "2022-10-02T00:00:00+00:00"),
)
def test_monthly_first_available_period_must_be_utc_month_start(period: str) -> None:
    with pytest.raises(ValueError, match="first_available_period"):
        ArchiveAvailabilityEntry.model_validate({**ENTRY, "first_available_period": period})


# ---------------------------------------------------------------------------
# Bootstrap test helpers
# ---------------------------------------------------------------------------


def _make_ohlcv_zip_bytes(
    asset: str, first_event: datetime, interval: str = "1d", rows: int = 3
) -> bytes:
    seconds = {"1h": 3600, "4h": 4 * 3600, "1d": 24 * 3600}[interval]
    lines: list[str] = []
    for i in range(rows):
        opened = first_event + timedelta(seconds=seconds * i)
        closed = opened + timedelta(seconds=seconds) - timedelta(milliseconds=1)
        lines.append(
            f"{int(opened.timestamp() * 1000)},50000,50100,49900,50050,100,"
            f"{int(closed.timestamp() * 1000)},5000000,100,50,2500000,0"
        )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{asset}-{interval}.csv", "\n".join(lines) + "\n")
    return output.getvalue()


def _make_funding_zip_bytes(asset: str, first_event: datetime, rows: int = 3) -> bytes:
    header = "calc_time,funding_interval_hours,last_funding_rate"
    lines = [header]
    event = first_event
    for _ in range(rows):
        lines.append(f"{int(event.timestamp() * 1000)},8,0.0001")
        event += timedelta(hours=8)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{asset}-funding.csv", "\n".join(lines) + "\n")
    return output.getvalue()


def _make_metrics_zip_bytes(asset: str, first_event: datetime, rows: int = 3) -> bytes:
    header = (
        "create_time,symbol,sum_open_interest,sum_open_interest_value,"
        "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
        "count_long_short_ratio,sum_taker_long_short_vol_ratio"
    )
    lines = [header]
    for i in range(rows):
        event = first_event + timedelta(minutes=5 * i)
        lines.append(f"{event:%Y-%m-%d %H:%M:%S},{asset},100000,5000000000,1.1,1.2,1.05,1.15")
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(f"{asset}-metrics.csv", "\n".join(lines) + "\n")
    return output.getvalue()


def _save_verified(
    raw_root: Path,
    relative_path: str,
    payload: bytes,
    *,
    asset: str,
    dataset: str,
    interval: str | None,
    source_period: str,
    url: str,
) -> None:
    """Save a verified raw artifact (ZIP + manifest sidecar) under raw_root."""
    zip_path = raw_root / relative_path
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(payload)
    content_sha = hashlib.sha256(payload).hexdigest()
    manifest = {
        "source_url": url,
        "fetched_at": datetime.now(UTC).isoformat(),
        "content_sha256": content_sha,
        "upstream_sha256": content_sha,
        "byte_count": len(payload),
        "asset": asset,
        "dataset": dataset,
        "interval": interval,
        "source_period": source_period,
    }
    manifest_path = zip_path.with_name(zip_path.name + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _seed_verified_monthly_ohlcv(tmp_path: Path, asset: str, period: str) -> Path:
    """Seed all required verified raw artifacts for *asset*.

    Monthly OHLCV starts at *period* (e.g. ``"2022-10"``) with the first
    event mid-month so that ``first_event_time > first_available_period``.
    Daily artifacts use the 19th of that month to align with the listing date.
    """
    raw_root = tmp_path / "raw"
    year, month = period.split("-")
    year_i, month_i = int(year), int(month)
    listing_day = datetime(year_i, month_i, 19, tzinfo=UTC)
    monthly_period = f"{year_i:04d}-{month_i:02d}"
    daily_period = listing_day.strftime("%Y-%m-%d")

    _save_verified(
        raw_root,
        f"ohlcv/{asset}/1d/{monthly_period}.zip",
        _make_ohlcv_zip_bytes(asset, listing_day, interval="1d"),
        asset=asset,
        dataset="ohlcv",
        interval="1d",
        source_period=monthly_period,
        url=f"https://data.binance.vision/data/futures/um/monthly/klines/{asset}/1d/{asset}-1d-{monthly_period}.zip",
    )
    _save_verified(
        raw_root,
        f"ohlcv/{asset}/1d/{daily_period}.zip",
        _make_ohlcv_zip_bytes(asset, listing_day, interval="1d", rows=1),
        asset=asset,
        dataset="ohlcv",
        interval="1d",
        source_period=daily_period,
        url=f"https://data.binance.vision/data/futures/um/daily/klines/{asset}/1d/{asset}-1d-{daily_period}.zip",
    )
    _save_verified(
        raw_root,
        f"funding/{asset}/native/{monthly_period}.zip",
        _make_funding_zip_bytes(asset, listing_day),
        asset=asset,
        dataset="funding",
        interval="native",
        source_period=monthly_period,
        url=f"https://data.binance.vision/data/futures/um/monthly/fundingRate/{asset}/{asset}-fundingRate-{monthly_period}.zip",
    )
    _save_verified(
        raw_root,
        f"metrics_oi/{asset}/native/{daily_period}.zip",
        _make_metrics_zip_bytes(asset, listing_day),
        asset=asset,
        dataset="metrics_oi",
        interval="native",
        source_period=daily_period,
        url=f"https://data.binance.vision/data/futures/um/daily/metrics/{asset}/{asset}-metrics-{daily_period}.zip",
    )
    return raw_root


def _seed_incomplete_raw(tmp_path: Path) -> Path:
    """Seed a raw directory with an unverifiable artifact (hash mismatch)."""
    raw_root = tmp_path / "raw"
    payload = _make_ohlcv_zip_bytes("APTUSDT", datetime(2022, 10, 19, tzinfo=UTC))
    zip_path = raw_root / "ohlcv/APTUSDT/1d/2022-10.zip"
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(payload)
    manifest = {
        "source_url": "https://example.com/APTUSDT-1d-2022-10.zip",
        "fetched_at": datetime.now(UTC).isoformat(),
        "content_sha256": "0" * 64,
        "upstream_sha256": "0" * 64,
        "byte_count": len(payload),
        "asset": "APTUSDT",
        "dataset": "ohlcv",
        "interval": "1d",
        "source_period": "2022-10",
    }
    manifest_path = zip_path.with_name(zip_path.name + ".manifest.json")
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return raw_root


# ---------------------------------------------------------------------------
# Bootstrap tests
# ---------------------------------------------------------------------------


def test_bootstrap_uses_monthly_source_period_not_first_event_time(tmp_path: Path) -> None:
    raw_root = _seed_verified_monthly_ohlcv(tmp_path, "APTUSDT", "2022-10")
    manifest = bootstrap_archive_availability(raw_root, assets=("APTUSDT",))
    entry = manifest.entry_for("APTUSDT", SourceDataset.OHLCV, SourceGranularity.MONTHLY)
    assert entry.first_available_period == datetime(2022, 10, 1, tzinfo=UTC)
    assert entry.first_event_time > entry.first_available_period


def test_bootstrap_rejects_unverified_evidence(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="ARCHIVE_AVAILABILITY_EVIDENCE_MISSING"):
        bootstrap_archive_availability(_seed_incomplete_raw(tmp_path), assets=("APTUSDT",))


def test_bootstrap_parses_only_the_earliest_verified_evidence_per_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_root = _seed_verified_monthly_ohlcv(tmp_path, "APTUSDT", "2022-10")
    _save_verified(
        raw_root,
        "ohlcv/APTUSDT/1d/2022-11.zip",
        _make_ohlcv_zip_bytes("APTUSDT", datetime(2022, 11, 1, tzinfo=UTC)),
        asset="APTUSDT",
        dataset="ohlcv",
        interval="1d",
        source_period="2022-11",
        url="https://example.com/APTUSDT-1d-2022-11.zip",
    )
    parsed_paths: list[Path] = []

    def record_parse(path: Path, **_: object) -> datetime:
        parsed_paths.append(path)
        return datetime(2022, 10, 19, tzinfo=UTC)

    monkeypatch.setattr(archive_availability, "_earliest_event_time", record_parse)
    bootstrap_archive_availability(raw_root, assets=("APTUSDT",))

    assert len(parsed_paths) == 4
    assert all("2022-11" not in str(path) for path in parsed_paths)
