"""Tests for the promotion policy gates."""

from __future__ import annotations

from bian_quant.validation.promotion import FoldMetrics, PromotionPolicy


def test_policy_rejects_strategy_driven_by_one_fold() -> None:
    """A strategy where only 1 of 4 folds is profitable fails POSITIVE_FOLD_RATIO."""
    folds = [
        FoldMetrics(net_return=0.50, sharpe=3.0, max_drawdown=-0.10),
        FoldMetrics(net_return=-0.02, sharpe=-0.2, max_drawdown=-0.12),
        FoldMetrics(net_return=-0.01, sharpe=-0.1, max_drawdown=-0.08),
        FoldMetrics(net_return=-0.03, sharpe=-0.3, max_drawdown=-0.09),
    ]

    decision = PromotionPolicy().evaluate(folds, sharpe_ci_lower=-0.1, stress_drawdown=-0.20)

    assert not decision.passed
    assert "POSITIVE_FOLD_RATIO" in decision.reasons


def test_policy_rejects_low_median_sharpe() -> None:
    """A strategy with median Sharpe below 0.80 fails MEDIAN_SHARPE."""
    folds = [
        FoldMetrics(net_return=0.10, sharpe=2.0, max_drawdown=-0.05),
        FoldMetrics(net_return=0.08, sharpe=0.5, max_drawdown=-0.06),
        FoldMetrics(net_return=0.06, sharpe=0.4, max_drawdown=-0.04),
        FoldMetrics(net_return=0.04, sharpe=0.3, max_drawdown=-0.03),
    ]

    decision = PromotionPolicy().evaluate(folds, sharpe_ci_lower=0.1, stress_drawdown=-0.10)

    assert not decision.passed
    assert "MEDIAN_SHARPE" in decision.reasons


def test_policy_rejects_non_positive_sharpe_ci() -> None:
    """A strategy with Sharpe CI lower bound <= 0 fails SHARPE_CI_LOWER."""
    folds = [
        FoldMetrics(net_return=0.10, sharpe=1.5, max_drawdown=-0.05),
        FoldMetrics(net_return=0.08, sharpe=1.2, max_drawdown=-0.04),
        FoldMetrics(net_return=0.06, sharpe=1.0, max_drawdown=-0.03),
        FoldMetrics(net_return=0.04, sharpe=0.9, max_drawdown=-0.02),
    ]

    decision = PromotionPolicy().evaluate(folds, sharpe_ci_lower=0.0, stress_drawdown=-0.10)

    assert not decision.passed
    assert "SHARPE_CI_LOWER" in decision.reasons


def test_policy_rejects_excessive_normal_drawdown() -> None:
    """A strategy with normal max drawdown below -15% fails NORMAL_MAX_DRAWDOWN."""
    folds = [
        FoldMetrics(net_return=0.10, sharpe=1.5, max_drawdown=-0.05),
        FoldMetrics(net_return=0.08, sharpe=1.2, max_drawdown=-0.20),
        FoldMetrics(net_return=0.06, sharpe=1.0, max_drawdown=-0.03),
        FoldMetrics(net_return=0.04, sharpe=0.9, max_drawdown=-0.02),
    ]

    decision = PromotionPolicy().evaluate(folds, sharpe_ci_lower=0.1, stress_drawdown=-0.10)

    assert not decision.passed
    assert "NORMAL_MAX_DRAWDOWN" in decision.reasons


def test_policy_rejects_excessive_stress_drawdown() -> None:
    """A strategy with stress drawdown below -25% fails STRESS_DRAWDOWN."""
    folds = [
        FoldMetrics(net_return=0.10, sharpe=1.5, max_drawdown=-0.05),
        FoldMetrics(net_return=0.08, sharpe=1.2, max_drawdown=-0.04),
        FoldMetrics(net_return=0.06, sharpe=1.0, max_drawdown=-0.03),
        FoldMetrics(net_return=0.04, sharpe=0.9, max_drawdown=-0.02),
    ]

    decision = PromotionPolicy().evaluate(folds, sharpe_ci_lower=0.1, stress_drawdown=-0.30)

    assert not decision.passed
    assert "STRESS_DRAWDOWN" in decision.reasons


def test_policy_rejects_failed_diagnostics() -> None:
    """Any false diagnostic adds a reason code and fails the decision."""
    folds = [
        FoldMetrics(net_return=0.10, sharpe=1.5, max_drawdown=-0.05),
        FoldMetrics(net_return=0.08, sharpe=1.2, max_drawdown=-0.04),
        FoldMetrics(net_return=0.06, sharpe=1.0, max_drawdown=-0.03),
        FoldMetrics(net_return=0.04, sharpe=0.9, max_drawdown=-0.02),
    ]

    decision = PromotionPolicy().evaluate(
        folds,
        sharpe_ci_lower=0.1,
        stress_drawdown=-0.10,
        baseline_increment=False,
        reproducibility=False,
    )

    assert not decision.passed
    assert "BASELINE_INCREMENT" in decision.reasons
    assert "REPRODUCIBILITY" in decision.reasons


def test_policy_passes_all_gates() -> None:
    """A strategy passing all gates gets a clean pass."""
    folds = [
        FoldMetrics(net_return=0.15, sharpe=2.0, max_drawdown=-0.05),
        FoldMetrics(net_return=0.12, sharpe=1.5, max_drawdown=-0.04),
        FoldMetrics(net_return=0.10, sharpe=1.2, max_drawdown=-0.03),
        FoldMetrics(net_return=0.08, sharpe=1.0, max_drawdown=-0.02),
    ]

    decision = PromotionPolicy().evaluate(
        folds,
        sharpe_ci_lower=0.5,
        stress_drawdown=-0.10,
    )

    assert decision.passed
    assert decision.reasons == []


def test_policy_does_not_mutate_reasons() -> None:
    """Reason codes should be stable across calls."""
    folds = [
        FoldMetrics(net_return=-0.01, sharpe=-0.1, max_drawdown=-0.20),
    ]

    d1 = PromotionPolicy().evaluate(folds, sharpe_ci_lower=-0.1, stress_drawdown=-0.30)
    d2 = PromotionPolicy().evaluate(folds, sharpe_ci_lower=-0.1, stress_drawdown=-0.30)

    assert d1.reasons == d2.reasons
