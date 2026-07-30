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
    assert len(paths) == len(set(paths)) == 3192
    assert all(not path.is_absolute() for path in paths)
    assert all(path.parts[0] in {"ohlcv", "funding", "metrics_oi"} for path in paths)


def test_partial_month_uses_daily_tail_only() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    july = [
        item
        for item in build_source_plan(config)
        if item.period_start.year == 2026 and item.period_start.month == 7
    ]
    assert july
    assert all(item.granularity == SourceGranularity.DAILY for item in july)
    assert max(item.period_start.day for item in july) == 26


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
