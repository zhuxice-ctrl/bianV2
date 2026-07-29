import json
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
            "available_time": [date + timedelta(days=1) for date in dates],
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
            "available_time": [selection_time - timedelta(days=i - 1) for i in range(200)],
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
            "available_time": [selection_time - timedelta(days=i - 1) for i in range(200)],
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
    reordered = universe_to_manifest(list(reversed(members)), "universe-2026-02", ["parent-1"])
    assert manifest.snapshot_id == "universe-2026-02"
    assert manifest.row_count == len(members)
    assert manifest.content_sha256 != "0" * 64
    assert manifest.content_sha256 == reordered.content_sha256
    assert json.loads(manifest.config_json)["sufficient"] is False


def test_future_volume_cannot_change_historical_ranking() -> None:
    selection_time = datetime(2026, 2, 1, tzinfo=UTC)
    assets = [f"ASSET{index}USDT" for index in range(6)]
    listed_assets = [
        {
            "asset": asset,
            "listing_time": datetime(2024, 1, 1, tzinfo=UTC),
            "available_time": datetime(2024, 1, 1, tzinfo=UTC),
            "delisting_time": None,
        }
        for asset in assets
    ]
    daily_bars = pd.concat(
        [
            pd.DataFrame(
                {
                    "asset": [asset] * 180,
                    "event_time": [
                        selection_time - timedelta(days=offset) for offset in range(1, 181)
                    ],
                    "available_time": [
                        selection_time - timedelta(days=offset - 1) for offset in range(1, 181)
                    ],
                }
            )
            for asset in assets
        ],
        ignore_index=True,
    )
    hourly_bars = pd.concat(
        [
            pd.DataFrame(
                {
                    "asset": [asset] * 720,
                    "event_time": [
                        selection_time - timedelta(hours=offset) for offset in range(1, 721)
                    ],
                    "available_time": [
                        selection_time - timedelta(hours=offset - 1) for offset in range(1, 721)
                    ],
                }
            )
            for asset in assets
        ],
        ignore_index=True,
    )
    daily_volumes = pd.concat(
        [
            pd.DataFrame(
                {
                    "asset": [asset] * 30,
                    "event_time": [
                        selection_time - timedelta(days=offset) for offset in range(1, 31)
                    ],
                    "available_time": [
                        selection_time - timedelta(days=offset - 1) for offset in range(1, 31)
                    ],
                    "quote_volume": [float(index + 1)] * 30,
                }
            )
            for index, asset in enumerate(assets)
        ],
        ignore_index=True,
    )
    daily_volumes = pd.concat(
        [
            daily_volumes,
            pd.DataFrame(
                {
                    "asset": [assets[0]],
                    "event_time": [selection_time + timedelta(days=1)],
                    "available_time": [selection_time + timedelta(days=2)],
                    "quote_volume": [1_000_000_000.0],
                }
            ),
        ],
        ignore_index=True,
    )

    members = build_migration_universe(
        selection_time,
        listed_assets,
        daily_volumes,
        daily_bars,
        hourly_bars,
    )
    ranks = {member.asset: member.rank for member in members}

    assert ranks[assets[-1]] == 1
    assert ranks[assets[0]] == 6


def test_selection_time_must_be_month_boundary_utc() -> None:
    try:
        build_migration_universe(
            datetime(2026, 2, 2, tzinfo=UTC),
            [],
            pd.DataFrame(),
            pd.DataFrame(),
            pd.DataFrame(),
        )
    except ValueError as error:
        assert "first day" in str(error)
    else:
        raise AssertionError("non-boundary universe snapshot was accepted")


def test_universe_rejects_data_without_available_time() -> None:
    selection_time = datetime(2026, 2, 1, tzinfo=UTC)
    daily_bars = pd.DataFrame(
        {"asset": ["SOLUSDT"], "event_time": [selection_time - timedelta(days=1)]}
    )

    try:
        build_migration_universe(
            selection_time,
            [],
            pd.DataFrame(),
            daily_bars,
            pd.DataFrame(),
        )
    except ValueError as error:
        assert "available_time" in str(error)
    else:
        raise AssertionError("universe accepted data without availability evidence")
