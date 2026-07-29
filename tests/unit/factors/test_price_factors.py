import pandas as pd
from pandas.testing import assert_series_equal

from bian_quant.factors.price import momentum, realized_volatility, reversal


def test_future_append_does_not_change_existing_factor_values() -> None:
    base = pd.Series(range(1, 101), dtype=float)
    extended = pd.concat([base, pd.Series([10_000.0])], ignore_index=True)

    assert_series_equal(momentum(base, periods=12), momentum(extended, periods=12).iloc[:-1])
    assert_series_equal(reversal(base, periods=6), reversal(extended, periods=6).iloc[:-1])
    assert_series_equal(
        realized_volatility(base, periods=12),
        realized_volatility(extended, periods=12).iloc[:-1],
    )


def test_momentum_correct_values() -> None:
    close = pd.Series([100.0, 110.0, 121.0])
    m = momentum(close, periods=1)
    assert round(m.iloc[1], 10) == round(110.0 / 100.0 - 1.0, 10)
    assert round(m.iloc[2], 10) == round(121.0 / 110.0 - 1.0, 10)
    assert pd.isna(m.iloc[0])


def test_reversal_is_negative_momentum() -> None:
    close = pd.Series([100.0, 110.0, 121.0])
    m = momentum(close, periods=1)
    r = reversal(close, periods=1)
    assert_series_equal(-m, r, check_names=False)


def test_realized_volatility_positive() -> None:
    import numpy as np

    close = pd.Series(np.geomspace(100, 200, 50))
    rv = realized_volatility(close, periods=12)
    assert (rv.dropna() >= 0).all()
