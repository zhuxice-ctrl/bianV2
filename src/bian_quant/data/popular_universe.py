"""Point-in-time selection of the popular USD-M perpetual universe."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd

from bian_quant.data.acquisition import PopularUniversePolicy

RULE_VERSION = "popular-usdm-v1"


@dataclass(frozen=True)
class PopularUniverseExclusion:
    """A seed symbol and the reason it was not eligible."""

    asset: str
    reason: str


@dataclass(frozen=True)
class PopularUniverseMember:
    """An admitted member of one daily universe artifact."""

    selection_time: datetime
    asset: str
    rank: int
    median_quote_volume: float
    median_oi_value: float
    rule_version: str


@dataclass(frozen=True)
class PopularUniverseArtifact:
    """Immutable point-in-time universe selection output."""

    artifact_id: str
    selection_time: datetime
    members: tuple[PopularUniverseMember, ...]
    exclusions: tuple[PopularUniverseExclusion, ...]
    source_hashes: dict[str, str] = field(default_factory=dict)
    selector_config_hash: str = ""

    @property
    def member_assets(self) -> tuple[str, ...]:
        return tuple(member.asset for member in self.members)


def _require_aware(value: datetime, name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")


def _canonical_json(payload: Any) -> str:
    """Serialize hash payloads in the one canonical form used by this module."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _frame_hash(frame: pd.DataFrame) -> str:
    """Hash visible source rows independently of their incoming column order."""
    if frame.empty:
        return _sha256(_canonical_json([]))
    normalized = json.loads(frame.sort_index(axis=1).to_json(orient="records", date_format="iso"))
    return _sha256(_canonical_json(normalized))


def _selector_config_hash(policy: PopularUniversePolicy) -> str:
    return _sha256(
        _canonical_json(
            {
                "max_selected": policy.max_selected,
                "min_selected": policy.min_selected,
                "minimum_listing_days": policy.minimum_listing_days,
                "rule_version": policy.rule_version,
                "seed_assets": list(policy.seed_assets),
                "trailing_days": policy.trailing_days,
            }
        )
    )


def _point_in_time_rows(frame: pd.DataFrame, selection_time: pd.Timestamp) -> pd.DataFrame:
    """Return rows visible at ``selection_time``, normalized to UTC timestamps."""
    required_columns = {"asset", "event_time", "available_time"}
    if not required_columns.issubset(frame.columns):
        return pd.DataFrame(columns=["asset", "event_time", "available_time"])

    visible = frame.copy()
    visible["event_time"] = pd.to_datetime(visible["event_time"], utc=True, errors="coerce")
    visible["available_time"] = pd.to_datetime(visible["available_time"], utc=True, errors="coerce")
    return visible.loc[
        (visible["event_time"] < selection_time) & (visible["available_time"] <= selection_time)
    ].copy()


def _visible_listing_metadata(
    listing_metadata: pd.DataFrame, selection_time: pd.Timestamp
) -> pd.DataFrame:
    """Return listing metadata records that were published by the cutoff."""
    required_columns = {"asset", "listing_time", "listing_available_time"}
    if not required_columns.issubset(listing_metadata.columns):
        return pd.DataFrame(columns=["asset", "listing_time", "listing_available_time"])
    visible = listing_metadata.copy()
    visible["listing_time"] = pd.to_datetime(visible["listing_time"], utc=True, errors="coerce")
    visible["listing_available_time"] = pd.to_datetime(
        visible["listing_available_time"], utc=True, errors="coerce"
    )
    return visible.loc[visible["listing_available_time"] <= selection_time].copy()


def _distinct_daily_count(frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    event_times = pd.to_datetime(frame["event_time"], utc=True, errors="coerce")
    return int(event_times.dt.normalize().nunique())


def _median(frame: pd.DataFrame, column: str) -> float | None:
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.median())


def _listing_for_asset(
    listing_metadata: pd.DataFrame, asset: str
) -> tuple[pd.Timestamp, pd.Timestamp] | None:
    """Return the earliest listing record that was known by the cutoff."""
    required_columns = {"asset", "listing_time", "listing_available_time"}
    if not required_columns.issubset(listing_metadata.columns):
        return None

    rows = listing_metadata.loc[listing_metadata["asset"] == asset].copy()
    if rows.empty:
        return None
    rows = rows.dropna(subset=["listing_time", "listing_available_time"])
    if rows.empty:
        return None
    first = rows.sort_values(["listing_time", "listing_available_time"], kind="stable").iloc[0]
    return pd.Timestamp(first["listing_time"]), pd.Timestamp(first["listing_available_time"])


def _descending_ranks(values: dict[str, float]) -> dict[str, int]:
    """Return competition ranks with the largest value ranked first."""
    ranks: dict[str, int] = {}
    previous_value: float | None = None
    current_rank = 0
    for position, (asset, value) in enumerate(
        sorted(values.items(), key=lambda item: (-item[1], item[0])), start=1
    ):
        if previous_value is None or value != previous_value:
            current_rank = position
            previous_value = value
        ranks[asset] = current_rank
    return ranks


