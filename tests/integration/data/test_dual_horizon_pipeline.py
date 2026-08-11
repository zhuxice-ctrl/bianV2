"""Offline integration tests for the dual-horizon pipeline."""

from __future__ import annotations

import hashlib
import io
import json
import shutil
import threading
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

import yaml

from bian_quant.data.acquisition import (
    DiskStatus,
    DualHorizonAcquisition,
    SourceDataset,
    build_source_plan,
)
from bian_quant.data.dual_horizon import (
    DualHorizonStatus,
    FixtureDownloader,
    prepare_dual_horizon,
)

POPULAR_ASSETS = (
    "ADAUSDT",
    "APTUSDT",
    "AVAXUSDT",
    "BCHUSDT",
    "BNBUSDT",
    "BTCUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "NEARUSDT",
    "SOLUSDT",
    "SUIUSDT",
    "TONUSDT",
    "TRXUSDT",
    "XRPUSDT",
)

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "binance"


def _miniature_config(tmp_path: Path) -> DualHorizonAcquisition:
    return DualHorizonAcquisition(
        assets=("BTCUSDT", "ETHUSDT", "BNBUSDT"),
        macro_start=datetime(2026, 7, 1, tzinfo=UTC),
        micro_start=datetime(2026, 7, 1, tzinfo=UTC),
        as_of=datetime(2026, 7, 3, 23, 59, 59, 999000, tzinfo=UTC),
        macro_intervals=("1d", "4h"),
        micro_intervals=("1h", "4h"),
        oi_delay_minutes=(5, 10, 15),
        funding_tail_strategy="monthly_archive_after_period_close",
        parent_snapshot_ids=(),
        raw_root=tmp_path / "raw",
        canonical_root=tmp_path / "canonical",
        research_root=tmp_path / "research",
        artifact_root=tmp_path / "artifacts",
        catalog_path=tmp_path / "catalog.sqlite",
        experiment_registry_path=tmp_path / "experiments.sqlite",
        factor_registry_path=tmp_path / "factors.sqlite",
        download_attempts=1,
        max_workers=1,
        disk_warn_gb=10,
        disk_block_gb=5,
        coverage={"ohlcv": 0.01, "funding": 0.01, "metrics_oi": 0.01},
        factor_protocol={
            "primary_interval": "4h",
            "sensitivity_interval": "1h",
            "development_months": 18,
            "holdout_months": 6,
            "development_start": "2026-07-01T00:00:00Z",
            "development_end_exclusive": "2026-07-02T00:00:00Z",
            "holdout_start": "2026-07-03T00:00:00Z",
            "holdout_end": "2026-07-03T23:59:59.999Z",
            "bh_alpha": 0.05,
            "minimum_inference_samples": 30,
            "max_candidates": 20,
            "cost_bps": [5, 10],
        },
    )


def test_offline_pipeline_builds_cataloged_macro_and_micro_snapshots(tmp_path: Path) -> None:
    config = _miniature_config(tmp_path)
    result = prepare_dual_horizon(
        config,
        code_sha="a" * 40,
        downloader=FixtureDownloader(FIXTURES),
    )
    assert result.status == DualHorizonStatus.PASSED
    assert result.blocked_periods == ()
    assert {snapshot.name for snapshot in result.snapshots} == {
        "macro-1d",
        "macro-4h",
        "micro-1h",
        "micro-4h",
    }
    quality = json.loads(result.quality_artifact.read_text(encoding="utf-8"))
    assert quality["coverage_reports"]
    acquisition = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    assert acquisition["funding_tail_strategy"] == ("monthly_archive_after_period_close")
    assert acquisition["cutoff_evidence"] == quality["cutoff_evidence"]
    assert all(item["asset"] for item in quality["coverage_reports"])
    assert all(item["identity_key"] for item in quality["coverage_reports"])
    assert any(
        item["dataset"] == "funding" and item["post_cutoff_rows_excluded"] > 0
        for item in acquisition["cutoff_evidence"]
    )
    assert all(manifest.max_event_time <= config.as_of for manifest in result.snapshots)
    assert all(manifest.max_available_time <= config.as_of for manifest in result.snapshots)

    resumed = prepare_dual_horizon(
        config,
        code_sha="a" * 40,
        downloader=FixtureDownloader(FIXTURES),
    )
    assert resumed.status == DualHorizonStatus.PASSED
    assert [snapshot.snapshot_id for snapshot in resumed.snapshots] == [
        snapshot.snapshot_id for snapshot in result.snapshots
    ]
    acquisition = json.loads(resumed.acquisition_artifact.read_text(encoding="utf-8"))
    assert {item["status"] for item in acquisition["results"]} == {"skipped"}


