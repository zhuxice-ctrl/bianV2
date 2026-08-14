"""Tests for point-in-time derivatives factors."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from bian_quant.factors.derivatives import (
    asof_join,
    funding_zscore,
    leverage_crowding,
    oi_change,
    relative_funding_pressure,
)


def _make_bars() -> pd.DataFrame:
    """5 bars at 4h intervals starting 2026-01-01 00:00 UTC."""
    return pd.DataFrame(
        {
            "timestamp": pd.date_range("2026-01-01", periods=5, freq="4h", tz="UTC"),
            "available_time": pd.date_range("2026-01-01", periods=5, freq="4h", tz="UTC"),
            "asset": "BTC",
            "close": [100.0, 101.0, 102.0, 103.0, 104.0],
        }
    )


def _make_funding() -> pd.DataFrame:
    """Funding records — the 3rd record arrives *after* bar 3."""
    return pd.DataFrame(
        {
            "available_time": pd.to_datetime(
                [
                    "2026-01-01 00:00",
                    "2026-01-01 04:00",
                    "2026-01-01 12:00",  # arrives after bar 2 (08:00) but before bar 3 (12:00)
                    "2026-01-01 16:00",
                    "2026-01-01 20:00",
                ],
                utc=True,
            ),
            "asset": "BTC",
            "funding_rate": [0.0001, 0.0002, 0.0003, 0.0004, 0.0005],
        }
    )


def test_late_funding_record_does_not_influence_earlier_bar() -> None:
    bars = _make_bars()
    funding = _make_funding()

    # Bar at 08:00 (index 2) should join to funding at 04:00, not 12:00
    merged = asof_join(bars, funding)
    assert merged.loc[2, "funding_rate"] == 0.0002
    assert merged.loc[2, "aux_available_time"] == pd.Timestamp("2026-01-01 04:00", tz="UTC")


def test_asof_join_preserves_all_bars() -> None:
    bars = _make_bars()
    funding = _make_funding()
    merged = asof_join(bars, funding)
    assert len(merged) == len(bars)


def test_funding_zscore_future_append_invariance() -> None:
    rng = np.random.default_rng(42)
    base = pd.Series(rng.normal(0.0001, 0.00005, 100))
    extended = pd.concat([base, pd.Series([0.001])], ignore_index=True)
    assert_series_equal(
        funding_zscore(base, periods=24),
        funding_zscore(extended, periods=24).iloc[:-1],
        check_names=False,
    )


def test_oi_change_future_append_invariance() -> None:
    base = pd.Series(np.linspace(1000, 2000, 100))
    extended = pd.concat([base, pd.Series([5000.0])], ignore_index=True)
    assert_series_equal(
        oi_change(base, periods=12),
        oi_change(extended, periods=12).iloc[:-1],
        check_names=False,
    )


def test_oi_change_preserves_missing_not_zero() -> None:
    oi = pd.Series([np.nan, 100.0, 200.0, np.nan, 300.0])
    result = oi_change(oi, periods=1)
    # Missing values should stay missing, not become zero
    assert pd.isna(result.iloc[0])
    assert pd.isna(result.iloc[3])


def test_leverage_crowding_only_positive_oi_delta() -> None:
    fz = pd.Series([1.0, 2.0, 3.0])
    oid = pd.Series([-0.5, 0.3, -0.1])
    lc = leverage_crowding(fz, oid)
    assert lc.iloc[0] == 0.0  # negative OI delta clipped to 0
    assert lc.iloc[1] == 0.6
    assert lc.iloc[2] == 0.0


def test_funding_zscore_zero_std_produces_nan() -> None:
    fr = pd.Series([0.0001] * 50)
    result = funding_zscore(fr, periods=24)
    assert pd.isna(result.iloc[-1])


def test_asof_join_multi_asset() -> None:
    bars = pd.DataFrame(
        {
            "available_time": pd.date_range("2026-01-01", periods=4, freq="4h", tz="UTC").repeat(2),
            "asset": ["BTC", "ETH"] * 4,
            "close": [100, 50, 101, 51, 102, 52, 103, 53],
        }
    )
    funding = pd.DataFrame(
        {
            "available_time": pd.to_datetime(
                ["2026-01-01 00:00", "2026-01-01 04:00"] * 2, utc=True
            ),
            "asset": ["BTC", "BTC", "ETH", "ETH"],
            "funding_rate": [0.0001, 0.0002, 0.0003, 0.0004],
        }
    )
    merged = asof_join(bars, funding)
    btc_rows = merged[merged["asset"] == "BTC"].sort_values("available_time")
    assert btc_rows.iloc[0]["funding_rate"] == 0.0001
    assert btc_rows.iloc[1]["funding_rate"] == 0.0002
    assert btc_rows.iloc[2]["funding_rate"] == 0.0002
    assert btc_rows.iloc[3]["funding_rate"] == 0.0002


def _make_pressure_frame(
    *,
    rates: tuple[float, ...] = (0.0003, 0.0001, -0.0001),
    assets: tuple[str, ...] = ("BTC", "ETH", "BNB"),
    available_time: str = "2026-01-01 00:00",
    funding_available_time: str = "2026-01-01 00:00",
    interval_hours: float = 8.0,
) -> pd.DataFrame:
    at = pd.Timestamp(available_time, tz="UTC")
    fat = pd.Timestamp(funding_available_time, tz="UTC")
    return pd.DataFrame(
        {
            "asset": list(assets),
            "available_time": [at] * len(assets),
            "funding_available_time": [fat] * len(assets),
            "funding_interval_hours": [interval_hours] * len(assets),
            "funding_rate": list(rates),
        }
    )


def _make_pressure_frame_multi() -> pd.DataFrame:
    timestamps = pd.date_range("2026-01-01", periods=2, freq="4h", tz="UTC")
    assets = ("BTC", "ETH", "BNB")
    rates = (0.0003, 0.0001, -0.0001)
    rows = []
    for at in timestamps:
        for asset, rate in zip(assets, rates, strict=True):
            rows.append(
                {
                    "asset": asset,
                    "available_time": at,
                    "funding_available_time": at,
                    "funding_interval_hours": 8.0,
                    "funding_rate": rate,
                }
            )
    return pd.DataFrame(rows)


def test_relative_funding_pressure_uses_median_and_mad() -> None:
    frame = _make_pressure_frame()
    values, reasons = relative_funding_pressure(frame)
    scale = 1.4826 * 0.0002
    assert values.tolist() == pytest.approx([0.0002 / scale, 0.0, -0.0002 / scale])
    assert reasons.isna().all()


def test_relative_funding_pressure_clips_to_five_sigma() -> None:
    # Extreme outlier: BTC funding far above peers -> raw z-score exceeds 5
    # and is clipped to +5.0; peers stay finite with NaN reasons.
    frame = _make_pressure_frame(rates=(1.0, 0.0001, -0.0001))
    values, reasons = relative_funding_pressure(frame)
    assert values.iloc[0] == pytest.approx(5.0)
    assert reasons.isna().all()


def test_relative_funding_pressure_insufficient_peer_coverage() -> None:
    frame = _make_pressure_frame()
    # ETH and BNB funding arrive in the future -> only BTC is valid.
    future = pd.Timestamp("2026-01-01 12:00", tz="UTC")
    frame.loc[1, "funding_available_time"] = future
    frame.loc[2, "funding_available_time"] = future
    values, reasons = relative_funding_pressure(frame)
    assert values.isna().all()
    assert reasons.loc[0] == "INSUFFICIENT_PEER_COVERAGE"
    assert reasons.loc[1] == "FUNDING_UNAVAILABLE_OR_GAPPED"
    assert reasons.loc[2] == "FUNDING_UNAVAILABLE_OR_GAPPED"


def test_relative_funding_pressure_future_or_gapped_records() -> None:
    frame = _make_pressure_frame()
    # BNB funding is stale: age (00:00 - prev-day 12:00 = 12h) > 8h interval.
    frame.loc[2, "funding_available_time"] = pd.Timestamp("2025-12-31 12:00", tz="UTC")
    values, reasons = relative_funding_pressure(frame)
    assert pd.isna(values.loc[2])
    assert reasons.loc[2] == "FUNDING_UNAVAILABLE_OR_GAPPED"
    # BTC and ETH remain valid peers and get finite values.
    assert values.loc[0] == pytest.approx((0.0003 - 0.0002) / (1.4826 * 0.0001))
    assert values.loc[1] == pytest.approx((0.0001 - 0.0002) / (1.4826 * 0.0001))

    # A future-available funding record is also gapped.
    frame2 = _make_pressure_frame()
    frame2.loc[2, "funding_available_time"] = pd.Timestamp("2026-01-01 12:00", tz="UTC")
    v2, r2 = relative_funding_pressure(frame2)
    assert r2.loc[2] == "FUNDING_UNAVAILABLE_OR_GAPPED"


def test_relative_funding_pressure_zero_mad() -> None:
    frame = _make_pressure_frame(rates=(0.0002, 0.0002, 0.0002))
    values, reasons = relative_funding_pressure(frame)
    assert values.isna().all()
    assert (reasons == "ZERO_CROSS_SECTIONAL_MAD").all()


def test_relative_funding_pressure_duplicate_rows_raises() -> None:
    frame = _make_pressure_frame()
    frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate asset/available_time"):
        relative_funding_pressure(frame)


def test_relative_funding_pressure_detects_semantic_duplicate_times() -> None:
    frame = _make_pressure_frame()
    frame.loc[0, "available_time"] = "2026-01-01T00:00:00Z"
    duplicate = frame.iloc[[0]].copy()
    duplicate["available_time"] = "2025-12-31T19:00:00-05:00"
    frame = pd.concat([frame, duplicate], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate asset/available_time"):
        relative_funding_pressure(frame)


def test_relative_funding_pressure_missing_columns_raises() -> None:
    frame = _make_pressure_frame().drop(columns=["funding_interval_hours"])
    with pytest.raises(ValueError, match="missing columns"):
        relative_funding_pressure(frame)


def test_relative_funding_pressure_does_not_mutate_input() -> None:
    frame = _make_pressure_frame()
    snapshot = frame.copy()
    relative_funding_pressure(frame)
    assert_series_equal(
        frame["funding_rate"].astype(float),
        snapshot["funding_rate"].astype(float),
        check_names=False,
    )
    assert list(frame.columns) == list(snapshot.columns)


def test_relative_funding_pressure_preserves_non_unique_index() -> None:
    frame = _make_pressure_frame()
    frame.index = pd.Index([7, 7, 9])
    values, reasons = relative_funding_pressure(frame)
    assert values.index.equals(frame.index)
    assert reasons.index.equals(frame.index)
    scale = 1.4826 * 0.0002
    assert values.tolist() == pytest.approx([0.0002 / scale, 0.0, -0.0002 / scale])
    assert reasons.isna().all()


@pytest.mark.parametrize("interval", [np.nan, np.inf, 1e308, "not-a-number"])
def test_relative_funding_pressure_invalid_interval_is_gapped(interval: object) -> None:
    frame = _make_pressure_frame()
    frame["funding_interval_hours"] = frame["funding_interval_hours"].astype(object)
    frame.loc[0, "funding_interval_hours"] = interval
    values, reasons = relative_funding_pressure(frame)
    assert pd.isna(values.iloc[0])
    assert reasons.iloc[0] == "FUNDING_UNAVAILABLE_OR_GAPPED"


def test_relative_funding_pressure_unparseable_funding_time_is_gapped() -> None:
    frame = _make_pressure_frame()
    frame["funding_available_time"] = frame["funding_available_time"].astype(object)
    frame.loc[0, "funding_available_time"] = "not-a-timestamp"
    values, reasons = relative_funding_pressure(frame)
    assert pd.isna(values.iloc[0])
    assert reasons.iloc[0] == "FUNDING_UNAVAILABLE_OR_GAPPED"


def test_relative_funding_pressure_prefix_invariance() -> None:
    base = _make_pressure_frame_multi()
    cutoff = pd.Timestamp("2026-01-01 00:00", tz="UTC")
    future = base.copy()
    # Mutate rates and availability strictly after the cutoff, then append
    # an entire future cross-section.  Neither can affect the prefix.
    future.loc[future["available_time"] > cutoff, "funding_rate"] *= -100.0
    future.loc[future["available_time"] > cutoff, "funding_available_time"] = pd.Timestamp(
        "2026-01-01 12:00", tz="UTC"
    )
    appended = _make_pressure_frame(
        available_time="2026-01-01 08:00",
        funding_available_time="2026-01-01 08:00",
    )
    future = pd.concat([future, appended], ignore_index=True)
    v_base, r_base = relative_funding_pressure(base)
    v_future, r_future = relative_funding_pressure(future)
    base_mask = base["available_time"] <= cutoff
    future_mask = future["available_time"] <= cutoff
    assert_series_equal(
        v_base[base_mask].reset_index(drop=True),
        v_future[future_mask].reset_index(drop=True),
        check_names=False,
    )
    assert_series_equal(
        r_base[base_mask].reset_index(drop=True),
        r_future[future_mask].reset_index(drop=True),
        check_names=False,
    )
