import numpy as np
import pytest

from bian_quant.validation.bootstrap import stationary_block_ci
from bian_quant.validation.metrics import max_drawdown, sharpe_ratio


def test_max_drawdown_uses_equity_path() -> None:
    assert max_drawdown([100.0, 120.0, 90.0, 110.0]) == -0.25


def test_block_ci_is_seeded() -> None:
    values = np.linspace(-0.01, 0.02, 200)
    first = stationary_block_ci(values, statistic=np.mean, block_size=12, samples=500, seed=7)
    second = stationary_block_ci(values, statistic=np.mean, block_size=12, samples=500, seed=7)
    assert first == second


def test_bootstrap_rejects_too_few_samples() -> None:
    with pytest.raises(ValueError, match="at least 100"):
        stationary_block_ci([1.0, 2.0], statistic=np.mean, block_size=2, samples=99, seed=7)


def test_zero_variance_sharpe_is_zero() -> None:
    assert sharpe_ratio(np.zeros(100), periods_per_year=365 * 6) == 0.0
