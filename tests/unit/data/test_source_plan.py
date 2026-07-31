"""Tests for the exact source-object plan builder."""

from pathlib import Path

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceGranularity,
    build_source_plan,
    source_plan_payload,
)

CONFIG = Path("configs/experiments/dual_horizon_derivatives.yaml")


def test_source_plan_never_downloads_five_years_of_metrics() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    plan = build_source_plan(config)
    metrics = [item for item in plan if item.dataset == SourceDataset.METRICS_OI]
    assert metrics
    assert min(item.period_start for item in metrics) >= config.micro_start


def test_4h_ohlcv_is_not_requested_twice() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    keys = [item.identity_key for item in build_source_plan(config)]
    assert len(keys) == len(set(keys))


def test_all_raw_targets_are_unique_and_relative_to_raw_root() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    plan = build_source_plan(config)
    paths = [item.relative_path for item in plan]
    assert len(paths) == len(set(paths)) == 3117
    assert all(not path.is_absolute() for path in paths)
    assert all(path.parts[0] in {"ohlcv", "funding", "metrics_oi"} for path in paths)


def test_locked_plan_uses_monthly_funding_tail() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    plan = build_source_plan(config)
    funding = [item for item in plan if item.dataset == SourceDataset.FUNDING]
    cutoff_month = [
        item for item in funding if (item.period_start.year, item.period_start.month) == (2026, 7)
    ]

    assert len(plan) == 3117
    assert len(funding) == 183
    assert all(item.granularity == SourceGranularity.MONTHLY for item in funding)
    assert {item.asset for item in cutoff_month} == {
        "BTCUSDT",
        "ETHUSDT",
        "BNBUSDT",
    }
    assert len(cutoff_month) == 3
    assert not [
        item
        for item in plan
        if item.dataset == SourceDataset.FUNDING and item.granularity == SourceGranularity.DAILY
    ]


def test_locked_plan_counts_are_exact() -> None:
    payload = source_plan_payload(DualHorizonAcquisition.from_yaml(CONFIG))
    assert payload["counts"] == {
        "total": 3117,
        "by_dataset": {"funding": 183, "metrics_oi": 2268, "ohlcv": 666},
        "by_granularity": {"daily": 2502, "monthly": 615},
    }
    assert payload["config_identity"]["funding_tail_strategy"] == (
        "monthly_archive_after_period_close"
    )


def test_partial_month_keeps_only_supported_daily_datasets() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    july = [
        item
        for item in build_source_plan(config)
        if (item.period_start.year, item.period_start.month) == (2026, 7)
    ]
    assert any(
        item.dataset == SourceDataset.FUNDING and item.granularity == SourceGranularity.MONTHLY
        for item in july
    )
    assert all(
        item.granularity == SourceGranularity.DAILY
        for item in july
        if item.dataset != SourceDataset.FUNDING
    )


def test_plan_is_deterministically_sorted() -> None:
    first = build_source_plan(DualHorizonAcquisition.from_yaml(CONFIG))
    second = build_source_plan(DualHorizonAcquisition.from_yaml(CONFIG))
    assert [item.identity_key for item in first] == [item.identity_key for item in second]


def test_source_plan_payload_is_json_safe_and_has_counts() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    payload = source_plan_payload(config)
    import json

    json.dumps(payload)  # must not raise
    assert "counts" in payload
    assert "objects" in payload
    assert payload["counts"]["total"] == len(build_source_plan(config))
    assert payload["counts"]["by_dataset"]["metrics_oi"] > 0