def test_local_only_pipeline_blocks_with_exact_missing_objects(tmp_path: Path) -> None:
    config = _miniature_config(tmp_path)
    result = prepare_dual_horizon(config, code_sha="b" * 40)
    assert result.status == DualHorizonStatus.BLOCKED
    assert result.snapshots == ()
    assert len(result.blocked_periods) == 39
    payload = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    assert payload["planned_objects"] == 39
    assert len([item for item in payload["results"] if item["status"] == "failed"]) == 39
    assert payload["partial_availability_exclusions"] == []
    assert payload["partial_availability_exclusion_sha256"] == hashlib.sha256(b"[]").hexdigest()


def test_disk_block_keeps_partial_exclusion_hash_null(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "bian_quant.data.dual_horizon.check_disk_budget",
        lambda *_args, **_kwargs: DiskStatus.BLOCKED,
    )
    result = prepare_dual_horizon(_miniature_config(tmp_path), code_sha="z" * 40)
    payload = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    assert result.status == DualHorizonStatus.BLOCKED
    assert payload["partial_availability_exclusion_sha256"] is None


def test_acquisition_honors_locked_worker_bound_and_persists_plan_order(
    tmp_path: Path,
    monkeypatch,
) -> None:
    config = _miniature_config(tmp_path).model_copy(update={"max_workers": 4})
    first_identity = build_source_plan(config)[0].identity_key
    inner = FixtureDownloader(FIXTURES)
    lock = threading.Lock()
    first_started = threading.Event()
    later_completed = threading.Event()
    later_completion_sampled = threading.Event()
    first_observed_completion_sample = False
    active = 0
    peak = 0
    real_disk_usage = shutil.disk_usage

    def recording_disk_usage(path):
        usage = real_disk_usage(path)
        if later_completed.is_set():
            later_completion_sampled.set()
        return usage

    monkeypatch.setattr("bian_quant.data.dual_horizon.shutil.disk_usage", recording_disk_usage)

    class RecordingDownloader:
        def acquire(self, source, current_config):
            nonlocal active, first_observed_completion_sample, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                if source.identity_key == first_identity:
                    first_started.set()
                    first_observed_completion_sample = later_completion_sampled.wait(timeout=5)
                    return inner.acquire(source, current_config)
                assert first_started.wait(timeout=5)
                time.sleep(0.01)
                result = inner.acquire(source, current_config)
                later_completed.set()
                return result
            finally:
                with lock:
                    active -= 1

    result = prepare_dual_horizon(
        config,
        code_sha="c" * 40,
        downloader=RecordingDownloader(),
    )
    assert result.status == DualHorizonStatus.PASSED
    assert 1 < peak <= config.max_workers
    assert first_observed_completion_sample
    payload = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    identity_keys = [item["identity_key"] for item in payload["results"]]
    assert identity_keys == sorted(identity_keys)


def test_worker_bound_parse_failure_is_blocked_and_persists_sorted_results(
    tmp_path: Path,
) -> None:
    config = _miniature_config(tmp_path).model_copy(update={"max_workers": 4})
    failed_identity = build_source_plan(config)[0].identity_key
    inner = FixtureDownloader(FIXTURES)
    lock = threading.Lock()
    active = 0
    peak = 0

    class ParseFailingDownloader:
        def acquire(self, source, current_config):
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            try:
                time.sleep(0.01)
                result = inner.acquire(source, current_config)
                if source.identity_key == failed_identity:
                    result.path.write_bytes(b"not-a-zip")
                return result
            finally:
                with lock:
                    active -= 1

    result = prepare_dual_horizon(
        config,
        code_sha="d" * 40,
        downloader=ParseFailingDownloader(),
    )
    assert result.status == DualHorizonStatus.BLOCKED
    assert result.blocked_periods == (failed_identity,)
    assert 1 < peak <= config.max_workers

    payload = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    assert payload["status"] == DualHorizonStatus.BLOCKED.value
    assert payload["blocked_periods"] == [failed_identity]
    result_keys = [(item["identity_key"], item["status"]) for item in payload["results"]]
    assert result_keys == sorted(result_keys)
    failed_results = [
        item for item in payload["results"] if item["identity_key"] == failed_identity
    ]
    assert [item["status"] for item in failed_results] == ["downloaded", "parse_failed"]


