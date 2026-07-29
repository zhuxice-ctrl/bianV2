from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SignalRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: str = Field(min_length=1)
    decision_time: datetime
    available_time: datetime
    horizon: str = Field(min_length=1)
    value: float = Field(ge=-1.0, le=1.0)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    factor_id: str = Field(min_length=1)
    factor_version: str = Field(min_length=1)

    @property
    def direction(self) -> int:
        return (self.value > 0) - (self.value < 0)

    @model_validator(mode="after")
    def validate_causality(self) -> "SignalRecord":
        for timestamp in (self.available_time, self.decision_time):
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                raise ValueError("signal timestamps must be timezone-aware")
        if self.available_time > self.decision_time:
            raise ValueError("signal was not available at decision_time")
        return self
