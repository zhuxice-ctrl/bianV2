"""Dual-horizon acquisition configuration, source-period grids, and disk policy."""

from __future__ import annotations

import calendar as _calendar
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DiskStatus(StrEnum):
    OK = "ok"
    WARNING = "warning"
    BLOCKED = "blocked"


class CoverageThresholds(BaseModel):
    model_config = ConfigDict(frozen=True)
    ohlcv: float = Field(gt=0.0, le=1.0)
    funding: float = Field(gt=0.0, le=1.0)
    metrics_oi: float = Field(gt=0.0, le=1.0)


class FactorProtocolConfig(BaseModel):
    model_config = ConfigDict(frozen=True)
    primary_interval: Literal["4h"]
    sensitivity_interval: Literal["1h"]
    development_months: Literal[18]
    holdout_months: Literal[6]
    development_start: datetime
    development_end_exclusive: datetime
    holdout_start: datetime
    holdout_end: datetime
    bh_alpha: float = Field(gt=0.0, lt=1.0)
    minimum_inference_samples: int = Field(ge=30)
    max_candidates: int = Field(ge=1, le=20)
    cost_bps: tuple[Literal[5], Literal[10]]

    @field_validator(
        "development_start",
        "development_end_exclusive",
        "holdout_start",
        "holdout_end",
    )
    @classmethod
    def validate_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("all timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_ordering(self) -> FactorProtocolConfig:
        if self.development_start >= self.development_end_exclusive:
            raise ValueError("development_start must precede development_end_exclusive")
        if self.holdout_start >= self.holdout_end:
            raise ValueError("holdout_start must precede holdout_end")
        if self.development_end_exclusive > self.holdout_start:
            raise ValueError(
                "development_end_exclusive must not follow holdout_start "
                "(alignment buffer lies between them)"
            )
        return self


class DualHorizonAcquisition(BaseModel):
    model_config = ConfigDict(frozen=True)

    assets: tuple[str, ...]
    macro_start: datetime
    micro_start: datetime
    as_of: datetime
    macro_intervals: tuple[Literal["1d", "4h"], ...]
    micro_intervals: tuple[Literal["1h", "4h"], ...]
    oi_delay_minutes: tuple[Literal[5], Literal[10], Literal[15]]
    parent_snapshot_ids: tuple[str, ...] = ()
    raw_root: Path
    canonical_root: Path
    research_root: Path
    artifact_root: Path
    catalog_path: Path
    experiment_registry_path: Path
    factor_registry_path: Path
    download_attempts: int = Field(ge=1, le=3)
    max_workers: int = Field(ge=1, le=8)
    disk_warn_gb: int = Field(ge=10)
    disk_block_gb: int = Field(ge=5)
    coverage: CoverageThresholds
    factor_protocol: FactorProtocolConfig

    @field_validator("macro_start", "micro_start", "as_of")
    @classmethod
    def validate_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("all timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_windows(self) -> DualHorizonAcquisition:
        if self.assets != ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
            raise ValueError("assets must be exactly BTCUSDT, ETHUSDT, BNBUSDT")
        if self.macro_start > self.micro_start:
            raise ValueError("macro_start must not follow micro_start")
        if self.micro_start >= self.as_of:
            raise ValueError("micro_start must precede as_of")
        if len(set(self.macro_intervals)) != len(self.macro_intervals):
            raise ValueError("macro_intervals must be unique")
        if len(set(self.micro_intervals)) != len(self.micro_intervals):
            raise ValueError("micro_intervals must be unique")
        if self.oi_delay_minutes != (5, 10, 15):
            raise ValueError("oi_delay_minutes must be exactly (5, 10, 15)")
        if self.disk_warn_gb <= self.disk_block_gb:
            raise ValueError("disk_warn_gb must exceed disk_block_gb")
        if len(set(self.parent_snapshot_ids)) != len(self.parent_snapshot_ids):
            raise ValueError("parent_snapshot_ids must be unique")
        return self

    @classmethod
    def from_yaml(cls, path: Path) -> DualHorizonAcquisition:
        with Path(path).open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
        return cls.model_validate(data)


@dataclass(frozen=True)
class DiskBudget:
    warn_bytes: int
    block_bytes: int


def calendar_months(start: datetime, end: datetime) -> tuple[tuple[int, int], ...]:
    """Return complete (year, month) tuples strictly before the month containing *end*.

    A month is *complete* only if its last day precedes *end*.  The month
    containing *end* is excluded because it may be partial.
    """
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    result: list[tuple[int, int]] = []
    year, month = start.year, start.month
    while (year, month) < (end.year, end.month):
        result.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return tuple(result)


def calendar_days(start: datetime, end: datetime) -> tuple[datetime, ...]:
    """Return UTC midnight timestamps for each complete day through the date of *end*."""
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    result: list[datetime] = []
    current = start.replace(hour=0, minute=0, second=0, microsecond=0)
    last = end.replace(hour=0, minute=0, second=0, microsecond=0)
    while current <= last:
        result.append(current)
        # Add one day
        days_in_month = _calendar.monthrange(current.year, current.month)[1]
        day = current.day + 1
        month = current.month
        year = current.year
        if day > days_in_month:
            day = 1
            month += 1
            if month > 12:
                month = 1
                year += 1
        current = datetime(year, month, day, tzinfo=UTC)
    return tuple(result)


def check_disk_budget(
    path: Path, budget: DiskBudget, *, free_bytes: int | None = None
) -> DiskStatus:
    """Check available disk space against warn/block thresholds."""
    if free_bytes is None:
        usage = shutil.disk_usage(path if path.exists() else path.parent or Path("."))
        free_bytes = usage.free
    if free_bytes < budget.block_bytes:
        return DiskStatus.BLOCKED
    if free_bytes < budget.warn_bytes:
        return DiskStatus.WARNING
    return DiskStatus.OK
