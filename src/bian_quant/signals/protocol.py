"""Unified causal signal protocol.

Every signal in the platform conforms to ``SignalRecord``, guaranteeing
causal ordering: the signal was *available* before the *decision* to act
on it was made.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SignalRecord(BaseModel):
    """Immutable, causally-valid signal record.

    Parameters
    ----------
    asset:
        Ticker / instrument identifier (e.g. ``"BTCUSDT"``).
    available_time:
        Wall-clock time at which the signal **could first be observed**.
        Must be timezone-aware.
    decision_time:
        Wall-clock time at which a trading decision based on this signal
        is executed.  Must be timezone-aware and must not precede
        ``available_time``.
    direction:
        ``+1`` for long, ``-1`` for short, ``0`` for flat / exit.
    confidence:
        Score in the closed interval ``[0, 1]`` indicating how strongly
        the signal is held.
    payload:
        Free-form dictionary of additional strategy-specific data.
    """

    model_config = ConfigDict(frozen=True)

    asset: str
    available_time: datetime
    decision_time: datetime
    direction: int = Field(ge=-1, le=1)
    confidence: float = Field(ge=0.0, le=1.0)
    payload: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_causality(self) -> SignalRecord:
        if self.available_time.tzinfo is None:
            raise ValueError("available_time must be timezone-aware")
        if self.decision_time.tzinfo is None:
            raise ValueError("decision_time must be timezone-aware")
        if self.available_time > self.decision_time:
            raise ValueError("available_time must not precede decision_time")
        return self
