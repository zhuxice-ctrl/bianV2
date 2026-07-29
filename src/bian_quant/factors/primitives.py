"""Safe expression-tree primitives for candidate factor generation.

No ``eval`` is ever used. Each node is a typed, pure pandas computation
with a declared lookback. The evaluator walks the tree directly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class ExprNode:
    """A node in a factor expression tree."""

    op: str
    children: tuple[ExprNode, ...] = ()
    params: tuple[Any, ...] = ()
    required_columns: tuple[str, ...] = ()
    output_unit: str = "dimensionless"
    parent_ids: tuple[str, ...] = ()

    @property
    def lookback(self) -> int:
        """Maximum backward lookback in bars."""
        child_lookbacks = [c.lookback for c in self.children]
        own = 0
        if self.op == "column":
            own = 0
        elif self.op in ("lag", "delta", "percent_change") or self.op in (
            "rolling_mean",
            "rolling_std",
            "zscore",
            "rolling_rank",
        ):
            own = int(self.params[0]) if self.params else 0
        if self.children and own:
            return own + max(child_lookbacks, default=0)
        return max([own] + child_lookbacks)

    @property
    def depth(self) -> int:
        """Expression-tree depth, with a column leaf at depth one."""
        return 1 + max((child.depth for child in self.children), default=0)

    @property
    def expression_hash(self) -> str:
        """Deterministic hash of the normalized expression tree."""
        return hashlib.sha256(self._canonical().encode()).hexdigest()[:16]

    def _canonical(self) -> str:
        """Canonical string representation for deduplication."""
        parts = [self.op]
        if self.params:
            parts.append("(" + ",".join(str(p) for p in self.params) + ")")
        if self.required_columns:
            parts.append("[" + ",".join(sorted(set(self.required_columns))) + "]")
        if self.children:
            child_parts = [child._canonical() for child in self.children]
            if self.op in {"add", "multiply"}:
                child_parts.sort()
            parts.append("{" + ",".join(child_parts) + "}")
        parts.append(f"unit={self.output_unit}")
        if self.parent_ids:
            parts.append("parents=[" + ",".join(sorted(self.parent_ids)) + "]")
        return ":".join(parts)


def column(name: str) -> ExprNode:
    """Reference a data column."""
    units = {
        "close": "quote_currency",
        "open": "quote_currency",
        "high": "quote_currency",
        "low": "quote_currency",
        "volume": "base_currency",
        "funding_rate": "ratio",
        "open_interest": "base_currency",
    }
    return ExprNode(op="column", required_columns=(name,), output_unit=units.get(name, "unknown"))


def lag(node: ExprNode, periods: int) -> ExprNode:
    if periods <= 0:
        raise ValueError("lag periods must be positive")
    return ExprNode(
        op="lag",
        children=(node,),
        params=(periods,),
        required_columns=node.required_columns,
        output_unit=node.output_unit,
        parent_ids=node.parent_ids,
    )


def delta(node: ExprNode, periods: int) -> ExprNode:
    if periods <= 0:
        raise ValueError("delta periods must be positive")
    return ExprNode(
        op="delta",
        children=(node,),
        params=(periods,),
        required_columns=node.required_columns,
        output_unit=node.output_unit,
        parent_ids=node.parent_ids,
    )


def percent_change(node: ExprNode, periods: int) -> ExprNode:
    if periods <= 0:
        raise ValueError("percent_change periods must be positive")
    return ExprNode(
        op="percent_change",
        children=(node,),
        params=(periods,),
        required_columns=node.required_columns,
        output_unit="ratio",
        parent_ids=node.parent_ids,
    )


def rolling_mean(node: ExprNode, window: int) -> ExprNode:
    if window < 2:
        raise ValueError("rolling window must be >= 2")
    return ExprNode(
        op="rolling_mean",
        children=(node,),
        params=(window,),
        required_columns=node.required_columns,
        output_unit=node.output_unit,
        parent_ids=node.parent_ids,
    )


def rolling_std(node: ExprNode, window: int) -> ExprNode:
    if window < 2:
        raise ValueError("rolling window must be >= 2")
    return ExprNode(
        op="rolling_std",
        children=(node,),
        params=(window,),
        required_columns=node.required_columns,
        output_unit=node.output_unit,
        parent_ids=node.parent_ids,
    )


def zscore(node: ExprNode, window: int) -> ExprNode:
    if window < 2:
        raise ValueError("zscore window must be >= 2")
    return ExprNode(
        op="zscore",
        children=(node,),
        params=(window,),
        required_columns=node.required_columns,
        output_unit="dimensionless",
        parent_ids=node.parent_ids,
    )


def rolling_rank(node: ExprNode, window: int) -> ExprNode:
    if window < 2:
        raise ValueError("rolling_rank window must be >= 2")
    return ExprNode(
        op="rolling_rank",
        children=(node,),
        params=(window,),
        required_columns=node.required_columns,
        output_unit="rank",
        parent_ids=node.parent_ids,
    )


def add(left: ExprNode, right: ExprNode) -> ExprNode:
    return ExprNode(
        op="add",
        children=(left, right),
        required_columns=left.required_columns + right.required_columns,
        output_unit=left.output_unit if left.output_unit == right.output_unit else "mixed",
        parent_ids=left.parent_ids + right.parent_ids,
    )


def subtract(left: ExprNode, right: ExprNode) -> ExprNode:
    return ExprNode(
        op="subtract",
        children=(left, right),
        required_columns=left.required_columns + right.required_columns,
        output_unit=left.output_unit if left.output_unit == right.output_unit else "mixed",
        parent_ids=left.parent_ids + right.parent_ids,
    )


def multiply(left: ExprNode, right: ExprNode) -> ExprNode:
    return ExprNode(
        op="multiply",
        children=(left, right),
        required_columns=left.required_columns + right.required_columns,
        output_unit=f"{left.output_unit}*{right.output_unit}",
        parent_ids=left.parent_ids + right.parent_ids,
    )


def safe_ratio(left: ExprNode, right: ExprNode, epsilon: float = 1e-10) -> ExprNode:
    return ExprNode(
        op="safe_ratio",
        children=(left, right),
        params=(epsilon,),
        required_columns=left.required_columns + right.required_columns,
        output_unit=f"{left.output_unit}/{right.output_unit}",
        parent_ids=left.parent_ids + right.parent_ids,
    )


def clip(node: ExprNode, lower: float | None = None, upper: float | None = None) -> ExprNode:
    return ExprNode(
        op="clip",
        children=(node,),
        params=(lower, upper),
        required_columns=node.required_columns,
        output_unit=node.output_unit,
        parent_ids=node.parent_ids,
    )


# Forbidden tokens — any candidate referencing these is rejected
FORBIDDEN_LABEL_NAMES = {"label", "forward_log_return", "forward_return", "y", "target"}
FORBIDDEN_COLUMN_NAMES = FORBIDDEN_LABEL_NAMES

ALLOWED_COLUMNS = {"close", "open", "high", "low", "volume", "funding_rate", "open_interest"}


def validate_node(node: ExprNode) -> None:
    """Reject expressions that could leak future information.

    Raises ``ValueError`` for:
    - Label names in column references
    - Negative lags
    - Centered windows
    - Unknown columns
    """
    if node.op == "column":
        col_name = node.required_columns[0] if node.required_columns else ""
        if col_name.lower() in FORBIDDEN_COLUMN_NAMES:
            raise ValueError(f"forbidden column reference: {col_name} (label leakage)")
        if col_name not in ALLOWED_COLUMNS:
            raise ValueError(f"unknown column: {col_name}")

    if node.op in ("lag", "delta", "percent_change"):
        periods = node.params[0] if node.params else 0
        if periods <= 0:
            raise ValueError(f"{node.op} requires positive periods, got {periods}")

    if node.op in ("rolling_mean", "rolling_std", "zscore", "rolling_rank"):
        window = node.params[0] if node.params else 0
        if window < 2:
            raise ValueError(f"{node.op} requires window >= 2, got {window}")

    for child in node.children:
        validate_node(child)


def evaluate_node(node: ExprNode, data: pd.DataFrame) -> pd.Series:
    """Evaluate an expression tree against data. Never uses ``eval``."""
    validate_node(node)
    return _eval(node, data)


def _eval(node: ExprNode, data: pd.DataFrame) -> pd.Series:
    if node.op == "column":
        col = node.required_columns[0]
        return data[col]

    children = [_eval(c, data) for c in node.children]

    if node.op == "lag":
        return children[0].shift(int(node.params[0]))
    elif node.op == "delta":
        return children[0].diff(int(node.params[0]))
    elif node.op == "percent_change":
        return children[0].pct_change(periods=int(node.params[0]), fill_method=None)
    elif node.op == "rolling_mean":
        return children[0].rolling(int(node.params[0]), min_periods=int(node.params[0])).mean()
    elif node.op == "rolling_std":
        return children[0].rolling(int(node.params[0]), min_periods=int(node.params[0])).std(ddof=1)
    elif node.op == "zscore":
        w = int(node.params[0])
        s = children[0]
        mean = s.rolling(w, min_periods=w).mean()
        std = s.rolling(w, min_periods=w).std(ddof=1)
        return (s - mean) / std.replace(0.0, np.nan)
    elif node.op == "rolling_rank":
        w = int(node.params[0])
        return children[0].rolling(w, min_periods=w).rank(pct=True)
    elif node.op == "add":
        return children[0] + children[1]
    elif node.op == "subtract":
        return children[0] - children[1]
    elif node.op == "multiply":
        return children[0] * children[1]
    elif node.op == "safe_ratio":
        epsilon = float(node.params[0])
        denom = children[1]
        result = children[0] / denom
        result = result.where(denom.abs() >= epsilon, np.nan)
        return result
    elif node.op == "clip":
        lower, upper = node.params
        return children[0].clip(lower=lower, upper=upper)
    else:
        raise ValueError(f"unknown operation: {node.op}")
