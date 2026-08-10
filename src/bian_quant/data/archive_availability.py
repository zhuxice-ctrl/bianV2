"""Immutable archive availability manifest and offline bootstrap from verified raw artifacts."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, TypedDict

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from bian_quant.data.acquisition import SourceDataset, SourceGranularity
from bian_quant.data.adapters.raw import (
    RawSourceIdentity,
    RawSourceManifest,
    reuse_verified_artifact,
)


class _VerifiedCandidate(TypedDict):
    asset: str
    dataset: SourceDataset
    granularity: SourceGranularity
    first_available_period: datetime
    evidence_identity_key: str
    evidence_url: str
    evidence_content_sha256: str
    evidence_path: Path
    interval: str | None


class ArchiveAvailabilityEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: str
    dataset: SourceDataset
    granularity: SourceGranularity
    first_available_period: datetime
    evidence_identity_key: str
    evidence_url: str
    evidence_content_sha256: str
    first_event_time: datetime

    @field_validator("first_available_period")
    @classmethod
    def normalize_first_available_period(cls, value: datetime) -> datetime:
        """Store archive boundaries as UTC timestamps, never local time."""
        if value.tzinfo is None:
            raise ValueError("first_available_period must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def validate_timezone_aware(self) -> ArchiveAvailabilityEntry:
        for field_name in ("first_available_period", "first_event_time"):
            value = getattr(self, field_name)
            if value.tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        period = self.first_available_period
        if any((period.hour, period.minute, period.second, period.microsecond)):
            raise ValueError("first_available_period must be UTC midnight")
        if self.granularity == SourceGranularity.MONTHLY and period.day != 1:
            raise ValueError(
                "monthly first_available_period must be the first day of the month"
            )
        return self


class ArchiveAvailabilityManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_version: Literal["popular-universe-availability-v1"]
    entries: tuple[ArchiveAvailabilityEntry, ...]

    @model_validator(mode="after")
    def validate_no_duplicates(self) -> ArchiveAvailabilityManifest:
        seen: set[tuple[str, str, str]] = set()
        for entry in self.entries:
            key = (entry.asset, entry.dataset.value, entry.granularity.value)
            if key in seen:
                raise ValueError("duplicate availability entry")
            seen.add(key)
        return self

    @property
    def content_sha256(self) -> str:
        encoded = json.dumps(
            self.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def entry_for(
        self, asset: str, dataset: SourceDataset, granularity: SourceGranularity
    ) -> ArchiveAvailabilityEntry:
        matches = [
            entry
            for entry in self.entries
            if (entry.asset, entry.dataset, entry.granularity)
            == (asset, dataset, granularity)
        ]
        if len(matches) != 1:
            raise ValueError("ARCHIVE_AVAILABILITY_MISSING")
        return matches[0]

    def require_expected_keys(self, *, assets: tuple[str, ...]) -> None:
        """Fail closed unless this manifest covers every configured popular asset.

        A missing boundary must never make a candidate silently bypass
        pre-listing filtering.
        """
        present = {(entry.asset, entry.dataset, entry.granularity) for entry in self.entries}
        expected = {
            (asset, dataset, granularity)
            for asset in assets
            for dataset, granularity in _REQUIRED_DATASETS
        }
        if not expected.issubset(present):
            raise ValueError("ARCHIVE_AVAILABILITY_MISSING")

    @classmethod
    def from_yaml(cls, path: Path) -> ArchiveAvailabilityManifest:
        with Path(path).open("r", encoding="utf-8") as stream:
            data = yaml.safe_load(stream)
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Offline bootstrap — no network calls
# ---------------------------------------------------------------------------

_SUFFIX = ".manifest.json"


def _derive_granularity(source_period: str) -> SourceGranularity:
    """Derive granularity from source_period format (YYYY-MM or YYYY-MM-DD)."""
    parts = source_period.split("-")
    if len(parts) == 2:
        return SourceGranularity.MONTHLY
    if len(parts) == 3:
        return SourceGranularity.DAILY
    raise ValueError(f"ARCHIVE_AVAILABILITY_INVALID_PERIOD: {source_period}")


def _period_start(source_period: str, granularity: SourceGranularity) -> datetime:
    """Convert a source_period string to a UTC datetime at period start."""
    if granularity == SourceGranularity.MONTHLY:
        year, month = source_period.split("-")
        return datetime(int(year), int(month), 1, tzinfo=UTC)
    year, month, day = source_period.split("-")
    return datetime(int(year), int(month), int(day), tzinfo=UTC)


def _earliest_event_time(
    zip_path: Path, *, asset: str, dataset: str, interval: str | None
) -> datetime:
    """Parse a verified ZIP and return the earliest event_time."""
    import pandas as pd

    from bian_quant.data.canonicalize import (
        canonicalize_funding_zip,
        canonicalize_metrics_zip,
        canonicalize_ohlcv_zip,
    )

    ingested_at = datetime.now(UTC)
    if dataset == "ohlcv":
        frame = canonicalize_ohlcv_zip(
            zip_path, asset=asset, interval=interval or "1d", ingested_at=ingested_at
        )
    elif dataset == "funding":
        frame = canonicalize_funding_zip(zip_path, asset=asset, ingested_at=ingested_at)
    else:
        frame = canonicalize_metrics_zip(
            zip_path, ingested_at=ingested_at, publication_delay=timedelta(minutes=5)
        )
    earliest = frame["event_time"].min()
    return pd.Timestamp(earliest).to_pydatetime()


def _verified_candidates(
    raw_root: Path, *, assets: tuple[str, ...]
) -> list[_VerifiedCandidate]:
    """Discover and verify all raw artifacts under *raw_root*.

    Only artifacts that pass integrity and identity verification are returned.
    """
    asset_set = set(assets)
    candidates: list[_VerifiedCandidate] = []

    for manifest_path in sorted(raw_root.rglob("*.zip.manifest.json")):
        try:
            manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest = RawSourceManifest.model_validate(manifest_data)
        except (ValueError, OSError):
            continue

        if manifest.asset not in asset_set:
            continue

        zip_name = manifest_path.name
        if not zip_name.endswith(_SUFFIX):
            continue
        zip_path = manifest_path.parent / zip_name[: -len(_SUFFIX)]

        identity = RawSourceIdentity(
            asset=manifest.asset,
            dataset=manifest.dataset,
            interval=manifest.interval,
            source_period=manifest.source_period,
        )

        try:
            result = reuse_verified_artifact(zip_path, expected=identity)
        except ValueError:
            continue

        granularity = _derive_granularity(manifest.source_period)
        period_start_dt = _period_start(manifest.source_period, granularity)

        interval_label = manifest.interval or "native"
        candidates.append(
            {
                "asset": manifest.asset,
                "dataset": SourceDataset(manifest.dataset),
                "granularity": granularity,
                "first_available_period": period_start_dt,
                "evidence_identity_key": "|".join(
                    (
                        manifest.dataset,
                        manifest.asset,
                        interval_label,
                        granularity.value,
                        period_start_dt.isoformat(),
                    )
                ),
                "evidence_url": manifest.source_url,
                "evidence_content_sha256": result.manifest.content_sha256,
                "evidence_path": result.path,
                "interval": manifest.interval,
            }
        )

    return candidates


def _earliest_by_key(
    candidates: list[_VerifiedCandidate],
) -> list[_VerifiedCandidate]:
    """Select the earliest candidate per (asset, dataset, granularity) key."""
    by_key: dict[tuple[str, str, str], _VerifiedCandidate] = {}
    for candidate in candidates:
        key = (
            candidate["asset"],
            candidate["dataset"].value,
            candidate["granularity"].value,
        )
        existing = by_key.get(key)
        if (
            existing is None
            or candidate["first_available_period"] < existing["first_available_period"]
        ):
            by_key[key] = candidate
    return list(by_key.values())


_REQUIRED_DATASETS: tuple[tuple[SourceDataset, SourceGranularity], ...] = (
    (SourceDataset.OHLCV, SourceGranularity.MONTHLY),
    (SourceDataset.OHLCV, SourceGranularity.DAILY),
    (SourceDataset.FUNDING, SourceGranularity.MONTHLY),
    (SourceDataset.METRICS_OI, SourceGranularity.DAILY),
)


def _require_expected_keys(
    entries: tuple[ArchiveAvailabilityEntry, ...],
    *,
    assets: tuple[str, ...],
) -> None:
    """Verify all required (asset, dataset, granularity) keys are present."""
    present = {(entry.asset, entry.dataset, entry.granularity) for entry in entries}
    for asset in assets:
        for dataset, granularity in _REQUIRED_DATASETS:
            if (asset, dataset, granularity) not in present:
                raise ValueError("ARCHIVE_AVAILABILITY_EVIDENCE_MISSING")


def _entry_from_candidate(item: _VerifiedCandidate) -> ArchiveAvailabilityEntry:
    try:
        first_event_time = _earliest_event_time(
            item["evidence_path"],
            asset=item["asset"],
            dataset=item["dataset"].value,
            interval=item["interval"],
        )
    except (ValueError, OSError) as exc:
        raise ValueError("ARCHIVE_AVAILABILITY_EVIDENCE_INVALID") from exc
    return ArchiveAvailabilityEntry(
        asset=item["asset"],
        dataset=item["dataset"],
        granularity=item["granularity"],
        first_available_period=item["first_available_period"],
        evidence_identity_key=item["evidence_identity_key"],
        evidence_url=item["evidence_url"],
        evidence_content_sha256=item["evidence_content_sha256"],
        first_event_time=first_event_time,
    )


def bootstrap_archive_availability(
    raw_root: Path, *, assets: tuple[str, ...]
) -> ArchiveAvailabilityManifest:
    """Build an availability manifest from verified raw artifacts.

    No network calls are made. Only artifacts that pass integrity and
    identity verification are used as evidence. Derives month/day granularity
    from source_period, dispatches to the existing canonicalizer, and
    preserves minimum event_time only as audit evidence.
    """
    candidates = _verified_candidates(raw_root, assets=assets)
    # Parse only the selected evidence archive for each availability key.
    entries = tuple(_entry_from_candidate(item) for item in _earliest_by_key(candidates))
    _require_expected_keys(entries, assets=assets)
    return ArchiveAvailabilityManifest(
        rule_version="popular-universe-availability-v1", entries=entries
    )
