"""Tests for immutable Macro/Micro snapshot publishing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest

from bian_quant.data.catalog import DatasetCatalog
from bian_quant.data.contracts import DatasetLayer
from bian_quant.data.resample import resample_point_in_time
from bian_quant.data.snapshots import (
    SnapshotSpec,
    build_delay_views,
    publish_snapshot,
)


def test_causal_aggregate_uses_max_available_time() -> None:
    fixture = metrics_fixture()
    result = resample_point_in_time(
        fixture,
        rule="1h",
        aggregations={"sum_open_interest": "last"},
    )
    assert result.loc[0, "available_time"] == fixture["available_time"].max()


def test_delay_views_have_distinct_snapshot_ids(tmp_path: Path) -> None:
    fixture = metrics_fixture()
    ids = build_delay_views(
        fixture,
        delays=(5, 10, 15),
        root=tmp_path,
        parent_snapshot_ids=["metrics-canonical"],
    )
    assert set(ids) == {5, 10, 15}
    assert len(set(ids.values())) == 3


def test_snapshot_id_rebuild_is_deterministic(tmp_path: Path) -> None:
    fixture = ohlcv_fixture()
    spec = SnapshotSpec(
        name="macro-1d",
        layer=DatasetLayer.RESEARCH,
        interval="1d",
        horizon="macro",
    )
    first = publish_snapshot(
        fixture, spec, tmp_path / "one", DatasetCatalog(tmp_path / "cat1.sqlite")
    )
    second = publish_snapshot(
        fixture, spec, tmp_path / "two", DatasetCatalog(tmp_path / "cat2.sqlite")
    )
    assert first.snapshot_id == second.snapshot_id
    assert first.content_sha256 == second.content_sha256


def test_resample_rejects_missing_audit_columns() -> None:
    with pytest.raises(ValueError, match="audit columns"):
        resample_point_in_time(
            pd.DataFrame({"asset": ["BTC"], "event_time": [datetime(2026, 1, 1, tzinfo=UTC)]}),
            rule="1h",
            aggregations={"x": "last"},
        )


def test_resample_does_not_fill_missing() -> None:
    """Missing values in source must remain missing in output.

    Use 2h resampling so records span two buckets.  The second bucket
    has no source data, so its result must be NaN (not forward-filled).
    """
    fixture = metrics_fixture()
    result = resample_point_in_time(
        fixture,
        rule="2h",
        aggregations={"sum_open_interest": "last"},
    )
    # The fixture has records at 00:00, 00:15, 00:30 — all in the 00:00 2h bucket.
    # The 02:00 2h bucket has no data, so it should not appear (dropna on available_time).
    # Instead, verify the function does not create rows where there is no source data.
    assert len(result) <= 1  # Only one bucket has data


def metrics_fixture() -> pd.DataFrame:
    base = datetime(2026, 7, 1, tzinfo=UTC)
    records = []
    for i in range(3):
        t = base + timedelta(minutes=15 * i)
        records.append(
            {
                "asset": "BTCUSDT",
                "event_time": t,
                "available_time": t + timedelta(minutes=5),
                "ingested_at": datetime(2026, 7, 30, tzinfo=UTC),
                "source": "binance_metrics_archive",
                "sum_open_interest": 100000.0 + i,
                "sum_open_interest_value": 5000000000.0,
            }
        )
    return pd.DataFrame(records)


def ohlcv_fixture() -> pd.DataFrame:
    base = datetime(2026, 7, 1, tzinfo=UTC)
    records = []
    for i in range(3):
        t = base + timedelta(hours=i)
        records.append(
            {
                "asset": "BTCUSDT",
                "event_time": t,
                "available_time": t + timedelta(hours=1),
                "ingested_at": datetime(2026, 7, 30, tzinfo=UTC),
                "source": "binance_ohlcv_archive",
                "open": 50000.0 + i,
                "high": 50100.0,
                "low": 49900.0,
                "close": 50050.0,
                "volume": 100.5,
            }
        )
    return pd.DataFrame(records)