def test_cutoff_month_funding_404_persists_temporary_error(tmp_path: Path) -> None:
    config = _miniature_config(tmp_path)
    inner = FixtureDownloader(FIXTURES)

    class TailUnavailableDownloader:
        def acquire(self, source, current_config):
            if (
                source.dataset.value == "funding"
                and source.period_start.month == current_config.as_of.month
            ):
                raise HTTPError(source.url, 404, "Not Found", hdrs=None, fp=None)
            return inner.acquire(source, current_config)

    result = prepare_dual_horizon(
        config,
        code_sha="e" * 40,
        downloader=TailUnavailableDownloader(),
    )
    assert result.status == DualHorizonStatus.BLOCKED
    assert result.error_code == "DATA_PIPELINE_BLOCKED"
    payload = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    failed = [item for item in payload["results"] if item["status"] == "failed"]
    assert len(failed) == 3
    assert {item["error_code"] for item in failed} == {"FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"}
    assert all(item["http_status"] == 404 for item in failed)
    assert all(item["attempt_count"] == 1 for item in failed)
    assert all(item["temporary"] is True for item in failed)
    assert result.snapshots == ()
    # Ordinary runs retain the legacy fail-closed behavior, even for a
    # temporary registered Funding-tail archive failure.
    assert payload["partial_availability_exclusions"] == []
    assert payload["partial_availability_exclusion_sha256"] == hashlib.sha256(b"[]").hexdigest()
    assert len(payload["blocked_periods"]) == 3
    assert all(key.startswith("funding|") for key in payload["blocked_periods"])


# ---------------------------------------------------------------------------
# Availability-aware pipeline tests
# ---------------------------------------------------------------------------


def _miniature_popular_config_with_availability(tmp_path: Path) -> DualHorizonAcquisition:
    """Create a 16-asset popular-universe config with an availability manifest.

    APTUSDT daily entries start on 2026-07-02 so that July 1st daily objects
    are pre-listing excluded.  All other entries start at 2020-01-01.
    """
    entries: list[dict[str, str]] = []
    for asset in POPULAR_ASSETS:
        for dataset, granularity in (
            ("ohlcv", "monthly"),
            ("ohlcv", "daily"),
            ("funding", "monthly"),
            ("metrics_oi", "daily"),
        ):
            interval_label = "1d" if dataset == "ohlcv" else "native"
            if asset == "APTUSDT" and granularity == "daily":
                period = "2026-07-02T00:00:00+00:00"
            else:
                period = "2020-01-01T00:00:00+00:00"
            entries.append(
                {
                    "asset": asset,
                    "dataset": dataset,
                    "granularity": granularity,
                    "first_available_period": period,
                    "evidence_identity_key": (
                        f"{dataset}|{asset}|{interval_label}|{granularity}|{period}"
                    ),
                    "evidence_url": f"https://example.com/{asset}-{dataset}.zip",
                    "evidence_content_sha256": "a" * 64,
                    "first_event_time": period,
                }
            )

    manifest_data = {
        "rule_version": "popular-universe-availability-v1",
        "entries": entries,
    }
    manifest_path = tmp_path / "availability.yaml"
    manifest_path.write_text(yaml.safe_dump(manifest_data), encoding="utf-8")

    return DualHorizonAcquisition(
        assets=POPULAR_ASSETS,
        universe_policy={
            "rule_version": "popular-usdm-v1",
            "minimum_listing_days": 180,
            "trailing_days": 30,
            "max_selected": 12,
            "min_selected": 8,
            "seed_assets": list(POPULAR_ASSETS),
        },
        macro_start=datetime(2026, 7, 1, tzinfo=UTC),
        # The first selector runs at micro_start.  Same-day fixture rows are
        # safely visible by this end-of-day cutoff, while future rows remain
        # excluded by point-in-time filtering.
        micro_start=datetime(2026, 7, 1, 23, 59, 59, 999000, tzinfo=UTC),
        as_of=datetime(2026, 7, 3, 23, 59, 59, 999000, tzinfo=UTC),
        macro_intervals=("1d", "4h"),
        micro_intervals=("1h", "4h"),
        oi_delay_minutes=(5, 10, 15),
        funding_tail_strategy="monthly_archive_after_period_close",
        parent_snapshot_ids=(),
        raw_root=tmp_path / "raw",
        canonical_root=tmp_path / "canonical",
        research_root=tmp_path / "research",
        artifact_root=tmp_path / "artifacts",
        catalog_path=tmp_path / "catalog.sqlite",
        experiment_registry_path=tmp_path / "experiments.sqlite",
        factor_registry_path=tmp_path / "factors.sqlite",
        archive_availability_path=manifest_path,
        download_attempts=1,
        max_workers=1,
        disk_warn_gb=10,
        disk_block_gb=5,
        coverage={"ohlcv": 0.01, "funding": 0.01, "metrics_oi": 0.01},
        factor_protocol={
            "primary_interval": "4h",
            "sensitivity_interval": "1h",
            "development_months": 18,
            "holdout_months": 6,
            "development_start": "2026-07-01T00:00:00Z",
            "development_end_exclusive": "2026-07-02T00:00:00Z",
            "holdout_start": "2026-07-03T00:00:00Z",
            "holdout_end": "2026-07-03T23:59:59.999Z",
            "bh_alpha": 0.05,
            "minimum_inference_samples": 30,
            "max_candidates": 20,
            "cost_bps": [5, 10],
        },
    )


