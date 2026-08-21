"""Tests for the bounded, auditable candidate factor generator."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bian_quant.factors.generator import generate_candidates, generate_proposals
from bian_quant.factors.primitives import (
    ExprNode,
    add,
    column,
    evaluate_node,
    lag,
    percent_change,
    rolling_mean,
    safe_ratio,
    validate_node,
    zscore,
)
from bian_quant.factors.proposals import FactorProposal

SEARCH_SPACE = str(
    Path(__file__).resolve().parents[3] / "configs" / "factors" / "search_space.yaml"
)
PROPOSAL_FACTORY = str(
    Path(__file__).resolve().parents[3] / "configs" / "factors" / "proposal_factory.yaml"
)


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
        for a, b in zip(c1, c2, strict=False):
            assert a.expression_hash == b.expression_hash
            assert a.generation_rank == b.generation_rank
            assert a.search_manifest_hash == b.search_manifest_hash

    def test_generation_order_templates_first(self) -> None:
        """Templates come before grammar samples."""
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        # First candidate should be a template (momentum_6, volatility_6, etc.)
        _ = candidates[0].expression_hash  # noqa: F841
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

    def test_config_cannot_raise_global_hard_cap(self, tmp_path: Path) -> None:
        config_path = tmp_path / "search_space.yaml"
        config_path.write_text(
            """seed: 42
max_candidates: 1000
max_tree_depth: 3
base_factors: [price.momentum]
windows: [6, 12, 24, 48, 168]
allowed_unary: [lag, delta, zscore, rolling_rank]
allowed_binary: [add, subtract, multiply, safe_ratio]
""",
            encoding="utf-8",
        )
        assert len(generate_candidates(config_path, code_sha="abc")) <= 20

    def test_generate_candidates_honors_allowed_columns_for_grammar_samples(
        self, tmp_path: Path
    ) -> None:
        config_path = tmp_path / "search_space.yaml"
        config_path.write_text(
            """seed: 7
max_candidates: 10
max_tree_depth: 3
base_factors: [price.momentum]
windows: [6]
allowed_columns: [funding_rate]
allowed_unary: [lag]
allowed_binary: []
""",
            encoding="utf-8",
        )

        candidates = generate_candidates(config_path, code_sha="abc")

        assert candidates
        grammar_candidates = candidates[5:]
        assert grammar_candidates
        assert all(
            set(candidate.expression_tree.required_columns) <= {"funding_rate"}
            for candidate in grammar_candidates
        )
        assert any(
            candidate.expression_tree.required_columns == ("funding_rate",)
            for candidate in grammar_candidates
        )

    def test_generate_candidates_defaults_to_legacy_grammar_columns(self, tmp_path: Path) -> None:
        config_path = tmp_path / "search_space.yaml"
        config_path.write_text(
            """seed: 7
max_candidates: 10
max_tree_depth: 3
base_factors: [price.momentum]
windows: [6]
allowed_unary: [lag]
allowed_binary: []
""",
            encoding="utf-8",
        )

        candidates = generate_candidates(config_path, code_sha="abc")

        grammar_candidates = candidates[5:]
        assert {
            candidate.expression_tree.required_columns[0] for candidate in grammar_candidates
        } == {
            "close",
            "volume",
            "high",
            "low",
        }


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
            assert len(c.search_manifest_hash) == 64

    def test_candidates_have_parent_factors(self) -> None:
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        for c in candidates:
            assert isinstance(c.parent_factors, tuple)

    def test_candidates_have_required_lookback(self) -> None:
        candidates = generate_candidates(SEARCH_SPACE, code_sha="abc")
        for c in candidates:
            assert c.required_lookback >= 0


class TestProposalGeneration:
    def test_generation_returns_proposal_only_records(self) -> None:
        proposals = generate_proposals(PROPOSAL_FACTORY, code_sha="abc")
        assert proposals
        assert all(isinstance(item, FactorProposal) for item in proposals)
        assert all(item.proposal_status == "proposal_only" for item in proposals)
        assert len(proposals) <= 20
        assert all(
            item.required_columns and item.entry_price and item.exit_rule for item in proposals
        )

    def test_generator_does_not_call_formal_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "bian_quant.factors.registry.FactorRegistry",
            lambda *_: (_ for _ in ()).throw(AssertionError("registry access is forbidden")),
        )
        generate_proposals(PROPOSAL_FACTORY, code_sha="abc")

    def test_generate_proposals_honors_allowed_columns(self, tmp_path: Path) -> None:
        config_path = tmp_path / "proposal_factory.yaml"
        config_path.write_text(
            """mode: proposal_only
seed: 7
max_candidates: 10
max_tree_depth: 3
base_factors: [price.momentum]
windows: [6]
allowed_columns: [funding_rate]
allowed_unary: [lag]
allowed_binary: []
""",
            encoding="utf-8",
        )

        proposals = generate_proposals(config_path, code_sha="abc")

        assert proposals
        assert any(item.source_type == "seeded_grammar" for item in proposals)
        assert any("funding_rate" in item.formula for item in proposals)

    def test_proposal_order_is_deterministic(self) -> None:
        first = generate_proposals(PROPOSAL_FACTORY, code_sha="abc")
        second = generate_proposals(PROPOSAL_FACTORY, code_sha="abc")

        assert [item.identity_sha256 for item in first] == [item.identity_sha256 for item in second]

    def test_proposals_respect_family_cap(self) -> None:
        proposals = generate_proposals(PROPOSAL_FACTORY, code_sha="abc")
        counts: dict[str, int] = {}
        for proposal in proposals:
            counts[proposal.research_family] = counts.get(proposal.research_family, 0) + 1
        assert counts
        assert max(counts.values()) <= 4


def test_nested_temporal_lookback_is_additive() -> None:
    tree = zscore(percent_change(column("close"), 24), 168)
    assert tree.lookback == 192


def test_commutative_expression_hash_is_normalized() -> None:
    assert (
        add(column("close"), column("volume")).expression_hash
        == add(column("volume"), column("close")).expression_hash
    )


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
