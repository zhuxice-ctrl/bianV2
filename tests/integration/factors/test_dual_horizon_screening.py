"""Integration tests for dual-horizon factor screening."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_series_equal

from bian_quant.factors.dual_horizon import (
    build_derivatives_factor_frame,
    dual_horizon_factor_specs,
    run_dual_horizon_screening,
)


def bars_fixture() -> pd.DataFrame:
    """Synthetic OHLCV bars with 4h frequency."""
    rng = np.random.default_rng(42)
    n = 200
    dates = pd.date_range("2025-12-01", periods=n, freq="4h", tz="UTC")
    close = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame({
        "event_time": dates,
        "available_time": dates + pd.Timedelta(minutes=1),
        "close": close,
        "volume": rng.lognormal(6, 0.5, n).astype(float),
    })


def funding_fixture() -> pd.DataFrame:
    """Synthetic funding rates every 8h."""
    rng = np.random.default_rng(43)
    dates = pd.date_range("2025-12-01", periods=70, freq="8h", tz="UTC")
    return pd.DataFrame({
        "event_time": dates,
        "available_time": dates + pd.Timedelta(minutes=1),
        "funding_rate": rng.normal(0.0001, 0.0005, 70),
    })


def oi_fixture() -> pd.DataFrame:
    """Synthetic open interest every 4h."""
    rng = np.random.default_rng(44)
    n = 200
    dates = pd.date_range("2025-12-01", periods=n, freq="4h", tz="UTC")
    oi = 1_000_000.0 * np.cumprod(1 + rng.normal(0, 0.02, n))
    return pd.DataFrame({
        "event_time": dates,
        "available_time": dates + pd.Timedelta(minutes=1),
        "open_interest": oi,
    })


def weak_signal_fixture() -> pd.DataFrame:
    """A frame where no factor has sufficient signal."""
    n = 50
    dates = pd.date_range("2025-12-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame({
        "event_time": dates,
        "available_time": dates + pd.Timedelta(minutes=1),
        "close": [100.0] * n,
        "volume": [1000.0] * n,
        "funding_rate": [0.0] * n,
        "open_interest": [1_000_000.0] * n,
    })


def screening_config(tmp_path: Path) -> dict:
    """Screening configuration for testing."""
    return {
        "artifact_dir": tmp_path / "artifacts",
        "bh_alpha": 0.05,
        "max_candidates": 20,
    }


class TestDualHorizonFactorSpecs:
    def test_eight_interpretable_factors_are_registered(self) -> None:
        specs = dual_horizon_factor_specs(primary_interval="4h")
        assert {spec.factor_id for spec in specs} == {
            "momentum_24",
            "reversal_12",
            "realized_vol_24",
            "volume_surprise_24",
            "amihud_24",
            "funding_zscore",
            "oi_change",
            "leverage_crowding",
        }

    def test_all_specs_are_frozen(self) -> None:
        specs = dual_horizon_factor_specs(primary_interval="4h")
        for spec in specs:
            assert spec.version == "1.0.0"

    def test_1h_lookbacks_preserve_elapsed_horizon(self) -> None:
        specs_4h = dual_horizon_factor_specs(primary_interval="4h")
        specs_1h = dual_horizon_factor_specs(primary_interval="1h")
        # Same factor IDs
        assert {s.factor_id for s in specs_4h} == {s.factor_id for s in specs_1h}
        # 1h horizon
        for spec in specs_1h:
            assert spec.horizon == "1h"


class TestBuildDerivativesFactorFrame:
    def test_delayed_oi_cannot_change_earlier_factor_values(self) -> None:
        five = build_derivatives_factor_frame(
            bars_fixture(), funding_fixture(), oi_fixture(), delay=5
        )
        fifteen = build_derivatives_factor_frame(
            bars_fixture(), funding_fixture(), oi_fixture(), delay=15
        )
        cutoff = pd.Timestamp("2026-01-01T04:10:00Z")
        assert_series_equal(
            five.loc[five.available_time <= cutoff, "oi_change"].reset_index(drop=True),
            fifteen.loc[fifteen.available_time <= cutoff, "oi_change"].reset_index(drop=True),
        )

    def test_all_eight_factors_computed(self) -> None:
        frame = build_derivatives_factor_frame(
            bars_fixture(), funding_fixture(), oi_fixture(), delay=5
        )
        expected = {
            "momentum_24",
            "reversal_12",
            "realized_vol_24",
            "volume_surprise_24",
            "amihud_24",
            "funding_zscore",
            "oi_change",
            "leverage_crowding",
        }
        assert expected.issubset(set(frame.columns))

    def test_availability_columns_retained(self) -> None:
        frame = build_derivatives_factor_frame(
            bars_fixture(), funding_fixture(), oi_fixture(), delay=5
        )
        assert "available_time" in frame.columns
        assert "funding_available_time" in frame.columns
        assert "oi_available_time" in frame.columns


class TestRunDualHorizonScreening:
    def test_zero_candidate_run_is_completed_not_failed(self, tmp_path: Path) -> None:
        result = run_dual_horizon_screening(
            weak_signal_fixture(),
            config=screening_config(tmp_path),
        )
        assert result.engineering_status == "passed"
        assert result.candidate_factor_ids == ()

    def test_strong_signal_produces_candidates(self, tmp_path: Path) -> None:
        frame = build_derivatives_factor_frame(
            bars_fixture(), funding_fixture(), oi_fixture(), delay=5
        )
        result = run_dual_horizon_screening(frame, config=screening_config(tmp_path))
        assert result.engineering_status == "passed"
        assert len(result.candidate_factor_ids) > 0
