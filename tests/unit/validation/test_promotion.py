from dataclasses import replace

from bian_quant.validation.promotion import (
    FoldMetrics,
    PromotionDiagnostics,
    PromotionPolicy,
)
from bian_quant.validation.scenarios import all_scenarios, base_config


def _diagnostics() -> PromotionDiagnostics:
    return PromotionDiagnostics(
        baseline_increment=True,
        concentration=True,
        parameter_stability=True,
        leakage=True,
        reproducibility=True,
        data_quality=True,
    )


def test_policy_rejects_strategy_driven_by_one_fold() -> None:
    folds = [
        FoldMetrics(net_return=0.50, sharpe=3.0, max_drawdown=-0.10),
        FoldMetrics(net_return=-0.02, sharpe=-0.2, max_drawdown=-0.12),
        FoldMetrics(net_return=-0.01, sharpe=-0.1, max_drawdown=-0.08),
        FoldMetrics(net_return=-0.03, sharpe=-0.3, max_drawdown=-0.09),
    ]
    decision = PromotionPolicy().evaluate(
        folds,
        sharpe_ci_lower=-0.1,
        stress_drawdown=-0.20,
        diagnostics=_diagnostics(),
    )
    assert not decision.passed
    assert "POSITIVE_FOLD_RATIO" in decision.reasons


def test_false_diagnostic_always_blocks() -> None:
    folds = [FoldMetrics(net_return=0.1, sharpe=1.0, max_drawdown=-0.1)] * 4
    decision = PromotionPolicy().evaluate(
        folds,
        sharpe_ci_lower=0.1,
        stress_drawdown=-0.2,
        diagnostics=replace(_diagnostics(), leakage=False),
    )
    assert decision.reasons == ("LEAKAGE",)


def test_all_required_scenarios_are_distinct_and_base_is_unchanged() -> None:
    base = base_config()
    scenarios = all_scenarios(base)
    assert set(scenarios) == {
        "ideal",
        "normal",
        "double_cost",
        "one_bar_delay",
        "parameter_down",
        "parameter_up",
        "data_gap",
        "price_spike",
    }
    assert scenarios["one_bar_delay"].execution_delay_bars == 2
    assert scenarios["data_gap"].data_gap_fraction > 0
    assert scenarios["price_spike"].price_spike_fraction > 0
    assert base == base_config()
