"""Factor redundancy clustering and incremental contribution control.

Train-only Spearman correlation → distance → hierarchical clustering.
One representative per cluster.  Incremental contribution via regularized
linear baseline + delta IC on validation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np
import pandas as pd
from scipy import stats as sp_stats
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform


@dataclass(frozen=True)
class ClusterResult:
    """Result of redundancy clustering for a set of factors."""

    clusters: dict[str, int]  # factor_name → cluster_id
    representatives: dict[int, str]  # cluster_id → representative factor_name
    rejected: dict[str, str]  # factor_name → rejection_reason


@dataclass(frozen=True)
class IncrementalResult:
    """Result of incremental contribution evaluation."""

    factor_name: str
    standalone_ic: float
    incremental_ic: float
    has_incremental_value: bool


def cluster_redundant_factors(
    factor_values: pd.DataFrame,
    *,
    distance_threshold: float = 0.3,
    inner_validation_scores: dict[str, float] | None = None,
) -> ClusterResult:
    """Cluster factors by train-only Spearman correlation.

    Parameters
    ----------
    factor_values
        DataFrame where each column is a factor's values (train data only).
    distance_threshold
        Maximum distance ``1 - abs(corr)`` for same cluster.
    inner_validation_scores
        Optional mapping of factor name to validation score.  The
        representative is the highest-scoring member.  If not provided,
        the first member alphabetically is chosen.
    """
    if factor_values.shape[1] < 2:
        names = list(factor_values.columns)
        return ClusterResult(
            clusters={n: 0 for n in names},
            representatives={0: names[0]} if names else {},
            rejected={},
        )

    # Compute train-only Spearman correlation
    corr_matrix = factor_values.corr(method="spearman").fillna(0.0)

    # Convert to distance matrix
    dist_matrix = 1.0 - corr_matrix.abs()
    # Ensure diagonal is zero and symmetric — work on a copy
    dist_arr = dist_matrix.values.copy()
    np.fill_diagonal(dist_arr, 0.0)
    dist_arr = np.clip(dist_arr, 0.0, None)
    dist_matrix = pd.DataFrame(dist_arr, index=factor_values.columns, columns=factor_values.columns)

    # Hierarchical clustering
    condensed = squareform(dist_matrix.values, checks=False)
    Z = linkage(condensed, method="average")
    labels = fcluster(Z, t=distance_threshold, criterion="distance")

    factor_names = list(factor_values.columns)
    clusters = {name: int(label) for name, label in zip(factor_names, labels)}

    # Select representative per cluster
    representatives: dict[int, str] = {}
    rejected: dict[str, str] = {}

    cluster_members: dict[int, list[str]] = {}
    for name, cid in clusters.items():
        cluster_members.setdefault(cid, []).append(name)

    for cid, members in cluster_members.items():
        if inner_validation_scores:
            best = max(members, key=lambda m: inner_validation_scores.get(m, float("-inf")))
            representatives[cid] = best
            for m in members:
                if m != best:
                    rejected[m] = f"redundant_with:{best}"
        else:
            # Without validation scores, pick first alphabetically
            best = sorted(members)[0]
            representatives[cid] = best
            for m in members:
                if m != best:
                    rejected[m] = f"redundant_with:{best}"

    return ClusterResult(
        clusters=clusters,
        representatives=representatives,
        rejected=rejected,
    )


def evaluate_incremental_contribution(
    candidate_factor: pd.Series,
    baseline_factors: pd.DataFrame,
    label: pd.Series,
    *,
    factor_name: str,
    alpha: float = 1.0,
) -> IncrementalResult:
    """Evaluate the incremental IC of a candidate over a regularized baseline.

    Parameters
    ----------
    candidate_factor
        The factor being evaluated for incremental value.
    baseline_factors
        DataFrame of already-approved baseline factors.
    label
        Forward return label.
    factor_name
        Name of the candidate factor.
    alpha
        L2 regularization strength for the linear baseline.
    """
    # Align data
    df = pd.DataFrame({"candidate": candidate_factor, "label": label})
    for col in baseline_factors.columns:
        df[col] = baseline_factors[col]
    df = df.dropna()

    if len(df) < 5:
        return IncrementalResult(
            factor_name=factor_name,
            standalone_ic=float("nan"),
            incremental_ic=float("nan"),
            has_incremental_value=False,
        )

    y = df["label"].values
    candidate = df["candidate"].values

    # Standalone IC
    if np.std(candidate) > 0 and np.std(y) > 0:
        standalone_ic = float(np.corrcoef(candidate, y)[0, 1])
    else:
        standalone_ic = 0.0

    # Baseline IC (using regularized linear combination)
    if baseline_factors.shape[1] > 0:
        X_base = df[baseline_factors.columns].values
        # Ridge regression: w = (X'X + alpha*I)^-1 X'y
        n_features = X_base.shape[1]
        reg = alpha * np.eye(n_features)
        try:
            w = np.linalg.solve(X_base.T @ X_base + reg, X_base.T @ y)
            baseline_pred = X_base @ w
            if np.std(baseline_pred) > 0 and np.std(y) > 0:
                baseline_ic = float(np.corrcoef(baseline_pred, y)[0, 1])
            else:
                baseline_ic = 0.0
        except np.linalg.LinAlgError:
            baseline_ic = 0.0
    else:
        baseline_ic = 0.0

    # Full model IC (baseline + candidate)
    if baseline_factors.shape[1] > 0:
        X_full = np.column_stack([X_base, candidate])
    else:
        X_full = candidate.reshape(-1, 1)

    n_full = X_full.shape[1]
    reg_full = alpha * np.eye(n_full)
    try:
        w_full = np.linalg.solve(X_full.T @ X_full + reg_full, X_full.T @ y)
        full_pred = X_full @ w_full
        if np.std(full_pred) > 0 and np.std(y) > 0:
            full_ic = float(np.corrcoef(full_pred, y)[0, 1])
        else:
            full_ic = 0.0
    except np.linalg.LinAlgError:
        full_ic = 0.0

    incremental_ic = full_ic - baseline_ic

    # A factor with no incremental value remains "observed" even if
    # standalone IC is strong
    has_incremental = incremental_ic > 0.001

    return IncrementalResult(
        factor_name=factor_name,
        standalone_ic=standalone_ic,
        incremental_ic=incremental_ic,
        has_incremental_value=has_incremental,
    )
