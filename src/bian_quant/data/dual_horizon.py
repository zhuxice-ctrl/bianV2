"""Resumable dual-horizon acquisition and snapshot build orchestrator."""

from __future__ import annotations

import hashlib
import io
import json
import math
import shutil
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Literal, Protocol, overload

import pandas as pd

from bian_quant.data.acquisition import (
    DiskBudget,
    DiskStatus,
    DualHorizonAcquisition,
    SourceDataset,
    SourceObject,
    build_source_plan_audit,
    check_disk_budget,
    source_plan_payload,
)
from bian_quant.data.acquisition_failures import (
    AcquisitionFailureEvidence,
    classify_acquisition_failure,
    is_funding_tail_period,
)
from bian_quant.data.adapters.binance_archive import download_verified
from bian_quant.data.adapters.raw import (
    AcquisitionObjectResult,
    AcquisitionObjectStatus,
    RawSourceManifest,
    reuse_verified_artifact,
    save_source_artifact,
)
from bian_quant.data.canonicalize import (
    canonicalize_funding_zip,
    canonicalize_metrics_zip,
    canonicalize_ohlcv_zip,
    write_canonical_partition,
)
from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import (
    DatasetLayer,
    DatasetManifest,
    QualityFinding,
    QualitySeverity,
)
from bian_quant.data.derivatives_quality import (
    CoverageReport,
    inspect_funding,
    inspect_metrics,
    inspect_ohlcv_coverage,
)
from bian_quant.data.evidence_cutoff import (
    CutoffEvidence,
    canonical_plan_path,
    canonical_snapshot_id,
    clip_to_evidence_cutoff,
)
from bian_quant.data.popular_universe import build_popular_universe
from bian_quant.data.snapshots import (
    build_delay_views,
    build_macro_snapshots,
    build_micro_snapshots,
)
from bian_quant.experiments.models import RunManifest, RunStatus
from bian_quant.experiments.registry import ExperimentRegistry


class DualHorizonStatus(StrEnum):
    PASSED = "passed"
    BLOCKED = "blocked"
    FAILED = "failed"


@dataclass(frozen=True)
class DualHorizonResult:
    run_id: str
    status: DualHorizonStatus
    snapshots: tuple[DatasetManifest, ...]
    acquisition_artifact: Path
    quality_artifact: Path
    blocked_periods: tuple[str, ...]
    error_code: str | None
    persistent_bytes: int
    peak_working_bytes: int


class Downloader(Protocol):
    def acquire(
        self, source: SourceObject, config: DualHorizonAcquisition
    ) -> AcquisitionObjectResult: ...


class BinanceDownloader:
    """Default downloader using Binance public archives."""

    def acquire(
        self, source: SourceObject, config: DualHorizonAcquisition
    ) -> AcquisitionObjectResult:
        target = config.raw_root / source.relative_path
        return download_verified(
            target,
            url=source.url,
            identity=source.raw_identity,
            attempts=config.download_attempts,
        )


class VerifiedLocalDownloader:
    """Reuse verified local raw objects without any network access."""

    def acquire(
        self, source: SourceObject, config: DualHorizonAcquisition
    ) -> AcquisitionObjectResult:
        return reuse_verified_artifact(
            config.raw_root / source.relative_path,
            expected=source.raw_identity,
        )


