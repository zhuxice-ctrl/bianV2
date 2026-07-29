"""Tests for factor evaluation, IC, and multiple-testing correction."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bian_quant.factors.evaluate import evaluate_factor
from bian_quant.factors.multiple_testing import benjamini_hochberg


def test_perfect_correlation_produces_rank_ic_one() -> None:
    """Factor [1,2,3,4] and label [10,20,30,40] must produce RankIC 1.0."""
    factor = pd.Series([1.0, 2.0, 3.0, 4.0], name="test_factor")
    label = pd.Series([10.0, 20.0, 30.0, 40.0])
    metadata = pd.DataFrame({"asset": ["A"] * 4, "regime": ["all"] * 4})

    results = evaluate_factor(factor, label, metadata, fold="fold_0")
    assert len(results) == 1
    assert results[0].spearman_ic == 1.0
    assert results[0].pearson_ic == pytest.approx(1.0, abs=1e-3)
    # CI is NaN for small samples (< 10)
    assert np.isnan(results[0].ci_lower)


def test_metadata_produces_all_group_keys() -> None:
    """Two assets, two folds, two regimes → 8 group keys, no pooled."""
    factor = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0], name="f")
    label = pd.Series([2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0])
    metadata = pd.DataFrame(
        {
            "asset": ["BTC", "BTC", "BTC", "BTC", "ETH", "ETH", "ETH", "ETH"],
            "regime": ["trend", "range", "trend", "range", "trend", "range", "trend", "range"],
        }
    )

    # Evaluate per fold
    all_results = []
    for fold in ["fold_1", "fold_2"]:
        all_results.extend(evaluate_factor(factor, label, metadata, fold=fold))

    # 2 folds × 2 assets × 2 regimes = 8 groups
    assert len(all_results) == 8

    # Verify no pooled group
    group_keys = {(r.fold, r.asset, r.regime) for r in all_results}
    assert len(group_keys) == 8
    assert ("fold_1", "BTC", "trend") in group_keys
    assert ("fold_2", "ETH", "range") in group_keys


def test_benjamini_hochberg() -> None:
    """p={a:0.001, b:0.02, c:0.20} at alpha=0.05 → accept a and b, reject c."""
    p_values = {"a": 0.001, "b": 0.02, "c": 0.20}
    result = benjamini_hochberg(p_values, alpha=0.05)
    assert result["a"] is True
    assert result["b"] is True
    assert result["c"] is False


def test_bh_rejects_all_when_all_pvalues_high() -> None:
    p_values = {"a": 0.10, "b": 0.20, "c": 0.30}
    result = benjamini_hochberg(p_values, alpha=0.05)
    assert all(not v for v in result.values())


def test_bh_validates_p_value_range() -> None:
    with pytest.raises(ValueError, match="out of range"):
        benjamini_hochberg({"a": -0.01}, alpha=0.05)
    with pytest.raises(ValueError, match="out of range"):
        benjamini_hochberg({"a": 1.01}, alpha=0.05)


def test_coverage_and_sample_count_with_missing() -> None:
    """Factor [1.0, NaN, 3.0, NaN] must report coverage 0.5 and sample_count 2."""
    factor = pd.Series([1.0, np.nan, 3.0, np.nan], name="f")
    label = pd.Series([10.0, 20.0, 30.0, 40.0])
    metadata = pd.DataFrame({"asset": ["A"] * 4, "regime": ["all"] * 4})

    results = evaluate_factor(factor, label, metadata, fold="fold_0")
    assert len(results) == 1
    assert results[0].coverage == 0.5
    assert results[0].sample_count == 2


def test_missing_values_not_turned_to_zeros() -> None:
    """The evaluator must not turn missing values into zeros."""
    factor = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0, 6.0], name="f")
    label = pd.Series([10.0, 20.0, 30.0, 40.0, 50.0, 60.0])
    metadata = pd.DataFrame({"asset": ["A"] * 6, "regime": ["all"] * 6})

    results = evaluate_factor(factor, label, metadata, fold="fold_0")
    assert len(results) == 1
    # Coverage should be 4/6, not 6/6
    assert results[0].coverage == 4 / 6
    assert results[0].sample_count == 4


def test_confidence_interval_is_reported() -> None:
    factor = pd.Series(np.random.default_rng(42).normal(0, 1, 100), name="f")
    label = pd.Series(np.random.default_rng(43).normal(0, 1, 100))
    metadata = pd.DataFrame({"asset": ["A"] * 100, "regime": ["all"] * 100})

    results = evaluate_factor(factor, label, metadata, fold="fold_0")
    assert len(results) == 1
    r = results[0]
    # CI should be reported (not NaN for 100 samples)
    assert not np.isnan(r.ci_lower)
    assert not np.isnan(r.ci_upper)
    assert r.ci_lower <= r.ci_upper
