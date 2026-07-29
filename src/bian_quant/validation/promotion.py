from dataclasses import dataclass
from math import isfinite
from statistics import median


@dataclass(frozen=True)
class FoldMetrics:
    net_return: float
    sharpe: float
    max_drawdown: float


@dataclass(frozen=True)
class PromotionDiagnostics:
    baseline_increment: bool
    concentration: bool
    parameter_stability: bool
    leakage: bool
    reproducibility: bool
    data_quality: bool


@dataclass(frozen=True)
class PromotionDecision:
    passed: bool
    reasons: tuple[str, ...]
    positive_fold_ratio: float
    median_sharpe: float
    normal_max_drawdown: float
    sharpe_ci_lower: float
    stress_drawdown: float


class PromotionPolicy:
    MIN_POSITIVE_FOLD_RATIO = 0.70
    MIN_MEDIAN_SHARPE = 0.80
    MIN_SHARPE_CI_LOWER = 0.0
    MIN_NORMAL_MAX_DRAWDOWN = -0.15
    MIN_STRESS_DRAWDOWN = -0.25

    def evaluate(
        self,
        folds: list[FoldMetrics],
        *,
        sharpe_ci_lower: float,
        stress_drawdown: float,
        diagnostics: PromotionDiagnostics,
    ) -> PromotionDecision:
        if not folds:
            raise ValueError("promotion requires at least one OOS fold")
        values = [
            value for fold in folds for value in (fold.net_return, fold.sharpe, fold.max_drawdown)
        ] + [sharpe_ci_lower, stress_drawdown]
        if not all(isfinite(value) for value in values):
            raise ValueError("promotion metrics must be finite")

        positive_fold_ratio = sum(fold.net_return > 0 for fold in folds) / len(folds)
        median_sharpe = float(median(fold.sharpe for fold in folds))
        normal_max_drawdown = min(fold.max_drawdown for fold in folds)
        reasons: list[str] = []
        if positive_fold_ratio < self.MIN_POSITIVE_FOLD_RATIO:
            reasons.append("POSITIVE_FOLD_RATIO")
        if median_sharpe < self.MIN_MEDIAN_SHARPE:
            reasons.append("MEDIAN_SHARPE")
        if sharpe_ci_lower <= self.MIN_SHARPE_CI_LOWER:
            reasons.append("SHARPE_CI_LOWER")
        if normal_max_drawdown < self.MIN_NORMAL_MAX_DRAWDOWN:
            reasons.append("NORMAL_MAX_DRAWDOWN")
        if stress_drawdown < self.MIN_STRESS_DRAWDOWN:
            reasons.append("STRESS_DRAWDOWN")

        diagnostic_values = {
            "BASELINE_INCREMENT": diagnostics.baseline_increment,
            "CONCENTRATION": diagnostics.concentration,
            "PARAMETER_STABILITY": diagnostics.parameter_stability,
            "LEAKAGE": diagnostics.leakage,
            "REPRODUCIBILITY": diagnostics.reproducibility,
            "DATA_QUALITY": diagnostics.data_quality,
        }
        reasons.extend(code for code, passed in diagnostic_values.items() if not passed)
        return PromotionDecision(
            passed=not reasons,
            reasons=tuple(reasons),
            positive_fold_ratio=positive_fold_ratio,
            median_sharpe=median_sharpe,
            normal_max_drawdown=normal_max_drawdown,
            sharpe_ci_lower=sharpe_ci_lower,
            stress_drawdown=stress_drawdown,
        )