class FixtureDownloader:
    """Test downloader that serves pre-existing fixture files."""

    def __init__(self, fixtures_dir: Path) -> None:
        self._fixtures = fixtures_dir

    def acquire(
        self, source: SourceObject, config: DualHorizonAcquisition
    ) -> AcquisitionObjectResult:
        fixture_map = {
            SourceDataset.OHLCV: self._fixtures / "ohlcv-mini.zip",
            SourceDataset.FUNDING: self._fixtures / "funding-mini.zip",
            SourceDataset.METRICS_OI: self._fixtures / "metrics-mini.zip",
        }
        payload = self._payload_for(source, fixture_map[source.dataset])
        content_sha = hashlib.sha256(payload).hexdigest()
        manifest = RawSourceManifest(
            source_url=source.url,
            fetched_at=datetime.now(UTC),
            content_sha256=content_sha,
            upstream_sha256=content_sha,
            byte_count=len(payload),
            asset=source.asset,
            dataset=source.dataset.value,
            interval=source.interval,
            source_period=source.raw_identity.source_period,
        )
        target = config.raw_root / source.relative_path
        if target.exists() or target.with_suffix(f"{target.suffix}.manifest.json").exists():
            return reuse_verified_artifact(target, expected=source.raw_identity)
        save_source_artifact(target, payload, manifest)
        return AcquisitionObjectResult(
            status=AcquisitionObjectStatus.DOWNLOADED,
            path=target,
            manifest=manifest,
        )

    @staticmethod
    def _payload_for(source: SourceObject, fixture_path: Path) -> bytes:
        """Create a source-period-aligned miniature archive for offline E2E tests."""
        with zipfile.ZipFile(fixture_path) as archive:
            member = archive.namelist()[0]
            header = archive.read(member).decode("utf-8").splitlines()[0]
        start = source.period_start
        if source.dataset == SourceDataset.OHLCV:
            seconds = {"1h": 3600, "4h": 4 * 3600, "1d": 24 * 3600}[source.interval]
            rows = [header]
            row_count = 1 if source.interval == "1d" else 3
            for index in range(row_count):
                opened = start + timedelta(seconds=seconds * index)
                closed = opened + timedelta(seconds=seconds) - timedelta(milliseconds=1)
                rows.append(
                    f"{int(opened.timestamp() * 1000)},50000,50100,49900,50050,100,"
                    f"{int(closed.timestamp() * 1000)},5000000,100,50,2500000,0"
                )
        elif source.dataset == SourceDataset.FUNDING:
            rows = [header]
            event = start
            natural_end = (
                start.replace(year=start.year + 1, month=1)
                if start.month == 12
                else start.replace(month=start.month + 1)
            )
            while event < natural_end:
                rows.append(f"{int(event.timestamp() * 1000)},8,0.0001")
                event += timedelta(hours=8)
        else:
            rows = [header]
            for index in range(3):
                event = start + timedelta(minutes=5 * index)
                rows.append(
                    f"{event:%Y-%m-%d %H:%M:%S},{source.asset},100000,5000000000,1.1,1.2,1.05,1.15"
                )
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(Path(member).name, "\n".join(rows) + "\n")
        return output.getvalue()


