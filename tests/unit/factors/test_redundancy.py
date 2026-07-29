"""Tests for factor redundancy clustering and incremental contribution."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from bian_quant.factors.redundancy import (
    cluster_redundant_factors,
    evaluate_incremental_contribution,
)


def test_redundant_factor_shares_cluster() -> None:
    """An exact scaled copy shares a cluster with the original."""
    rng = np.random.default_rng(42)
    base = rng.normal(0, 1, 100)

    factors = pd.DataFrame(
        {
            "momentum": base,
            "momentum_scaled": base * 2.0 + 1.0,  # exact linear transform
            "independent": rng.normal(0, 1, 100),
        }
    )

    result = cluster_redundant_factors(factors, distance_threshold=0.3)

    # momentum and momentum_scaled should be in the same cluster
    assert result.clusters["momentum"] == result.clusters["momentum_scaled"]
    # independent should be in a different cluster
    assert result.clusters["independent"] != result.clusters["momentum"]
    # One is rejected as redundant
    assert "momentum_scaled" in result.rejected or "momentum" in result.rejected


def test_representative_uses_inner_validation_score() -> None:
    """Scaled copy cannot both become the cluster representative."""
    rng = np.random.default_rng(42)
    base = rng.normal(0, 1, 100)

    factors = pd.DataFrame(
        {
            "factor_a": base,
            "factor_b": base * 3.0,  # redundant
        }
    )

    # factor_a has higher validation score
    scores = {"factor_a": 0.05, "factor_b": 0.02}
    result = cluster_redundant_factors(
        factors, distance_threshold=0.3, inner_validation_scores=scores
    )

    # factor_a should be the representative
    cluster_id = result.clusters["factor_a"]
    assert result.representatives[cluster_id] == "factor_a"
    assert "factor_b" in result.rejected


def test_single_factor_no_clustering() -> None:
    factors = pd.DataFrame({"only": np.random.default_rng(42).normal(0, 1, 50)})
    result = cluster_redundant_factors(factors)
    assert result.clusters == {"only": 0}
    assert result.representatives == {0: "only"}
    assert result.rejected == {}


def test_incremental_contribution_positive() -> None:
    """An independent factor with signal has positive incremental IC."""
    rng = np.random.default_rng(42)
    n = 200

    label = rng.normal(0, 1, n)
    baseline = pd.DataFrame({"base": rng.normal(0, 1, n)})
    candidate = label * 0.3 + rng.normal(0, 0.5, n)  # correlated with label

    result = evaluate_incremental_contribution(
        pd.Series(candidate, name="cand"),
        baseline,
        pd.Series(label),
        factor_name="cand",
    )

    assert result.standalone_ic > 0
    assert result.incremental_ic > 0
    assert result.has_incremental_value


def test_incremental_contribution_zero_for_redundant() -> None:
    """A factor redundant with baseline has no incremental value."""
    rng = np.random.default_rng(42)
    n = 200

    base_signal = rng.normal(0, 1, n)
    label = base_signal * 0.5 + rng.normal(0, 0.5, n)

    baseline = pd.DataFrame({"base": base_signal})
    # Candidate is just a scaled copy of baseline
    candidate = base_signal * 2.0

    result = evaluate_incremental_contribution(
        pd.Series(candidate, name="cand"),
        baseline,
        pd.Series(label),
        factor_name="cand",
    )

    assert result.standalone_ic > 0  # has signal on its own
    assert not result.has_incremental_value  # but no incremental value


def test_no_incremental_means_stays_observed() -> None:
    """A factor with no incremental value remains observed, not promoted."""
    rng = np.random.default_rng(42)
    n = 100

    base = rng.normal(0, 1, n)
    label = base * 0.3 + rng.normal(0, 0.5, n)

    baseline = pd.DataFrame({"base": base})
    candidate = base * 1.5  # perfectly redundant

    result = evaluate_incremental_contribution(
        pd.Series(candidate, name="cand"),
        baseline,
        pd.Series(label),
        factor_name="cand",
    )

    # Even if standalone IC is strong, no incremental value
    assert result.standalone_ic > 0.1
    assert not result.has_incremental_value
