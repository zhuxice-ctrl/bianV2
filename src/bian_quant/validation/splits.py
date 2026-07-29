"""Purged anchored walk-forward split generation.

Provides two splitting primitives:

* ``anchored_walk_forward`` – expanding-window folds with a purge gap
  between train and validation to prevent leakage from overlapping
  return horizons.

* ``partition_locked_holdout`` – carves out a final holdout segment that
  is never touched during walk-forward, ensuring a truly unseen test set.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TimeFold:
    """A single walk-forward fold.

    Attributes
    ----------
    fold_index:
        Zero-based fold ordinal.
    train_start, train_end:
        Inclusive start / exclusive end timestamps of the training window.
    val_start, val_end:
        Inclusive start / exclusive end timestamps of the validation window.
    """

    fold_index: int
    train_start: pd.Timestamp
    train_end: pd.Timestamp
    val_start: pd.Timestamp
    val_end: pd.Timestamp

    def __post_init__(self) -> None:
        if self.train_start > self.train_end:
            raise ValueError("train_start must not follow train_end")
        if self.val_start > self.val_end:
            raise ValueError("val_start must not follow val_end")
        if self.train_end > self.val_start:
            raise ValueError(
                "train_end must not overlap val_start "
                "(purge gap must be non-negative)"
            )


def anchored_walk_forward(
    index: pd.DatetimeIndex,
    *,
    n_folds: int,
    val_size: int,
    purge: int = 0,
) -> list[TimeFold]:
    """Generate ``n_folds`` expanding-window folds with a purge gap.

    Parameters
    ----------
    index:
        Sorted DatetimeIndex of the full dataset.
    n_folds:
        Number of walk-forward folds to generate.
    val_size:
        Number of bars in each validation window.
    purge:
        Number of bars to purge (skip) between the end of train and the
        start of validation, to eliminate look-ahead from overlapping
        return horizons.

    Returns
    -------
    list[TimeFold]
        ``n_folds`` folds, ordered by fold index.

    Raises
    ------
    ValueError
        If parameters are inconsistent with the length of ``index``.
    """
    if n_folds < 1:
        raise ValueError("n_folds must be >= 1")
    if val_size < 1:
        raise ValueError("val_size must be >= 1")
    if purge < 0:
        raise ValueError("purge must be >= 0")

    n = len(index)
    # Validation windows are contiguous segments at the tail.
    # For fold i (0-indexed), using inclusive bar positions:
    #   val_start_pos = n - (n_folds - i) * val_size
    #   val_end_pos   = val_start_pos + val_size - 1
    #   train_end_pos = val_start_pos - purge - 1  (last train bar)
    #   train_start_pos = 0  (anchored)
    min_required = val_size * n_folds + purge * n_folds + 1
    if n < min_required:
        raise ValueError(
            f"index has {n} bars but at least {min_required} are required "
            f"for n_folds={n_folds}, val_size={val_size}, purge={purge}"
        )

    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a DatetimeIndex")

    folds: list[TimeFold] = []
    for i in range(n_folds):
        val_start_pos = n - (n_folds - i) * val_size
        val_end_pos = val_start_pos + val_size - 1
        train_end_pos = val_start_pos - purge - 1
        train_start_pos = 0  # anchored: always starts from the beginning

        fold = TimeFold(
            fold_index=i,
            train_start=index[train_start_pos],
            train_end=index[train_end_pos],
            val_start=index[val_start_pos],
            val_end=index[val_end_pos],
        )
        folds.append(fold)

    return folds


def partition_locked_holdout(
    index: pd.DatetimeIndex,
    *,
    holdout_size: int,
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    """Split ``index`` into (development, holdout) segments.

    The holdout is the final ``holdout_size`` bars and must never be used
    during model development.

    Parameters
    ----------
    index:
        Sorted DatetimeIndex.
    holdout_size:
        Number of trailing bars to reserve as holdout.

    Returns
    -------
    (dev_index, holdout_index)
    """
    if holdout_size < 1:
        raise ValueError("holdout_size must be >= 1")
    n = len(index)
    if holdout_size >= n:
        raise ValueError(
            f"holdout_size ({holdout_size}) must be smaller than "
            f"index length ({n})"
        )
    return index[:-holdout_size], index[-holdout_size:]