def test_artifacts_persist_manifest_hash_and_exclusions(tmp_path: Path) -> None:
    result = prepare_dual_horizon(
        _miniature_popular_config_with_availability(tmp_path),
        code_sha="a" * 40,
        downloader=FixtureDownloader(FIXTURES),
    )
    artifact = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    assert artifact["availability_manifest_sha256"]
    assert {row["reason"] for row in artifact["pre_listing_exclusions"]} == {"PRE_LISTING_EXCLUDED"}
    quality = json.loads(result.quality_artifact.read_text(encoding="utf-8"))
    assert quality["availability_manifest_sha256"]


class PostBoundary404Downloader:
    """Fail the first post-boundary OHLCV object with a 404."""

    def __init__(self) -> None:
        self._inner = FixtureDownloader(FIXTURES)
        self._failed = False

    def acquire(self, source, config):
        if not self._failed and source.dataset == SourceDataset.OHLCV:
            self._failed = True
            raise HTTPError(source.url, 404, "Not Found", hdrs=None, fp=None)
        return self._inner.acquire(source, config)


def test_post_boundary_404_remains_blocking(tmp_path: Path) -> None:
    result = prepare_dual_horizon(
        _miniature_popular_config_with_availability(tmp_path),
        code_sha="b" * 40,
        downloader=PostBoundary404Downloader(),
    )
    assert result.status == DualHorizonStatus.BLOCKED


# ---------------------------------------------------------------------------
# Partial availability pipeline tests
# ---------------------------------------------------------------------------


def _popular_config_with_tail_gap(tmp_path: Path) -> DualHorizonAcquisition:
    """Popular config with relaxed policy for partial-availability testing."""
    config = _miniature_popular_config_with_availability(tmp_path)
    return config.model_copy(
        update={
            "universe_policy": config.universe_policy.model_copy(
                update={
                    "minimum_listing_days": 0,
                    "trailing_days": 1,
                }
            ),
        }
    )


class TailGapDownloader:
    """Delegate to FixtureDownloader but 404 TONUSDT monthly Funding in the tail."""

    def __init__(self) -> None:
        self._inner = FixtureDownloader(FIXTURES)

    def acquire(self, source, config):
        if (
            source.dataset == SourceDataset.FUNDING
            and source.granularity.value == "monthly"
            and source.asset == "TONUSDT"
        ):
            raise HTTPError(source.url, 404, "Not Found", hdrs=None, fp=None)
        return self._inner.acquire(source, config)


def test_partial_funding_tail_passes_with_enough_assets(tmp_path: Path) -> None:
    config = _popular_config_with_tail_gap(tmp_path)
    result = prepare_dual_horizon(
        config,
        code_sha="f" * 40,
        downloader=TailGapDownloader(),
    )
    assert result.status == DualHorizonStatus.PASSED
    assert result.blocked_periods == ()
    assert result.snapshots

    acquisition = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    quality = json.loads(result.quality_artifact.read_text(encoding="utf-8"))

    assert {row["reason"] for row in acquisition["partial_availability_exclusions"]} == {
        "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE"
    }
    assert (
        acquisition["partial_availability_exclusions"]
        == quality["partial_availability_exclusions"]
    )
    assert acquisition["partial_availability_impact"]["affected_periods"] > 0
    assert (
        acquisition["partial_availability_impact"] == quality["partial_availability_impact"]
    )
    assert acquisition["partial_availability_exclusion_sha256"]
    assert (
        acquisition["partial_availability_exclusion_sha256"]
        == quality["partial_availability_exclusion_sha256"]
    )
    assert acquisition["popular_universe_artifacts"][0]["selection_time"] == (
        config.micro_start.isoformat()
    )


