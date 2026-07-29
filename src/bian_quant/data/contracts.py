from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DatasetLayer(StrEnum):
    RAW = "raw"
    CANONICAL = "canonical"
    RESEARCH = "research"


class QualitySeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    BLOCKING = "blocking"


class MarketRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: str
    event_time: datetime
    available_time: datetime
    ingested_at: datetime
    source: str

    @model_validator(mode="after")
    def validate_times(self) -> "MarketRecord":
        for value in (self.event_time, self.available_time, self.ingested_at):
            if value.tzinfo is None:
                raise ValueError("all timestamps must be timezone-aware")
        if self.available_time < self.event_time:
            raise ValueError("available_time must not precede event_time")
        if self.ingested_at < self.available_time:
            raise ValueError("ingested_at must not precede available_time")
        return self


class DatasetManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    snapshot_id: str
    layer: DatasetLayer
    name: str
    content_sha256: str
    row_count: int = Field(ge=0)
    min_event_time: datetime | None
    max_event_time: datetime | None
    parent_snapshot_ids: list[str]
    config_json: str

    @field_validator("content_sha256")
    @classmethod
    def validate_content_hash(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("content_sha256 must be 64 lowercase hexadecimal characters")
        return value

    @model_validator(mode="after")
    def validate_event_range(self) -> "DatasetManifest":
        for value in (self.min_event_time, self.max_event_time):
            if value is not None and value.tzinfo is None:
                raise ValueError("manifest timestamps must be timezone-aware")
        if (
            self.min_event_time is not None
            and self.max_event_time is not None
            and self.min_event_time > self.max_event_time
        ):
            raise ValueError("min_event_time must not follow max_event_time")
        if self.snapshot_id in self.parent_snapshot_ids:
            raise ValueError("a snapshot cannot be its own parent")
        return self


class RawArtifactManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_url: str
    fetched_at: datetime
    content_sha256: str
    upstream_sha256: str | None = None
    byte_count: int = Field(ge=0)

    @field_validator("fetched_at")
    @classmethod
    def validate_fetched_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("fetched_at must be timezone-aware")
        return value

    @field_validator("content_sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("SHA-256 values must be 64 lowercase hexadecimal characters")
        return value

    @field_validator("upstream_sha256")
    @classmethod
    def validate_optional_sha256(cls, value: str | None) -> str | None:
        if value is not None:
            cls.validate_sha256(value)
        return value


class QualityFinding(BaseModel):
    model_config = ConfigDict(frozen=True)

    code: str
    severity: QualitySeverity
    message: str
    rows: list[int] = Field(default_factory=list)
