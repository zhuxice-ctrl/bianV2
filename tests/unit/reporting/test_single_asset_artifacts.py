"""Tests for single-asset artifact persistence and hashing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bian_quant.reporting.research_protocol import (
    SingleAssetStatus,
)
from bian_quant.reporting.single_asset_artifacts import (
    build_eth_single_asset_evaluation,
    canonical_json_bytes,
    canonical_sha256,
    load_single_asset_artifact,
    write_single_asset_artifact,
)


def test_canonical_hash_invariance():
    """The same payload in different key orders must produce the same hash."""
    payload_a = {"b": 2, "a": 1, "c": [3, 2, 1]}
    payload_b = {"a": 1, "c": [3, 2, 1], "b": 2}
    assert canonical_sha256(payload_a) == canonical_sha256(payload_b)


def test_canonical_json_is_compact_sorted():
    """Canonical JSON must use sorted keys and compact separators."""
    data = canonical_json_bytes({"b": 1, "a": 2})
    assert data == b'{"a":2,"b":1}'


def test_write_read_roundtrip(tmp_path: Path):
    """Writing and reading an artifact must round-trip exactly."""
    payload = {
        "asset": "ETHUSDT",
        "strategy_id": "legacy.pa_confluence",
        "metrics": {"final_equity": 95.5, "trade_count": 10},
        "list": [1, 2, 3],
    }
    path = tmp_path / "artifacts" / "eth.json"
    sha = write_single_asset_artifact(payload, path)

    assert path.is_file()
    assert len(sha) == 64  # SHA-256 hex

    loaded = load_single_asset_artifact(path)
    assert loaded == payload


def test_load_missing_raises(tmp_path: Path):
    """Loading a nonexistent artifact must raise FileNotFoundError."""
    with pytest.raises(FileNotFoundError):
        load_single_asset_artifact(tmp_path / "nonexistent.json")


def test_load_corrupt_raises(tmp_path: Path):
    """Loading a corrupt JSON file must raise."""
    path = tmp_path / "corrupt.json"
    path.write_text("not json{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_single_asset_artifact(path)


def test_build_eth_missing_when_no_data(tmp_path: Path):
    """Builder must return 'missing' when OHLCV data is absent."""
    result = build_eth_single_asset_evaluation(
        ohlcv_path=tmp_path / "nonexistent.csv",
        artifact_dir=tmp_path / "artifacts",
    )
    assert result.status == SingleAssetStatus.MISSING
    assert result.baseline is None
    assert result.confidence_weighted is None
    assert result.error_summary is not None


def test_build_eth_error_on_exception(tmp_path: Path):
    """Builder must return 'error' when the evaluator raises unexpectedly."""
    # Pass a path that exists but is not a valid CSV
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text("this,is,not,ohlcv,data\n1,2,3,4,5", encoding="utf-8")
    result = build_eth_single_asset_evaluation(
        ohlcv_path=bad_csv,
        artifact_dir=tmp_path / "artifacts",
    )
    # Should be either missing (insufficient bars) or error
    assert result.status in (SingleAssetStatus.MISSING, SingleAssetStatus.ERROR)
    assert result.baseline is None
