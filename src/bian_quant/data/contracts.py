from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, model_validator


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
    snapshot_id: str
    layer: DatasetLayer
    name: str
    content_sha256: str
    row_count: int
    min_event_time: datetime | None
    max_event_time: datetime | None
    parent_snapshot_ids: list[str]
    config_json: str


class QualityFinding(BaseModel):
    code: str
    severity: QualitySeverity
    message: str
    rows: list[int] = []
