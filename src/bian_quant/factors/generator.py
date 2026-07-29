"""Bounded, deterministic, auditable candidate factor generator.

Generation order: registered economic templates first, then seeded grammar
samples.  ``max_candidates=20`` is a hard upper bound.  All candidates
register as ``researching`` and cannot transition during generation.
"""

from __future__ import annotations

import hashlib
import itertools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bian_quant.factors.primitives import (
    ExprNode,
    add,
    column,
    delta,
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


@dataclass(frozen=True)
class CandidateFactor:
    """A generated candidate factor with full audit trail."""

    expression_tree: ExprNode
    expression_hash: str
    search_manifest_hash: str
    generation_rank: int
    parent_factors: tuple[str, ...]
    required_lookback: int
    code_sha: str
    factor_id: str = ""

    def __post_init__(self) -> None:
        if not self.factor_id:
            object.__setattr__(self, "factor_id", f"candidate.{self.expression_hash}")


def _load_search_space(config_path: Path | str) -> dict[str, Any]:
    """Load search space configuration."""
    with open(config_path, encoding="utf-8") as file:
        loaded = yaml.safe_load(file)
    if not isinstance(loaded, dict):
        raise ValueError("search space must be a YAML mapping")
    return {str(key): value for key, value in loaded.items()}


def _build_templates(windows: list[int]) -> list[tuple[str, ExprNode]]:
    """Build registered economic template expressions."""
    templates: list[tuple[str, ExprNode]] = []

    for w in windows:
        templates.append((f"momentum_{w}", percent_change(column("close"), w)))
        templates.append((f"volatility_{w}", rolling_std(column("close"), w)))
        templates.append((f"volume_trend_{w}", rolling_mean(column("volume"), w)))
        templates.append((f"zscore_close_{w}", zscore(column("close"), w)))
        templates.append((f"rank_close_{w}", rolling_rank(column("close"), w)))

    return templates


def _build_grammar_samples(
    windows: list[int],
    allowed_unary: list[str],
    allowed_binary: list[str],
    columns: list[str],
    rng_seed: int,
) -> list[tuple[str, ExprNode]]:
    """Build seeded grammar sample expressions."""
    rng = __import__("numpy").random.default_rng(rng_seed)

    samples: list[tuple[str, ExprNode]] = []

    unary_ops = {
        "lag": lambda n, w: lag(n, w),
        "delta": lambda n, w: delta(n, w),
        "zscore": lambda n, w: zscore(n, w),
        "rolling_rank": lambda n, w: rolling_rank(n, w),
    }
    binary_ops: dict[str, Any] = {
        "add": add,
        "subtract": subtract,
        "multiply": multiply,
        "safe_ratio": safe_ratio,
    }

    # Generate combinations: unary(column, window)
    for col_name, w, op_name in itertools.product(columns, windows, allowed_unary):
        if op_name in unary_ops and col_name not in ("label", "target", "y"):
            try:
                node = unary_ops[op_name](column(col_name), w)
                validate_node(node)
                samples.append((f"{op_name}_{col_name}_{w}", node))
            except ValueError:
                pass

    # Generate binary combinations
    for w, op_name in itertools.product(windows, allowed_binary):
        if op_name in binary_ops:
            for col_a, col_b in itertools.product(columns, columns):
                if col_a == col_b:
                    continue
                if col_a in ("label", "target", "y") or col_b in ("label", "target", "y"):
                    continue
                try:
                    a = rolling_mean(column(col_a), w)
                    b = rolling_mean(column(col_b), w)
                    node = binary_ops[op_name](a, b)
                    validate_node(node)
                    samples.append((f"{op_name}_{col_a}_{col_b}_{w}", node))
                except ValueError:
                    pass

    # Shuffle deterministically
    rng.shuffle(samples)
    return samples


def generate_candidates(
    config_path: Path | str,
    *,
    code_sha: str = "",
) -> list[CandidateFactor]:
    """Generate bounded, deterministic candidate factors.

    Parameters
    ----------
    config_path
        Path to the search space YAML configuration.
    code_sha
        Code SHA for audit trail.

    Returns
    -------
    List of ``CandidateFactor`` objects,最多 ``max_candidates`` 个.
    """
    config = _load_search_space(config_path)

    seed = config.get("seed", 7)
    configured_max = int(config.get("max_candidates", 20))
    if configured_max <= 0:
        raise ValueError("max_candidates must be positive")
    max_candidates = min(configured_max, 20)
    max_tree_depth = int(config.get("max_tree_depth", 3))
    if max_tree_depth <= 0:
        raise ValueError("max_tree_depth must be positive")
    base_factors = config.get("base_factors", [])
    windows = config.get("windows", [6, 12, 24, 48, 168])
    allowed_unary = config.get("allowed_unary", ["lag", "delta", "zscore", "rolling_rank"])
    allowed_binary = config.get("allowed_binary", ["add", "subtract", "multiply", "safe_ratio"])

    # Compute search manifest hash
    manifest_str = yaml.dump(config, sort_keys=True, default_flow_style=False)
    search_manifest_hash = hashlib.sha256(manifest_str.encode()).hexdigest()

    # 1. Templates first (deterministic order)
    templates = _build_templates(windows)
    # 2. Grammar samples (seeded, deterministic)
    grammar_samples = _build_grammar_samples(
        windows, allowed_unary, allowed_binary, ["close", "volume", "high", "low"], seed
    )

    # Combine and deduplicate by expression hash
    all_expressions: list[tuple[str, ExprNode]] = templates + grammar_samples
    seen_hashes: set[str] = set()
    unique: list[tuple[str, ExprNode]] = []
    for name, node in all_expressions:
        if node.depth > max_tree_depth:
            continue
        h = node.expression_hash
        if h not in seen_hashes:
            seen_hashes.add(h)
            unique.append((name, node))

    # Enforce max_candidates hard cap
    unique = unique[:max_candidates]

    candidates: list[CandidateFactor] = []
    for rank, (name, node) in enumerate(unique):
        parent_factors = _parents_for_expression(name, node, base_factors)
        candidates.append(
            CandidateFactor(
                expression_tree=node,
                expression_hash=node.expression_hash,
                search_manifest_hash=search_manifest_hash,
                generation_rank=rank,
                parent_factors=parent_factors,
                required_lookback=node.lookback,
                code_sha=code_sha,
            )
        )

    return candidates


def _parents_for_expression(name: str, node: ExprNode, base_factors: list[str]) -> tuple[str, ...]:
    """Resolve auditable parent factor families from template names and columns."""
    families: set[str] = set()
    if name.startswith(("momentum_", "volatility_", "zscore_close_", "rank_close_")):
        families.add("price")
    if name.startswith("volume_trend_"):
        families.add("volume")
    if "funding_rate" in node.required_columns or "open_interest" in node.required_columns:
        families.add("derivatives")
    if "volume" in node.required_columns:
        families.add("volume")
    if any(
        column_name in node.required_columns for column_name in ("close", "open", "high", "low")
    ):
        families.add("price")
    return tuple(factor for factor in base_factors if factor.partition(".")[0] in families)
