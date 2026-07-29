from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bian_quant.signals.legacy_pa import adapt_confluence_signals
from bian_quant.validation.pa_evaluation import evaluate_pa


def _make_4h_fixture(n_bars: int = 500) -> pd.DataFrame:
    generator = np.random.default_rng(42)
    index = pd.date_range(datetime(2025, 1, 1, tzinfo=UTC), periods=n_bars, freq="4h")
    close = 50_000 * np.cumprod(1 + generator.normal(0.0005, 0.015, n_bars))
    open_price = close * (1 + generator.uniform(-0.005, 0.005, n_bars))
    spread = generator.uniform(0.001, 0.01, n_bars)
    return pd.DataFrame(
        {
            "open": open_price,
            "high": np.maximum(open_price, close) * (1 + spread),
            "low": np.minimum(open_price, close) * (1 - spread),
            "close": close,
            "volume": generator.uniform(100, 1000, n_bars),
        },
        index=index,
    )


def test_adapter_matches_legacy_signal_count_and_close_time() -> None:
    from strategies.price_action import confluence_signals

    frame = _make_4h_fixture()
    legacy = confluence_signals(frame)
    expected_timestamps = list(legacy.index[legacy["signal"] != 0] + pd.Timedelta("4h"))
    signals = adapt_confluence_signals(frame, asset="BTCUSDT")

    assert expected_timestamps
    assert len(signals) == len(expected_timestamps)
    assert [pd.Timestamp(signal.decision_time) for signal in signals] == expected_timestamps
    assert all(signal.available_time == signal.decision_time for signal in signals)


def test_adapter_emits_common_factor_contract() -> None:
    signals = adapt_confluence_signals(_make_4h_fixture(), asset="ETHUSDT")
    assert signals
    for signal in signals:
        assert signal.asset == "ETHUSDT"
        assert signal.horizon == "4h"
        assert signal.factor_id == "legacy.pa_confluence"
        assert signal.factor_version == "baseline-0"
        assert signal.confidence is None
        assert signal.value in (-1.0, 1.0)


def test_adapter_rejects_naive_or_unsorted_input() -> None:
    naive = _make_4h_fixture()
    naive.index = naive.index.tz_localize(None)
    with pytest.raises(ValueError, match="timezone-aware"):
        adapt_confluence_signals(naive, asset="BTCUSDT")

    unsorted = _make_4h_fixture().iloc[::-1]
    with pytest.raises(ValueError, match="sorted"):
        adapt_confluence_signals(unsorted, asset="BTCUSDT")


def test_pa_evaluation_produces_real_locked_holdout_decision() -> None:
    repo_root = Path(__file__).parents[3]
    evidence = evaluate_pa(repo_root, code_sha="test-code-sha")

    assert evidence["normal_folds"]
    assert evidence["run_manifest"]["locked_holdout"] is not None
    assert evidence["locked_holdout"]["portfolio"]["trades"] > 0
    assert evidence["decision"]["passed"] is False
    assert evidence["decision"]["reasons"]
