"""Integration tests for the legacy PA signal adapter.

These tests verify that the adapter correctly converts legacy PA
confluence signals into ``SignalRecord`` objects without modifying the
legacy strategy math.
"""

from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd

from bian_quant.signals.legacy_pa import adapt_confluence_signals
from bian_quant.signals.protocol import SignalRecord


def _make_4h_fixture(n_bars: int = 300) -> pd.DataFrame:
    """Create a deterministic 4h OHLCV fixture for testing.

    The fixture has enough bars for EMA200 to be defined and includes
    trending and ranging segments to generate a mix of signals.
    """
    base = datetime(2025, 1, 1, tzinfo=UTC)
    rng = np.random.default_rng(42)
    dates = pd.date_range(base, periods=n_bars, freq="4h", tz="UTC")

    # Generate a random walk with drift for close prices
    returns = rng.normal(0.0005, 0.015, n_bars)
    close = 50000 * np.cumprod(1 + returns)

    # Generate OHLV from close
    intrabar = rng.uniform(0.001, 0.01, n_bars)
    open_ = close * (1 + rng.uniform(-0.005, 0.005, n_bars))
    high = np.maximum(open_, close) * (1 + intrabar)
    low = np.minimum(open_, close) * (1 - intrabar)
    volume = rng.uniform(100, 1000, n_bars)

    return pd.DataFrame(
        {
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        },
        index=dates,
    )


class TestSignalCountAndTiming:
    """Test that the adapter emits the correct number of signals with correct timing."""

    def test_adapter_emits_signal_for_every_nonzero_legacy_signal(self) -> None:
        """One SignalRecord for every nonzero legacy signal."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="BTCUSDT")

        # Verify each signal is non-zero
        for sig in signals:
            assert sig.direction in (-1, 1)

        # The count should match the number of non-zero signals in the legacy output
        from strategies.price_action import confluence_signals

        legacy = confluence_signals(df)
        expected_count = int((legacy["signal"] != 0).sum())
        assert len(signals) == expected_count

    def test_decision_time_equals_available_time(self) -> None:
        """decision_time and available_time are both set to the signal bar close."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="BTCUSDT")

        for sig in signals:
            assert sig.decision_time == sig.available_time

    def test_horizon_is_4h(self) -> None:
        """All signals have horizon '4h' in the payload."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="BTCUSDT")

        for sig in signals:
            assert sig.payload["horizon"] == "4h"

    def test_next_bar_open_not_exposed(self) -> None:
        """The signal record must not contain the next bar's open timestamp."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="BTCUSDT")

        all_timestamps = set(df.index)
        for sig in signals:
            # Signal timestamp must be in the original data (not a future bar)
            sig_ts = pd.Timestamp(sig.decision_time)
            assert sig_ts in all_timestamps

    def test_factor_id_and_version(self) -> None:
        """All signals have the correct factor_id and factor_version in payload."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="BTCUSDT")

        for sig in signals:
            assert sig.payload["factor_id"] == "legacy.pa_confluence"
            assert sig.payload["factor_version"] == "baseline-0"

    def test_confidence_is_neutral(self) -> None:
        """Legacy PA does not emit confidence — it is set to 0.5 (neutral)."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="BTCUSDT")

        for sig in signals:
            assert sig.confidence == 0.5

    def test_direction_values_are_int(self) -> None:
        """Signal directions are exactly -1 or 1 as integers."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="BTCUSDT")

        for sig in signals:
            assert isinstance(sig.direction, int)
            assert sig.direction in (-1, 1)

    def test_asset_is_propagated(self) -> None:
        """The asset parameter is correctly set on all signals."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="ETHUSDT")

        for sig in signals:
            assert sig.asset == "ETHUSDT"

    def test_signals_are_causal(self) -> None:
        """All signals satisfy the SignalRecord causality constraint."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="BTCUSDT")

        # SignalRecord already validates available_time <= decision_time
        # at construction time, but verify explicitly
        for sig in signals:
            assert sig.available_time <= sig.decision_time

    def test_returns_signal_records(self) -> None:
        """All returned objects are SignalRecord instances."""
        df = _make_4h_fixture()
        signals = adapt_confluence_signals(df, asset="BTCUSDT")

        for sig in signals:
            assert isinstance(sig, SignalRecord)
