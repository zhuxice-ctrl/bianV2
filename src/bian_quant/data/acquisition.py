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

from bian_quant.data.adapters.raw import RawSourceIdentity


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


class PopularUniversePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_version: Literal["popular-usdm-v1"]
    minimum_listing_days: Literal[180]
    trailing_days: Literal[30]
    max_selected: Literal[12]
    min_selected: Literal[8]
    seed_assets: tuple[str, ...]

    @model_validator(mode="after")
    def validate_seed_assets(self) -> "PopularUniversePolicy":
        if len(self.seed_assets) != 16 or len(set(self.seed_assets)) != 16:
            raise ValueError("popular universe requires exactly 16 unique seed assets")
        if tuple(sorted(self.seed_assets)) != self.seed_assets:
            raise ValueError("popular seed assets must be lexicographically sorted")
        return self


class DualHorizonAcquisition(BaseModel):
    model_config = ConfigDict(frozen=True)

    assets: tuple[str, ...]
    universe_policy: PopularUniversePolicy | None = None
    macro_start: datetime
    micro_start: datetime
    as_of: datetime
    macro_intervals: tuple[Literal["1d", "4h"], ...]
    micro_intervals: tuple[Literal["1h", "4h"], ...]
    oi_delay_minutes: tuple[Literal[5], Literal[10], Literal[15]]
    funding_tail_strategy: Literal["monthly_archive_after_period_close"]
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
        if self.universe_policy is None:
            if self.assets != ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
                raise ValueError("assets must be exactly BTCUSDT, ETHUSDT, BNBUSDT")
        elif self.assets != self.universe_policy.seed_assets:
            raise ValueError("assets must match universe_policy.seed_assets")
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


def funding_months_through_cutoff(start: datetime, as_of: datetime) -> tuple[tuple[int, int], ...]:
    """Return (year, month) tuples from *start* through the month containing *as_of*.

    Unlike :func:`calendar_months`, the cutoff month is included so the official
    monthly archive can be acquired after the source month closes.
    """
    months = list(calendar_months(start, as_of))
    cutoff_month = (as_of.year, as_of.month)
    if cutoff_month not in months:
        months.append(cutoff_month)
    return tuple(months)


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


# ---------------------------------------------------------------------------
# Source-object plan
# ---------------------------------------------------------------------------


class SourceDataset(StrEnum):
    OHLCV = "ohlcv"
    FUNDING = "funding"
    METRICS_OI = "metrics_oi"


class SourceGranularity(StrEnum):
    MONTHLY = "monthly"
    DAILY = "daily"


@dataclass(frozen=True, order=True)
class SourceObject:
    dataset: SourceDataset
    asset: str
    interval: str
    granularity: SourceGranularity
    period_start: datetime
    url: str
    relative_path: Path

    @property
    def identity_key(self) -> str:
        return "|".join(
            (
                self.dataset.value,
                self.asset,
                self.interval,
                self.granularity.value,
                self.period_start.isoformat(),
            )
        )

    @property
    def raw_identity(self) -> RawSourceIdentity:
        return RawSourceIdentity(
            asset=self.asset,
            dataset=self.dataset.value,
            interval=self.interval or None,
            source_period=self.period_start.strftime(
                "%Y-%m" if self.granularity == SourceGranularity.MONTHLY else "%Y-%m-%d"
            ),
        )


def _make_monthly_ohlcv(
    asset: str, interval: str, year: int, month: int, raw_root: Path
) -> SourceObject:
    from bian_quant.data.adapters.binance_archive import archive_url

    period_start = datetime(year, month, 1, tzinfo=UTC)
    stamp = f"{year:04d}-{month:02d}"
    return SourceObject(
        dataset=SourceDataset.OHLCV,
        asset=asset,
        interval=interval,
        granularity=SourceGranularity.MONTHLY,
        period_start=period_start,
        url=archive_url(asset, interval, year, month),
        relative_path=Path("ohlcv") / asset / interval / f"{stamp}.zip",
    )


def _make_daily_ohlcv(asset: str, interval: str, day: datetime, raw_root: Path) -> SourceObject:
    from bian_quant.data.adapters.binance_archive import daily_archive_url

    stamp = day.strftime("%Y-%m-%d")
    return SourceObject(
        dataset=SourceDataset.OHLCV,
        asset=asset,
        interval=interval,
        granularity=SourceGranularity.DAILY,
        period_start=day,
        url=daily_archive_url(asset, interval, day.date()),
        relative_path=Path("ohlcv") / asset / interval / f"{stamp}.zip",
    )


def _make_monthly_funding(asset: str, year: int, month: int, raw_root: Path) -> SourceObject:
    from bian_quant.data.adapters.binance_derivatives import funding_url

    period_start = datetime(year, month, 1, tzinfo=UTC)
    stamp = f"{year:04d}-{month:02d}"
    return SourceObject(
        dataset=SourceDataset.FUNDING,
        asset=asset,
        interval="native",
        granularity=SourceGranularity.MONTHLY,
        period_start=period_start,
        url=funding_url(asset, year, month),
        relative_path=Path("funding") / asset / "native" / f"{stamp}.zip",
    )


