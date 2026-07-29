import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

import pandas as pd
from pydantic import BaseModel

from bian_quant.data.contracts import DatasetLayer, DatasetManifest


class UniverseMember(BaseModel):
    model_config = {"frozen": True}

    selection_time: datetime
    asset: str
    rank: int
    eligible: bool
    median_volume: float | None
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
    if selection_time.utcoffset() != timedelta(0) or (
        selection_time.day,
        selection_time.hour,
        selection_time.minute,
        selection_time.second,
        selection_time.microsecond,
    ) != (1, 0, 0, 0, 0):
        raise ValueError("selection_time must be the first day of the month at 00:00 UTC")

    members: list[UniverseMember] = []

    for name, frame in (
        ("daily_volumes", daily_volumes),
        ("daily_bars", daily_bars),
        ("hourly_bars", hourly_bars),
    ):
        if not frame.empty and "available_time" not in frame.columns:
            raise ValueError(f"{name} must include available_time")

    for asset in CORE_ASSETS:
        members.append(
            UniverseMember(
                selection_time=selection_time,
                asset=asset,
                rank=0,
                eligible=True,
                median_volume=None,
                rule_version=RULE_VERSION,
            )
        )

    cutoff = selection_time
    trailing_30 = cutoff - timedelta(days=30)

    candidates: list[tuple[str, float]] = []
    seen_assets: set[str] = set()
    for info in listed_assets:
        asset = info["asset"]
        if asset in seen_assets:
            raise ValueError(f"duplicate listing metadata for {asset}")
        seen_assets.add(asset)
        if asset in CORE_ASSETS:
            continue
        if _is_excluded(asset):
            continue
        listing_time = info.get("listing_time")
        delisting_time = info.get("delisting_time")
        metadata_available_time = info.get("available_time", listing_time)
        if metadata_available_time is None or metadata_available_time > cutoff:
            continue
        if listing_time is not None and listing_time > cutoff:
            continue
        delisting_available_time = info.get("delisting_available_time", delisting_time)
        known_delisting_time = (
            delisting_time
            if delisting_available_time is not None and delisting_available_time <= cutoff
            else None
        )
        if known_delisting_time is not None and known_delisting_time <= cutoff:
            continue

        asset_daily = (
            daily_bars[daily_bars["asset"] == asset]
            if "asset" in daily_bars.columns
            else pd.DataFrame()
        )
        if asset_daily.empty:
            continue
        daily_event_times = pd.to_datetime(asset_daily["event_time"], utc=True)
        daily_available_times = pd.to_datetime(asset_daily["available_time"], utc=True)
        completed_daily = asset_daily[
            (daily_event_times < cutoff) & (daily_available_times <= cutoff)
        ]
        if completed_daily["event_time"].nunique() < MIN_BARS:
            continue

        asset_hourly = (
            hourly_bars[hourly_bars["asset"] == asset]
            if "asset" in hourly_bars.columns
            else pd.DataFrame()
        )
        if asset_hourly.empty:
            continue
        hourly_event_times = pd.to_datetime(asset_hourly["event_time"], utc=True)
        hourly_available_times = pd.to_datetime(asset_hourly["available_time"], utc=True)
        trailing = asset_hourly[
            (hourly_event_times >= trailing_30)
            & (hourly_event_times < cutoff)
            & (hourly_available_times <= cutoff)
        ]
        expected_bars = 30 * 24
        observed_bars = trailing["event_time"].nunique()
        missing_pct = max(0.0, (1 - observed_bars / expected_bars) * 100)
        if missing_pct > MAX_MISSING_PCT:
            continue

        vol_data = (
            daily_volumes[daily_volumes["asset"] == asset]
            if "asset" in daily_volumes.columns
            else pd.DataFrame()
        )
        if vol_data.empty:
            continue
        volume_event_times = pd.to_datetime(vol_data["event_time"], utc=True)
        volume_available_times = pd.to_datetime(vol_data["available_time"], utc=True)
        trailing_vol = vol_data[
            (volume_event_times >= trailing_30)
            & (volume_event_times < cutoff)
            & (volume_available_times <= cutoff)
        ]
        if trailing_vol.empty:
            continue
        volume_column = "quote_volume" if "quote_volume" in trailing_vol.columns else "volume"
        median_vol = float(trailing_vol[volume_column].median())
        candidates.append((asset, median_vol))

    candidates.sort(key=lambda item: (-item[1], item[0]))
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
    migration_count = sum(member.asset not in CORE_ASSETS for member in members)
    sufficient = migration_count >= MIN_SELECTION
    member_payload = [
        member.model_dump(mode="json") for member in sorted(members, key=lambda item: item.asset)
    ]
    content_sha256 = hashlib.sha256(
        json.dumps(member_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return DatasetManifest(
        snapshot_id=snapshot_id,
        layer=DatasetLayer.RESEARCH,
        name="migration_universe",
        content_sha256=content_sha256,
        row_count=len(members),
        min_event_time=min(m.selection_time for m in members) if members else None,
        max_event_time=max(m.selection_time for m in members) if members else None,
        parent_snapshot_ids=parent_snapshot_ids,
        config_json=json.dumps(
            {
                "rule_version": RULE_VERSION,
                "migration_count": migration_count,
                "sufficient": sufficient,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
