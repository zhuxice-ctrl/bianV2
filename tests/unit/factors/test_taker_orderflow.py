"""Tests for taker_orderflow_imbalance signal."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bian_quant.factors.taker_orderflow import taker_orderflow_imbalance


def _make_frame(
    n_assets: int = 4,
    n_bars: int = 3,
    *,
    start: str = "2024-07-01",
) -> pd.DataFrame:
    rows = []
    times = pd.date_range(start, periods=n_bars, freq="h", tz="UTC")
    for bar_idx, ts in enumerate(times):
        for a in range(n_assets):
            vol = 1000.0 + bar_idx * 10 + a
            buy = vol * (0.3 + a * 0.1 + bar_idx * 0.02)
            rows.append(
                {
                    "asset": f"ASSET{a}",
                    "event_time": ts,
                    "available_time": ts,
                    "volume": vol,
                    "taker_buy_base": buy,
                    "taker_buy_quote": buy * 100.0,
                }
            )
    return pd.DataFrame(rows)


def test_signal_basic_formula_and_clip() -> None:
    frame = _make_frame(n_assets=5, n_bars=1)
    values, reasons = taker_orderflow_imbalance(frame)
    valid = reasons == ""
    assert valid.sum() == 5
    # z-scores should be centered (median maps to ~0)
    assert values[valid].abs().max() <= 5.0


def test_signal_clips_at_five() -> None:
    """One extreme outlier should clip at 5."""
    frame = _make_frame(n_assets=5, n_bars=1)
    # make one asset have an extreme buy share
    frame.loc[frame["asset"] == "ASSET0", "taker_buy_base"] = (
        frame.loc[frame["asset"] == "ASSET0", "volume"] * 0.99
    )
    frame.loc[frame["asset"] == "ASSET1", "taker_buy_base"] = (
        frame.loc[frame["asset"] == "ASSET1", "volume"] * 0.01
    )
    values, reasons = taker_orderflow_imbalance(frame)
    assert values.abs().max() <= 5.0


def test_signal_zero_mad_all_equal() -> None:
    frame = _make_frame(n_assets=3, n_bars=1)
    # make all buy_share equal
    frame["taker_buy_base"] = frame["volume"] * 0.5
    values, reasons = taker_orderflow_imbalance(frame)
    assert (reasons == "ZERO_CROSS_SECTIONAL_MAD_TAKER").all()
    assert values.isna().all()


def test_signal_volume_zero() -> None:
    frame = _make_frame(n_assets=3, n_bars=1)
    frame.loc[frame["asset"] == "ASSET0", "volume"] = 0
    values, reasons = taker_orderflow_imbalance(frame)
    assert reasons.loc[frame["asset"] == "ASSET0"].iloc[0] == "TAKER_VOLUME_ZERO"


def test_signal_taker_field_missing() -> None:
    frame = _make_frame(n_assets=3, n_bars=1)
    frame.loc[frame["asset"] == "ASSET0", "taker_buy_base"] = np.nan
    values, reasons = taker_orderflow_imbalance(frame)
    assert reasons.loc[frame["asset"] == "ASSET0"].iloc[0] == "TAKER_FIELD_MISSING"


def test_signal_insufficient_peer_coverage() -> None:
    """Only 1 valid asset in a timestamp -> INSUFFICIENT_PEER_COVERAGE."""
    frame = _make_frame(n_assets=3, n_bars=1)
    frame.loc[frame["asset"] == "ASSET1", "volume"] = 0
    frame.loc[frame["asset"] == "ASSET2", "volume"] = 0
    values, reasons = taker_orderflow_imbalance(frame)
    assert reasons.loc[frame["asset"] == "ASSET0"].iloc[0] == "INSUFFICIENT_PEER_COVERAGE"


def test_buy_share_range_zero_to_one() -> None:
    """buy_share = taker_buy_base / volume should be in [0, 1] when valid."""
    frame = _make_frame(n_assets=5, n_bars=3)
    # Normal data: buy < vol
    values, reasons = taker_orderflow_imbalance(frame)
    assert (reasons == "").sum() > 0
    frame.loc[frame["asset"] == "ASSET0", "taker_buy_base"] = (
        2.0 * frame.loc[frame["asset"] == "ASSET0", "volume"]
    )
    _, invalid_reasons = taker_orderflow_imbalance(frame)
    assert invalid_reasons.loc[frame["asset"] == "ASSET0"].iloc[0] == "TAKER_RATIO_INVALID"


def test_signal_rejects_negative_or_nonfinite_volume() -> None:
    frame = _make_frame(n_assets=3, n_bars=1)
    frame.loc[frame["asset"] == "ASSET0", "volume"] = -1.0
    frame.loc[frame["asset"] == "ASSET1", "volume"] = np.inf
    _, reasons = taker_orderflow_imbalance(frame)
    assert reasons.loc[frame["asset"] == "ASSET0"].iloc[0] == "TAKER_VOLUME_ZERO"
    assert reasons.loc[frame["asset"] == "ASSET1"].iloc[0] == "TAKER_VOLUME_ZERO"


def test_signal_row_order_independence() -> None:
    frame = _make_frame(n_assets=5, n_bars=2)
    v1, r1 = taker_orderflow_imbalance(frame)
    shuffled = frame.sample(frac=1, random_state=42).reset_index(drop=True)
    v2, r2 = taker_orderflow_imbalance(shuffled)
    # Same values regardless of row order
    assert np.allclose(np.sort(v1.values), np.sort(v2.values))


def test_invalid_ratio_is_excluded_from_peer_statistics() -> None:
    frame = _make_frame(n_assets=4, n_bars=1)
    frame.loc[frame["asset"] == "ASSET0", "taker_buy_base"] = (
        2.0 * frame.loc[frame["asset"] == "ASSET0", "volume"]
    )
    values, reasons = taker_orderflow_imbalance(frame)
    assert reasons.loc[frame["asset"] == "ASSET0"].iloc[0] == "TAKER_RATIO_INVALID"
    assert pd.isna(values.loc[frame["asset"] == "ASSET0"].iloc[0])


def test_signal_future_prefix_invariance() -> None:
    """Adding future bars should not change past signal values."""
    frame_short = _make_frame(n_assets=5, n_bars=2)
    frame_long = _make_frame(n_assets=5, n_bars=4)
    v_short, _ = taker_orderflow_imbalance(frame_short)
    v_long, _ = taker_orderflow_imbalance(frame_long)
    # First 2 bars should have same values
    short_vals = v_short.values
    long_vals = v_long.values[: len(short_vals)]
    assert np.allclose(short_vals, long_vals)


def test_signal_raises_on_missing_columns() -> None:
    frame = pd.DataFrame({"asset": ["A"], "volume": [1.0]})
    with pytest.raises(ValueError, match="missing required columns"):
        taker_orderflow_imbalance(frame)