def _make_daily_funding(asset: str, day: datetime, raw_root: Path) -> SourceObject:
    from bian_quant.data.adapters.binance_derivatives import daily_funding_url

    stamp = day.strftime("%Y-%m-%d")
    return SourceObject(
        dataset=SourceDataset.FUNDING,
        asset=asset,
        interval="native",
        granularity=SourceGranularity.DAILY,
        period_start=day,
        url=daily_funding_url(asset, day),
        relative_path=Path("funding") / asset / "native" / f"{stamp}.zip",
    )


def _make_daily_metrics(asset: str, day: datetime, raw_root: Path) -> SourceObject:
    from bian_quant.data.adapters.binance_derivatives import metrics_url

    stamp = day.strftime("%Y-%m-%d")
    return SourceObject(
        dataset=SourceDataset.METRICS_OI,
        asset=asset,
        interval="native",
        granularity=SourceGranularity.DAILY,
        period_start=day,
        url=metrics_url(asset, day),
        relative_path=Path("metrics_oi") / asset / "native" / f"{stamp}.zip",
    )


def build_source_plan(config: DualHorizonAcquisition) -> tuple[SourceObject, ...]:
    """Build the exact, ordered set of source objects to acquire.

    Rules:
    - Monthly OHLCV for macro intervals from macro_start; monthly OHLCV for
      micro-only intervals from micro_start.  4h is shared and only requested
      from macro_start.
    - Daily OHLCV for all intervals in the partial month of as_of.
    - Monthly Funding from macro_start; daily Funding for the partial month.
    - Daily Metrics/OI only from micro_start (never five years).
    - No object later than as_of.
    - Sorted by (dataset, asset, interval, period_start).
    """
    raw_root = config.raw_root
    objects: list[SourceObject] = []

    macro_set = set(config.macro_intervals)
    micro_only = set(config.micro_intervals) - macro_set
    all_intervals = sorted(macro_set | set(config.micro_intervals))

    # Monthly OHLCV from macro_start
    for macro_interval in sorted(macro_set):
        for asset in config.assets:
            for year, month in calendar_months(config.macro_start, config.as_of):
                objects.append(_make_monthly_ohlcv(asset, macro_interval, year, month, raw_root))

    # Monthly OHLCV from micro_start (micro-only intervals)
    for micro_interval in sorted(micro_only):
        for asset in config.assets:
            for year, month in calendar_months(config.micro_start, config.as_of):
                objects.append(_make_monthly_ohlcv(asset, micro_interval, year, month, raw_root))

    # Daily OHLCV for partial month (month of as_of)
    partial_start = config.as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    for daily_interval in all_intervals:
        for asset in config.assets:
            for day in calendar_days(partial_start, config.as_of):
                objects.append(_make_daily_ohlcv(asset, daily_interval, day, raw_root))

    # Monthly Funding from macro_start through the cutoff month (inclusive)
    for asset in config.assets:
        for year, month in funding_months_through_cutoff(config.macro_start, config.as_of):
            objects.append(_make_monthly_funding(asset, year, month, raw_root))

    # Daily Metrics/OI from micro_start
    for asset in config.assets:
        for day in calendar_days(config.micro_start, config.as_of):
            objects.append(_make_daily_metrics(asset, day, raw_root))

    objects.sort(key=lambda o: (o.dataset.value, o.asset, o.interval, o.period_start))
    return tuple(objects)


def source_plan_payload(config: DualHorizonAcquisition) -> dict[str, object]:
    """Return a JSON-safe dry-run summary of the source plan.

    Does not access the network or filesystem beyond reading the config.
    """
    plan = build_source_plan(config)

    counts_by_dataset: dict[str, int] = {}
    counts_by_granularity: dict[str, int] = {}
    for obj in plan:
        counts_by_dataset[obj.dataset.value] = counts_by_dataset.get(obj.dataset.value, 0) + 1
        counts_by_granularity[obj.granularity.value] = (
            counts_by_granularity.get(obj.granularity.value, 0) + 1
        )

    first_period = plan[0].period_start.isoformat() if plan else None
    last_period = plan[-1].period_start.isoformat() if plan else None

    return {
        "config_identity": {
            "assets": list(config.assets),
            "macro_start": config.macro_start.isoformat(),
            "micro_start": config.micro_start.isoformat(),
            "as_of": config.as_of.isoformat(),
            "macro_intervals": list(config.macro_intervals),
            "micro_intervals": list(config.micro_intervals),
            "funding_tail_strategy": config.funding_tail_strategy,
        },
        "counts": {
            "total": len(plan),
            "by_dataset": counts_by_dataset,
            "by_granularity": counts_by_granularity,
        },
        "first_period": first_period,
        "last_period": last_period,
        "disk_thresholds": {
            "warn_gb": config.disk_warn_gb,
            "block_gb": config.disk_block_gb,
        },
        "objects": [
            {
                "identity_key": obj.identity_key,
                "url": obj.url,
                "relative_path": str(obj.relative_path),
            }
            for obj in plan
        ],
    }
