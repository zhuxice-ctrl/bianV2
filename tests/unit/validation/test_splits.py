import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from bian_quant.validation.splits import anchored_walk_forward, partition_locked_holdout


@given(embargo=st.integers(min_value=1, max_value=8))
def test_train_labels_never_overlap_test(embargo: int) -> None:
    index = pd.date_range("2020-01-01", periods=240, freq="D", tz="UTC")
    folds = anchored_walk_forward(
        index,
        initial_train=120,
        test_size=24,
        step=24,
        label_horizon=embargo,
        embargo=embargo,
    )
    assert folds
    for fold in folds:
        assert fold.train.max() < fold.test.min()
        assert fold.train.min() == index.min()
        assert fold.train.intersection(fold.test).empty


def test_locked_holdout_is_disjoint() -> None:
    index = pd.date_range("2020-01-01", periods=100, freq="h", tz="UTC")
    research, locked = partition_locked_holdout(index, 20)
    assert research.intersection(locked).empty
    assert locked.min() > research.max()


def test_split_rejects_unsorted_index() -> None:
    index = pd.date_range("2020-01-01", periods=100, freq="h", tz="UTC")[::-1]
    with pytest.raises(ValueError, match="sorted"):
        partition_locked_holdout(index, 20)
