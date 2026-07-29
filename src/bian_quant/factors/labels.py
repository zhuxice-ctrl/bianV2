"""Causal forward return labels.

This module is intentionally isolated from production factor modules.
No ``bian_quant.factors.*`` module other than this one may import it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def forward_log_return(close: pd.Series, *, periods: int) -> pd.Series:
    """Compute the forward log return as a prediction label.

    Parameters
    ----------
    close
        Close price series aligned to the bar index.
    periods
        Number of bars to look forward.  Must be positive.

    Returns
    -------
    Series of ``log(close[t+periods] / close[t])`` with NaN for the
    last ``periods`` bars.
    """
    if periods <= 0:
        raise ValueError("periods must be positive")
    return np.log(close.shift(-periods) / close).rename(f"forward_log_return_{periods}")
