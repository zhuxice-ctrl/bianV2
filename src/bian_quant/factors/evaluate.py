"""Factor evaluation: IC, stability, and multiple-testing correction."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sp_stats  # type: ignore[import-untyped]

MIN_INFERENCE_SAMPLES = 30


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
    p_value: float
    ci_lower: float
    ci_upper: float
    horizon: str = "primary"


def _winsorize(series: pd.Series, lower: float, upper: float) -> pd.Series:
    """Clip values to [lower, upper] quantiles."""
    lo = series.quantile(lower)
    hi = series.quantile(upper)
    return series.clip(lower=lo, upper=hi)


def _bootstrap_rank_ic_ci(
    f_vals: np.ndarray,
    l_vals: np.ndarray,
    block_size: int = 5,
    n_resamples: int = 500,
    seed: int = 42,
) -> tuple[float, float]:
    """Stationary-block bootstrap confidence interval for Spearman RankIC."""
    n = len(f_vals)
    rng = np.random.default_rng(seed)
    resampled = np.empty(n_resamples)

    for i in range(n_resamples):
        idx: list[int] = []
        while len(idx) < n:
            block_len = max(1, rng.geometric(1.0 / block_size))
            start = rng.integers(0, n)
            block = [int((start + j) % n) for j in range(block_len)]
            idx.extend(block)
        idx_arr = np.array(idx[:n])
        f_sample = f_vals[idx_arr]
        l_sample = l_vals[idx_arr]
        # Guard against zero variance in resample.
        if np.ptp(f_sample) > 0.0 and np.ptp(l_sample) > 0.0:
            factor_ranks = np.asarray(sp_stats.rankdata(f_sample), dtype=float)
            label_ranks = np.asarray(sp_stats.rankdata(l_sample), dtype=float)
            resampled[i] = float(np.corrcoef(factor_ranks, label_ranks)[0, 1])
        else:
            resampled[i] = np.nan

    valid = resampled[np.isfinite(resampled)]
    if len(valid) < 2:
        return (float("nan"), float("nan"))
    return (float(np.percentile(valid, 2.5)), float(np.percentile(valid, 97.5)))


def evaluate_factor(
    factor: pd.Series,
    label: pd.Series,
    metadata: pd.DataFrame,
    *,
    fold: str,
    horizon: str = "primary",
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
        # Align factor and label
        common = group[["factor", "label"]].dropna()
        if len(common) < 2:
            continue

        f_vals = common["factor"].to_numpy(dtype=float)
        l_vals = common["label"].to_numpy(dtype=float)

        # Coverage
        total = len(group)
        valid = len(common)
        coverage = valid / total if total > 0 else 0.0

        # Turnover (mean absolute change)
        turnover = float(np.mean(np.abs(np.diff(f_vals)))) if len(f_vals) > 1 else 0.0

        # IC
        pearson_ic = _safe_pearson(f_vals, l_vals)
        constant_input = np.ptp(f_vals) == 0.0 or np.ptp(l_vals) == 0.0
        spearman_result = None if constant_input else sp_stats.spearmanr(f_vals, l_vals)
        spearman_ic = (
            float(spearman_result.statistic)
            if spearman_result is not None and not np.isnan(spearman_result.statistic)
            else float("nan")
        )
        p_value = float("nan")
        if (
            valid >= MIN_INFERENCE_SAMPLES
            and spearman_result is not None
            and not np.isnan(spearman_result.pvalue)
        ):
            p_value = float(spearman_result.pvalue)

        # Confidence interval via block bootstrap on the IC itself
        if valid >= MIN_INFERENCE_SAMPLES and not constant_input:
            ci_lower, ci_upper = _bootstrap_rank_ic_ci(f_vals, l_vals)
        else:
            ci_lower, ci_upper = float("nan"), float("nan")

        results.append(
            FactorEvaluation(
                factor_name=str(factor.name or "factor"),
                horizon=horizon,
                fold=fold,
                asset=str(asset),
                regime=str(regime),
                pearson_ic=pearson_ic,
                spearman_ic=spearman_ic,
                coverage=coverage,
                turnover=turnover,
                sample_count=valid,
                p_value=p_value,
                ci_lower=ci_lower,
                ci_upper=ci_upper,
            )
        )

    return results


def _safe_pearson(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2 or np.ptp(left) == 0.0 or np.ptp(right) == 0.0:
        return float("nan")
    return float(np.corrcoef(left, right)[0, 1])
