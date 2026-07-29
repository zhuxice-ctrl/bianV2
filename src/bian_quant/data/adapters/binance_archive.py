import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import urlopen

from bian_quant.data.adapters.raw import save_raw_artifact
from bian_quant.data.contracts import RawArtifactManifest

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"


def archive_url(asset: str, interval: str, year: int, month: int) -> str:
    filename = f"{asset}-{interval}-{year:04d}-{month:02d}.zip"
    return f"{BASE}/{asset}/{interval}/{filename}"


def verify_checksum(payload: bytes, checksum_payload: bytes) -> str:
    tokens = checksum_payload.decode("ascii").strip().split()
    if not tokens or len(tokens[0]) != 64:
        raise ValueError("BINANCE_CHECKSUM_INVALID: malformed checksum response")
    expected = tokens[0].lower()
    actual = hashlib.sha256(payload).hexdigest()
    if actual != expected:
        raise ValueError(f"BINANCE_CHECKSUM_MISMATCH: expected {expected}, got {actual}")
    return expected


def download_verified(path: Path, *, url: str) -> RawArtifactManifest:
    if path.exists() or path.with_suffix(f"{path.suffix}.manifest.json").exists():
        raise FileExistsError(f"raw artifact already exists: {path}")
    with urlopen(url, timeout=60) as response:
        payload = response.read()
    with urlopen(f"{url}.CHECKSUM", timeout=60) as response:
        checksum_payload = response.read()
    upstream_sha256 = verify_checksum(payload, checksum_payload)
    manifest = RawArtifactManifest(
        source_url=url,
        fetched_at=datetime.now(UTC),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        upstream_sha256=upstream_sha256,
        byte_count=len(payload),
    )
    return save_raw_artifact(path, payload, manifest)


def download_month(
    path: Path, *, asset: str, interval: str, year: int, month: int
) -> RawArtifactManifest:
    return download_verified(path, url=archive_url(asset, interval, year, month))
