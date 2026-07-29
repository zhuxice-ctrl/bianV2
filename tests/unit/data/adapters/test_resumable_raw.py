"""Tests for resumable raw artifact acquisition."""

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from bian_quant.data.adapters.binance_archive import daily_archive_url
from bian_quant.data.adapters.binance_derivatives import daily_funding_url
from bian_quant.data.adapters.raw import (
    AcquisitionObjectStatus,
    RawSourceIdentity,
    RawSourceManifest,
    reuse_verified_artifact,
    save_source_artifact,
)


def _source_manifest(
    path: Path, *, payload: bytes, source_period: str
) -> RawSourceManifest:
    import hashlib

    return RawSourceManifest(
        source_url=f"https://test/{path.name}",
        fetched_at=datetime(2026, 7, 1, tzinfo=UTC),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
        asset="BTCUSDT",
        dataset="ohlcv",
        interval="1h",
        source_period=source_period,
    )


def test_daily_ohlcv_url() -> None:
    assert daily_archive_url("BTCUSDT", "1h", date(2026, 7, 2)).endswith(
        "/daily/klines/BTCUSDT/1h/BTCUSDT-1h-2026-07-02.zip"
    )


def test_daily_funding_url() -> None:
    assert daily_funding_url("ETHUSDT", date(2026, 7, 2)).endswith(
        "/daily/fundingRate/ETHUSDT/ETHUSDT-fundingRate-2026-07-02.zip"
    )


def test_verified_existing_artifact_is_skipped(tmp_path: Path) -> None:
    target = tmp_path / "object.zip"
    manifest = _source_manifest(target, payload=b"frozen", source_period="2026-07")
    save_source_artifact(target, b"frozen", manifest)
    result = reuse_verified_artifact(target, expected=manifest)
    assert result.status == AcquisitionObjectStatus.SKIPPED
    assert result.manifest.content_sha256 == manifest.content_sha256


def test_partial_or_tampered_artifact_fails_closed(tmp_path: Path) -> None:
    target = tmp_path / "object.zip"
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="RAW_ARTIFACT_INCOMPLETE"):
        reuse_verified_artifact(target, expected=None)


def test_hash_mismatch_is_detected(tmp_path: Path) -> None:
    target = tmp_path / "object.zip"
    manifest = _source_manifest(target, payload=b"original", source_period="2026-07")
    save_source_artifact(target, b"original", manifest)
    # Tamper with the zip content but keep the manifest
    target.write_bytes(b"tampered")
    with pytest.raises(ValueError, match="RAW_HASH_MISMATCH"):
        reuse_verified_artifact(target, expected=None)


def test_identity_mismatch_is_detected(tmp_path: Path) -> None:
    target = tmp_path / "object.zip"
    manifest = _source_manifest(target, payload=b"frozen", source_period="2026-07")
    save_source_artifact(target, b"frozen", manifest)
    wrong_identity = RawSourceIdentity(
        asset="ETHUSDT",
        dataset="ohlcv",
        interval="1h",
        source_period="2026-07",
    )
    with pytest.raises(ValueError, match="RAW_IDENTITY_MISMATCH"):
        reuse_verified_artifact(target, expected=wrong_identity)
