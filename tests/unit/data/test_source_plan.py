"""Tests for the exact source-object plan builder."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from bian_quant.data.acquisition import (
    DualHorizonAcquisition,
    SourceDataset,
    SourceGranularity,
    build_source_plan,
    build_source_plan_audit,
    source_plan_payload,
)
from bian_quant.data.dual_horizon import _source_plan_hash

CONFIG = Path("configs/experiments/dual_horizon_derivatives.yaml")
POPULAR_CONFIG = Path("configs/experiments/popular_universe_100u.yaml")

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


def _popular_config_with_availability(
    tmp_path: Path,
    *,
    apt_month: str = "2022-10",
    sha: str = "a" * 64,
) -> DualHorizonAcquisition:
    """Create a popular-universe config with an availability manifest.

    All assets except APTUSDT have first_available_period at 2021-07-01
    (before macro_start), so no filtering occurs for them.  APTUSDT's
    monthly entries start at *apt_month* and daily entries at the 19th
    of that month, causing pre-listing months to be excluded.
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
            if asset == "APTUSDT":
                if granularity == "monthly":
                    period = f"{apt_month}-01T00:00:00+00:00"
                else:
                    year, mon = apt_month.split("-")
                    period = f"{year}-{mon}-19T00:00:00+00:00"
            else:
                period = "2021-07-01T00:00:00+00:00"
            entries.append(
                {
                    "asset": asset,
                    "dataset": dataset,
                    "granularity": granularity,
                    "first_available_period": period,
                    "evidence_identity_key": (
                        f"{dataset}|{asset}|{interval_label}|{granularity}|{period}"
                    ),
                    "evidence_url": f"https://example.com/{asset}-{dataset}-{granularity}.zip",
                    "evidence_content_sha256": sha,
                    "first_event_time": period,
                }
            )

    manifest_data = {
        "rule_version": "popular-universe-availability-v1",
        "entries": entries,
    }
    manifest_path = tmp_path / "availability.yaml"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
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
        macro_start=datetime(2022, 9, 1, tzinfo=UTC),
        micro_start=datetime(2022, 11, 1, tzinfo=UTC),
        as_of=datetime(2022, 11, 30, 23, 59, 59, 999000, tzinfo=UTC),
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
            "development_start": "2022-09-01T00:00:00Z",
            "development_end_exclusive": "2022-10-01T00:00:00Z",
            "holdout_start": "2022-10-01T00:00:00Z",
            "holdout_end": "2022-11-30T23:59:59.999Z",
            "bh_alpha": 0.05,
            "minimum_inference_samples": 30,
            "max_candidates": 20,
            "cost_bps": [5, 10],
        },
    )


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


# ---------------------------------------------------------------------------
# Availability-aware plan cropping tests
# ---------------------------------------------------------------------------


def test_popular_plan_keeps_first_existing_month_and_excludes_prior_months(
    tmp_path: Path,
) -> None:
    config = _popular_config_with_availability(tmp_path, apt_month="2022-10")
    keys = {item.identity_key for item in build_source_plan(config)}
    assert "ohlcv|APTUSDT|1d|monthly|2022-09-01T00:00:00+00:00" not in keys
    assert "ohlcv|APTUSDT|1d|monthly|2022-10-01T00:00:00+00:00" in keys


def test_three_asset_plan_stays_locked() -> None:
    assert len(build_source_plan(DualHorizonAcquisition.from_yaml(CONFIG))) == 3117


def test_changing_evidence_sha_changes_popular_plan_payload(tmp_path: Path) -> None:
    config_a = _popular_config_with_availability(tmp_path / "a", sha="a" * 64)
    config_b = _popular_config_with_availability(tmp_path / "b", sha="b" * 64)
    payload_a = source_plan_payload(config_a)
    payload_b = source_plan_payload(config_b)
    assert payload_a["availability_manifest_sha256"] != payload_b["availability_manifest_sha256"]


def test_popular_plan_rejects_manifest_missing_a_required_key(tmp_path: Path) -> None:
    config = _popular_config_with_availability(tmp_path)
    manifest_data = yaml.safe_load(config.archive_availability_path.read_text(encoding="utf-8"))
    manifest_data["entries"] = [
        entry
        for entry in manifest_data["entries"]
        if not (
            entry["asset"] == "APTUSDT"
            and entry["dataset"] == "metrics_oi"
            and entry["granularity"] == "daily"
        )
    ]
    config.archive_availability_path.write_text(
        yaml.safe_dump(manifest_data), encoding="utf-8"
    )

    with pytest.raises(ValueError, match="ARCHIVE_AVAILABILITY_MISSING"):
        build_source_plan(config)


def test_actual_plan_hash_includes_availability_manifest_hash(tmp_path: Path) -> None:
    config_a = _popular_config_with_availability(tmp_path / "a", sha="a" * 64)
    config_b = _popular_config_with_availability(tmp_path / "b", sha="b" * 64)
    audit_a = build_source_plan_audit(config_a)
    audit_b = build_source_plan_audit(config_b)

    assert audit_a.objects == audit_b.objects
    assert _source_plan_hash(
        audit_a.objects, availability_manifest_sha256=audit_a.availability_manifest_sha256
    ) != _source_plan_hash(
        audit_b.objects, availability_manifest_sha256=audit_b.availability_manifest_sha256
    )


def test_popular_plan_exclusions_are_audit_only(tmp_path: Path) -> None:
    config = _popular_config_with_availability(tmp_path, apt_month="2022-10")
    audit = build_source_plan_audit(config)
    assert audit.availability_manifest_sha256 is not None
    assert audit.pre_listing_exclusions
    assert {row["reason"] for row in audit.pre_listing_exclusions} == {"PRE_LISTING_EXCLUDED"}
    assert all(row["asset"] == "APTUSDT" for row in audit.pre_listing_exclusions)
