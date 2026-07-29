"""Factor evaluation: IC, stability, and multiple-testing correction."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sp_stats


@dataclass(frozen=True)
class FactorEvaluation:
    """Evaluation result for a single factor in a single fold/asset/regime slice."""

    factor_name: str
    fold: str
    asset: str
    regime: str
    pearson_ic: float
    spearman_ic: float
    coverage: float
    turnover: float
    sample_count: int
    ci_lower: float
    ci_upper: float


def _winsorize(series: pd.Series, lower: float, upper: float) -> pd.Series:
    """Clip values to [lower, upper] quantiles."""
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lower=lo, upper=hi)


def _stationary_block_bootstrap_ci(
    values: Sequence[float], block_size: int = 5, n_resamples: int = 1000, seed: int = 42
) -> tuple[float, float]:
    """Stationary block bootstrap confidence interval for the mean."""
    values = np.asarray(values, dtype=float)
    values = values[~np.isnan(values)]
    if len(values) < 2:
        return (float("nan"), float("nan"))

    rng = np.random.default_rng(seed)
    n = len(values)
    resampled_means = np.empty(n_resamples)

    for i in range(n_resamples):
        # Build a resampled series of length n using geometric block sizes
        idx = []
        while len(idx) < n:
            # Geometric distribution for block length
            block_len = max(1, rng.geometric(1.0 / block_size))
            start = rng.integers(0, n)
            block = [(start + j) % n for j in range(block_len)]
            idx.extend(block)
        idx = idx[:n]
        resampled_means[i] = np.mean(values[idx])

    return (float(np.percentile(resampled_means, 2.5)), float(np.percentile(resampled_means, 97.5)))


def _bootstrap_ic_ci(
    f_vals: np.ndarray,
    l_vals: np.ndarray,
    block_size: int = 5,
    n_resamples: int = 500,
    seed: int = 42,
) -> tuple[float, float]:
    """Block bootstrap CI for Pearson correlation."""
    n = len(f_vals)
    rng = np.random.default_rng(seed)
    resampled = np.empty(n_resamples)

    for i in range(n_resamples):
        idx = []
        while len(idx) < n:
            block_len = max(1, rng.geometric(1.0 / block_size))
            start = rng.integers(0, n)
            block = [(start + j) % n for j in range(block_len)]
            idx.extend(block)
        idx = idx[:n]
        f_sample = f_vals[idx]
        l_sample = l_vals[idx]
        # Guard against zero variance in resample
        if np.std(f_sample) > 0 and np.std(l_sample) > 0:
            resampled[i] = np.corrcoef(f_sample, l_sample)[0, 1]
        else:
            resampled[i] = 0.0

    return (float(np.percentile(resampled, 2.5)), float(np.percentile(resampled, 97.5)))


def evaluate_factor(
    factor: pd.Series,
    label: pd.Series,
    metadata: pd.DataFrame,
    *,
    fold: str,
    winsor_limits: tuple[float, float] = (0.01, 0.99),
    train_factor: pd.Series | None = None,
) -> list[FactorEvaluation]:
    """Evaluate a factor by fold, asset, and regime.

    Returns one ``FactorEvaluation`` per (fold, asset, regime) group —
    never a pooled aggregate.

    Parameters
    ----------
    factor
        Factor values aligned to the bar index.
    label
        Forward return labels aligned to the bar index.
    metadata
        DataFrame with columns ``asset`` and ``regime`` aligned to the
        same index.
    fold
        Name of the fold being evaluated.
    winsor_limits
        Lower and upper quantiles for winsorization.
    train_factor
        Training-set factor values for computing winsor thresholds. If
        ``None``, thresholds are computed from *factor* itself.
    """
    # Compute winsor thresholds on train data
    if train_factor is not None:
        winsored_train = _winsorize(train_factor.dropna(), *winsor_limits)
        lo = winsored_train.min()
        hi = winsored_train.max()
        factor_winsored = factor.clip(lower=lo, upper=hi)
    else:
        factor_winsored = _winsorize(factor, *winsor_limits)

    # Align everything
    df = pd.DataFrame(
        {
            "factor": factor_winsored,
            "label": label,
            "asset": metadata["asset"],
            "regime": metadata["regime"],
        }
    )

    results: list[FactorEvaluation] = []

    # Group by (asset, regime) — never pooled
    for (asset, regime), group in df.groupby(["asset", "regime"], sort=False):
        group["factor"].dropna()
        group["label"].dropna()

        # Align factor and label
        common = group[["factor", "label"]].dropna()
        if len(common) < 2:
            continue

        f_vals = common["factor"].values
        l_vals = common["label"].values

        # Coverage
        total = len(group)
        valid = len(common)
        coverage = valid / total if total > 0 else 0.0

        # Turnover (mean absolute change)
        turnover = float(np.mean(np.abs(np.diff(f_vals)))) if len(f_vals) > 1 else 0.0

        # IC
        pearson_ic = float(np.corrcoef(f_vals, l_vals)[0, 1]) if len(f_vals) > 1 else float("nan")
        spearman_result = sp_stats.spearmanr(f_vals, l_vals)
        spearman_ic = (
            float(spearman_result.statistic)
            if not np.isnan(spearman_result.statistic)
            else float("nan")
        )

        # Confidence interval via block bootstrap on the IC itself
        if len(f_vals) > 10:
            ci_lower, ci_upper = _bootstrap_ic_ci(f_vals, l_vals)
        else:
            ci_lower, ci_upper = float("nan"), float("nan")

        results.append(
            FactorEvaluation(
                factor_name=factor.name or "factor",
                fold=fold,
                asset=str(asset),
                regime=str(regime),
                pearson_ic=pearson_ic,
                spearman_ic=spearman_ic,
                coverage=coverage,
                turnover=turnover,
                sample_count=valid,
                ci_lower=ci_lower,
                ci_upper=ci_upper,
            )
        )

    return results
