import pandas as pd

from bian_quant.data.hashing import dataframe_content_hash


def test_hash_is_independent_of_input_row_order() -> None:
    frame = pd.DataFrame({"asset": ["ETH", "BTC"], "value": [2.0, 1.0]})

    assert dataframe_content_hash(frame, sort_by=["asset"]) == dataframe_content_hash(
        frame.iloc[::-1], sort_by=["asset"]
    )


def test_hash_breaks_duplicate_sort_key_ties_deterministically() -> None:
    frame = pd.DataFrame({"asset": ["BTC", "BTC"], "value": [2.0, 1.0]})

    assert dataframe_content_hash(frame, sort_by=["asset"]) == dataframe_content_hash(
        frame.iloc[::-1], sort_by=["asset"]
    )