class DuplicateTailFundingDownloader:
    """Inject a duplicate into one popular-universe Funding tail archive."""

    def __init__(self) -> None:
        self._inner = FixtureDownloader(FIXTURES)
        self._corrupted = False

    def acquire(self, source, config):
        result = self._inner.acquire(source, config)
        if (
            not self._corrupted
            and source.dataset == SourceDataset.FUNDING
            and source.granularity.value == "monthly"
            and source.asset == "BTCUSDT"
        ):
            with zipfile.ZipFile(result.path) as archive:
                member = archive.namelist()[0]
                rows = archive.read(member).decode("utf-8").splitlines()
            rows.append(rows[1])
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(member, "\n".join(rows) + "\n")
            result.path.write_bytes(payload.getvalue())
            self._corrupted = True
        return result


class SparseTailFundingDownloader:
    """Inject a clean but coverage-incomplete popular Funding tail archive."""

    def __init__(self) -> None:
        self._inner = FixtureDownloader(FIXTURES)
        self._corrupted = False

    def acquire(self, source, config):
        result = self._inner.acquire(source, config)
        if (
            not self._corrupted
            and source.dataset == SourceDataset.FUNDING
            and source.granularity.value == "monthly"
            and source.asset == "BTCUSDT"
        ):
            with zipfile.ZipFile(result.path) as archive:
                member = archive.namelist()[0]
                rows = archive.read(member).decode("utf-8").splitlines()
            payload = io.BytesIO()
            with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(member, "\n".join(rows[:2]) + "\n")
            result.path.write_bytes(payload.getvalue())
            self._corrupted = True
        return result


def test_popular_clean_tail_coverage_gap_is_partial_availability(tmp_path: Path) -> None:
    config = _popular_config_with_tail_gap(tmp_path)
    config = config.model_copy(
        update={"coverage": config.coverage.model_copy(update={"funding": 0.02})}
    )
    result = prepare_dual_horizon(
        config,
        code_sha="i" * 40,
        downloader=SparseTailFundingDownloader(),
    )
    assert result.status == DualHorizonStatus.PASSED
    acquisition = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    assert acquisition["partial_availability_exclusions"] == [
        {
            "asset": "BTCUSDT",
            "dataset": "funding",
            "error_code": "FUNDING_TAIL_COVERAGE_INCOMPLETE",
            "granularity": "monthly",
            "identity_key": "funding|BTCUSDT|native|monthly|2026-07-01T00:00:00+00:00",
            "period": "2026-07",
            "reason": "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE",
            "temporary": True,
        }
    ]


def test_popular_tail_duplicate_is_a_hard_block_not_partial_availability(tmp_path: Path) -> None:
    config = _popular_config_with_tail_gap(tmp_path)
    result = prepare_dual_horizon(
        config,
        code_sha="h" * 40,
        downloader=DuplicateTailFundingDownloader(),
    )
    assert result.status == DualHorizonStatus.BLOCKED
    assert result.snapshots == ()

    acquisition = json.loads(result.acquisition_artifact.read_text(encoding="utf-8"))
    assert any("funding|BTCUSDT|native|monthly" in key for key in result.blocked_periods)
    assert acquisition["partial_availability_exclusions"] == []
    assert acquisition["partial_availability_exclusion_sha256"] == hashlib.sha256(b"[]").hexdigest()


def test_partial_funding_tail_blocks_when_min_selected_too_high(tmp_path: Path) -> None:
    config = _popular_config_with_tail_gap(tmp_path)
    config = config.model_copy(
        update={
            "universe_policy": config.universe_policy.model_copy(
                update={
                    "min_selected": 16,
                    "max_selected": 16,
                }
            ),
        }
    )
    result = prepare_dual_horizon(
        config,
        code_sha="g" * 40,
        downloader=TailGapDownloader(),
    )
    assert result.status == DualHorizonStatus.BLOCKED
    assert any(
        key.startswith("popular-universe|") for key in result.blocked_periods
    )
    assert result.snapshots == ()
