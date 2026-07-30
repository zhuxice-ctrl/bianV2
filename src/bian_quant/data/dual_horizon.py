"""Resumable dual-horizon acquisition and snapshot build orchestrator."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
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
)
from bian_quant.data.canonicalize import (
    canonicalize_funding_zip,
    canonicalize_metrics_zip,
    canonicalize_ohlcv_zip,
)
from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import DatasetManifest
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
        target = config.raw_root / source.relative_path.name
        return download_verified(
            target,
            url=source.url,
            identity=source.raw_identity,
            attempts=config.download_attempts,
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
        payload = fixture_map[source.dataset].read_bytes()
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
        target = config.raw_root / source.relative_path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        return AcquisitionObjectResult(
            status=AcquisitionObjectStatus.DOWNLOADED,
            path=target,
            manifest=manifest,
        )


def _source_plan_hash(plan: tuple[SourceObject, ...]) -> str:
    payload = json.dumps([obj.identity_key for obj in plan], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _directory_size(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


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
        downloader = BinanceDownloader()

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

    # Check disk
    budget = DiskBudget(
        warn_bytes=config.disk_warn_gb * 1024**3,
        block_bytes=config.disk_block_gb * 1024**3,
    )
    disk_status = check_disk_budget(config.raw_root, budget)
    if disk_status == DiskStatus.BLOCKED:
        return DualHorizonResult(
            run_id=run_manifest.run_id,
            status=DualHorizonStatus.BLOCKED,
            snapshots=(),
            acquisition_artifact=config.artifact_root / "data-acquisition.json",
            quality_artifact=config.artifact_root / "data-quality.json",
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
    blocked_periods: list[str] = []

    for source in plan:
        try:
            result = downloader.acquire(source, config)
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
            blocked_periods.append(source.raw_identity.source_period)

        # Track peak working bytes
        current_free = shutil.disk_usage(config.raw_root).free
        reduction = baseline_free - current_free
        if reduction > peak_reduction:
            peak_reduction = reduction

    # Canonicalize and build snapshots
    snapshots: list[DatasetManifest] = []

    # Parse OHLCV
    ohlcv_frames: list[pd.DataFrame] = []
    funding_frames: list[pd.DataFrame] = []
    metrics_frames: list[pd.DataFrame] = []

    for source in plan:
        raw_path = config.raw_root / source.relative_path.name
        if not raw_path.exists():
            continue
        try:
            if source.dataset == SourceDataset.OHLCV:
                frame = canonicalize_ohlcv_zip(
                    raw_path,
                    asset=source.asset,
                    interval=source.interval,
                    ingested_at=datetime.now(UTC),
                )
                ohlcv_frames.append(frame)
            elif source.dataset == SourceDataset.FUNDING:
                frame = canonicalize_funding_zip(
                    raw_path,
                    asset=source.asset,
                    ingested_at=datetime.now(UTC),
                )
                funding_frames.append(frame)
            elif source.dataset == SourceDataset.METRICS_OI:
                from datetime import timedelta

                frame = canonicalize_metrics_zip(
                    raw_path,
                    ingested_at=datetime.now(UTC),
                    publication_delay=timedelta(minutes=5),
                )
                metrics_frames.append(frame)
        except Exception:
            pass

    # Build snapshots if we have data
    if ohlcv_frames:
        ohlcv_combined = pd.concat(ohlcv_frames, ignore_index=True)
        macro_intervals = config.macro_intervals
        macro_snaps = build_macro_snapshots(
            ohlcv_combined,
            None,
            intervals=macro_intervals,
            root=config.research_root,
            catalog=catalog,
        )
        snapshots.extend(macro_snaps)

        micro_intervals = config.micro_intervals
        micro_snaps = build_micro_snapshots(
            ohlcv_combined,
            None,
            None,
            intervals=micro_intervals,
            root=config.research_root,
            catalog=catalog,
        )
        snapshots.extend(micro_snaps)

    # Build delay views for metrics
    if metrics_frames:
        metrics_combined = pd.concat(metrics_frames, ignore_index=True)
        build_delay_views(
            metrics_combined,
            delays=config.oi_delay_minutes,
            root=config.research_root,
            parent_snapshot_ids=tuple(s.snapshot_id for s in snapshots),
        )

    # Write artifacts
    acquisition_artifact = config.artifact_root / "data-acquisition.json"
    quality_artifact = config.artifact_root / "data-quality.json"

    acquisition_data = {
        "run_id": run_manifest.run_id,
        "plan_hash": plan_hash,
        "results": acquisition_results,
        "blocked_periods": blocked_periods,
    }
    acquisition_artifact.write_text(
        json.dumps(acquisition_data, indent=2, default=str), encoding="utf-8"
    )

    quality_data = {
        "run_id": run_manifest.run_id,
        "coverage_reports": [],
        "blocked_periods": blocked_periods,
    }
    quality_artifact.write_text(json.dumps(quality_data, indent=2, default=str), encoding="utf-8")

    # Calculate persistent bytes
    persistent = (
        _directory_size(config.raw_root)
        + _directory_size(config.canonical_root)
        + _directory_size(config.research_root)
        + _directory_size(config.artifact_root)
    )

    # Transition run
    with ExperimentRegistry(registry_path) as registry:
        if blocked_periods and not snapshots:
            registry.transition(run_manifest.run_id, RunStatus.BLOCKED)
            status = DualHorizonStatus.BLOCKED
        else:
            registry.transition(run_manifest.run_id, RunStatus.PASSED)
            status = DualHorizonStatus.PASSED

    return DualHorizonResult(
        run_id=run_manifest.run_id,
        status=status,
        snapshots=tuple(snapshots),
        acquisition_artifact=acquisition_artifact,
        quality_artifact=quality_artifact,
        blocked_periods=tuple(blocked_periods),
        error_code=None if not blocked_periods else "PARTIAL_FAILURE",
        persistent_bytes=persistent,
        peak_working_bytes=peak_reduction,
    )
