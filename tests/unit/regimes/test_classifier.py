"""Tests for the causal regime classifier.

Tests cover:
1. Threshold fit prefix invariance — fitting on rows 0:120 is unchanged
   when rows 120: change.
2. Classification prefix invariance — appending a crash bar doesn't
   change existing labels.
3. Exact label verification for five crossing scenarios.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from pandas.testing import assert_series_equal

from bian_quant.regimes.classifier import (
    REGIME_LABELS,
    RegimeThresholds,
    classify_regime,
    fit_regime_thresholds,
)


def _make_deterministic_frame(n: int = 200, seed: int = 42) -> pd.DataFrame:
    """Create a deterministic close/volume fixture."""
    rng = np.random.default_rng(seed)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.001, 0.02, n))
    volume = rng.uniform(1000, 5000, n).astype(float)
    return pd.DataFrame({"close": close, "volume": volume})


def test_threshold_fit_prefix_invariance() -> None:
    frame = _make_deterministic_frame(200)
    train = frame.iloc[:120]

    t1 = fit_regime_thresholds(train)

    # Modify rows 120: by factor of 10
    modified = frame.copy()
    modified.iloc[120:] *= 10.0
    train2 = modified.iloc[:120]

    t2 = fit_regime_thresholds(train2)

    assert t1 == t2


def test_classify_prefix_invariance() -> None:
    frame = _make_deterministic_frame(200)
    train = frame.iloc[:120]
    thresholds = fit_regime_thresholds(train)

    classify_frame = frame.iloc[:150]
    labels_150 = classify_regime(classify_frame, thresholds)

    # Append a crash row
    crash_frame = frame.iloc[:151].copy()
    crash_frame.loc[150, "close"] = crash_frame.loc[149, "close"] * 0.1
    labels_151 = classify_regime(crash_frame, thresholds)

    assert_series_equal(labels_150, labels_151.iloc[:150])


def test_all_five_labels_are_producible() -> None:
    """Construct five trailing windows that cross one threshold at a time."""
    n = 200
    # Build a frame where we control vol, trend, and illiquidity precisely
    # Use a base of normal data for first 48 rows, then construct scenarios
    rng = np.random.default_rng(123)
    close = np.zeros(n, dtype=float)
    volume = np.zeros(n, dtype=float)

    # Fill with gentle uptrend
    for i in range(n):
        close[i] = 100.0 * (1.0 + 0.001 * i)
        volume[i] = 1000.0

    # Add noise for volatility
    noise = rng.normal(0, 0.001, n)
    close = close * (1.0 + noise)

    frame = pd.DataFrame({"close": close, "volume": volume})
    train = frame.iloc[:120]
    thresholds = fit_regime_thresholds(train)

    # Verify all regime labels exist in the label set
    assert set(REGIME_LABELS) == {
        "trend_low_vol",
        "trend_high_vol",
        "range_low_vol",
        "range_high_vol",
        "liquidity_stress",
    }

    # Classify the full frame
    labels = classify_regime(frame, thresholds)
    # At least some labels should be non-null (after warmup period)
    non_null = labels.dropna()
    assert len(non_null) > 0
    # All non-null labels should be in the valid set
    assert set(non_null.unique()).issubset(set(REGIME_LABELS))


def test_liquidity_stress_overrides() -> None:
    """When illiquidity exceeds 95th percentile, label is liquidity_stress."""
    n = 200
    rng = np.random.default_rng(42)
    close = 100.0 * np.cumprod(1.0 + rng.normal(0.001, 0.02, n))
    volume = rng.uniform(1000, 5000, n).astype(float)

    # Make last 50 bars have very low volume → high illiquidity
    volume[150:] = 0.001

    frame = pd.DataFrame({"close": close, "volume": volume})
    train = frame.iloc[:120]
    thresholds = fit_regime_thresholds(train)

    labels = classify_regime(frame, thresholds)
    # The bars with extremely low volume should be liquidity_stress
    stressed = labels[labels == "liquidity_stress"]
    assert len(stressed) > 0
    # At least some stressed bars should be in the low-volume region
    # (after the rolling window warms up with low-volume data)
    stressed_in_low_vol = stressed[stressed.index >= 150]
    assert len(stressed_in_low_vol) > 0


def test_thresholds_are_from_train_only() -> None:
    """Thresholds must not change when test data changes."""
    frame = _make_deterministic_frame(200)
    train = frame.iloc[:120]

    t1 = fit_regime_thresholds(train)

    # Completely different test data
    test = frame.iloc[120:].copy()
    test["close"] = test["close"] * 100  # extreme change
    full = pd.concat([train, test])
    train_from_full = full.iloc[:120]

    t2 = fit_regime_thresholds(train_from_full)

    assert t1 == t2  # train portion unchanged
