"""Factor specifications and lifecycle states."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FactorState(StrEnum):
    RESEARCHING = "researching"
    OBSERVED = "observed"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    RETIRED = "retired"


class FactorSpec(BaseModel):
    """Immutable specification of a factor.

    All fields are frozen after creation.  A new version requires a new
    registration with an incremented ``version`` string.
    """

    model_config = ConfigDict(frozen=True)

    factor_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    version: str = Field(min_length=1, pattern=r"^\d+\.\d+\.\d+$")
    formula: str = Field(min_length=1)
    direction: Literal["positive", "negative", "two_sided"]
    hypothesis: str = Field(min_length=20)
    required_columns: list[str]
    horizon: str
    missing_policy: Literal["preserve", "zero_if_structural"]
    winsor_limits: tuple[float, float]
    valid_regimes: list[str]
    failure_conditions: list[str]
    parent_factors: list[str]
    research_family: str | None = None
    universe_id: str | None = None

    @field_validator("required_columns", "valid_regimes", "failure_conditions")
    @classmethod
    def require_non_empty_lists(cls, value: list[str]) -> list[str]:
        if not value or any(not item.strip() for item in value):
            raise ValueError("factor list fields must contain non-empty values")
        return value

    @model_validator(mode="after")
    def validate_winsor_limits(self) -> FactorSpec:
        lower, upper = self.winsor_limits
        if not 0.0 <= lower < upper <= 1.0:
            raise ValueError("winsor_limits must satisfy 0 <= lower < upper <= 1")
        return self
