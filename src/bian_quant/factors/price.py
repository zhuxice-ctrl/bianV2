"""Interpretable price-based factors.

All functions are pure: they only read their inputs and produce outputs
aligned to the same index.  They pass future-append invariance — appending
a new bar to the end of the series does not change any existing value.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def momentum(close: pd.Series, *, periods: int) -> pd.Series:
    """Percentage return over *periods* bars."""
    return (close / close.shift(periods) - 1.0).rename(f"momentum_{periods}")


def reversal(close: pd.Series, *, periods: int) -> pd.Series:
    """Negative momentum — a mean-reversion signal."""
    return (-momentum(close, periods=periods)).rename(f"reversal_{periods}")


def realized_volatility(close: pd.Series, *, periods: int) -> pd.Series:
    """Rolling standard deviation of log returns."""
    returns = np.log(close / close.shift(1))
    return returns.rolling(periods, min_periods=periods).std(ddof=1).rename(
        f"realized_vol_{periods}"
    )
