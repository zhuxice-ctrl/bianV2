"""Stationary block bootstrap for dependence-aware confidence intervals.

Uses circular (wrapping) block resampling with a geometric block-length
distribution, following Politis & Romano (1994).
"""

from __future__ import annotations

from typing import Callable

import numpy as np


def stationary_block_ci(
    data: np.ndarray | list[float],
    *,
    statistic: Callable[[np.ndarray], float],
    n_bootstrap: int = 1000,
    block_length: int = 10,
    ci_level: float = 0.95,
    seed: int | None = None,
) -> tuple[float, float]:
    """Bootstrap confidence interval using stationary block bootstrap.

    Parameters
    ----------
    data:
        1-D array of observations (e.g. period returns).
    statistic:
        Function that takes a 1-D array and returns a scalar.
    n_bootstrap:
        Number of bootstrap resamples.
    block_length:
        Expected (mean) block length for the geometric distribution.
    ci_level:
        Confidence level in ``(0, 1)``.
    seed:
        Random seed for reproducibility.

    Returns
    -------
    (lower, upper)
        Percentile-based confidence interval bounds.
    """
    arr = np.asarray(data, dtype=np.float64)
    n = arr.size
    if n == 0:
        raise ValueError("data must not be empty")
    if block_length < 1:
        raise ValueError("block_length must be >= 1")
    if not 0.0 < ci_level < 1.0:
        raise ValueError("ci_level must be in (0, 1)")

    rng = np.random.default_rng(seed)

    # Geometric distribution parameter: p = 1 / block_length
    p = 1.0 / block_length

    boot_stats = np.empty(n_bootstrap, dtype=np.float64)

    for b in range(n_bootstrap):
        sample = np.empty(n, dtype=np.float64)
        pos = 0  # position in the resampled array
        # Start index in the original (circular) array
        start = rng.integers(0, n)

        while pos < n:
            # Draw block length from geometric distribution
            block_len = rng.geometric(p)
            for j in range(block_len):
                if pos >= n:
                    break
                sample[pos] = arr[(start + j) % n]  # circular wrap
                pos += 1
            # Next block starts at a random position (stationary bootstrap)
            start = rng.integers(0, n)

        boot_stats[b] = statistic(sample)

    alpha = (1.0 - ci_level) / 2.0
    lower = float(np.percentile(boot_stats, 100 * alpha))
    upper = float(np.percentile(boot_stats, 100 * (1.0 - alpha)))
    return lower, upper