def _source_plan_hash(
    plan: tuple[SourceObject, ...], *, availability_manifest_sha256: str | None = None
) -> str:
    payload = json.dumps(
        {
            "availability_manifest_sha256": availability_manifest_sha256,
            "object_identity_keys": [obj.identity_key for obj in plan],
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _period_end(source: SourceObject, as_of: datetime) -> datetime:
    natural_end = _natural_period_end(source)
    return min(natural_end, as_of + timedelta(microseconds=1))


def _natural_period_end(source: SourceObject) -> datetime:
    if source.granularity.value == "daily":
        return source.period_start + timedelta(days=1)
    if source.period_start.month == 12:
        return source.period_start.replace(year=source.period_start.year + 1, month=1)
    return source.period_start.replace(month=source.period_start.month + 1)


def _quality_report(
    source: SourceObject,
    frame: pd.DataFrame,
    config: DualHorizonAcquisition,
) -> CoverageReport:
    natural_end = _natural_period_end(source)
    period_end = _period_end(source, config.as_of)
    left_closed = (frame["event_time"] >= source.period_start) & (frame["event_time"] < natural_end)
    source_mask = left_closed
    metrics_right_closed = False
    if source.dataset == SourceDataset.METRICS_OI and source.granularity.value == "daily":
        right_closed = (frame["event_time"] > source.period_start) & (
            frame["event_time"] <= natural_end + timedelta(seconds=1)
        )
        if int(right_closed.sum()) > int(left_closed.sum()):
            source_mask = right_closed
            metrics_right_closed = True
    source_frame = frame.loc[source_mask]
    in_period = source_frame.loc[
        (source_frame["event_time"] <= config.as_of)
        & (source_frame["available_time"] <= config.as_of)
    ]
    outside_rows = len(frame) - len(source_frame)
    if source.dataset == SourceDataset.OHLCV:
        seconds = {"1h": 3600, "4h": 4 * 3600, "1d": 24 * 3600}[source.interval]
        available_event_cutoff = (
            config.as_of - timedelta(seconds=seconds) + timedelta(milliseconds=1)
        )
        latest_eligible_event = min(natural_end - timedelta(microseconds=1), available_event_cutoff)
        expected = (
            max(
                0,
                math.floor((latest_eligible_event - source.period_start).total_seconds() / seconds)
                + 1,
            )
            if available_event_cutoff >= source.period_start
            else 0
        )
        report = inspect_ohlcv_coverage(
            observed=in_period["event_time"].nunique(),
            expected=expected,
            threshold=config.coverage.ohlcv,
            source_period=source.raw_identity.source_period,
        )
        findings = list(report.findings)
        invalid_prices = (
            (in_period[["open", "high", "low", "close"]] <= 0).any(axis=1)
            | (in_period["volume"] < 0)
            | (in_period["high"] < in_period[["open", "close", "low"]].max(axis=1))
            | (in_period["low"] > in_period[["open", "close", "high"]].min(axis=1))
        ).sum()
        duplicates = in_period.duplicated(["asset", "event_time"]).sum()
        event_times: list[datetime] = [
            value.to_pydatetime()
            for value in pd.to_datetime(in_period.sort_values("event_time")["event_time"], utc=True)
        ]
        long_gaps = sum(
            (current - previous).total_seconds() > 2 * seconds
            for previous, current in zip(event_times, event_times[1:], strict=False)
        )
        causal = (in_period["available_time"] < in_period["event_time"]).sum()
        for code, count in (
            ("OHLCV_VALUE_INVALID", invalid_prices),
            ("OHLCV_DUPLICATE", duplicates),
            ("OHLCV_GAP_UNEXPLAINED", long_gaps),
            ("AVAILABLE_TIME_VIOLATION", causal),
        ):
            if count:
                findings.append(
                    QualityFinding(
                        code=code,
                        severity=QualitySeverity.BLOCKING,
                        message=f"{int(count)} violations in {source.identity_key}",
                    )
                )
        report = report.model_copy(update={"findings": tuple(findings)})
    elif source.dataset == SourceDataset.FUNDING:
        complete_report = inspect_funding(
            source_frame,
            period_start=source.period_start,
            period_end=natural_end,
            threshold=config.coverage.funding,
        )
        report = inspect_funding(
            in_period,
            period_start=source.period_start,
            period_end=period_end,
            threshold=config.coverage.funding,
        )
        report = report.model_copy(update={"findings": complete_report.findings})
    else:
        metrics_event_cutoff = config.as_of - timedelta(minutes=min(config.oi_delay_minutes))
        metrics_period_end = min(
            natural_end,
            metrics_event_cutoff + timedelta(microseconds=1),
        )
        expected_rows = None
        if metrics_right_closed:
            expected_rows = max(
                0,
                math.floor(
                    (min(natural_end, metrics_event_cutoff) - source.period_start).total_seconds()
                    / 300
                ),
            )
        report = inspect_metrics(
            in_period,
            period_start=source.period_start,
            period_end=metrics_period_end,
            threshold=config.coverage.metrics_oi,
            expected_rows=expected_rows,
        )
    if outside_rows:
        finding = QualityFinding(
            code="SOURCE_PERIOD_MISMATCH",
            severity=QualitySeverity.BLOCKING,
            message=f"{outside_rows} rows fall outside {source.identity_key}",
        )
        report = report.model_copy(update={"findings": (*report.findings, finding)})
    return report.model_copy(update={"asset": source.asset, "identity_key": source.identity_key})


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(
            payload,
            stream,
            indent=2,
            sort_keys=True,
            allow_nan=False,
            default=str,
        )


def _derive_listing_metadata(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """Derive listing metadata from the earliest OHLCV event per asset."""
    rows = []
    for asset, group in ohlcv.groupby("asset", sort=True):
        first = group.sort_values("event_time").iloc[0]
        rows.append(
            {
                "asset": asset,
                "listing_time": first["event_time"],
                "listing_available_time": first["available_time"],
            }
        )
    return pd.DataFrame(rows)


def _partial_exclusion(source: SourceObject, *, error_code: str) -> dict[str, object]:
    """Build a run-scoped partial availability exclusion entry."""
    return {
        "identity_key": source.identity_key,
        "asset": source.asset,
        "dataset": source.dataset.value,
        "granularity": source.granularity.value,
        "period": source.raw_identity.source_period,
        "reason": "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE",
        "error_code": error_code,
        "temporary": True,
    }


def _is_partializable_funding_tail_coverage(
    source: SourceObject,
    report: CoverageReport,
    config: DualHorizonAcquisition,
) -> bool:
    """Return whether a tail quality failure is safe to treat as temporary.

    Partial availability is a popular-universe-only concession.  A registered
    Funding tail may be excluded only for an otherwise clean coverage gap;
    malformed or causally invalid data always remains a hard blocker.
    """
    blocking_codes = {
        finding.code
        for finding in report.findings
        if finding.severity == QualitySeverity.BLOCKING
    }
    return (
        config.universe_policy is not None
        and is_funding_tail_period(source, config)
        and blocking_codes == {"DATA_COVERAGE_BLOCKED"}
    )


@dataclass(frozen=True)
class PopularUniverseBuildResult:
    artifacts: list[dict[str, object]]
    shortages: list[dict[str, str]]


def _has_funding_days_shortage(
    artifact: dict[str, object], partial_assets: list[str]
) -> bool:
    """Whether a popular-universe artifact excludes a partially available asset."""
    exclusions = artifact.get("exclusions")
    if not isinstance(exclusions, list):
        return False
    return any(
        isinstance(row, dict)
        and str(row.get("asset")) in partial_assets
        and str(row.get("reason")) == "FUNDING_DAYS_INSUFFICIENT"
        for row in exclusions
    )


def _build_popular_universe_artifacts(
    config: DualHorizonAcquisition,
    ohlcv: pd.DataFrame,
    funding: pd.DataFrame,
    metrics: pd.DataFrame,
) -> PopularUniverseBuildResult:
    """Build one popular-universe artifact per UTC daily boundary.

    Returns a PopularUniverseBuildResult with artifacts and any daily
    shortages (below min_selected) as hard blockers.
    """
    policy = config.universe_policy
    assert policy is not None

    listing = _derive_listing_metadata(ohlcv)

    # Include every configured daily selector boundary, beginning at
    # micro_start.  Point-in-time filtering in build_popular_universe keeps
    # same-day rows out until they are actually available.
    start = pd.Timestamp(config.micro_start).tz_convert("UTC")
    end = pd.Timestamp(config.as_of).tz_convert("UTC")

    artifacts_dir = config.artifact_root / "popular-universe"
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, object]] = []
    shortages: list[dict[str, str]] = []
    current = start
    while current <= end:
        selection_time = current.to_pydatetime()
        try:
            artifact = build_popular_universe(
                selection_time=selection_time,
                listing_metadata=listing,
                ohlcv=ohlcv,
                funding=funding,
                metrics=metrics,
                policy=policy,
            )
        except RuntimeError as exc:
            if str(exc).startswith("POPULAR_UNIVERSE_INSUFFICIENT:"):
                shortages.append(
                    {
                        "identity_key": f"popular-universe|{selection_time:%Y-%m-%d}",
                        "message": str(exc),
                    }
                )
                current = current + pd.Timedelta(days=1)
                continue
            raise

        artifact_path = artifacts_dir / f"{selection_time:%Y-%m-%dT%H-%M-%S}.json"
        payload = {
            "artifact_id": artifact.artifact_id,
            "selection_time": selection_time.isoformat(),
            "selector_config_hash": artifact.selector_config_hash,
            "members": [
                {
                    "asset": m.asset,
                    "rank": m.rank,
                    "median_quote_volume": m.median_quote_volume,
                    "median_oi_value": m.median_oi_value,
                }
                for m in artifact.members
            ],
            "exclusions": [{"asset": e.asset, "reason": e.reason} for e in artifact.exclusions],
            "source_hashes": artifact.source_hashes,
        }
        with artifact_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True, default=str)

        results.append(
            {
                "artifact_id": artifact.artifact_id,
                "selection_time": selection_time.isoformat(),
                "selector_config_hash": artifact.selector_config_hash,
                "member_assets": list(artifact.member_assets),
                "exclusions": [
                    {"asset": e.asset, "reason": e.reason} for e in artifact.exclusions
                ],
            }
        )
        current = current + pd.Timedelta(days=1)

    return PopularUniverseBuildResult(artifacts=results, shortages=shortages)


