"""Proposal-only protocol for factor research artifacts."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FactorProposal(BaseModel):
    """Immutable proposal record for a factor under research."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    factor_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    factor_version: str = Field(min_length=1, pattern=r"^\d+\.\d+\.\d+$")
    research_family: str = Field(min_length=1)
    economic_hypothesis: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    direction: Literal["positive", "negative", "two_sided"]
    required_columns: tuple[str, ...]
    signal_time: str = Field(min_length=1)
    decision_time: str = Field(min_length=1)
    entry_price: str = Field(min_length=1)
    holding_rule: str = Field(min_length=1)
    exit_rule: str = Field(min_length=1)
    missing_policy: str = Field(min_length=1)
    parent_factors: tuple[str, ...]
    source_type: str = Field(min_length=1)
    proposal_status: Literal["proposal_only"]

    @field_validator(
        "factor_id",
        "factor_version",
        "research_family",
        "economic_hypothesis",
        "formula",
        "signal_time",
        "decision_time",
        "entry_price",
        "holding_rule",
        "exit_rule",
        "missing_policy",
        "source_type",
    )
    @classmethod
    def _require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("proposal text fields must be non-empty")
        return value

    @field_validator("required_columns")
    @classmethod
    def _require_required_columns(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("required_columns must contain at least one value")
        return value

    @field_validator("parent_factors")
    @classmethod
    def _require_parent_factor_names(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value):
            raise ValueError("parent_factors must contain non-empty values")
        return value

    @property
    def identity_sha256(self) -> str:
        """Stable canonical identity hash for the proposal."""

        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
