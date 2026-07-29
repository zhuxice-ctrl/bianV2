"""Causal two-stage regime classifier.

Thresholds are fit on **train folds only** — never on the full sample.
The classifier supports prefix invariance: appending bars does not
change existing labels.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

REGIME_LABELS = (
    "trend_low_vol",
    "trend_high_vol",
    "range_low_vol",
    "range_high_vol",
    "liquidity_stress",
)


@dataclass(frozen=True)
class RegimeThresholds:
    """Quantile thresholds fit on training data only."""

    vol_48_q75: float
    trend_q60: float
    illiquidity_q95: float


def _rolling_volatility(close: pd.Series, window: int = 48) -> pd.Series:
    returns = np.log(close / close.shift(1))
    return returns.rolling(window, min_periods=window).std(ddof=1)


def _trend_strength(close: pd.Series, window: int = 48) -> pd.Series:
    vol = _rolling_volatility(close, window)
    abs_ret = (close / close.shift(window) - 1.0).abs()
    return (abs_ret / vol.replace(0.0, np.nan)).rename("trend_strength")


def _illiquidity(close: pd.Series, volume: pd.Series, window: int = 48) -> pd.Series:
    abs_ret = np.log(close / close.shift(1)).abs()
    dollar_vol = close * volume
    ratio = abs_ret / dollar_vol.replace(0.0, np.nan)
    return ratio.rolling(window, min_periods=window).mean().rename("illiquidity")


def fit_regime_thresholds(train_frame: pd.DataFrame) -> RegimeThresholds:
    """Fit regime thresholds from training data only.

    Parameters
    ----------
    train_frame
        DataFrame with columns ``close``, ``volume`` and at least
        ``window`` (default 48) rows.
    """
    close = train_frame["close"]
    volume = train_frame["volume"]

    vol = _rolling_volatility(close)
    trend = _trend_strength(close)
    illiq = _illiquidity(close, volume)

    return RegimeThresholds(
        vol_48_q75=float(vol.dropna().quantile(0.75)),
        trend_q60=float(trend.dropna().quantile(0.60)),
        illiquidity_q95=float(illiq.dropna().quantile(0.95)),
    )


def classify_regime(frame: pd.DataFrame, thresholds: RegimeThresholds) -> pd.Series:
    """Classify each bar into one of five regime labels.

    The classification uses only backward-looking rolling statistics
    and the train-only thresholds.  Liquidity stress overrides other
    classes when illiquidity exceeds its 95th percentile.
    """
    close = frame["close"]
    volume = frame["volume"]

    vol = _rolling_volatility(close)
    trend = _trend_strength(close)
    illiq = _illiquidity(close, volume)

    high_vol = vol > thresholds.vol_48_q75
    trending = trend > thresholds.trend_q60
    stressed = illiq > thresholds.illiquidity_q95

    labels = pd.Series(index=close.index, dtype=object)

    # Liquidity stress overrides
    labels[stressed.fillna(False)] = "liquidity_stress"

    # Non-stress bars
    non_stress = ~stressed.fillna(False)
    high_vol_ns = high_vol.fillna(False) & non_stress
    low_vol_ns = ~high_vol.fillna(False) & non_stress
    trending_ns = trending.fillna(False) & non_stress
    ranging_ns = ~trending.fillna(False) & non_stress

    labels[trending_ns & low_vol_ns] = "trend_low_vol"
    labels[trending_ns & high_vol_ns] = "trend_high_vol"
    labels[ranging_ns & low_vol_ns] = "range_low_vol"
    labels[ranging_ns & high_vol_ns] = "range_high_vol"

    return labels.rename("regime")
