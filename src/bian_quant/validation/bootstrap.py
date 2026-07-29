from collections.abc import Callable

import numpy as np
from numpy.typing import NDArray


def stationary_block_ci(
    values: NDArray[np.float64] | list[float],
    *,
    statistic: Callable[[NDArray[np.float64]], float],
    block_size: int,
    samples: int,
    seed: int,
) -> tuple[float, float]:
    data = np.asarray(values, dtype=np.float64)
    if data.size == 0:
        raise ValueError("values must not be empty")
    if block_size < 2:
        raise ValueError("block_size must be at least 2")
    if samples < 100:
        raise ValueError("samples must be at least 100")

    generator = np.random.default_rng(seed)
    statistics = np.empty(samples, dtype=np.float64)
    for sample_number in range(samples):
        chunks: list[NDArray[np.float64]] = []
        remaining = data.size
        while remaining > 0:
            start = int(generator.integers(0, data.size))
            indices = (start + np.arange(min(block_size, remaining))) % data.size
            chunks.append(data[indices])
            remaining -= len(indices)
        statistics[sample_number] = statistic(np.concatenate(chunks))
    lower, upper = np.percentile(statistics, [2.5, 97.5])
    return float(lower), float(upper)
