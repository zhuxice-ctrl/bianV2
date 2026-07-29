from pathlib import Path
from urllib.error import HTTPError

import pytest

from bian_quant.data.adapters import raw


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.payload


def test_raw_http_retries_429_and_saves_manifest(monkeypatch, tmp_path: Path) -> None:
    calls = 0

    def flaky_urlopen(url: str, *, timeout: int) -> _Response:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise HTTPError(url, 429, "rate limited", hdrs=None, fp=None)
        return _Response(b'{"data": [1]}')

    monkeypatch.setattr(raw, "urlopen", flaky_urlopen)
    target = tmp_path / "response.json"

    manifest = raw.fetch_raw_http(target, url="https://example.test/data")

    assert calls == 3
    assert target.read_bytes() == b'{"data": [1]}'
    assert target.with_suffix(".json.manifest.json").exists()
    assert manifest.upstream_sha256 is None


def test_raw_http_failure_does_not_publish_empty_artifact(monkeypatch, tmp_path: Path) -> None:
    def timed_out(url: str, *, timeout: int) -> _Response:
        raise TimeoutError(url)

    monkeypatch.setattr(raw, "urlopen", timed_out)
    target = tmp_path / "response.json"

    with pytest.raises(RuntimeError, match="failed after 3 attempts"):
        raw.fetch_raw_http(target, url="https://example.test/data")

    assert not target.exists()
    assert not target.with_suffix(".json.manifest.json").exists()