@overload
def prepare_dual_horizon(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    downloader: Downloader | None = None,
    dry_run: Literal[True],
) -> dict[str, object]: ...


@overload
def prepare_dual_horizon(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    downloader: Downloader | None = None,
    dry_run: Literal[False] = False,
) -> DualHorizonResult: ...


def prepare_dual_horizon(
    config: DualHorizonAcquisition,
    *,
    code_sha: str,
    downloader: Downloader | None = None,
    dry_run: bool = False,
) -> DualHorizonResult | dict[str, object]:
    """Execute the dual-horizon acquisition and snapshot build pipeline.

    If *dry_run* is True, returns a JSON-safe dict without network access.
    """
    if dry_run:
        payload = source_plan_payload(config)
        payload["as_of"] = config.as_of.isoformat()
        payload["network_access"] = False
        return payload

    if downloader is None:
        downloader = VerifiedLocalDownloader()

    plan_audit = build_source_plan_audit(config)
    plan = plan_audit.objects
    plan_hash = _source_plan_hash(
        plan, availability_manifest_sha256=plan_audit.availability_manifest_sha256
    )

    # Register run
    registry_path = config.experiment_registry_path
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    catalog = DatasetCatalog(config.catalog_path)

    run_manifest = RunManifest.create(
        strategy_name="dual_horizon_derivatives",
        code_sha=code_sha,
        dataset_snapshot_ids=[f"source-plan-{plan_hash[:16]}"] + list(config.parent_snapshot_ids),
        config={"plan_hash": plan_hash, "as_of": config.as_of.isoformat()},
        seed=0,
    )

    with ExperimentRegistry(registry_path) as registry:
        registry.create(run_manifest)
        registry.transition(run_manifest.run_id, RunStatus.RUNNING)

    run_dir = config.artifact_root / run_manifest.run_id
    acquisition_artifact = run_dir / "data-acquisition.json"
    quality_artifact = run_dir / "data-quality.json"

    # Check disk
    budget = DiskBudget(
        warn_bytes=config.disk_warn_gb * 1024**3,
        block_bytes=config.disk_block_gb * 1024**3,
    )
    disk_status = check_disk_budget(config.raw_root, budget)
    if disk_status == DiskStatus.BLOCKED:
        _write_json(
            acquisition_artifact,
            {
                "run_id": run_manifest.run_id,
                "status": "blocked",
                "error_code": "DISK_BLOCKED",
                "results": [],
                "persistent_bytes": 0,
                "peak_working_bytes": 0,
                "availability_manifest_sha256": plan_audit.availability_manifest_sha256,
                "pre_listing_exclusions": list(plan_audit.pre_listing_exclusions),
                "partial_availability_exclusions": [],
                "partial_availability_impact": {
                    "affected_assets": [],
                    "affected_periods": 0,
                    "affected_selection_days": 0,
                },
                "partial_availability_exclusion_sha256": None,
            },
        )
        _write_json(
            quality_artifact,
            {
                "run_id": run_manifest.run_id,
                "status": "blocked",
                "findings": [{"code": "DISK_BLOCKED", "severity": "blocking"}],
                "coverage_reports": [],
                "availability_manifest_sha256": plan_audit.availability_manifest_sha256,
                "pre_listing_exclusions": list(plan_audit.pre_listing_exclusions),
                "partial_availability_exclusions": [],
                "partial_availability_impact": {
                    "affected_assets": [],
                    "affected_periods": 0,
                    "affected_selection_days": 0,
                },
                "partial_availability_exclusion_sha256": None,
            },
        )
        with ExperimentRegistry(registry_path) as registry:
            registry.transition(run_manifest.run_id, RunStatus.BLOCKED)
        return DualHorizonResult(
            run_id=run_manifest.run_id,
            status=DualHorizonStatus.BLOCKED,
            snapshots=(),
            acquisition_artifact=acquisition_artifact,
            quality_artifact=quality_artifact,
            blocked_periods=(),
            error_code="DISK_BLOCKED",
            persistent_bytes=0,
            peak_working_bytes=0,
        )

    # Execute downloads
    config.raw_root.mkdir(parents=True, exist_ok=True)
    config.canonical_root.mkdir(parents=True, exist_ok=True)
    config.research_root.mkdir(parents=True, exist_ok=True)
    config.artifact_root.mkdir(parents=True, exist_ok=True)

    baseline_free = shutil.disk_usage(config.raw_root).free
    peak_reduction = 0

    acquisition_results: list[dict[str, object]] = []
    acquisition_failures: list[AcquisitionFailureEvidence] = []
    acquired: dict[str, AcquisitionObjectResult] = {}
    blocked_periods: list[str] = []
    partial_exclusions: list[dict[str, object]] = []

    def acquire_one(
        source: SourceObject,
    ) -> tuple[SourceObject, AcquisitionObjectResult | None, Exception | None]:
        try:
            return source, downloader.acquire(source, config), None
        except Exception as error:
            return source, None, error

    completed_outcomes: dict[
        int, tuple[SourceObject, AcquisitionObjectResult | None, Exception | None]
    ] = {}
    with ThreadPoolExecutor(max_workers=config.max_workers) as executor:
        indexed_futures = {
            executor.submit(acquire_one, source): index for index, source in enumerate(plan)
        }
        for future in as_completed(indexed_futures):
            outcome = future.result()
            current_free = shutil.disk_usage(config.raw_root).free
            reduction = baseline_free - current_free
            if reduction > peak_reduction:
                peak_reduction = reduction
            completed_outcomes[indexed_futures[future]] = outcome

    for index in range(len(plan)):
        source, result, error = completed_outcomes[index]
        if result is not None:
            acquired[source.identity_key] = result
            acquisition_results.append(
                {
                    "identity_key": source.identity_key,
                    "status": result.status,
                    "content_sha256": result.manifest.content_sha256,
                    "byte_count": result.manifest.byte_count,
                    "fetched_at": result.manifest.fetched_at.isoformat(),
                }
            )
        else:
            assert error is not None
            failure = classify_acquisition_failure(source, config, error)
            acquisition_failures.append(failure)
            acquisition_results.append(
                {
                    "identity_key": source.identity_key,
                    "status": "failed",
                    **failure.model_dump(mode="json", exclude={"identity_key"}),
                }
            )
            if (
                config.universe_policy is not None
                and failure.temporary
                and is_funding_tail_period(source, config)
            ):
                partial_exclusions.append(
                    _partial_exclusion(source, error_code=failure.error_code)
                )
            else:
                blocked_periods.append(source.identity_key)

    # Canonicalize verified objects and persist immutable partitions.
    snapshots: list[DatasetManifest] = []
    ohlcv_frames: list[pd.DataFrame] = []
    funding_frames: list[pd.DataFrame] = []
    metrics_frames: list[pd.DataFrame] = []
    coverage_reports: list[CoverageReport] = []
    cutoff_evidence: list[CutoffEvidence] = []

    for source in plan:
        acquired_result = acquired.get(source.identity_key)
        if acquired_result is None:
            continue
        try:
            ingested_at = acquired_result.manifest.fetched_at.astimezone(UTC)
            if source.dataset == SourceDataset.OHLCV:
                frame = canonicalize_ohlcv_zip(
                    acquired_result.path,
                    asset=source.asset,
                    interval=source.interval,
                    ingested_at=ingested_at,
                )
            elif source.dataset == SourceDataset.FUNDING:
                frame = canonicalize_funding_zip(
                    acquired_result.path,
                    asset=source.asset,
                    ingested_at=ingested_at,
                )
            else:
                frame = canonicalize_metrics_zip(
                    acquired_result.path,
                    ingested_at=ingested_at,
                    publication_delay=timedelta(minutes=5),
                )
            report = _quality_report(source, frame, config)
            coverage_reports.append(report)
            cutoff_slice = clip_to_evidence_cutoff(source, frame, as_of=config.as_of)
            cutoff_evidence.append(cutoff_slice.evidence)
            eligible_frame = cutoff_slice.eligible
            if eligible_frame.empty:
                if report.expected_rows == 0 and source.dataset == SourceDataset.OHLCV:
                    continue
                raise ValueError(
                    f"EVIDENCE_CUTOFF_VIOLATION: no eligible rows for {source.identity_key}"
                )
            if source.dataset == SourceDataset.OHLCV:
                ohlcv_frames.append(eligible_frame)
            elif source.dataset == SourceDataset.FUNDING:
                funding_frames.append(eligible_frame)
            else:
                metrics_frames.append(eligible_frame)
            canonical_path = canonical_plan_path(
                config.canonical_root,
                plan_hash=plan_hash,
                relative_path=source.relative_path,
            )
            content_sha = write_canonical_partition(eligible_frame, canonical_path)
            canonical_id = canonical_snapshot_id(
                source,
                content_sha=content_sha,
                plan_hash=plan_hash,
            )
            canonical_config = json.dumps(
                {
                    "identity_key": source.identity_key,
                    "raw_sha256": acquired_result.manifest.content_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            canonical_manifest = DatasetManifest(
                snapshot_id=canonical_id,
                layer=DatasetLayer.CANONICAL,
                name=f"canonical-{source.dataset.value}-{source.interval}",
                content_sha256=content_sha,
                row_count=len(eligible_frame),
                min_event_time=eligible_frame["event_time"].min(),
                max_event_time=eligible_frame["event_time"].max(),
                min_available_time=eligible_frame["available_time"].min(),
                max_available_time=eligible_frame["available_time"].max(),
                parent_snapshot_ids=[f"raw-{acquired_result.manifest.content_sha256}"],
                config_json=canonical_config,
            )
            catalog.register(canonical_manifest, path=canonical_path)
            if report.blocking:
                if _is_partializable_funding_tail_coverage(source, report, config):
                    partial_exclusions.append(
                        _partial_exclusion(
                            source, error_code="FUNDING_TAIL_COVERAGE_INCOMPLETE"
                        )
                    )
                else:
                    blocked_periods.append(source.identity_key)
        except Exception as exc:
            blocked_periods.append(source.identity_key)
            acquisition_results.append(
                {
                    "identity_key": source.identity_key,
                    "status": "parse_failed",
                    "error": str(exc),
                }
            )

    blocked_periods = sorted(set(blocked_periods))
    if not ohlcv_frames and not blocked_periods:
        blocked_periods.append("required-dataset|ohlcv")
    if not funding_frames and not blocked_periods:
        blocked_periods.append("required-dataset|funding")
    if not metrics_frames and not blocked_periods:
        blocked_periods.append("required-dataset|metrics_oi")
    blocked_periods = sorted(set(blocked_periods))
    blocking = bool(blocked_periods)
    popular_universe_artifacts: list[dict[str, object]] = []
    ohlcv_combined = pd.DataFrame()
    funding_combined = pd.DataFrame()
    metrics_combined = pd.DataFrame()

    # Pre-check: build popular universe to detect daily shortages.
    if not blocking and ohlcv_frames and funding_frames and metrics_frames:
        ohlcv_combined = pd.concat(ohlcv_frames, ignore_index=True)
        funding_combined = pd.concat(funding_frames, ignore_index=True)
        metrics_combined = pd.concat(metrics_frames, ignore_index=True)
        if config.universe_policy is not None:
            popular_build = _build_popular_universe_artifacts(
                config, ohlcv_combined, funding_combined, metrics_combined
            )
            popular_universe_artifacts = popular_build.artifacts
            blocked_periods.extend(
                shortage["identity_key"] for shortage in popular_build.shortages
            )
            blocked_periods = sorted(set(blocked_periods))
            blocking = bool(blocked_periods)

    # Publish only after every required input and quality gate passes.
    if not blocking and not ohlcv_combined.empty:
        macro_ohlcv = ohlcv_combined.loc[ohlcv_combined["event_time"] >= config.macro_start]
        micro_ohlcv = ohlcv_combined.loc[ohlcv_combined["event_time"] >= config.micro_start]
        raw_hashes = sorted(result.manifest.content_sha256 for result in acquired.values())
        raw_set_sha = hashlib.sha256("".join(raw_hashes).encode()).hexdigest()
        lineage = (f"raw-set-{raw_set_sha}", *config.parent_snapshot_ids)

    # Deduplicate and sort partial exclusions.
    seen_keys: set[str] = set()
    deduped_exclusions: list[dict[str, object]] = []
    for exclusion in partial_exclusions:
        key = str(exclusion["identity_key"])
        if key not in seen_keys:
            seen_keys.add(key)
            deduped_exclusions.append(exclusion)
    deduped_exclusions.sort(key=lambda item: str(item["identity_key"]))

    partial_exclusion_sha256 = hashlib.sha256(
        json.dumps(deduped_exclusions, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    # Compute deterministic impact.
    partial_assets = sorted({str(row["asset"]) for row in deduped_exclusions})
    affected_selection_days = sum(
        1
        for artifact in popular_universe_artifacts
        if _has_funding_days_shortage(artifact, partial_assets)
    )
    partial_impact = {
        "affected_assets": partial_assets,
        "affected_periods": len(deduped_exclusions),
        "affected_selection_days": affected_selection_days,
    }

    if not blocking and not ohlcv_combined.empty:
        snapshot_config_dict: dict[str, object] = {
            "assets": config.assets,
            "macro_start": config.macro_start.isoformat(),
            "micro_start": config.micro_start.isoformat(),
            "as_of": config.as_of.isoformat(),
            "code_sha": code_sha,
            "plan_hash": plan_hash,
            "raw_set_sha256": raw_set_sha,
            "availability_manifest_sha256": plan_audit.availability_manifest_sha256,
            "partial_availability_exclusion_sha256": partial_exclusion_sha256,
        }
        if popular_universe_artifacts:
            snapshot_config_dict["popular_universe_artifact_ids"] = [
                str(item["artifact_id"]) for item in popular_universe_artifacts
            ]
        snapshot_config = json.dumps(
            snapshot_config_dict,
            sort_keys=True,
            separators=(",", ":"),
        )
        macro_snaps = build_macro_snapshots(
            macro_ohlcv,
            funding_combined,
            intervals=config.macro_intervals,
            root=config.research_root,
            catalog=catalog,
            parent_snapshot_ids=lineage,
            config_json=snapshot_config,
        )
        snapshots.extend(macro_snaps)
        micro_snaps = build_micro_snapshots(
            micro_ohlcv,
            funding_combined,
            metrics_combined,
            intervals=config.micro_intervals,
            root=config.research_root,
            catalog=catalog,
            parent_snapshot_ids=lineage,
            config_json=snapshot_config,
        )
        snapshots.extend(micro_snaps)
        delay_snapshot_ids = build_delay_views(
            metrics_combined,
            delays=config.oi_delay_minutes,
            root=config.research_root,
            parent_snapshot_ids=tuple(s.snapshot_id for s in snapshots),
            as_of=config.as_of,
        )
    else:
        delay_snapshot_ids = {}

    # Calculate persistent bytes
    persistent = (
        _directory_size(config.raw_root)
        + _directory_size(config.canonical_root)
        + _directory_size(config.research_root)
        + _directory_size(config.artifact_root)
    )

    status = DualHorizonStatus.BLOCKED if blocking else DualHorizonStatus.PASSED
    result_status_order = {
        AcquisitionObjectStatus.DOWNLOADED: 0,
        AcquisitionObjectStatus.SKIPPED: 0,
        "failed": 0,
        "parse_failed": 1,
    }
    acquisition_results.sort(
        key=lambda item: (
            str(item["identity_key"]),
            result_status_order.get(str(item["status"]), 2),
            str(item["status"]),
        )
    )
    cutoff_payload = [
        item.model_dump(mode="json")
        for item in sorted(cutoff_evidence, key=lambda item: item.identity_key)
    ]
    run_error_code = "DATA_PIPELINE_BLOCKED" if blocked_periods else None
    acquisition_data: dict[str, object] = {
        "run_id": run_manifest.run_id,
        "status": status.value,
        "plan_hash": plan_hash,
        "planned_objects": len(plan),
        "results": acquisition_results,
        "blocked_periods": blocked_periods,
        "persistent_bytes": persistent,
        "peak_working_bytes": peak_reduction,
        "funding_tail_strategy": config.funding_tail_strategy,
        "cutoff_evidence": cutoff_payload,
        "snapshot_ids": [snapshot.snapshot_id for snapshot in snapshots],
        "delay_snapshot_ids": delay_snapshot_ids,
        "popular_universe_artifacts": popular_universe_artifacts,
        "availability_manifest_sha256": plan_audit.availability_manifest_sha256,
        "pre_listing_exclusions": list(plan_audit.pre_listing_exclusions),
        "partial_availability_exclusions": deduped_exclusions,
        "partial_availability_impact": partial_impact,
        "partial_availability_exclusion_sha256": partial_exclusion_sha256,
    }
    quality_data: dict[str, object] = {
        "run_id": run_manifest.run_id,
        "status": status.value,
        "coverage_reports": [report.model_dump(mode="json") for report in coverage_reports],
        "blocked_periods": blocked_periods,
        "funding_tail_strategy": config.funding_tail_strategy,
        "cutoff_evidence": cutoff_payload,
        "popular_universe_artifacts": popular_universe_artifacts,
        "availability_manifest_sha256": plan_audit.availability_manifest_sha256,
        "pre_listing_exclusions": list(plan_audit.pre_listing_exclusions),
        "partial_availability_exclusions": deduped_exclusions,
        "partial_availability_impact": partial_impact,
        "partial_availability_exclusion_sha256": partial_exclusion_sha256,
    }
    _write_json(acquisition_artifact, acquisition_data)
    _write_json(quality_artifact, quality_data)

    with ExperimentRegistry(registry_path) as registry:
        if status == DualHorizonStatus.BLOCKED:
            registry.transition(run_manifest.run_id, RunStatus.BLOCKED)
        else:
            registry.transition(run_manifest.run_id, RunStatus.PASSED)

    return DualHorizonResult(
        run_id=run_manifest.run_id,
        status=status,
        snapshots=tuple(snapshots),
        acquisition_artifact=acquisition_artifact,
        quality_artifact=quality_artifact,
        blocked_periods=tuple(blocked_periods),
        error_code=run_error_code,
        persistent_bytes=persistent,
        peak_working_bytes=peak_reduction,
    )
