"""Tests for point-in-time derivatives factors."""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.testing import assert_series_equal

from bian_quant.factors.derivatives import (
    asof_join,
    funding_zscore,
    leverage_crowding,
    oi_change,
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
