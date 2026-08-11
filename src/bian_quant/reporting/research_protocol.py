"""Research terminal response protocol — backend contract layer.

Mirrors ``docs/contracts/research-terminal-ui-contract.md`` v1 exactly:
``ResearchTerminalResponse`` and all nested types are translated 1:1 from the
contract's TypeScript definitions into Pydantic v2 models.  Field names, types,
enum values and nullability match the contract verbatim, so any
``ResearchTerminalResponse`` serialized from these models is guaranteed to
conform to the wire contract consumed by the ``/research`` terminal.

This module is the single source of truth for the ``GET /api/research/latest``
response shape; the aggregator (``research_terminal.py``) only assembles
instances of these models.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class TerminalState(StrEnum):
    EMPTY = "empty"
    BLOCKED = "blocked"
    PASSED = "passed"


class CoverageStatus(StrEnum):
    PASSED = "passed"
    EXCLUDED = "excluded"
    BLOCKED = "blocked"
    UNAVAILABLE = "unavailable"


class DatasetName(StrEnum):
    OHLCV = "ohlcv"
    FUNDING = "funding"
    METRICS_OI = "metrics_oi"


class Granularity(StrEnum):
    MONTHLY = "monthly"
    DAILY = "daily"


class SnapshotName(StrEnum):
    MACRO_1D = "macro-1d"
    MACRO_4H = "macro-4h"
    MICRO_1H = "micro-1h"
    MICRO_4H = "micro-4h"


class SnapshotStatus(StrEnum):
    PUBLISHED = "published"


class ExclusionReason(StrEnum):
    PRE_LISTING_EXCLUDED = "PRE_LISTING_EXCLUDED"


class PartialExclusionReason(StrEnum):
    TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE = "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE"


class RunInfo(BaseModel):
    """Contract ``run`` block."""

    model_config = ConfigDict(frozen=True)

    id: str | None
    status: TerminalState
    as_of: str | None  # ISO-8601 UTC
    planned_objects: int
    availability_manifest_sha256: str | None
    pre_listing_exclusion_count: int
    artifact_path: str | None


class Kpis(BaseModel):
    """Contract ``kpis`` block."""

    model_config = ConfigDict(frozen=True)

    popular_member_count: int | None
    published_snapshot_count: int
    blocked_period_count: int
    temporary_blocker_count: int


class PopularMember(BaseModel):
    """Contract ``PopularMember``."""

    model_config = ConfigDict(frozen=True)

    rank: int
    asset: str
    composite_score: int | None
    quote_volume_rank: int | None
    open_interest_rank: int | None


class DailyCount(BaseModel):
    """Contract ``popular_universe.daily_counts`` entry."""

    model_config = ConfigDict(frozen=True)

    date: str  # YYYY-MM-DD
    member_count: int


class PopularUniverse(BaseModel):
    """Contract ``popular_universe`` block."""

    model_config = ConfigDict(frozen=True)

    latest_date: str | None  # YYYY-MM-DD
    latest_members: list[PopularMember]
    daily_counts: list[DailyCount]


class CoverageRow(BaseModel):
    """Contract ``CoverageRow``."""

    model_config = ConfigDict(frozen=True)

    asset: str
    ohlcv: CoverageStatus
    funding: CoverageStatus
    metrics_oi: CoverageStatus


class Blocker(BaseModel):
    """Contract ``Blocker``."""

    model_config = ConfigDict(frozen=True)

    identity_key: str
    asset: str | None
    dataset: DatasetName | None
    period: str | None
    error_code: str
    message: str
    temporary: bool


class Exclusion(BaseModel):
    """Contract ``Exclusion``."""

    model_config = ConfigDict(frozen=True)

    identity_key: str
    asset: str
    dataset: DatasetName
    granularity: Granularity
    reason: ExclusionReason


class PartialAvailabilityExclusion(BaseModel):
    """Contract ``PartialAvailabilityExclusion``."""

    model_config = ConfigDict(frozen=True)

    identity_key: str
    asset: str
    dataset: DatasetName
    granularity: Granularity
    period: str
    reason: PartialExclusionReason
    error_code: str
    temporary: bool


class PartialAvailabilityImpact(BaseModel):
    """Contract ``PartialAvailabilityImpact``."""

    model_config = ConfigDict(frozen=True)

    affected_assets: list[str]
    affected_periods: int
    affected_selection_days: int


class Snapshot(BaseModel):
    """Contract ``Snapshot``."""

    model_config = ConfigDict(frozen=True)

    name: SnapshotName
    id: str
    min_event_time: str
    max_event_time: str
    status: SnapshotStatus = SnapshotStatus.PUBLISHED


class ResearchTerminalResponse(BaseModel):
    """Contract ``ResearchTerminalResponse`` — wire shape of ``GET /api/research/latest``."""

    model_config = ConfigDict(frozen=True)

    schema_version: str = Field(default="research-terminal-v1")
    state: TerminalState
    generated_at: str  # ISO-8601 UTC
    run: RunInfo
    kpis: Kpis
    popular_universe: PopularUniverse
    coverage: list[CoverageRow]
    blockers: list[Blocker]
    pre_listing_exclusions: list[Exclusion]
    partial_availability_exclusions: list[PartialAvailabilityExclusion]
    partial_availability_impact: PartialAvailabilityImpact
    snapshots: list[Snapshot]
