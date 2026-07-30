"""Unit controls for locked development promotion gates."""

from __future__ import annotations

from typing import Any

import pandas as pd

import bian_quant.research.dual_horizon as research
from bian_quant.factors.dual_horizon import dual_horizon_factor_specs
from bian_quant.factors.evaluate import FactorEvaluation
from bian_quant.factors.multiple_testing import benjamini_hochberg_details
from bian_quant.factors.redundancy import ClusterResult, IncrementalResult


def _evaluations(name: str) -> list[FactorEvaluation]:
    slices = [
        ("fold_0", "BTCUSDT", "trend_low_vol"),
        ("fold_0", "ETHUSDT", "range_low_vol"),
        ("fold_1", "BTCUSDT", "range_low_vol"),
        ("fold_1", "ETHUSDT", "trend_low_vol"),
    ]
    return [
        FactorEvaluation(
            factor_name=name,
            fold=fold,
            asset=asset,
            regime=regime,
            pearson_ic=0.2,
            spearman_ic=0.2,
            coverage=1.0,
            turnover=0.1,
            sample_count=30,
            p_value=0.001,
            ci_lower=0.05,
            ci_upper=0.3,
        )
        for fold, asset, regime in slices
    ]


def _incremental(name: str, cost: int, delta: float = 0.001) -> IncrementalResult:
    return IncrementalResult(
        factor_name=name,
        standalone_ic=0.2,
        baseline_ic=0.1,
        full_ic=0.2,
        incremental_ic=0.1,
        baseline_cost_adjusted_return=0.001,
        full_cost_adjusted_return=0.001 + delta,
        delta_cost_adjusted_return=delta,
        has_incremental_value=cost == 5 or delta >= 0,
    )


def _accepted(evaluations: list[FactorEvaluation]) -> dict[str, Any]:
    return benjamini_hochberg_details(
        {research._evaluation_key(item): item.p_value for item in evaluations}, alpha=0.05
    )


def test_all_locked_gates_are_required_for_candidate(monkeypatch: Any) -> None:
    name = "momentum_24"
    evaluations = _evaluations(name)
    monkeypatch.setattr(research, "_factor_direction", lambda *_args: 1.0)
    sensitivity = pd.DataFrame({name: [1.0]})
    cluster = ClusterResult({name: 0}, {0: name}, {})
    incrementals = {name: {5: _incremental(name, 5), 10: _incremental(name, 10)}}

    gates, diagnostics, candidates = research._apply_gates(
        [name],
        {name: dual_horizon_factor_specs()[0]},
        evaluations,
        _accepted(evaluations),
        cluster,
        incrementals,
        sensitivity=sensitivity,
        delay_frames={},
        primary=pd.DataFrame(),
        interval="4h",
    )

    assert gates[name] == ["ALL_DEVELOPMENT_GATES_PASSED"]
    assert diagnostics[name]["asset_support_concentration"] == 0.5
    assert diagnostics[name]["regime_support_concentration"] == 0.5
    assert candidates == [name]

    incrementals[name][5] = _incremental(name, 5, delta=0.0)
    failed, _, failed_candidates = research._apply_gates(
        [name],
        {name: dual_horizon_factor_specs()[0]},
        evaluations,
        _accepted(evaluations),
        cluster,
        incrementals,
        sensitivity=sensitivity,
        delay_frames={},
        primary=pd.DataFrame(),
        interval="4h",
    )
    assert "FINAL_FOLD_5BPS_NON_POSITIVE" in failed[name]
    assert failed_candidates == []


def test_oi_factor_requires_all_three_delay_scenarios(monkeypatch: Any) -> None:
    name = "oi_change"
    evaluations = _evaluations(name)
    monkeypatch.setattr(research, "_factor_direction", lambda *_args: 1.0)

    gates, _, candidates = research._apply_gates(
        [name],
        {name: dual_horizon_factor_specs()[6]},
        evaluations,
        _accepted(evaluations),
        ClusterResult({name: 0}, {0: name}, {}),
        {name: {5: _incremental(name, 5), 10: _incremental(name, 10)}},
        sensitivity=pd.DataFrame({name: [1.0]}),
        delay_frames={},
        primary=pd.DataFrame(),
        interval="4h",
    )

    assert "OI_DELAY_STABILITY_UNAVAILABLE" in gates[name]
    assert candidates == []
