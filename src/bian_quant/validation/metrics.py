import numpy as np
from numpy.typing import NDArray


def max_drawdown(equity: NDArray[np.float64] | list[float]) -> float:
    values = np.asarray(equity, dtype=np.float64)
    if values.size == 0:
        return 0.0
    if not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("equity must contain finite positive values")
    peak = np.maximum.accumulate(values)
    return float(np.min(values / peak - 1.0))


def sharpe_ratio(returns: NDArray[np.float64] | list[float], *, periods_per_year: int) -> float:
    values = np.asarray(returns, dtype=np.float64)
    if values.size < 2:
        return 0.0
    if periods_per_year <= 0:
        raise ValueError("periods_per_year must be positive")
    std = float(np.std(values, ddof=1))
    if std == 0.0 or not np.isfinite(std):
        return 0.0
    return float(np.mean(values) / std * np.sqrt(periods_per_year))
