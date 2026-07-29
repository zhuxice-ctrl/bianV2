"""Promotion policy for strategy evaluation.

A strategy must pass all gates before it can be promoted from research
to production.  The policy is deliberately strict: it rejects strategies
whose performance is driven by a single fold, whose Sharpe ratio is
statistically indistinguishable from zero, or whose drawdown exceeds
design thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median


@dataclass(frozen=True)
class FoldMetrics:
    """Performance metrics for a single walk-forward fold.

    Attributes
    ----------
    net_return:
        Net return for the fold (fractional, e.g. 0.15 = 15%).
    sharpe:
        Annualised Sharpe ratio for the fold.
    max_drawdown:
        Maximum drawdown (negative fraction, e.g. -0.10 = -10%).
    """

    net_return: float
    sharpe: float
    max_drawdown: float


@dataclass(frozen=True)
class PromotionDecision:
    """Result of evaluating a strategy through the promotion gate.

    Attributes
    ----------
    passed:
        Whether the strategy passed all gates.
    reasons:
        List of reason codes for failure (empty if passed).
    """

    passed: bool
    reasons: list[str] = field(default_factory=list)


class PromotionPolicy:
    """Multi-gate promotion policy.

    A strategy must pass **all** of the following gates:

    1. ``positive_fold_ratio >= 0.70`` — at least 70% of folds must be profitable.
    2. ``median_sharpe >= 0.80`` — the median fold Sharpe must be at least 0.80.
    3. ``sharpe_ci_lower > 0.0`` — the lower bound of the Sharpe CI must be positive.
    4. ``normal_max_drawdown >= -0.15`` — max drawdown in normal scenarios must not exceed 15%.
    5. ``stress_drawdown >= -0.25`` — max drawdown in stress scenarios must not exceed 25%.

    Additionally, all boolean diagnostics must be ``True``:

    - ``baseline_increment``: strategy beats the baseline.
    - ``concentration``: returns are not concentrated in one asset.
    - ``parameter_stability``: performance is stable across parameter perturbations.
    - ``leakage``: no data leakage detected.
    - ``reproducibility``: results are reproducible.
    - ``data_quality``: data quality checks passed.
    """

    # Thresholds (design constants — do not tune using PA results)
    MIN_POSITIVE_FOLD_RATIO: float = 0.70
    MIN_MEDIAN_SHARPE: float = 0.80
    MIN_SHARPE_CI_LOWER: float = 0.0
    MIN_NORMAL_MAX_DRAWDOWN: float = -0.15
    MIN_STRESS_DRAWDOWN: float = -0.25

    def evaluate(
        self,
        folds: list[FoldMetrics],
        *,
        sharpe_ci_lower: float,
        stress_drawdown: float,
        baseline_increment: bool = True,
        concentration: bool = True,
        parameter_stability: bool = True,
        leakage: bool = True,
        reproducibility: bool = True,
        data_quality: bool = True,
    ) -> PromotionDecision:
        """Evaluate a strategy against all promotion gates.

        Parameters
        ----------
        folds:
            Per-fold metrics from the normal scenario.
        sharpe_ci_lower:
            Lower bound of the Sharpe ratio confidence interval.
        stress_drawdown:
            Maximum drawdown observed in stress scenarios.
        baseline_increment:
            Whether the strategy beats the baseline.
        concentration:
            Whether returns are diversified (not concentrated).
        parameter_stability:
            Whether performance is stable across parameter perturbations.
        leakage:
            Whether no data leakage was detected.
        reproducibility:
            Whether results are reproducible.
        data_quality:
            Whether data quality checks passed.

        Returns
        -------
        PromotionDecision
        """
        reasons: list[str] = []

        # Gate 1: Positive fold ratio
        if folds:
            positive_count = sum(1 for f in folds if f.net_return > 0)
            ratio = positive_count / len(folds)
        else:
            ratio = 0.0
        if ratio < self.MIN_POSITIVE_FOLD_RATIO:
            reasons.append("POSITIVE_FOLD_RATIO")

        # Gate 2: Median Sharpe
        med_sharpe = median(f.sharpe for f in folds) if folds else 0.0
        if med_sharpe < self.MIN_MEDIAN_SHARPE:
            reasons.append("MEDIAN_SHARPE")

        # Gate 3: Sharpe CI lower bound
        if sharpe_ci_lower <= self.MIN_SHARPE_CI_LOWER:
            reasons.append("SHARPE_CI_LOWER")

        # Gate 4: Normal max drawdown
        normal_mdd = min(f.max_drawdown for f in folds) if folds else -1.0
        if normal_mdd < self.MIN_NORMAL_MAX_DRAWDOWN:
            reasons.append("NORMAL_MAX_DRAWDOWN")

        # Gate 5: Stress drawdown
        if stress_drawdown < self.MIN_STRESS_DRAWDOWN:
            reasons.append("STRESS_DRAWDOWN")

        # Boolean diagnostics
        if not baseline_increment:
            reasons.append("BASELINE_INCREMENT")
        if not concentration:
            reasons.append("CONCENTRATION")
        if not parameter_stability:
            reasons.append("PARAMETER_STABILITY")
        if not leakage:
            reasons.append("LEAKAGE")
        if not reproducibility:
            reasons.append("REPRODUCIBILITY")
        if not data_quality:
            reasons.append("DATA_QUALITY")

        return PromotionDecision(
            passed=len(reasons) == 0,
            reasons=reasons,
        )
