"""Audited source exclusions for Canonical input selection."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PermanentSourceExclusion(BaseModel):
    """Immutable evidence that one planned source is permanently unavailable."""

    model_config = ConfigDict(frozen=True)

    identity_key: str
    status: Literal["permanently_unavailable"]
    reason_code: Literal["SOURCE_ARCHIVE_404"]
    source_url: str
    evidence_ref: str
    observed_on: date

    @field_validator("observed_on")
    @classmethod
    def validate_observed_on(cls, value: date) -> date:
        return value


class PermanentSourceExclusionFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    schema_version: Literal["canonical-input-exclusions-v1"]
    exclusions: tuple[PermanentSourceExclusion, ...] = Field(default_factory=tuple)


def load_permanent_source_exclusions(path: Path | None) -> tuple[PermanentSourceExclusion, ...]:
    """Load and validate an immutable exclusion file, or return no exclusions."""
    if path is None:
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        parsed = PermanentSourceExclusionFile.model_validate(payload)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"CANONICAL_INPUT_EXCLUSIONS_INVALID:{path}") from error
    ordered = tuple(sorted(parsed.exclusions, key=lambda item: item.identity_key))
    if len({item.identity_key for item in ordered}) != len(ordered):
        raise ValueError(f"CANONICAL_INPUT_EXCLUSIONS_DUPLICATE:{path}")
    return ordered
