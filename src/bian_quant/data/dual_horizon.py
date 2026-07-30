"""Resumable dual-horizon acquisition and snapshot build orchestrator."""

from __future__ import annotations

import hashlib
import io
import json
import math
import shutil
import zipfile
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
    build_source_plan,
    check_disk_budget,
    source_plan_payload,
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
            for index in range(3):
                event = start + timedelta(hours=8 * index)
                rows.append(f"{int(event.timestamp() * 1000)},8,0.0001")
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


def _source_plan_hash(plan: tuple[SourceObject, ...]) -> str:
    payload = json.dumps([obj.identity_key for obj in plan], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _period_end(source: SourceObject, as_of: datetime) -> datetime:
    if source.granularity.value == "daily":
        natural_end = source.period_start + timedelta(days=1)
    elif source.period_start.month == 12:
        natural_end = source.period_start.replace(year=source.period_start.year + 1, month=1)
    else:
        natural_end = source.period_start.replace(month=source.period_start.month + 1)
    return min(natural_end, as_of + timedelta(microseconds=1))


def _quality_report(
    source: SourceObject,
    frame: pd.DataFrame,
    config: DualHorizonAcquisition,
) -> CoverageReport:
    period_end = _period_end(source, config.as_of)
    in_period = frame.loc[
        (frame["event_time"] >= source.period_start)
        & (frame["event_time"] < period_end)
        & (frame["event_time"] <= config.as_of)
    ]
    outside_rows = len(frame) - len(in_period)
    if source.dataset == SourceDataset.OHLCV:
        seconds = {"1h": 3600, "4h": 4 * 3600, "1d": 24 * 3600}[source.interval]
        expected = max(
            1,
            math.ceil((period_end - source.period_start).total_seconds() / seconds),
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
        report = inspect_funding(
            in_period,
            period_start=source.period_start,
            period_end=period_end,
            threshold=config.coverage.funding,
        )
    else:
        report = inspect_metrics(
            in_period,
            period_start=source.period_start,
            period_end=period_end,
            threshold=config.coverage.metrics_oi,
        )
    if outside_rows:
        finding = QualityFinding(
            code="SOURCE_PERIOD_MISMATCH",
            severity=QualitySeverity.BLOCKING,
            message=f"{outside_rows} rows fall outside {source.identity_key}",
        )
        report = report.model_copy(update={"findings": (*report.findings, finding)})
    return report


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

    plan = build_source_plan(config)
    plan_hash = _source_plan_hash(plan)

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
            },
        )
        _write_json(
            quality_artifact,
            {
                "run_id": run_manifest.run_id,
                "status": "blocked",
                "findings": [{"code": "DISK_BLOCKED", "severity": "blocking"}],
                "coverage_reports": [],
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
    acquired: dict[str, AcquisitionObjectResult] = {}
    blocked_periods: list[str] = []

    for source in plan:
        try:
            result = downloader.acquire(source, config)
            acquired[source.identity_key] = result
            acquisition_results.append(
                {
                    "identity_key": source.identity_key,
                    "status": result.status,
                    "content_sha256": result.manifest.content_sha256,
                    "byte_count": result.manifest.byte_count,
                }
            )
        except Exception as exc:
            acquisition_results.append(
                {
                    "identity_key": source.identity_key,
                    "status": "failed",
                    "error": str(exc),
                }
            )
            blocked_periods.append(source.identity_key)

        # Track peak working bytes
        current_free = shutil.disk_usage(config.raw_root).free
        reduction = baseline_free - current_free
        if reduction > peak_reduction:
            peak_reduction = reduction

    # Canonicalize verified objects and persist immutable partitions.
    snapshots: list[DatasetManifest] = []
    ohlcv_frames: list[pd.DataFrame] = []
    funding_frames: list[pd.DataFrame] = []
    metrics_frames: list[pd.DataFrame] = []
    coverage_reports: list[CoverageReport] = []

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
                ohlcv_frames.append(frame)
            elif source.dataset == SourceDataset.FUNDING:
                frame = canonicalize_funding_zip(
                    acquired_result.path,
                    asset=source.asset,
                    ingested_at=ingested_at,
                )
                funding_frames.append(frame)
            else:
                frame = canonicalize_metrics_zip(
                    acquired_result.path,
                    ingested_at=ingested_at,
                    publication_delay=timedelta(minutes=5),
                )
                metrics_frames.append(frame)
            report = _quality_report(source, frame, config)
            coverage_reports.append(report)
            canonical_path = config.canonical_root / source.relative_path.with_suffix(".parquet")
            content_sha = write_canonical_partition(frame, canonical_path)
            canonical_config = json.dumps(
                {
                    "identity_key": source.identity_key,
                    "raw_sha256": acquired_result.manifest.content_sha256,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
            canonical_manifest = DatasetManifest(
                snapshot_id=(
                    f"canonical-{source.dataset.value}-{content_sha[:16]}-"
                    f"{hashlib.sha256(source.identity_key.encode()).hexdigest()[:12]}"
                ),
                layer=DatasetLayer.CANONICAL,
                name=f"canonical-{source.dataset.value}-{source.interval}",
                content_sha256=content_sha,
                row_count=len(frame),
                min_event_time=frame["event_time"].min(),
                max_event_time=frame["event_time"].max(),
                min_available_time=frame["available_time"].min(),
                max_available_time=frame["available_time"].max(),
                parent_snapshot_ids=[f"raw-{acquired_result.manifest.content_sha256}"],
                config_json=canonical_config,
            )
            catalog.register(canonical_manifest, path=canonical_path)
            if report.blocking:
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

    # Publish only after every required input and quality gate passes.
    if not blocking and ohlcv_frames and funding_frames and metrics_frames:
        ohlcv_combined = pd.concat(ohlcv_frames, ignore_index=True)
        funding_combined = pd.concat(funding_frames, ignore_index=True)
        metrics_combined = pd.concat(metrics_frames, ignore_index=True)
        ohlcv_combined = ohlcv_combined.loc[ohlcv_combined["event_time"] <= config.as_of]
        macro_ohlcv = ohlcv_combined.loc[ohlcv_combined["event_time"] >= config.macro_start]
        micro_ohlcv = ohlcv_combined.loc[ohlcv_combined["event_time"] >= config.micro_start]
        raw_hashes = sorted(result.manifest.content_sha256 for result in acquired.values())
        raw_set_sha = hashlib.sha256("".join(raw_hashes).encode()).hexdigest()
        lineage = (f"raw-set-{raw_set_sha}", *config.parent_snapshot_ids)
        snapshot_config = json.dumps(
            {
                "assets": config.assets,
                "macro_start": config.macro_start.isoformat(),
                "micro_start": config.micro_start.isoformat(),
                "as_of": config.as_of.isoformat(),
                "code_sha": code_sha,
                "plan_hash": plan_hash,
                "raw_set_sha256": raw_set_sha,
            },
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
        build_delay_views(
            metrics_combined,
            delays=config.oi_delay_minutes,
            root=config.research_root,
            parent_snapshot_ids=tuple(s.snapshot_id for s in snapshots),
        )

    # Calculate persistent bytes
    persistent = (
        _directory_size(config.raw_root)
        + _directory_size(config.canonical_root)
        + _directory_size(config.research_root)
        + _directory_size(config.artifact_root)
    )

    status = DualHorizonStatus.BLOCKED if blocking else DualHorizonStatus.PASSED
    acquisition_data: dict[str, object] = {
        "run_id": run_manifest.run_id,
        "status": status.value,
        "plan_hash": plan_hash,
        "planned_objects": len(plan),
        "results": acquisition_results,
        "blocked_periods": blocked_periods,
        "persistent_bytes": persistent,
        "peak_working_bytes": peak_reduction,
    }
    quality_data: dict[str, object] = {
        "run_id": run_manifest.run_id,
        "status": status.value,
        "coverage_reports": [report.model_dump(mode="json") for report in coverage_reports],
        "blocked_periods": blocked_periods,
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
        error_code=None if not blocked_periods else "DATA_PIPELINE_BLOCKED",
        persistent_bytes=persistent,
        peak_working_bytes=peak_reduction,
    )
