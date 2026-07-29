"""Tests for the causal vector screening engine."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bian_quant.backtest.vector import VectorResult, vector_backtest


def _make_series(returns: list[float], signals: list[int]) -> tuple[pd.Series, pd.Series]:
    idx = pd.date_range("2026-01-01", periods=len(returns), freq="D")
    return pd.Series(returns, index=idx), pd.Series(signals, index=idx, dtype=int)


class TestCausality:
    def test_signal_delayed_one_bar(self):
        """Signal on bar 0 should NOT earn the return on bar 0."""
        returns, signal = _make_series(
            [0.10, 0.01, 0.01, 0.01],
            [1, 0, 0, 0],
        )
        result = vector_backtest(returns, signal)
        # Signal at bar 0 is delayed to bar 1, so bar 0 return (0.10) is NOT captured
        # Strategy return on bar 0 = 0 (no position), bar 1 = 1 * 0.01 = 0.01
        strat_ret = result.cumulative_returns
        # First bar should have 0 return (no position yet)
        assert strat_ret.iloc[0] == pytest.approx(0.0, abs=1e-10)

    def test_no_lookahead_bias(self):
        """If signal perfectly predicts the next return, it should earn it."""
        # Signal 1 at bar 0 → earns return at bar 1 (0.05)
        returns, signal = _make_series(
            [0.0, 0.05, 0.0, 0.0],
            [1, 0, 0, 0],
        )
        result = vector_backtest(returns, signal)
        # Only bar 1 should have a non-zero strategy return
        assert result.n_trades == 1

    def test_signal_on_last_bar_earns_nothing(self):
        """A signal on the last bar cannot earn returns (no next bar)."""
        returns, signal = _make_series(
            [0.01, 0.01, 0.01, 0.10],
            [0, 0, 0, 1],
        )
        result = vector_backtest(returns, signal)
        assert result.n_trades == 0  # signal delayed beyond data


class TestVectorResult:
    def test_positive_sharpe_for_winning_strategy(self):
        rng = np.random.default_rng(42)
        n = 500
        rets = pd.Series(rng.normal(0.001, 0.02, n), index=pd.date_range("2026-01-01", periods=n, freq="D"))
        # Perfect signal (knows future) → but delayed, so it earns t+1 return
        signal = np.sign(rets).astype(int)
        result = vector_backtest(rets, signal)
        assert result.sharpe > 0.0

    def test_short_signal_negates_returns(self):
        returns, signal = _make_series(
            [0.01, 0.02, -0.01, 0.03],
            [0, -1, -1, 0],
        )
        result = vector_backtest(returns, signal)
        # Bar 1: signal=-1 (delayed from bar 0) → strategy return = -0.02
        # Bar 2: signal=-1 (delayed from bar 1) → strategy return = 0.01
        # Cumulative should be negative overall
        assert result.cumulative_returns.iloc[-1] < 0

    def test_empty_signal_zero_trades(self):
        returns, signal = _make_series(
            [0.01, 0.02, 0.03],
            [0, 0, 0],
        )
        result = vector_backtest(returns, signal)
        assert result.n_trades == 0
        assert result.sharpe == 0.0
        assert result.hit_rate == 0.0

    def test_hit_rate(self):
        returns, signal = _make_series(
            [0.05, -0.02, 0.03, 0.04],
            [1, 1, 1, 0],
        )
        result = vector_backtest(returns, signal)
        # Delayed signal: bar 1 (ret=-0.02), bar 2 (ret=0.03), bar 3 (ret=0.04)
        # Active bars: 1, 2, 3 → 2 positive out of 3
        assert result.n_trades == 3
        assert result.hit_rate == pytest.approx(2.0 / 3.0, abs=1e-6)

    def test_max_drawdown_non_positive(self):
        rng = np.random.default_rng(0)
        n = 200
        rets = pd.Series(rng.normal(0, 0.02, n), index=pd.date_range("2026-01-01", periods=n, freq="D"))
        signal = pd.Series(1, index=rets.index)
        result = vector_backtest(rets, signal)
        assert result.max_drawdown <= 0.0

    def test_returns_isolation_by_asset(self):
        """Signals from asset A must not affect returns of asset B."""
        idx = pd.date_range("2026-01-01", periods=5, freq="D")
        rets_a = pd.Series([0.01, 0.02, -0.01, 0.03, 0.01], index=idx)
        rets_b = pd.Series([0.05, -0.05, 0.05, -0.05, 0.05], index=idx)
        sig_a = pd.Series([1, 0, 0, 0, 0], index=idx, dtype=int)

        result_a = vector_backtest(rets_a, sig_a)
        result_b = vector_backtest(rets_b, sig_a)

        # Same signal, different returns → different results
        assert result_a.cumulative_returns.iloc[-1] != result_b.cumulative_returns.iloc[-1]
