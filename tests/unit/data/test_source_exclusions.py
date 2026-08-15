"""Tests for immutable permanent Canonical-input exclusions."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from bian_quant.data.source_exclusions import load_permanent_source_exclusions


def test_load_permanent_source_exclusions_is_sorted_and_immutable(tmp_path: Path) -> None:
    path = tmp_path / "exclusions.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "canonical-input-exclusions-v1",
                "exclusions": [
                    {
                        "identity_key": "b",
                        "status": "permanently_unavailable",
                        "reason_code": "SOURCE_ARCHIVE_404",
                        "source_url": "https://example.invalid/b",
                        "evidence_ref": "test-b",
                        "observed_on": "2026-08-15",
                    },
                    {
                        "identity_key": "a",
                        "status": "permanently_unavailable",
                        "reason_code": "SOURCE_ARCHIVE_404",
                        "source_url": "https://example.invalid/a",
                        "evidence_ref": "test-a",
                        "observed_on": "2026-08-15",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    result = load_permanent_source_exclusions(path)

    assert tuple(item.identity_key for item in result) == ("a", "b")
    assert result[0].observed_on == date(2026, 8, 15)
    with pytest.raises(ValueError):
        result[0].identity_key = "changed"  # type: ignore[misc]


def test_duplicate_permanent_exclusions_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "exclusions.json"
    item = {
        "identity_key": "a",
        "status": "permanently_unavailable",
        "reason_code": "SOURCE_ARCHIVE_404",
        "source_url": "https://example.invalid/a",
        "evidence_ref": "test-a",
        "observed_on": "2026-08-15",
    }
    path.write_text(
        json.dumps({"schema_version": "canonical-input-exclusions-v1", "exclusions": [item, item]}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="CANONICAL_INPUT_EXCLUSIONS_DUPLICATE"):
        load_permanent_source_exclusions(path)
