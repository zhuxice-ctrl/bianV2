"""Factor specifications and lifecycle states."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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

    factor_id: str
    version: str
    formula: str
    direction: Literal["positive", "negative", "two_sided"]
    hypothesis: str = Field(min_length=20)
    required_columns: list[str]
    horizon: str
    missing_policy: Literal["preserve", "zero_if_structural"]
    winsor_limits: tuple[float, float]
    valid_regimes: list[str]
    failure_conditions: list[str]
    parent_factors: list[str]
