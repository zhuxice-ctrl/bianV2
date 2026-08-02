"""Unit tests for point-in-time popular universe selection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from bian_quant.data.acquisition import PopularUniversePolicy
from bian_quant.data.popular_universe import (
    RULE_VERSION,
    build_popular_universe,
)

SEED_ASSETS = (
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


def _policy() -> PopularUniversePolicy:
    return PopularUniversePolicy(
        rule_version=RULE_VERSION,
        minimum_listing_days=180,
        trailing_days=30,
        max_selected=12,
        min_selected=8,
        seed_assets=SEED_ASSETS,
    )


def _daily_rows(
    asset: str, *, start: datetime, days: int, quote_volume: float, oi_value: float
) -> pd.DataFrame:
    dates = pd.date_range(start=start, periods=days, freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "asset": asset,
            "event_time": dates,
            "available_time": dates + timedelta(minutes=5),
            "quote_volume": quote_volume,
            "sum_open_interest_value": oi_value,
        }
    )


def _listing(asset: str, listing_time: datetime) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "asset": [asset],
            "listing_time": [listing_time],
            "listing_available_time": [listing_time + timedelta(hours=1)],
        }
    )


def _full_fixture(
    selection_time: datetime, *, quote_volumes: dict[str, float], oi_values: dict[str, float]
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    window_start = selection_time - timedelta(days=35)
    listing_frames: list[pd.DataFrame] = []
    ohlcv_frames: list[pd.DataFrame] = []
    funding_frames: list[pd.DataFrame] = []
    metrics_frames: list[pd.DataFrame] = []
    for asset in SEED_ASSETS:
        listing_frames.append(_listing(asset, listing_time=selection_time - timedelta(days=400)))
        rows = _daily_rows(
            asset,
            start=window_start,
            days=35,
            quote_volume=quote_volumes.get(asset, 1000.0),
            oi_value=oi_values.get(asset, 1_000_000.0),
        )
        ohlcv_frames.append(rows[["asset", "event_time", "available_time", "quote_volume"]].copy())
        funding_frames.append(rows[["asset", "event_time", "available_time"]].copy())
        metrics_frames.append(
            rows[["asset", "event_time", "available_time", "sum_open_interest_value"]].copy()
        )
    return (
        pd.concat(listing_frames, ignore_index=True),
        pd.concat(ohlcv_frames, ignore_index=True),
        pd.concat(funding_frames, ignore_index=True),
        pd.concat(metrics_frames, ignore_index=True),
    )


def test_selects_top_members_and_assigns_ranks() -> None:
    selection_time = datetime(2026, 7, 1, tzinfo=UTC)
    quote_volumes = {asset: 1000.0 for asset in SEED_ASSETS}
    quote_volumes["ADAUSDT"] = 5000.0
    quote_volumes["APTUSDT"] = 4000.0
    oi_values = {asset: 1_000_000.0 for asset in SEED_ASSETS}
    oi_values["ADAUSDT"] = 5_000_000.0
    oi_values["APTUSDT"] = 4_000_000.0
    listing, ohlcv, funding, metrics = _full_fixture(
        selection_time, quote_volumes=quote_volumes, oi_values=oi_values
    )
    artifact = build_popular_universe(selection_time, listing, ohlcv, funding, metrics, _policy())
    assert [member.asset for member in artifact.members[:2]] == ["ADAUSDT", "APTUSDT"]
    assert artifact.members[0].rank == 1
    assert all(member.selection_time == selection_time for member in artifact.members)
    assert artifact.selector_config_hash
    assert len(artifact.members) == 12


def test_179_day_listing_is_excluded() -> None:
    selection_time = datetime(2026, 7, 1, tzinfo=UTC)
    listing, ohlcv, funding, metrics = _full_fixture(selection_time, quote_volumes={}, oi_values={})
    young = selection_time - timedelta(days=179)
    listing = listing.copy()
    listing.loc[listing["asset"] == "ADAUSDT", "listing_time"] = young
    artifact = build_popular_universe(selection_time, listing, ohlcv, funding, metrics, _policy())
    assert "ADAUSDT" in {exclusion.asset for exclusion in artifact.exclusions}
    assert "ADAUSDT" not in artifact.member_assets


def test_future_volume_spike_cannot_change_historical_rank() -> None:
    selection_time = datetime(2026, 7, 1, tzinfo=UTC)
    quote_volumes = {asset: 1000.0 for asset in SEED_ASSETS}
    quote_volumes["ADAUSDT"] = 5000.0
    oi_values = {asset: 1_000_000.0 for asset in SEED_ASSETS}
    listing, ohlcv, funding, metrics = _full_fixture(
        selection_time, quote_volumes=quote_volumes, oi_values=oi_values
    )
    future_rows = _daily_rows(
        "DOGEUSDT",
        start=selection_time,
        days=5,
        quote_volume=1_000_000.0,
        oi_value=1_000_000_000.0,
    )
    ohlcv_with_future = pd.concat(
        [
            ohlcv,
            future_rows[["asset", "event_time", "available_time", "quote_volume"]],
        ],
        ignore_index=True,
    )
    metrics_with_future = pd.concat(
        [
            metrics,
            future_rows[["asset", "event_time", "available_time", "sum_open_interest_value"]],
        ],
        ignore_index=True,
    )
    artifact = build_popular_universe(
        selection_time, listing, ohlcv_with_future, funding, metrics_with_future, _policy()
    )
    assert artifact.members[0].asset == "ADAUSDT"
    assert "DOGEUSDT" not in {member.asset for member in artifact.members[:1]}


def test_missing_funding_day_excludes_symbol() -> None:
    selection_time = datetime(2026, 7, 1, tzinfo=UTC)
    listing, ohlcv, funding, metrics = _full_fixture(selection_time, quote_volumes={}, oi_values={})
    funding = funding.drop(funding.loc[funding["asset"] == "ADAUSDT"].index[:10])
    artifact = build_popular_universe(selection_time, listing, ohlcv, funding, metrics, _policy())
    assert "ADAUSDT" in {exclusion.asset for exclusion in artifact.exclusions}
    assert "ADAUSDT" not in artifact.member_assets


def test_missing_oi_day_excludes_symbol() -> None:
    selection_time = datetime(2026, 7, 1, tzinfo=UTC)
    listing, ohlcv, funding, metrics = _full_fixture(selection_time, quote_volumes={}, oi_values={})
    metrics = metrics.drop(metrics.loc[metrics["asset"] == "ADAUSDT"].index[:10])
    artifact = build_popular_universe(selection_time, listing, ohlcv, funding, metrics, _policy())
    assert "ADAUSDT" in {exclusion.asset for exclusion in artifact.exclusions}
    assert "ADAUSDT" not in artifact.member_assets


def test_composite_rank_uses_both_quote_volume_and_oi() -> None:
    selection_time = datetime(2026, 7, 1, tzinfo=UTC)
    quote_volumes = {asset: 1000.0 for asset in SEED_ASSETS}
    oi_values = {asset: 1_000_000.0 for asset in SEED_ASSETS}
    quote_volumes["ADAUSDT"] = 5000.0  # best quote volume
    oi_values["ADAUSDT"] = 1.0  # worst OI value
    quote_volumes["APTUSDT"] = 4000.0
    oi_values["APTUSDT"] = 5_000_000.0  # best OI value
    listing, ohlcv, funding, metrics = _full_fixture(
        selection_time, quote_volumes=quote_volumes, oi_values=oi_values
    )
    artifact = build_popular_universe(selection_time, listing, ohlcv, funding, metrics, _policy())
    # APT (qv rank 2 + oi rank 1 = 3) beats ADA (qv rank 1 + oi rank 16 = 17).
    assert artifact.members[0].asset == "APTUSDT"
    assert "ADAUSDT" not in artifact.member_assets


def test_equal_scores_break_by_symbol() -> None:
    selection_time = datetime(2026, 7, 1, tzinfo=UTC)
    listing, ohlcv, funding, metrics = _full_fixture(selection_time, quote_volumes={}, oi_values={})
    artifact = build_popular_universe(selection_time, listing, ohlcv, funding, metrics, _policy())
    assets = [member.asset for member in artifact.members]
    assert assets == sorted(assets)


def test_insufficient_eligible_symbols_raise() -> None:
    selection_time = datetime(2026, 7, 1, tzinfo=UTC)
    listing, ohlcv, funding, metrics = _full_fixture(selection_time, quote_volumes={}, oi_values={})
    keep = set(SEED_ASSETS[:6])
    listing = listing.copy()
    young = selection_time - timedelta(days=10)
    listing.loc[~listing["asset"].isin(keep), "listing_time"] = young
    with pytest.raises(RuntimeError, match="POPULAR_UNIVERSE_INSUFFICIENT"):
        build_popular_universe(selection_time, listing, ohlcv, funding, metrics, _policy())


def test_fixture_is_nan_free() -> None:
    selection_time = datetime(2026, 7, 1, tzinfo=UTC)
    listing, ohlcv, funding, metrics = _full_fixture(selection_time, quote_volumes={}, oi_values={})
    assert not np.isnan(ohlcv["quote_volume"]).any()
    assert not np.isnan(metrics["sum_open_interest_value"]).any()
