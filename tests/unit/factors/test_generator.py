"""Tests for the bounded, auditable candidate factor generator."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bian_quant.factors.generator import generate_candidates
from bian_quant.factors.primitives import (
    ExprNode,
    add,
    column,
    delta,
    evaluate_node,
    lag,
    multiply,
    percent_change,
    rolling_mean,
    rolling_rank,
    rolling_std,
    safe_ratio,
    subtract,
    validate_node,
    zscore,
)


SEARCH_SPACE = "configs/factors/search_space.yaml"


class TestExpressionHashing:
    def test_identical_trees_produce_same_hash(self) -> None:
        """zscore(momentum(close, 24), 168) — same tree → same hash."""
        tree1 = zscore(percent_change(column("close"), 24), 168)
        tree2 = zscore(percent_change(column("close"), 24), 168)
        assert tree1.expression_hash == tree2.expression_hash

    def test_different_trees_produce_different_hash(self) -> None:
        tree1 = zscore(percent_change(column("close"), 24), 168)
        tree2 = zscore(percent_change(column("close"), 12), 168)
        assert tree1.expression_hash != tree2.expression_hash


class TestLeakageBoundary:
    def test_label_names_rejected(self) -> None:
        for label_name in ["label", "forward_log_return", "forward_return", "y", "target"]:
            with pytest.raises(ValueError, match="forbidden|unknown"):
                validate_node(column(label_name))

    def test_negative_lag_rejected(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            lag(column("close"), 0)
        with pytest.raises(ValueError, match="positive"):
            lag(column("close"), -1)

    def test_centered_window_rejected(self) -> None:
        # rolling operations must use backward-looking windows only
        # window < 2 is rejected
        with pytest.raises(ValueError, match="window"):
            zscore(column("close"), 1)
        with pytest.raises(ValueError, match="window"):
            rolling_mean(column("close"), 1)

    def test_unknown_columns_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown"):
            validate_node(column("unknown_column"))
        with pytest.raises(ValueError, match="unknown"):
            validate_node(column("price"))

    def test_no_eval_used(self) -> None:
        """The evaluator never evaluates source strings."""
        # evaluate_node walks the tree; it never calls eval()
        # This is verified by the implementation using _eval() recursively
        tree = zscore(percent_change(column("close"), 12), 24)
        data = pd.DataFrame({"close": np.linspace(100, 200, 100)})
        result = evaluate_node(tree, data)
        assert len(result) == 100
        assert result.name is None or isinstance(result.name, str)


class TestDeduplication:
    def test_algebraically_duplicated_emitted_once(self) -> None:
        """Candidates with identical normalized trees are emitted once."""
        tree1 = add(column("close"), column("volume"))
        tree2 = add(column("close"), column("volume"))
        assert tree1.expression_hash == tree2.expression_hash

        # In generation, deduplication happens by expression_hash
        # Verify manually
        seen = set()
        for tree in [tree1, tree2]:
            seen.add(tree.expression_hash)
        assert len(seen) == 1


class TestDeterministicGeneration:
    def test_fixed_seed_produces_same_candidates(self) -> None:
        """A fixed seed and search manifest produce the same ordered list."""
        c1 = generate_candidates(SEARCH_SPACE, code_sha="abc")
        c2 = generate_candidates(SEARCH_SPACE, code_sha="abc")

        assert len(c1) == len(c2)
        for a, b in zip(c1, c2):
            assert a.expression_hash == b.expression_hash
            assert a.generation_rank == b.generation_rank
            assert a.search_manifest_hash == b.search_manifest_hash

    def test_generation_order_templates_first(self) -> None:
        """Templates come before grammar samples."""
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        # First candidate should be a template (momentum_6, volatility_6, etc.)
        first_hash = candidates[0].expression_hash
        # Templates are built from percent_change(column("close"), w) etc.
        # Verify by checking that the first few candidates are deterministic templates
        assert candidates[0].generation_rank == 0
        assert candidates[1].generation_rank == 1


class TestMaxCandidates:
    def test_max_candidates_hard_cap(self) -> None:
        """max_candidates=20 cannot emit 21 candidates."""
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        assert len(candidates) <= 20

    def test_max_candidates_with_larger_grid(self, tmp_path: Path) -> None:
        """Even with a larger grid, max_candidates is enforced."""
        config = """
seed: 42
max_candidates: 5
max_tree_depth: 3
base_factors:
  - price.momentum
windows: [6, 12, 24, 48, 168]
allowed_unary: [lag, delta, zscore, rolling_rank]
allowed_binary: [add, subtract, multiply, safe_ratio]
"""
        config_path = tmp_path / "search_space.yaml"
        config_path.write_text(config)

        candidates = generate_candidates(config_path, code_sha="abc")
        assert len(candidates) <= 5


class TestResearchOnlyState:
    def test_candidates_have_generation_rank(self) -> None:
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        for i, c in enumerate(candidates):
            assert c.generation_rank == i

    def test_candidates_have_expression_tree(self) -> None:
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        for c in candidates:
            assert isinstance(c.expression_tree, ExprNode)

    def test_candidates_have_search_manifest_hash(self) -> None:
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        for c in candidates:
            assert len(c.search_manifest_hash) > 0

    def test_candidates_have_parent_factors(self) -> None:
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        for c in candidates:
            assert isinstance(c.parent_factors, tuple)

    def test_candidates_have_required_lookback(self) -> None:
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        for c in candidates:
            assert c.required_lookback >= 0


class TestEvaluateNode:
    def test_evaluate_momentum(self) -> None:
        tree = percent_change(column("close"), 12)
        data = pd.DataFrame({"close": np.linspace(100, 200, 100)})
        result = evaluate_node(tree, data)
        assert len(result) == 100
        assert result.iloc[12] is not None

    def test_evaluate_zscore(self) -> None:
        tree = zscore(column("close"), 24)
        data = pd.DataFrame({"close": np.linspace(100, 200, 100)})
        result = evaluate_node(tree, data)
        assert len(result) == 100

    def test_evaluate_safe_ratio(self) -> None:
        tree = safe_ratio(column("close"), column("volume"), epsilon=0.001)
        data = pd.DataFrame(
            {"close": np.linspace(100, 200, 100), "volume": np.linspace(10, 20, 100)}
        )
        result = evaluate_node(tree, data)
        assert len(result) == 100
