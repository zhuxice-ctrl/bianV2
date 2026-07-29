from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TimeFold:
    number: int
    train: pd.DatetimeIndex
    test: pd.DatetimeIndex


def _validate_index(index: pd.DatetimeIndex) -> None:
    if not isinstance(index, pd.DatetimeIndex):
        raise TypeError("index must be a DatetimeIndex")
    if index.tz is None:
        raise ValueError("index must be timezone-aware")
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise ValueError("index must be sorted and unique")


def anchored_walk_forward(
    index: pd.DatetimeIndex,
    *,
    initial_train: int,
    test_size: int,
    step: int,
    label_horizon: int,
    embargo: int,
) -> list[TimeFold]:
    _validate_index(index)
    if min(initial_train, test_size, step) < 1:
        raise ValueError("initial_train, test_size, and step must be positive")
    if label_horizon < 0 or embargo < 0:
        raise ValueError("label_horizon and embargo must be non-negative")

    folds: list[TimeFold] = []
    test_start = initial_train
    while test_start + test_size <= len(index):
        train_stop = test_start - label_horizon - embargo
        if train_stop <= 0:
            raise ValueError("purge and embargo remove the training set")
        folds.append(
            TimeFold(
                number=len(folds),
                train=index[:train_stop],
                test=index[test_start : test_start + test_size],
            )
        )
        test_start += step
    return folds


def partition_locked_holdout(
    index: pd.DatetimeIndex, holdout_size: int
) -> tuple[pd.DatetimeIndex, pd.DatetimeIndex]:
    _validate_index(index)
    if holdout_size <= 0:
        raise ValueError("holdout_size must be positive")
    if holdout_size >= len(index):
        raise ValueError("holdout_size must be smaller than the index")
    research = index[:-holdout_size]
    locked = index[-holdout_size:]
    if research.intersection(locked).size:
        raise AssertionError("research and locked holdout overlap")
    return research, locked
