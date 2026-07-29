"""Tests for purged anchored walk-forward splits."""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from bian_quant.validation.splits import (
    TimeFold,
    anchored_walk_forward,
    partition_locked_holdout,
)


def _make_index(n: int, freq: str = "h") -> pd.DatetimeIndex:
    return pd.date_range("2026-01-01", periods=n, freq=freq)


class TestTimeFold:
    def test_valid_fold(self):
        idx = _make_index(3)
        f = TimeFold(
            fold_index=0,
            train_start=idx[0],
            train_end=idx[0],
            val_start=idx[1],
            val_end=idx[2],
        )
        assert f.fold_index == 0

    def test_train_end_after_val_start_rejected(self):
        idx = _make_index(3)
        with pytest.raises(ValueError, match="overlap"):
            TimeFold(
                fold_index=0,
                train_start=idx[0],
                train_end=idx[2],
                val_start=idx[1],
                val_end=idx[2],
            )


class TestAnchoredWalkForward:
    def test_basic_3_folds(self):
        idx = _make_index(100)
        folds = anchored_walk_forward(idx, n_folds=3, val_size=10, purge=0)
        assert len(folds) == 3

    def test_train_always_anchored_from_start(self):
        idx = _make_index(100)
        folds = anchored_walk_forward(idx, n_folds=3, val_size=10, purge=2)
        for f in folds:
            assert f.train_start == idx[0]

    def test_validation_windows_are_contiguous_and_non_overlapping(self):
        idx = _make_index(100)
        folds = anchored_walk_forward(idx, n_folds=3, val_size=10, purge=0)
        for i in range(len(folds) - 1):
            # next fold's val_start should be exactly after current val_end
            assert folds[i].val_end < folds[i + 1].val_start

    def test_purge_creates_gap(self):
        idx = _make_index(100)
        purge = 5
        folds = anchored_walk_forward(idx, n_folds=2, val_size=10, purge=purge)
        for f in folds:
            # train_end should be at least purge bars before val_start
            train_end_pos = idx.get_indexer([f.train_end])[0]
            val_start_pos = idx.get_indexer([f.val_start])[0]
            assert val_start_pos - train_end_pos >= purge

    def test_no_purge_train_end_equals_val_start_minus_1(self):
        idx = _make_index(50)
        folds = anchored_walk_forward(idx, n_folds=2, val_size=10, purge=0)
        f = folds[0]
        train_end_pos = idx.get_indexer([f.train_end])[0]
        val_start_pos = idx.get_indexer([f.val_start])[0]
        assert val_start_pos - train_end_pos == 1

    def test_expanding_window(self):
        """Train size grows with each fold (anchored = expanding)."""
        idx = _make_index(100)
        folds = anchored_walk_forward(idx, n_folds=3, val_size=10, purge=0)
        train_sizes = []
        for f in folds:
            train_sizes.append(idx.get_indexer([f.train_end])[0])
        assert train_sizes[0] < train_sizes[1] < train_sizes[2]

    def test_too_short_index_raises(self):
        idx = _make_index(10)
        with pytest.raises(ValueError, match="at least"):
            anchored_walk_forward(idx, n_folds=5, val_size=5, purge=2)

    def test_zero_folds_raises(self):
        idx = _make_index(100)
        with pytest.raises(ValueError, match="n_folds"):
            anchored_walk_forward(idx, n_folds=0, val_size=10)

    def test_last_fold_val_ends_at_last_bar(self):
        idx = _make_index(100)
        folds = anchored_walk_forward(idx, n_folds=3, val_size=10, purge=0)
        last = folds[-1]
        assert last.val_end == idx[-1]


class TestPartitionLockedHoldout:
    def test_basic_split(self):
        idx = _make_index(100)
        dev, holdout = partition_locked_holdout(idx, holdout_size=20)
        assert len(dev) == 80
        assert len(holdout) == 20
        assert dev[-1] < holdout[0]

    def test_holdout_is_contiguous_tail(self):
        idx = _make_index(50)
        dev, holdout = partition_locked_holdout(idx, holdout_size=10)
        assert holdout[0] == idx[-10]
        assert holdout[-1] == idx[-1]

    def test_holdout_too_large_raises(self):
        idx = _make_index(10)
        with pytest.raises(ValueError, match="smaller than"):
            partition_locked_holdout(idx, holdout_size=10)

    def test_holdout_zero_raises(self):
        idx = _make_index(10)
        with pytest.raises(ValueError, match="holdout_size"):
            partition_locked_holdout(idx, holdout_size=0)


class TestHypothesisProperties:
    @given(
        n_folds=st.integers(min_value=1, max_value=5),
        val_size=st.integers(min_value=1, max_value=10),
        purge=st.integers(min_value=0, max_value=5),
    )
    @settings(max_examples=50)
    def test_fold_count_and_ordering(self, n_folds: int, val_size: int, purge: int):
        min_bars = val_size * n_folds + purge * n_folds + 2
        idx = _make_index(min_bars + 20)
        folds = anchored_walk_forward(idx, n_folds=n_folds, val_size=val_size, purge=purge)

        assert len(folds) == n_folds
        for i, f in enumerate(folds):
            assert f.fold_index == i
            assert f.train_start <= f.train_end
            assert f.val_start <= f.val_end
            assert f.train_end <= f.val_start  # purge gap >= 0
