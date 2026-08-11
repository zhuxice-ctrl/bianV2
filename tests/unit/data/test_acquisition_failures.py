from datetime import UTC, datetime
from pathlib import Path
from urllib.error import HTTPError

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceGranularity,
    SourceObject,
    build_source_plan,
)
from bian_quant.data.acquisition_failures import classify_acquisition_failure

CONFIG = Path("configs/experiments/dual_horizon_derivatives.yaml")


def _http_404(url: str) -> HTTPError:
    return HTTPError(url, 404, "Not Found", hdrs=None, fp=None)


def _funding_sources(config: DualHorizonAcquisition) -> dict[str, object]:
    """Map ``source_period`` (YYYY-MM) to SourceObject for BTCUSDT monthly Funding."""
    return {
        item.raw_identity.source_period: item
        for item in build_source_plan(config)
        if item.dataset == SourceDataset.FUNDING
        and item.asset == "BTCUSDT"
        and item.granularity.value == "monthly"
    }


def test_cutoff_month_funding_404_is_temporary() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = next(
        item
        for item in build_source_plan(config)
        if item.identity_key == "funding|BTCUSDT|native|monthly|2026-07-01T00:00:00+00:00"
    )
    result = classify_acquisition_failure(source, config, _http_404(source.url))
    assert result.error_code == "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
    assert result.http_status == 404
    assert result.attempt_count == 1
    assert result.temporary


def test_current_and_previous_funding_month_404_are_temporary() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    sources = _funding_sources(config)
    for period in ("2026-06", "2026-07"):
        result = classify_acquisition_failure(
            sources[period], config, _http_404(sources[period].url)
        )
        assert result.error_code == "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
        assert result.temporary is True
        assert result.attempt_count == 1


def test_pre_tail_funding_month_404_is_not_temporary() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    sources = _funding_sources(config)
    result = classify_acquisition_failure(
        sources["2026-05"], config, _http_404(sources["2026-05"].url)
    )
    assert result.error_code == "RAW_DOWNLOAD_FAILED"
    assert not result.temporary


def test_daily_funding_404_is_not_temporary() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = SourceObject(
        dataset=SourceDataset.FUNDING,
        asset="BTCUSDT",
        interval="native",
        granularity=SourceGranularity.DAILY,
        period_start=datetime(2026, 7, 3, tzinfo=UTC),
        url="https://example.com/funding/BTCUSDT/2026-07-03.zip",
        relative_path=Path("funding/BTCUSDT/native/2026-07-03.zip"),
    )
    result = classify_acquisition_failure(source, config, _http_404(source.url))
    assert result.error_code == "RAW_DOWNLOAD_FAILED"
    assert not result.temporary


def test_historical_funding_404_is_required_source_failure() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = next(
        item
        for item in build_source_plan(config)
        if item.identity_key == "funding|BTCUSDT|native|monthly|2025-07-01T00:00:00+00:00"
    )
    result = classify_acquisition_failure(source, config, _http_404(source.url))
    assert result.error_code == "RAW_DOWNLOAD_FAILED"
    assert result.http_status == 404
    assert not result.temporary


def test_local_integrity_code_is_preserved() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    source = build_source_plan(config)[0]
    result = classify_acquisition_failure(
        source,
        config,
        ValueError("RAW_HASH_MISMATCH: stored bytes changed"),
    )
    assert result.error_code == "RAW_HASH_MISMATCH"
    assert result.attempt_count == 0
    assert not result.temporary
