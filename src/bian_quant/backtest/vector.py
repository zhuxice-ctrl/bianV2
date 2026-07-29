"""Causal vector backtest engine for fast signal screening.

The key causality rule: a signal generated on bar *t* can only earn
returns on bar *t+1*.  This is enforced by ``shift(1)`` on the signal
before computing returns, preventing look-ahead bias.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class VectorResult:
    """Result of a vector backtest.

    Attributes
    ----------
    cumulative_returns:
        Cumulative return series indexed like the input.
    sharpe:
        Annualised Sharpe ratio.
    max_drawdown:
        Maximum drawdown (negative fraction).
    n_trades:
        Number of bars with an active position.
    hit_rate:
        Fraction of active bars with positive returns.
    """

    cumulative_returns: pd.Series
    sharpe: float
    max_drawdown: float
    n_trades: int
    hit_rate: float


def vector_backtest(
    returns: pd.Series,
    signal: pd.Series,
    *,
    periods_per_year: int = 252,
) -> VectorResult:
    """Run a causal vector backtest.

    Parameters
    ----------
    returns:
        Period-by-period simple returns (e.g. daily pct change).
    signal:
        Position signal: ``+1`` long, ``-1`` short, ``0`` flat.
        Generated on bar *t*, applied to bar *t+1* via ``shift(1)``.
    periods_per_year:
        Annualisation factor for Sharpe ratio.

    Returns
    -------
    VectorResult
    """
    # Align indices
    signal = signal.reindex(returns.index).fillna(0)
    returns = returns.fillna(0.0)

    # Causality: signal at bar t earns returns at bar t+1
    delayed_signal = signal.shift(1).fillna(0)

    # Strategy returns
    strategy_returns = delayed_signal * returns

    # Cumulative
    cumulative = (1.0 + strategy_returns).cumprod() - 1.0

    # Sharpe
    std = strategy_returns.std(ddof=1)
    sharpe = float(strategy_returns.mean() / std * np.sqrt(periods_per_year)) if std > 0 else 0.0

    # Max drawdown
    wealth = (1.0 + strategy_returns).cumprod()
    running_max = wealth.cummax()
    drawdown = wealth / running_max - 1.0
    mdd = float(drawdown.min()) if len(drawdown) > 0 else 0.0

    # Trade stats
    active = delayed_signal != 0
    n_trades = int(active.sum())
    if n_trades > 0:
        hit_rate = float((strategy_returns[active] > 0).sum() / n_trades)
    else:
        hit_rate = 0.0

    return VectorResult(
        cumulative_returns=cumulative,
        sharpe=sharpe,
        max_drawdown=mdd,
        n_trades=n_trades,
        hit_rate=hit_rate,
    )
