"""Volume-based liquidity factors.

All functions are pure and pass future-append invariance.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def volume_surprise(volume: pd.Series, *, periods: int) -> pd.Series:
    """Z-score of volume relative to its rolling mean."""
    if periods <= 1:
        raise ValueError("periods must be greater than one")
    mean = volume.rolling(periods, min_periods=periods).mean()
    std = volume.rolling(periods, min_periods=periods).std(ddof=1)
    return ((volume - mean) / std.replace(0.0, np.nan)).rename(f"volume_surprise_{periods}")


def amihud_illiquidity(close: pd.Series, volume: pd.Series, *, periods: int) -> pd.Series:
    """Rolling Amihud illiquidity measure.

    ``|log_return| / dollar_volume`` averaged over a window.
    """
    if periods <= 1:
        raise ValueError("periods must be greater than one")
    ratio_values = (close / close.shift(1)).to_numpy(dtype=float)
    absolute_return = pd.Series(np.abs(np.log(ratio_values)), index=close.index, dtype=float)
    dollar_volume = close * volume
    ratio = absolute_return / dollar_volume.replace(0.0, np.nan)
    result = ratio.rolling(periods, min_periods=periods).mean()
    return pd.Series(result, index=close.index, name=f"amihud_{periods}", dtype=float)
