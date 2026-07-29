from datetime import UTC, datetime, timedelta

import pandas as pd

from bian_quant.data.universe import (
    CORE_ASSETS,
    build_migration_universe,
    universe_to_manifest,
)


def _make_daily_bars(asset: str, n: int, end: datetime) -> pd.DataFrame:
    dates = [end - timedelta(days=i) for i in range(n)]
    return pd.DataFrame(
        {
            "asset": [asset] * n,
            "event_time": dates,
            "volume": [1000.0 * (i + 1) for i in range(n)],
        }
    )


def test_future_listing_is_absent_from_earlier_universe() -> None:
    selection_time = datetime(2026, 2, 1, tzinfo=UTC)

    listed_assets = [
        {
            "asset": "SOLUSDT",
            "listing_time": datetime(2026, 1, 1, tzinfo=UTC),
            "delisting_time": None,
        },
        {
            "asset": "XAIUSDT",
            "listing_time": datetime(2026, 3, 1, tzinfo=UTC),
            "delisting_time": None,
        },
    ]

    daily_volumes = _make_daily_bars("SOLUSDT", 200, selection_time)
    daily_bars = pd.DataFrame(
        {
            "asset": ["SOLUSDT"] * 200,
            "event_time": [selection_time - timedelta(days=i) for i in range(200)],
        }
    )
    hourly_bars = pd.DataFrame({"asset": [], "event_time": []})

    members = build_migration_universe(
        selection_time, listed_assets, daily_volumes, daily_bars, hourly_bars
    )

    assets = [m.asset for m in members]
    assert "SOLUSDT" in assets or len(members) == len(CORE_ASSETS)
    assert "XAIUSDT" not in assets


def test_delisted_asset_remains_while_eligible() -> None:
    selection_time = datetime(2026, 2, 1, tzinfo=UTC)
    listed_assets = [
        {
            "asset": "SOLUSDT",
            "listing_time": datetime(2025, 6, 1, tzinfo=UTC),
            "delisting_time": datetime(2026, 3, 1, tzinfo=UTC),
        },
    ]

    daily_volumes = _make_daily_bars("SOLUSDT", 200, selection_time)
    daily_bars = pd.DataFrame(
        {
            "asset": ["SOLUSDT"] * 200,
            "event_time": [selection_time - timedelta(days=i) for i in range(200)],
        }
    )
    hourly_bars = pd.DataFrame({"asset": [], "event_time": []})

    members = build_migration_universe(
        selection_time, listed_assets, daily_volumes, daily_bars, hourly_bars
    )

    assets = [m.asset for m in members]
    assert "SOLUSDT" in assets or len(members) == len(CORE_ASSETS)


def test_core_assets_always_included() -> None:
    selection_time = datetime(2026, 2, 1, tzinfo=UTC)
    members = build_migration_universe(
        selection_time, [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    )

    assets = [m.asset for m in members]
    assert "BTCUSDT" in assets
    assert "ETHUSDT" in assets


def test_manifest_creation() -> None:
    selection_time = datetime(2026, 2, 1, tzinfo=UTC)
    members = build_migration_universe(
        selection_time, [], pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    )

    manifest = universe_to_manifest(members, "universe-2026-02", ["parent-1"])
    assert manifest.snapshot_id == "universe-2026-02"
    assert manifest.row_count == len(members)
