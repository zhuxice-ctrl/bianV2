import numpy as np
import pandas as pd
from pandas.testing import assert_series_equal

from bian_quant.factors.volume import amihud_illiquidity, volume_surprise


def test_future_append_does_not_change_existing_volume_values() -> None:
    close = pd.Series(range(1, 101), dtype=float)
    volume = pd.Series(np.random.default_rng(42).uniform(100, 1000, 100))

    close_ext = pd.concat([close, pd.Series([10_000.0])], ignore_index=True)
    vol_ext = pd.concat([volume, pd.Series([999.0])], ignore_index=True)

    assert_series_equal(
        volume_surprise(volume, periods=24),
        volume_surprise(vol_ext, periods=24).iloc[:-1],
    )
    assert_series_equal(
        amihud_illiquidity(close, volume, periods=24),
        amihud_illiquidity(close_ext, vol_ext, periods=24).iloc[:-1],
    )


def test_volume_surprise_zero_std_produces_nan() -> None:
    volume = pd.Series([100.0] * 50)
    vs = volume_surprise(volume, periods=24)
    assert vs.iloc[-1] != vs.iloc[-1]  # NaN check


def test_amihud_positive() -> None:
    close = pd.Series(np.geomspace(100, 200, 50))
    volume = pd.Series(np.full(50, 1000.0))
    ai = amihud_illiquidity(close, volume, periods=24)
    assert (ai.dropna() >= 0).all()
