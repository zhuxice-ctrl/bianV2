"""Data-contract tests for the causal Funding-alignment adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from bian_quant.data.funding_alignment import (
    FundingAlignmentRecord,
    build_daily_funding_alignment,
    latest_alignment_through,
)

_SHA = "a" * 64


def _record(**overrides: object) -> FundingAlignmentRecord:
    base: dict[str, object] = {
        "decision_time": datetime(2026, 1, 2, tzinfo=UTC),
        "available_time": datetime(2026, 1, 2, tzinfo=UTC),
        "member_count": 12,
        "positive_rate_share": 0.5,
        "median_rate": 0.0001,
        "coverage_ratio": 1.0,
        "source_sha256": _SHA,
    }
    base.update(overrides)
    return FundingAlignmentRecord(**base)  # type: ignore[arg-type]


def test_record_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError):
        _record(decision_time=datetime(2026, 1, 2))


def test_record_rejects_available_after_decision() -> None:
    with pytest.raises(ValueError):
        _record(
            decision_time=datetime(2026, 1, 2, tzinfo=UTC),
            available_time=datetime(2026, 1, 3, tzinfo=UTC),
        )


def test_record_rejects_out_of_range_shares() -> None:
    with pytest.raises(ValueError):
        _record(positive_rate_share=1.5)
    with pytest.raises(ValueError):
        _record(coverage_ratio=-0.1)


def test_record_rejects_negative_member_count() -> None:
    with pytest.raises(ValueError):
        _record(member_count=-1)


def test_record_rejects_bad_source_sha() -> None:
    with pytest.raises(ValueError):
        _record(source_sha256="XYZ")
    with pytest.raises(ValueError):
        _record(source_sha256="A" * 64)  # uppercase rejected


def _write_funding_parquet(
    canonical_root: Path,
    asset: str,
    rows: list[dict[str, object]],
) -> None:
    native = canonical_root / "plan=test" / "funding" / asset / "native"
    native.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(rows)
    month = pd.Timestamp(rows[0]["event_time"]).strftime("%Y-%m")
    frame.to_parquet(native / f"{month}.parquet", index=False)


def test_loader_excludes_future_available_time(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    as_of = datetime(2026, 1, 2, 0, 0, tzinfo=UTC)
    early = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    future = datetime(2026, 1, 3, 8, 0, tzinfo=UTC)

    rows = [
        {
            "asset": "ETHUSDT",
            "event_time": early,
            "available_time": early,
            "funding_rate": 0.0001,
        },
        {
            "asset": "ETHUSDT",
            "event_time": future,
            "available_time": future,
            "funding_rate": -0.0002,
        },
    ]
    _write_funding_parquet(canonical, "ETHUSDT", rows)

    records = build_daily_funding_alignment(canonical, assets=("ETHUSDT",), as_of=as_of)
    # The future (Jan 3) record must be excluded; only the Jan 1 record remains.
    assert len(records) == 1
    only = records[0]
    assert only.available_time <= as_of
    assert only.member_count == 1
    assert only.coverage_ratio == 1.0
    assert only.positive_rate_share == 1.0
    assert len(only.source_sha256) == 64


def test_loader_aggregates_multiple_assets(tmp_path: Path) -> None:
    canonical = tmp_path / "canonical"
    as_of = datetime(2026, 1, 1, 23, 59, tzinfo=UTC)
    moment = datetime(2026, 1, 1, 8, 0, tzinfo=UTC)
    _write_funding_parquet(
        canonical,
        "ETHUSDT",
        [
            {
                "asset": "ETHUSDT",
                "event_time": moment,
                "available_time": moment,
                "funding_rate": 0.0001,
            }
        ],
    )
    _write_funding_parquet(
        canonical,
        "BTCUSDT",
        [
            {
                "asset": "BTCUSDT",
                "event_time": moment,
                "available_time": moment,
                "funding_rate": -0.0002,
            }
        ],
    )

    records = build_daily_funding_alignment(canonical, assets=("ETHUSDT", "BTCUSDT"), as_of=as_of)
    assert len(records) == 1
    record = records[0]
    assert record.member_count == 2
    assert record.coverage_ratio == 1.0
    assert record.positive_rate_share == 0.5  # one positive of two
    assert record.median_rate == pytest.approx(-0.00005)


def test_loader_missing_root_returns_empty(tmp_path: Path) -> None:
    records = build_daily_funding_alignment(
        tmp_path / "missing", assets=("ETHUSDT",), as_of=datetime(2026, 1, 1, tzinfo=UTC)
    )
    assert records == ()


def test_latest_alignment_through_filters_causally() -> None:
    r1 = _record(
        decision_time=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
        available_time=datetime(2026, 1, 1, 8, 0, tzinfo=UTC),
    )
    r2 = _record(
        decision_time=datetime(2026, 1, 2, 8, 0, tzinfo=UTC),
        available_time=datetime(2026, 1, 2, 8, 0, tzinfo=UTC),
    )
    decision = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
    assert latest_alignment_through((r1, r2), decision) is r1
    assert latest_alignment_through((r1, r2), datetime(2020, 1, 1, tzinfo=UTC)) is None
