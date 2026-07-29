import hashlib
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from bian_quant.data.contracts import RawArtifactManifest


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
