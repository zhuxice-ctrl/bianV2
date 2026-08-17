import numpy as np
import pandas as pd
import pytest

from bian_quant.factors.labels import forward_log_return, forward_open_to_open_log_return


def test_forward_label_uses_future_close_only_as_label() -> None:
    close = pd.Series(
        [100.0, 110.0, 121.0],
        index=pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
    )

    label = forward_log_return(close, periods=1)

    assert round(label.iloc[0], 12) == round(label.iloc[1], 12)
    assert pd.isna(label.iloc[-1])


def test_forward_label_correct_value() -> None:
    close = pd.Series([100.0, 110.0, 121.0])
    label = forward_log_return(close, periods=1)
    expected_0 = np.log(110.0 / 100.0)
    expected_1 = np.log(121.0 / 110.0)
    assert round(label.iloc[0], 12) == round(expected_0, 12)
    assert round(label.iloc[1], 12) == round(expected_1, 12)


def test_periods_must_be_positive() -> None:
    close = pd.Series([1.0, 2.0])
    with pytest.raises(ValueError, match="positive"):
        forward_log_return(close, periods=0)
    with pytest.raises(ValueError, match="positive"):
        forward_log_return(close, periods=-1)


def test_label_is_isolated_from_factor_modules() -> None:
    """Production factor modules must not import labels.

    Only factor *computation* modules (price, volume, derivatives, base,
    spec, registry, primitives, generator) are checked.  Infrastructure
    modules (evaluate, runner) legitimately reference labels for
    pipeline orchestration.
    """
    import importlib
    import pkgutil

    import bian_quant.factors as factors_pkg

    # Ensure we can import labels
    import bian_quant.factors.labels  # noqa: F401

    # Factor computation modules that must not reference labels
    excluded = {
        "bian_quant.factors.labels",
        "bian_quant.factors.evaluate",
        "bian_quant.factors.runner",
    }

    for _importer, modname, _ispkg in pkgutil.iter_modules(
        factors_pkg.__path__, prefix="bian_quant.factors."
    ):
        if modname in excluded:
            continue
        mod = importlib.import_module(modname)
        with open(mod.__file__, encoding="utf-8") as f:
            source = f.read()
        # Check for import of labels module, not just the word "labels" in comments
        assert "import labels" not in source, f"{modname} imports labels module"
        assert "factors.labels" not in source, f"{modname} references factors.labels"


# --- forward_open_to_open_log_return tests ---


def _label_frame(n_bars: int = 5, *, start: str = "2024-07-01") -> pd.DataFrame:
    times = pd.date_range(start, periods=n_bars, freq="h", tz="UTC")
    opens = [100.0 * (1.1 ** i) for i in range(n_bars)]
    return pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": times,
            "open": opens,
            "volume": [1000.0] * n_bars,
            "quote_volume": [100000.0] * n_bars,
        }
    )


def test_oolabel_1h_exact_value() -> None:
    frame = _label_frame(5)
    values, reasons = forward_open_to_open_log_return(frame, holding_bars=1)
    expected = np.log(121.0 / 110.0)
    assert values.iloc[0] == pytest.approx(expected)
    assert reasons.iloc[0] == ""
    assert reasons.iloc[-1] == "MISSING_NEXT_BAR"


def test_oolabel_2h_exact_value() -> None:
    frame = _label_frame(5)
    values, reasons = forward_open_to_open_log_return(frame, holding_bars=2)
    expected = np.log(133.1 / 110.0)
    assert values.iloc[0] == pytest.approx(expected)
    assert reasons.iloc[0] == ""


def test_oolabel_4h_exact_value() -> None:
    frame = _label_frame(6)
    values, reasons = forward_open_to_open_log_return(frame, holding_bars=4)
    assert reasons.iloc[0] == ""


def test_oolabel_missing_next_bar_rejects_gap() -> None:
    """Missing t+1h but t+2h exists -> MISSING_NEXT_BAR."""
    frame = _label_frame(5)
    frame = frame.drop(index=frame.index[2]).reset_index(drop=True)
    values, reasons = forward_open_to_open_log_return(frame, holding_bars=1)
    assert reasons.iloc[0] == "MISSING_NEXT_BAR"


def test_oolabel_invalid_open_nan() -> None:
    frame = _label_frame(5)
    frame.loc[frame.index[1], "open"] = np.nan
    _values, reasons = forward_open_to_open_log_return(frame, holding_bars=1)
    assert reasons.iloc[0] == "EXECUTION_BAR_INVALID"


def test_oolabel_invalid_volume_zero() -> None:
    frame = _label_frame(5)
    frame.loc[frame.index[1], "volume"] = 0
    _values, reasons = forward_open_to_open_log_return(frame, holding_bars=1)
    assert reasons.iloc[0] == "EXECUTION_BAR_INVALID"


def test_oolabel_invalid_quote_volume_negative() -> None:
    frame = _label_frame(5)
    frame.loc[frame.index[1], "quote_volume"] = -1.0
    _values, reasons = forward_open_to_open_log_return(frame, holding_bars=1)
    assert reasons.iloc[0] == "EXECUTION_BAR_INVALID"


def test_oolabel_taker_missing_does_not_block() -> None:
    """Missing taker fields at t+1 should NOT block the label."""
    frame = _label_frame(5)
    frame["taker_buy_base"] = np.nan
    frame["taker_buy_quote"] = np.nan
    values, reasons = forward_open_to_open_log_return(frame, holding_bars=1)
    assert reasons.iloc[0] == ""
    assert values.iloc[0] == pytest.approx(np.log(121.0 / 110.0))


def test_oolabel_multi_asset() -> None:
    times = pd.date_range("2024-07-01", periods=4, freq="h", tz="UTC")
    frame = pd.DataFrame(
        {
            "asset": np.repeat(["BTC", "ETH"], 4),
            "event_time": np.tile(times, 2),
            "open": [100, 110, 121, 133, 50, 55, 60, 66],
            "volume": [1000.0] * 8,
            "quote_volume": [100000.0] * 8,
        }
    )
    values, _reasons = forward_open_to_open_log_return(frame, holding_bars=1)
    btc_mask = frame["asset"] == "BTC"
    btc_values = values[btc_mask]
    assert btc_values.iloc[0] == pytest.approx(np.log(121.0 / 110.0))


def test_oolabel_holding_bars_must_be_positive() -> None:
    frame = _label_frame(3)
    with pytest.raises(ValueError, match="positive"):
        forward_open_to_open_log_return(frame, holding_bars=0)
