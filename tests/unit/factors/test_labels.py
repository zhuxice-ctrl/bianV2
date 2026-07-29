import pandas as pd

from bian_quant.factors.labels import forward_log_return


def test_forward_label_uses_future_close_only_as_label() -> None:
    close = pd.Series(
        [100.0, 110.0, 121.0],
        index=pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"),
    )

    label = forward_log_return(close, periods=1)

    assert round(label.iloc[0], 12) == round(label.iloc[1], 12)
    assert pd.isna(label.iloc[-1])


def test_forward_label_correct_value() -> None:
    import numpy as np

    close = pd.Series([100.0, 110.0, 121.0])
    label = forward_log_return(close, periods=1)
    expected_0 = np.log(110.0 / 100.0)
    expected_1 = np.log(121.0 / 110.0)
    assert round(label.iloc[0], 12) == round(expected_0, 12)
    assert round(label.iloc[1], 12) == round(expected_1, 12)


def test_periods_must_be_positive() -> None:
    import pytest

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
    excluded = {"bian_quant.factors.labels", "bian_quant.factors.evaluate", "bian_quant.factors.runner"}

    for importer, modname, ispkg in pkgutil.iter_modules(
        factors_pkg.__path__, prefix="bian_quant.factors."
    ):
        if modname in excluded:
            continue
        mod = importlib.import_module(modname)
        source = open(mod.__file__).read()
        # Check for import of labels module, not just the word "labels" in comments
        assert "import labels" not in source, f"{modname} imports labels module"
        assert "factors.labels" not in source, f"{modname} references factors.labels"
