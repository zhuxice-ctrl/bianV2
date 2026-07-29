from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel

from bian_quant.data.contracts import DatasetLayer, DatasetManifest


class UniverseMember(BaseModel):
    selection_time: datetime
    asset: str
    rank: int
    eligible: bool
    median_volume: float
    rule_version: str


CORE_ASSETS = ["BTCUSDT", "ETHUSDT"]
RULE_VERSION = "v1"
MIN_BARS = 180
MAX_MISSING_PCT = 1.0
MAX_SELECTION = 8
MIN_SELECTION = 5


def _is_excluded(asset: str) -> bool:
    lower = asset.lower()
    stablecoin_pairs = ["usdcusdt", "busdusdt", "tusdusdt", "usdpusdt", "fdusdusdt"]
    leveraged = ["upusdt", "downusdt", "bullusdt", "bearusdt"]
    wrapped = ["wbtcusdt", "cethusdt", "stethusdt"]
    if lower in stablecoin_pairs:
        return True
    for suffix in leveraged:
        if lower.endswith(suffix):
            return True
    return lower in wrapped


def build_migration_universe(
    selection_time: datetime,
    listed_assets: list[dict[str, Any]],
    daily_volumes: pd.DataFrame,
    daily_bars: pd.DataFrame,
    hourly_bars: pd.DataFrame,
) -> list[UniverseMember]:
    if selection_time.tzinfo is None:
        raise ValueError("selection_time must be timezone-aware")

    members: list[UniverseMember] = []

    for asset in CORE_ASSETS:
        members.append(
            UniverseMember(
                selection_time=selection_time,
                asset=asset,
                rank=0,
                eligible=True,
                median_volume=float("inf"),
                rule_version=RULE_VERSION,
            )
        )

    cutoff = selection_time
    trailing_30 = cutoff - timedelta(days=30)

    candidates: list[tuple[str, float]] = []
    for info in listed_assets:
        asset = info["asset"]
        if asset in CORE_ASSETS:
            continue
        if _is_excluded(asset):
            continue
        listing_time = info.get("listing_time")
        delisting_time = info.get("delisting_time")
        if listing_time is not None and listing_time > cutoff:
            continue
        if delisting_time is not None and delisting_time <= cutoff:
            continue

        asset_daily = (
            daily_bars[daily_bars["asset"] == asset]
            if "asset" in daily_bars.columns
            else pd.DataFrame()
        )
        if len(asset_daily) < MIN_BARS:
            continue

        asset_hourly = (
            hourly_bars[hourly_bars["asset"] == asset]
            if "asset" in hourly_bars.columns
            else pd.DataFrame()
        )
        if not asset_hourly.empty:
            trailing = asset_hourly[
                pd.to_datetime(asset_hourly["event_time"], utc=True) >= trailing_30
            ]
            expected_bars = 30 * 24
            if len(trailing) > 0:
                missing_pct = (1 - len(trailing) / expected_bars) * 100
                if missing_pct > MAX_MISSING_PCT:
                    continue

        vol_data = (
            daily_volumes[daily_volumes["asset"] == asset]
            if "asset" in daily_volumes.columns
            else pd.DataFrame()
        )
        if vol_data.empty:
            continue
        trailing_vol = vol_data[pd.to_datetime(vol_data["event_time"], utc=True) >= trailing_30]
        if trailing_vol.empty:
            continue
        median_vol = float(trailing_vol["volume"].median())
        candidates.append((asset, median_vol))

    candidates.sort(key=lambda x: x[1], reverse=True)
    selected = candidates[:MAX_SELECTION]

    if len(selected) < MIN_SELECTION:
        return members

    for rank, (asset, median_vol) in enumerate(selected, start=1):
        members.append(
            UniverseMember(
                selection_time=selection_time,
                asset=asset,
                rank=rank,
                eligible=True,
                median_volume=median_vol,
                rule_version=RULE_VERSION,
            )
        )

    return members


def universe_to_manifest(
    members: list[UniverseMember],
    snapshot_id: str,
    parent_snapshot_ids: list[str],
) -> DatasetManifest:
    return DatasetManifest(
        snapshot_id=snapshot_id,
        layer=DatasetLayer.RESEARCH,
        name="migration_universe",
        content_sha256="0" * 64,
        row_count=len(members),
        min_event_time=min(m.selection_time for m in members) if members else None,
        max_event_time=max(m.selection_time for m in members) if members else None,
        parent_snapshot_ids=parent_snapshot_ids,
        config_json=RULE_VERSION,
    )
