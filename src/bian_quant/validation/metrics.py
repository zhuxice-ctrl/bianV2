"""Performance metrics for strategy evaluation.

All functions accept simple numpy arrays or pandas Series of returns.
"""

from __future__ import annotations

import numpy as np


def max_drawdown(returns: np.ndarray | list[float]) -> float:
    """Maximum drawdown of a return stream.

    Parameters
    ----------
    returns:
        Period-by-period simple returns (not log returns).

    Returns
    -------
    float
        The maximum drawdown as a negative fraction (e.g. ``-0.25`` for
        a 25 % peak-to-trough decline).  Returns ``0.0`` if there is no
        drawdown.
    """
    r = np.asarray(returns, dtype=np.float64)
    if r.size == 0:
        return 0.0
    # Cumulative wealth index starting from 1.0
    wealth = np.cumprod(1.0 + r)
    running_max = np.maximum.accumulate(wealth)
    drawdown = wealth / running_max - 1.0
    return float(drawdown.min())


def sharpe_ratio(
    returns: np.ndarray | list[float],
    *,
    rf: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    """Annualised Sharpe ratio.

    Parameters
    ----------
    returns:
        Period-by-period simple returns.
    rf:
        Risk-free rate per period (default 0).
    periods_per_year:
        Annualisation factor (default 252 for daily data).

    Returns
    -------
    float
        Annualised Sharpe ratio.  Returns ``0.0`` if the standard
        deviation is zero or input is empty.
    """
    r = np.asarray(returns, dtype=np.float64)
    if r.size == 0:
        return 0.0
    excess = r - rf
    std = excess.std(ddof=1) if r.size > 1 else 0.0
    if std == 0.0:
        return 0.0
    mean_excess = excess.mean()
    return float(mean_excess / std * np.sqrt(periods_per_year))
