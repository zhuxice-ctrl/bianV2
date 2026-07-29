"""Raw artifact storage with immutable manifests and resumable acquisition."""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from pydantic import BaseModel, ConfigDict

from bian_quant.data.contracts import RawArtifactManifest


class RawSourceIdentity(BaseModel):
    model_config = ConfigDict(frozen=True)
    asset: str
    dataset: Literal["ohlcv", "funding", "metrics_oi"]
    interval: str | None = None
    source_period: str


class RawSourceManifest(RawArtifactManifest):
    asset: str
    dataset: Literal["ohlcv", "funding", "metrics_oi"]
    interval: str | None = None
    source_period: str


class AcquisitionObjectStatus:
    DOWNLOADED = "downloaded"
    SKIPPED = "skipped"


class AcquisitionObjectResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    status: str
    path: Path
    manifest: RawSourceManifest


def save_raw_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def save_raw_artifact(
    path: Path, payload: bytes, manifest: RawArtifactManifest
) -> RawArtifactManifest:
    manifest_path = path.with_suffix(f"{path.suffix}.manifest.json")
    if path.exists() or manifest_path.exists():
        raise FileExistsError(f"raw artifact already exists: {path}")
    save_raw_bytes(path, payload)
    with manifest_path.open("xb") as stream:
        stream.write(manifest.model_dump_json(indent=2).encode("utf-8"))
    return manifest


def save_source_artifact(
    path: Path, payload: bytes, manifest: RawSourceManifest
) -> RawSourceManifest:
    """Save a raw artifact with an extended source manifest."""
    manifest_path = path.with_suffix(f"{path.suffix}.manifest.json")
    if path.exists() or manifest_path.exists():
        raise FileExistsError(f"raw artifact already exists: {path}")
    save_raw_bytes(path, payload)
    with manifest_path.open("xb") as stream:
        stream.write(manifest.model_dump_json(indent=2).encode("utf-8"))
    return manifest


def reuse_verified_artifact(
    path: Path, *, expected: RawSourceIdentity | None
) -> AcquisitionObjectResult:
    """Check an existing artifact for integrity and return SKIPPED if valid.

    Raises ValueError with stable error codes for any integrity problem.
    """
    manifest_path = path.with_suffix(f"{path.suffix}.manifest.json")
    if not path.exists() or not manifest_path.exists():
        raise ValueError("RAW_ARTIFACT_INCOMPLETE: missing zip or sidecar manifest")
    payload = path.read_bytes()
    content_sha = hashlib.sha256(payload).hexdigest()
    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest = RawSourceManifest.model_validate(manifest_data)
    if manifest.content_sha256 != content_sha:
        raise ValueError("RAW_HASH_MISMATCH: stored content does not match manifest hash")
    if expected is not None and (
        manifest.asset != expected.asset
        or manifest.dataset != expected.dataset
        or manifest.interval != expected.interval
        or manifest.source_period != expected.source_period
    ):
        raise ValueError("RAW_IDENTITY_MISMATCH: artifact identity does not match expected")
    return AcquisitionObjectResult(
        status=AcquisitionObjectStatus.SKIPPED,
        path=path,
        manifest=manifest,
    )


def fetch_raw_http(
    path: Path,
    *,
    url: str,
    attempts: int = 3,
    timeout: int = 60,
) -> RawArtifactManifest:
    if attempts < 1:
        raise ValueError("attempts must be positive")
    if path.exists() or path.with_suffix(f"{path.suffix}.manifest.json").exists():
        raise FileExistsError(f"raw artifact already exists: {path}")

    last_error: Exception | None = None
    for _ in range(attempts):
        try:
            with urlopen(url, timeout=timeout) as response:
                payload = response.read()
            break
        except HTTPError as error:
            if error.code != 429 and error.code < 500:
                raise
            last_error = error
        except (TimeoutError, URLError) as error:
            last_error = error
    else:
        raise RuntimeError(f"HTTP fetch failed after {attempts} attempts: {url}") from last_error

    manifest = RawArtifactManifest(
        source_url=url,
        fetched_at=datetime.now(UTC),
        content_sha256=hashlib.sha256(payload).hexdigest(),
        byte_count=len(payload),
    )
    return save_raw_artifact(path, payload, manifest)
