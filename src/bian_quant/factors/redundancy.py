"""Factor redundancy clustering and incremental contribution control.

Train-only Spearman correlation → distance → hierarchical clustering.
One representative per cluster.  Incremental contribution via regularized
linear baseline + delta IC on validation.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage  # type: ignore[import-untyped]
from scipy.spatial.distance import squareform  # type: ignore[import-untyped]


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
    baseline_ic: float
    full_ic: float
    incremental_ic: float
    baseline_cost_adjusted_return: float
    full_cost_adjusted_return: float
    delta_cost_adjusted_return: float
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
    clusters = {name: int(label) for name, label in zip(factor_names, labels, strict=False)}

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
    validation_candidate_factor: pd.Series | None = None,
    validation_baseline_factors: pd.DataFrame | None = None,
    validation_label: pd.Series | None = None,
    cost_rate_bps: float = 5.0,
) -> IncrementalResult:
    """Evaluate validation-only incremental IC and cost-adjusted return.

    Parameters
    ----------
    The first three arguments are the training fold. Optional validation
    arguments provide a disjoint evaluation fold. When omitted, the training
    fold is reused for backwards compatibility with small unit fixtures.
    factor_name
        Name of the candidate factor.
    alpha
        L2 regularization strength for the linear baseline.
    """
    if cost_rate_bps < 0:
        raise ValueError("cost_rate_bps must be non-negative")

    train = pd.DataFrame({"candidate": candidate_factor, "label": label})
    for col in baseline_factors.columns:
        train[str(col)] = baseline_factors[col]
    train = train.dropna()

    validation_candidate = (
        candidate_factor if validation_candidate_factor is None else validation_candidate_factor
    )
    validation_baseline = (
        baseline_factors if validation_baseline_factors is None else validation_baseline_factors
    )
    validation_target = label if validation_label is None else validation_label
    validation = pd.DataFrame({"candidate": validation_candidate, "label": validation_target})
    for col in validation_baseline.columns:
        validation[str(col)] = validation_baseline[col]
    validation = validation.dropna()

    if len(train) < 5 or len(validation) < 5:
        return IncrementalResult(
            factor_name=factor_name,
            standalone_ic=float("nan"),
            baseline_ic=float("nan"),
            full_ic=float("nan"),
            incremental_ic=float("nan"),
            baseline_cost_adjusted_return=float("nan"),
            full_cost_adjusted_return=float("nan"),
            delta_cost_adjusted_return=float("nan"),
            has_incremental_value=False,
        )

    train_y = train["label"].to_numpy(dtype=float)
    validation_y = validation["label"].to_numpy(dtype=float)
    train_candidate = train["candidate"].to_numpy(dtype=float)
    validation_candidate_values = validation["candidate"].to_numpy(dtype=float)

    standalone_ic = _correlation(validation_candidate_values, validation_y)

    baseline_columns = [str(column) for column in baseline_factors.columns]
    if baseline_columns:
        train_base = train[baseline_columns].to_numpy(dtype=float)
        validation_base = validation[baseline_columns].to_numpy(dtype=float)
        baseline_pred = _ridge_predict(train_base, train_y, validation_base, alpha=alpha)
    else:
        train_base = np.empty((len(train), 0), dtype=float)
        validation_base = np.empty((len(validation), 0), dtype=float)
        baseline_pred = np.zeros(len(validation), dtype=float)

    train_full = np.column_stack([train_base, train_candidate])
    validation_full = np.column_stack([validation_base, validation_candidate_values])
    full_pred = _ridge_predict(train_full, train_y, validation_full, alpha=alpha)

    baseline_ic = _correlation(baseline_pred, validation_y)
    full_ic = _correlation(full_pred, validation_y)

    incremental_ic = full_ic - baseline_ic
    baseline_return = _cost_adjusted_return(
        baseline_pred, validation_y, cost_rate_bps=cost_rate_bps
    )
    full_return = _cost_adjusted_return(full_pred, validation_y, cost_rate_bps=cost_rate_bps)
    delta_return = full_return - baseline_return

    has_incremental = incremental_ic > 0.001 and delta_return > 0.0

    return IncrementalResult(
        factor_name=factor_name,
        standalone_ic=standalone_ic,
        baseline_ic=baseline_ic,
        full_ic=full_ic,
        incremental_ic=incremental_ic,
        baseline_cost_adjusted_return=baseline_return,
        full_cost_adjusted_return=full_return,
        delta_cost_adjusted_return=delta_return,
        has_incremental_value=has_incremental,
    )


def _ridge_predict(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    *,
    alpha: float,
) -> np.ndarray:
    if train_x.shape[1] == 0:
        return np.zeros(len(validation_x), dtype=float)
    regularizer = alpha * np.eye(train_x.shape[1])
    try:
        weights = np.linalg.solve(train_x.T @ train_x + regularizer, train_x.T @ train_y)
    except np.linalg.LinAlgError:
        return np.zeros(len(validation_x), dtype=float)
    return np.asarray(validation_x @ weights, dtype=float)


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    if len(left) < 2 or np.ptp(left) == 0.0 or np.ptp(right) == 0.0:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


def _cost_adjusted_return(
    prediction: np.ndarray, label: np.ndarray, *, cost_rate_bps: float
) -> float:
    positions = np.sign(prediction)
    gross = float(np.mean(positions * label))
    turnover = float(np.mean(np.abs(np.diff(positions)))) if len(positions) > 1 else 0.0
    return gross - turnover * cost_rate_bps / 10_000.0
