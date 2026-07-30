"""Binance USD-M futures archive URL construction and verified downloads."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from bian_quant.data.adapters.raw import (
    AcquisitionObjectResult,
    AcquisitionObjectStatus,
    RawSourceIdentity,
    RawSourceManifest,
    reuse_verified_artifact,
    save_source_artifact,
)

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"
DAILY_BASE = "https://data.binance.vision/data/futures/um/daily/klines"


def archive_url(asset: str, interval: str, year: int, month: int) -> str:
    filename = f"{asset}-{interval}-{year:04d}-{month:02d}.zip"
    return f"{BASE}/{asset}/{interval}/{filename}"


def daily_archive_url(asset: str, interval: str, day: date) -> str:
    stamp = day.isoformat()
    filename = f"{asset}-{interval}-{stamp}.zip"
    return f"{DAILY_BASE}/{asset}/{interval}/{filename}"


def verify_checksum(payload: bytes, checksum_payload: bytes) -> str:
    tokens = checksum_payload.decode("ascii").strip().split()
    if not tokens or len(tokens[0]) != 64:
        raise ValueError("BINANCE_CHECKSUM_INVALID: malformed checksum response")
    expected = tokens[0].lower()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(f"BINANCE_CHECKSUM_MISMATCH: expected {expected}, got {actual}")
    return expected


def _fetch_bytes(url: str, *, timeout: int = 60) -> bytes:
    with urlopen(url, timeout=timeout) as response:
        return cast(bytes, response.read())


def download_verified(
    path: Path,
    *,
    url: str,
    identity: RawSourceIdentity | None = None,
    attempts: int = 3,
    byte_reader: Callable[[str], bytes] | None = None,
) -> AcquisitionObjectResult:
    """Download a Binance archive with checksum verification and resumability.

    If the artifact already exists and is verified, returns SKIPPED.
    Retries 429/5xx/timeout/URL errors at most *attempts* times.
    Never leaves a partial target or sidecar after a failed attempt.
    """
    manifest_path = path.with_suffix(f"{path.suffix}.manifest.json")
    if path.exists() or manifest_path.exists():
        return reuse_verified_artifact(path, expected=identity)

    reader = byte_reader or _fetch_bytes
    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            payload = reader(url)
            checksum_payload = reader(f"{url}.CHECKSUM")
            break
        except HTTPError as error:
            if error.code != 429 and error.code < 500:
                raise
            last_error = error
        except (TimeoutError, URLError) as error:
            last_error = error
    else:
        raise RuntimeError(
            f"RAW_DOWNLOAD_FAILED: fetch failed after {attempts} attempts: {url}"
        ) from last_error

    upstream_sha256 = verify_checksum(payload, checksum_payload)
    manifest = RawSourceManifest(
        source_url=url,
        fetched_at=datetime.now(UTC),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        upstream_sha256=upstream_sha256,
        byte_count=len(payload),
        asset=identity.asset if identity else "",
        dataset=identity.dataset if identity else "ohlcv",
        interval=identity.interval if identity else None,
        source_period=identity.source_period if identity else "",
    )
    save_source_artifact(path, payload, manifest)
    return AcquisitionObjectResult(
        status=AcquisitionObjectStatus.DOWNLOADED,
        path=path,
        manifest=manifest,
    )


def download_month(
    path: Path, *, asset: str, interval: str, year: int, month: int
) -> AcquisitionObjectResult:
    identity = RawSourceIdentity(
        asset=asset, dataset="ohlcv", interval=interval, source_period=f"{year:04d}-{month:02d}"
    )
    return download_verified(path, url=archive_url(asset, interval, year, month), identity=identity)
