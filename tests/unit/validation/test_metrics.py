"""Tests for metrics and block bootstrap."""

from __future__ import annotations

import numpy as np
import pytest

from bian_quant.validation.bootstrap import stationary_block_ci
from bian_quant.validation.metrics import max_drawdown, sharpe_ratio


class TestMaxDrawdown:
    def test_no_drawdown(self):
        r = np.array([0.01, 0.02, 0.01, 0.03])
        assert max_drawdown(r) == 0.0

    def test_simple_drawdown(self):
        # wealth: 1.0, 1.1, 0.99, 1.089
        # peak=1.1, trough=0.99 → dd = 0.99/1.1 - 1 = -0.1
        r = np.array([0.10, -0.10, 0.10])
        dd = max_drawdown(r)
        assert dd == pytest.approx(-0.1, abs=1e-6)

    def test_empty(self):
        assert max_drawdown([]) == 0.0

    def test_all_negative(self):
        r = np.array([-0.05, -0.05, -0.05])
        dd = max_drawdown(r)
        assert dd < 0.0

    def test_list_input(self):
        r = [0.01, -0.02, 0.01]
        assert isinstance(max_drawdown(r), float)


class TestSharpeRatio:
    def test_positive_sharpe(self):
        rng = np.random.default_rng(42)
        r = rng.normal(0.001, 0.02, size=500)
        sr = sharpe_ratio(r)
        assert sr > 0.0

    def test_zero_volatility(self):
        r = np.array([0.01, 0.01, 0.01])
        assert sharpe_ratio(r) == 0.0

    def test_empty(self):
        assert sharpe_ratio([]) == 0.0

    def test_single_element(self):
        assert sharpe_ratio([0.05]) == 0.0

    def test_negative_sharpe(self):
        r = np.array([-0.01, -0.02, -0.01, -0.02])
        sr = sharpe_ratio(r)
        assert sr < 0.0

    def test_annualization(self):
        # daily mean=0.001, daily std=0.02
        # annualised = 0.001/0.02 * sqrt(252) ≈ 0.7937
        r = np.array([0.001, 0.001, 0.001, 0.001])
        # Need variation for non-zero std
        r = np.array([0.021, -0.019, 0.021, -0.019])
        sr = sharpe_ratio(r, periods_per_year=252)
        expected = r.mean() / r.std(ddof=1) * np.sqrt(252)
        assert sr == pytest.approx(expected, rel=1e-4)


class TestStationaryBlockCI:
    def test_reproducible_with_seed(self):
        data = np.random.default_rng(0).normal(0, 1, size=200)
        ci1 = stationary_block_ci(data, statistic=np.mean, seed=123)
        ci2 = stationary_block_ci(data, statistic=np.mean, seed=123)
        assert ci1 == ci2

    def test_different_seeds_different_results(self):
        data = np.random.default_rng(0).normal(0, 1, size=200)
        ci1 = stationary_block_ci(data, statistic=np.mean, seed=123)
        ci2 = stationary_block_ci(data, statistic=np.mean, seed=999)
        assert ci1 != ci2

    def test_ci_contains_true_mean(self):
        rng = np.random.default_rng(42)
        data = rng.normal(0.5, 1.0, size=500)
        lower, upper = stationary_block_ci(
            data, statistic=np.mean, n_bootstrap=2000, seed=42
        )
        assert lower < 0.5 < upper

    def test_ci_ordering(self):
        data = np.random.default_rng(0).normal(0, 1, size=100)
        lower, upper = stationary_block_ci(data, statistic=np.mean, seed=1)
        assert lower < upper

    def test_empty_data_raises(self):
        with pytest.raises(ValueError, match="empty"):
            stationary_block_ci([], statistic=np.mean)

    def test_invalid_ci_level(self):
        with pytest.raises(ValueError, match="ci_level"):
            stationary_block_ci([1.0, 2.0], statistic=np.mean, ci_level=1.5)

    def test_circular_wrapping(self):
        """Small data with large block_length forces wrapping."""
        data = np.array([1.0, 2.0, 3.0])
        lower, upper = stationary_block_ci(
            data, statistic=np.mean, n_bootstrap=100, block_length=5, seed=0
        )
        # Mean of [1,2,3] is 2.0; CI should be around that
        assert lower < 2.0 < upper