def build_popular_universe(
    selection_time: datetime,
    listing_metadata: pd.DataFrame,
    ohlcv: pd.DataFrame,
    funding: pd.DataFrame,
    metrics: pd.DataFrame,
    policy: PopularUniversePolicy,
) -> PopularUniverseArtifact:
    """Build the daily universe using only information available at the cutoff."""
    _require_aware(selection_time, "selection_time")
    if policy.rule_version != RULE_VERSION:
        raise ValueError(f"unsupported rule_version: {policy.rule_version}")

    cutoff = pd.Timestamp(selection_time).tz_convert("UTC")
    window_start = cutoff - pd.Timedelta(days=policy.trailing_days)
    selector_config_hash = _selector_config_hash(policy)
    ohlcv_visible = _point_in_time_rows(ohlcv, cutoff)
    funding_visible = _point_in_time_rows(funding, cutoff)
    metrics_visible = _point_in_time_rows(metrics, cutoff)
    listing_visible = _visible_listing_metadata(listing_metadata, cutoff)

    source_hashes = {
        "funding": _frame_hash(funding_visible),
        "listing_metadata": _frame_hash(listing_visible),
        "metrics": _frame_hash(metrics_visible),
        "ohlcv": _frame_hash(ohlcv_visible),
    }
    eligible: list[dict[str, float | str]] = []
    exclusions: list[PopularUniverseExclusion] = []

    for asset in policy.seed_assets:
        listing = _listing_for_asset(listing_visible, asset)
        if listing is None:
            exclusions.append(PopularUniverseExclusion(asset, "LISTING_METADATA_UNAVAILABLE"))
            continue
        listing_time, _ = listing
        if cutoff - listing_time < pd.Timedelta(days=policy.minimum_listing_days):
            exclusions.append(PopularUniverseExclusion(asset, "LISTING_AGE_BELOW_180_DAYS"))
            continue

        asset_ohlcv = ohlcv_visible.loc[
            (ohlcv_visible["asset"] == asset) & (ohlcv_visible["event_time"] >= window_start)
        ]
        asset_funding = funding_visible.loc[
            (funding_visible["asset"] == asset) & (funding_visible["event_time"] >= window_start)
        ]
        asset_metrics = metrics_visible.loc[
            (metrics_visible["asset"] == asset) & (metrics_visible["event_time"] >= window_start)
        ]
        if _distinct_daily_count(asset_ohlcv) < policy.trailing_days:
            exclusions.append(PopularUniverseExclusion(asset, "OHLCV_DAYS_INSUFFICIENT"))
            continue
        if _distinct_daily_count(asset_funding) < policy.trailing_days:
            exclusions.append(PopularUniverseExclusion(asset, "FUNDING_DAYS_INSUFFICIENT"))
            continue
        if _distinct_daily_count(asset_metrics) < policy.trailing_days:
            exclusions.append(PopularUniverseExclusion(asset, "METRICS_OI_DAYS_INSUFFICIENT"))
            continue

        median_quote_volume = _median(asset_ohlcv, "quote_volume")
        median_oi_value = _median(asset_metrics, "sum_open_interest_value")
        if median_quote_volume is None or median_oi_value is None:
            exclusions.append(PopularUniverseExclusion(asset, "MEDIAN_UNAVAILABLE"))
            continue
        eligible.append(
            {
                "asset": asset,
                "median_quote_volume": median_quote_volume,
                "median_oi_value": median_oi_value,
            }
        )

    if len(eligible) < policy.min_selected:
        raise RuntimeError(
            "POPULAR_UNIVERSE_INSUFFICIENT: "
            f"only {len(eligible)} eligible symbols (minimum {policy.min_selected})"
        )

    quote_volume_ranks = _descending_ranks(
        {str(item["asset"]): float(item["median_quote_volume"]) for item in eligible}
    )
    oi_value_ranks = _descending_ranks(
        {str(item["asset"]): float(item["median_oi_value"]) for item in eligible}
    )
    scored = sorted(
        eligible,
        key=lambda item: (
            quote_volume_ranks[str(item["asset"])] + oi_value_ranks[str(item["asset"])],
            str(item["asset"]),
        ),
    )[: policy.max_selected]
    members = tuple(
        PopularUniverseMember(
            selection_time=selection_time,
            asset=str(item["asset"]),
            rank=rank,
            median_quote_volume=float(item["median_quote_volume"]),
            median_oi_value=float(item["median_oi_value"]),
            rule_version=RULE_VERSION,
        )
        for rank, item in enumerate(scored, start=1)
    )
    artifact_id = _sha256(
        _canonical_json(
            {
                "exclusions": [
                    {"asset": exclusion.asset, "reason": exclusion.reason}
                    for exclusion in exclusions
                ],
                "members": [
                    {
                        "asset": member.asset,
                        "median_oi_value": member.median_oi_value,
                        "median_quote_volume": member.median_quote_volume,
                        "rank": member.rank,
                        "rule_version": member.rule_version,
                        "selection_time": member.selection_time.isoformat(),
                    }
                    for member in members
                ],
                "selection_time": selection_time.isoformat(),
                "selector_config_hash": selector_config_hash,
                "source_hashes": source_hashes,
            }
        )
    )
    return PopularUniverseArtifact(
        artifact_id=artifact_id,
        selection_time=selection_time,
        members=members,
        exclusions=tuple(exclusions),
        source_hashes=source_hashes,
        selector_config_hash=selector_config_hash,
    )
