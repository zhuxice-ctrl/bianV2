"""Integration tests for dual-horizon factor screening."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from pandas.testing import assert_frame_equal, assert_series_equal

from bian_quant.factors.dual_horizon import (
    build_derivatives_factor_frame,
    compute_dual_horizon_factor_columns,
    dual_horizon_factor_specs,
)
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorState
from bian_quant.research.dual_horizon import run_dual_horizon_screening


def bars_fixture() -> pd.DataFrame:
    """Synthetic OHLCV bars with 4h frequency."""
    rng = np.random.default_rng(42)
    n = 200
    dates = pd.date_range("2025-12-01", periods=n, freq="4h", tz="UTC")
    close = 100.0 * np.cumprod(1 + rng.normal(0, 0.01, n))
    return pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": dates,
            "available_time": dates + pd.Timedelta(minutes=1),
            "close": close,
            "volume": rng.lognormal(6, 0.5, n).astype(float),
        }
    )


def funding_fixture() -> pd.DataFrame:
    """Synthetic funding rates every 8h."""
    rng = np.random.default_rng(43)
    dates = pd.date_range("2025-12-01", periods=70, freq="8h", tz="UTC")
    return pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": dates,
            "available_time": dates + pd.Timedelta(minutes=1),
            "funding_rate": rng.normal(0.0001, 0.0005, 70),
        }
    )


def oi_fixture() -> pd.DataFrame:
    """Synthetic open interest every 4h."""
    rng = np.random.default_rng(44)
    n = 200
    dates = pd.date_range("2025-12-01", periods=n, freq="4h", tz="UTC")
    oi = 1_000_000.0 * np.cumprod(1 + rng.normal(0, 0.02, n))
    return pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": dates,
            "available_time": dates + pd.Timedelta(minutes=1),
            "open_interest": oi,
        }
    )


def weak_signal_fixture() -> pd.DataFrame:
    """A frame where no factor has sufficient signal."""
    n = 50
    dates = pd.date_range("2025-12-01", periods=n, freq="4h", tz="UTC")
    return pd.DataFrame(
        {
            "asset": "BTCUSDT",
            "event_time": dates,
            "available_time": dates + pd.Timedelta(minutes=1),
            "close": [100.0] * n,
            "volume": [1000.0] * n,
            "funding_rate": [0.0] * n,
            "open_interest": [1_000_000.0] * n,
        }
    )


def multi_asset_pressure_frame() -> pd.DataFrame:
    """Three assets (BTC, ETH, BNB) with simultaneous valid funding.

    Every asset shares the same ``available_time`` grid so the
    cross-sectional pressure is well-defined at each timestamp.
    """
    dates = pd.date_range("2025-12-01", periods=40, freq="4h", tz="UTC")
    rows: list[dict[str, Any]] = []
    for asset, rate in [("BTCUSDT", 0.0003), ("ETHUSDT", 0.0001), ("BNBUSDT", -0.0001)]:
        for t in dates:
            rows.append(
                {
                    "asset": asset,
                    "event_time": t,
                    "available_time": t + pd.Timedelta(minutes=1),
                    "close": 100.0,
                    "high": 101.0,
                    "low": 99.0,
                    "volume": 1000.0,
                    "funding_rate": rate,
                    "funding_available_time": t,
                    "funding_interval_hours": 8,
                    "open_interest": 1_000_000.0,
                }
            )
    return pd.DataFrame(rows)


def screening_config(tmp_path: Path) -> dict:
    """Screening configuration for testing."""
    return {
        "artifact_dir": tmp_path / "artifacts",
        "bh_alpha": 0.05,
        "max_candidates": 20,
    }


class TestDualHorizonFactorSpecs:
    def test_nine_interpretable_factors_are_registered(self) -> None:
        specs = dual_horizon_factor_specs(primary_interval="4h")
        assert {spec.factor_id for spec in specs} == {
            "momentum_24",
            "reversal_12",
            "realized_vol_24",
            "volume_surprise_24",
            "amihud_24",
            "funding_zscore",
            "relative_funding_pressure",
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

    def test_all_nine_factors_computed(self) -> None:
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
            "relative_funding_pressure",
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

    def test_interleaved_assets_do_not_share_derivatives_or_rolling_history(self) -> None:
        bars = pd.concat(
            [
                bars_fixture().iloc[:30],
                bars_fixture().iloc[:30].assign(asset="ETHUSDT", close=50.0),
            ],
            ignore_index=True,
        ).sort_values("available_time")
        funding = pd.concat(
            [
                funding_fixture().iloc[:15],
                funding_fixture().iloc[:15].assign(asset="ETHUSDT", funding_rate=0.25),
            ],
            ignore_index=True,
        ).sort_values("available_time")
        oi = pd.concat(
            [
                oi_fixture().iloc[:30],
                oi_fixture().iloc[:30].assign(asset="ETHUSDT", open_interest=10.0),
            ],
            ignore_index=True,
        ).sort_values("available_time")

        frame = build_derivatives_factor_frame(bars, funding, oi, delay=5)
        btc = frame.loc[frame.asset == "BTCUSDT"]
        eth = frame.loc[frame.asset == "ETHUSDT"]

        assert btc["funding_rate"].max() < 0.01
        assert eth["funding_rate"].min() == 0.25
        assert eth["momentum_24"].dropna().eq(0.0).all()
        assert btc["open_interest"].min() > 100_000
        assert eth["open_interest"].dropna().eq(10.0).all()

    def test_missing_derivatives_remain_null(self) -> None:
        bars = bars_fixture().iloc[:30].assign(asset="ETHUSDT")
        frame = build_derivatives_factor_frame(
            bars,
            funding_fixture().iloc[:5],
            oi_fixture().iloc[:5],
        )

        assert frame["funding_rate"].isna().all()
        assert frame["open_interest"].isna().all()
        assert frame["funding_zscore"].isna().all()
        assert frame["oi_change"].isna().all()
        assert frame["relative_funding_pressure"].isna().all()

    def test_delay_scenarios_diverge_only_after_their_publication_boundary(self) -> None:
        bars = pd.DataFrame(
            {
                "asset": "BTCUSDT",
                "available_time": pd.to_datetime(
                    ["2026-01-01T00:04Z", "2026-01-01T00:10Z", "2026-01-01T00:16Z"]
                ),
                "close": [100.0, 101.0, 102.0],
                "volume": [10.0, 10.0, 10.0],
            }
        )
        funding = funding_fixture().iloc[:1]
        oi = pd.DataFrame(
            {
                "asset": ["BTCUSDT"],
                "event_time": pd.to_datetime(["2026-01-01T00:00Z"]),
                "open_interest": [123.0],
            }
        )

        five = build_derivatives_factor_frame(bars, funding, oi, delay=5)
        ten = build_derivatives_factor_frame(bars, funding, oi, delay=10)
        fifteen = build_derivatives_factor_frame(bars, funding, oi, delay=15)

        assert five["open_interest"].isna().tolist() == [True, False, False]
        assert ten["open_interest"].isna().tolist() == [True, False, False]
        assert fifteen["open_interest"].isna().tolist() == [True, True, False]

    def test_existing_canonical_oi_delay_is_not_applied_twice(self) -> None:
        bars = pd.DataFrame(
            {
                "asset": "BTCUSDT",
                "available_time": pd.to_datetime(
                    ["2026-01-01T00:09Z", "2026-01-01T00:14Z", "2026-01-01T00:16Z"]
                ),
                "close": [100.0, 101.0, 102.0],
                "volume": [10.0, 10.0, 10.0],
            }
        )
        oi = pd.DataFrame(
            {
                "asset": ["BTCUSDT"],
                "event_time": pd.to_datetime(["2026-01-01T00:00Z"]),
                "available_time": pd.to_datetime(["2026-01-01T00:10Z"]),
                "availability_assumption": ["BINANCE_METRICS_DELAY_10M"],
                "open_interest": [123.0],
            }
        )

        fifteen = build_derivatives_factor_frame(bars, funding_fixture().iloc[:1], oi, delay=15)

        assert fifteen["open_interest"].isna().tolist() == [True, True, False]

    def test_gapped_derivatives_are_null_with_exclusion_evidence(self) -> None:
        bars = bars_fixture().iloc[:5].copy()
        bars["available_time"] = pd.date_range("2026-01-01T00:00Z", periods=5, freq="4h")
        funding = pd.DataFrame(
            {
                "asset": ["BTCUSDT"],
                "available_time": pd.to_datetime(["2026-01-01T00:00Z"]),
                "funding_rate": [0.001],
                "funding_interval_hours": [8],
            }
        )
        oi = pd.DataFrame(
            {
                "asset": ["BTCUSDT"],
                "event_time": pd.to_datetime(["2025-12-31T23:55Z"]),
                "open_interest": [123.0],
            }
        )

        frame = build_derivatives_factor_frame(bars, funding, oi, delay=5, interval="4h")

        assert pd.isna(frame.loc[3, "funding_rate"])
        assert frame.loc[3, "funding_exclusion_reason"] == "FUNDING_UNAVAILABLE_OR_GAPPED"
        assert pd.isna(frame.loc[2, "open_interest"])
        assert frame.loc[2, "oi_exclusion_reason"] == "OI_UNAVAILABLE_OR_GAPPED"

    def test_1h_and_4h_use_clock_equivalent_price_lookbacks(self) -> None:
        bars_1h = bars_fixture().iloc[:120].copy()
        bars_1h["available_time"] = pd.date_range(
            "2025-12-01T00:01Z", periods=len(bars_1h), freq="1h"
        )
        bars_1h["close"] = np.arange(1.0, len(bars_1h) + 1.0)
        bars_4h = bars_1h.iloc[::4].reset_index(drop=True)

        one = build_derivatives_factor_frame(
            bars_1h, funding_fixture(), oi_fixture(), interval="1h"
        )
        four = build_derivatives_factor_frame(
            bars_4h, funding_fixture(), oi_fixture(), interval="4h"
        )

        assert one["momentum_24"].first_valid_index() == 96
        assert four["momentum_24"].first_valid_index() == 24


class TestRelativeFundingPressureFactor:
    def test_pressure_columns_present_for_multi_asset_frame(self) -> None:
        frame = compute_dual_horizon_factor_columns(multi_asset_pressure_frame())
        assert "relative_funding_pressure" in frame.columns
        assert "relative_funding_pressure_exclusion_reason" in frame.columns

    def test_three_assets_have_non_missing_pressure_at_same_timestamp(self) -> None:
        frame = compute_dual_horizon_factor_columns(multi_asset_pressure_frame())
        timestamp = frame["available_time"].iloc[0]
        mask = frame["available_time"] == timestamp
        assert mask.sum() == 3
        assert frame.loc[mask, "relative_funding_pressure"].notna().all()

    def test_prefix_causality_future_funding_does_not_change_past(self) -> None:
        base = multi_asset_pressure_frame()
        computed_base = compute_dual_horizon_factor_columns(base)

        # Corrupt funding rates after the cutoff.
        cutoff = base["available_time"].iloc[20]
        future = base.copy()
        future.loc[future["available_time"] > cutoff, "funding_rate"] *= -100
        computed_future = compute_dual_horizon_factor_columns(future)

        # Filter both sides by the same cutoff and compare prefix bytes.
        prefix_base = (
            computed_base.loc[computed_base["available_time"] <= cutoff]
            .sort_values(["asset", "available_time"])
            .reset_index(drop=True)
        )
        prefix_future = (
            computed_future.loc[computed_future["available_time"] <= cutoff]
            .sort_values(["asset", "available_time"])
            .reset_index(drop=True)
        )

        cols = [
            "asset",
            "available_time",
            "relative_funding_pressure",
            "relative_funding_pressure_exclusion_reason",
        ]
        assert_frame_equal(prefix_base[cols], prefix_future[cols])

    def test_missing_funding_metadata_yields_nan_pressure_and_preserves_existing_factors(
        self,
    ) -> None:
        full = multi_asset_pressure_frame()
        # Remove the three funding metadata columns.
        stripped = full.drop(
            columns=["funding_rate", "funding_available_time", "funding_interval_hours"]
        )
        computed = compute_dual_horizon_factor_columns(stripped)

        # New factor should be all missing.
        assert computed["relative_funding_pressure"].isna().all()

        # Existing eight factors should match the full-frame computation
        # (stripped of funding_rate which feeds funding_zscore/leverage).
        full_computed = compute_dual_horizon_factor_columns(
            full.drop(columns=["funding_rate", "funding_available_time", "funding_interval_hours"])
        )
        eight_cols = [
            "momentum_24",
            "reversal_12",
            "realized_vol_24",
            "volume_surprise_24",
            "amihud_24",
            "funding_zscore",
            "oi_change",
            "leverage_crowding",
        ]
        assert_frame_equal(
            computed[["asset", "available_time", *eight_cols]]
            .sort_values(["asset", "available_time"])
            .reset_index(drop=True),
            full_computed[["asset", "available_time", *eight_cols]]
            .sort_values(["asset", "available_time"])
            .reset_index(drop=True),
        )


class TestRunDualHorizonScreening:
    def test_zero_candidate_run_is_completed_not_failed(self, tmp_path: Path) -> None:
        result = run_dual_horizon_screening(
            weak_signal_fixture(),
            config={
                **screening_config(tmp_path),
                "development_start": "2025-12-01T00:00:00Z",
                "development_end": "2026-02-01T00:00:00Z",
            },
        )
        assert result.engineering_status == "passed"
        assert result.candidate_factor_ids == ()

    def test_unconfigured_or_weak_signal_never_promotes_by_variance(self, tmp_path: Path) -> None:
        frame = build_derivatives_factor_frame(
            bars_fixture(), funding_fixture(), oi_fixture(), delay=5
        )
        result = run_dual_horizon_screening(
            frame,
            config={
                **screening_config(tmp_path),
                "development_start": "2025-12-01T00:00:00Z",
                "development_end": "2026-02-01T00:00:00Z",
            },
        )
        assert result.engineering_status == "passed"
        assert result.candidate_factor_ids == ()

    def test_signal_added_after_development_window_is_inaccessible(self, tmp_path: Path) -> None:
        base = build_derivatives_factor_frame(
            bars_fixture(), funding_fixture(), oi_fixture(), delay=5
        )
        config = {
            **screening_config(tmp_path),
            "development_start": "2025-12-01T00:00:00Z",
            "development_end": "2025-12-25T00:00:00Z",
        }
        original = run_dual_horizon_screening(base, config=config)
        future = base.loc[base.available_time >= config["development_end"]].copy()
        future["momentum_24"] = np.linspace(1.0, 1_000_000.0, len(future))
        changed = pd.concat(
            [base.loc[base.available_time < config["development_end"]], future],
            ignore_index=True,
        )

        extended = run_dual_horizon_screening(changed, config=config)

        assert extended.candidate_factor_ids == original.candidate_factor_ids
        assert extended.gate_reasons == original.gate_reasons
        assert extended.factor_evaluations == original.factor_evaluations
        assert extended.factor_diagnostics == original.factor_diagnostics

    def test_completed_evidence_precedes_lifecycle_and_is_append_only(self, tmp_path: Path) -> None:
        registry_path = tmp_path / "factor-registry.sqlite"
        config = {
            **screening_config(tmp_path),
            "run_id": "repair-3-lifecycle",
            "code_sha": "a" * 40,
            "factor_registry_path": registry_path,
            "development_start": "2025-12-01T00:00:00Z",
            "development_end": "2026-02-01T00:00:00Z",
        }
        frame = build_derivatives_factor_frame(
            bars_fixture(), funding_fixture(), oi_fixture(), delay=5
        )

        result = run_dual_horizon_screening(frame, config=config)

        assert result.artifact_path is not None
        assert result.lifecycle_artifact_path is not None
        import json

        payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
        assert payload["stage"] == "completed_development_evidence"
        assert payload["holdout_accessed"] is False
        assert payload["planned_lifecycle_states"]["momentum_24"] == "observed"
        assert payload["factor_diagnostics"]["momentum_24"]["reason_codes"]
        development_bytes = result.artifact_path.read_bytes()
        with FactorRegistry(registry_path) as registry:
            assert registry.state("momentum_24", "1.0.0") == FactorState.OBSERVED
            history_before = registry.history("momentum_24", "1.0.0")
            assert history_before[-1]["evidence_run_id"] == "repair-3-lifecycle"

        import pytest

        with pytest.raises(FileExistsError, match="already exists"):
            run_dual_horizon_screening(frame, config=config)
        assert result.artifact_path.read_bytes() == development_bytes
        with FactorRegistry(registry_path) as registry:
            assert registry.history("momentum_24", "1.0.0") == history_before

    def test_candidate_ids_do_not_promote_development_lifecycle(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import json

        import bian_quant.research.dual_horizon as research

        def forced_gates(
            names: list[str], *_args: Any, **_kwargs: Any
        ) -> tuple[dict[str, list[str]], dict[str, dict[str, Any]], list[str]]:
            reasons = {name: ["ALL_DEVELOPMENT_GATES_PASSED"] for name in names}
            diagnostics = {name: {"reason_codes": reasons[name]} for name in names}
            return reasons, diagnostics, ["momentum_24"]

        monkeypatch.setattr(research, "_apply_gates", forced_gates)
        registry_path = tmp_path / "factor-registry.sqlite"
        result = run_dual_horizon_screening(
            build_derivatives_factor_frame(
                bars_fixture(), funding_fixture(), oi_fixture(), delay=5
            ),
            config={
                **screening_config(tmp_path),
                "run_id": "candidate-state-guard",
                "code_sha": "a" * 40,
                "factor_registry_path": registry_path,
                "development_start": "2025-12-01T00:00:00Z",
                "development_end": "2026-02-01T00:00:00Z",
            },
        )

        assert result.candidate_factor_ids == ("momentum_24",)
        assert result.artifact_path is not None
        payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
        assert payload["planned_lifecycle_states"]["momentum_24"] == "observed"
        with FactorRegistry(registry_path) as registry:
            assert registry.state("momentum_24", "1.0.0") is FactorState.OBSERVED

    def test_generator_runs_only_after_all_nine_interpretable_factors(
        self, tmp_path: Path, monkeypatch: Any
    ) -> None:
        import bian_quant.research.dual_horizon as research

        events: list[str] = []
        real_evaluate = research.evaluate_factor

        def recording_evaluate(factor: pd.Series, *args: Any, **kwargs: Any) -> Any:
            events.append(str(factor.name))
            return real_evaluate(factor, *args, **kwargs)

        def recording_generate(*args: Any, **kwargs: Any) -> list[Any]:
            events.append("__generator__")
            return []

        monkeypatch.setattr(research, "evaluate_factor", recording_evaluate)
        monkeypatch.setattr(research, "generate_candidates", recording_generate)
        frame = build_derivatives_factor_frame(
            bars_fixture(), funding_fixture(), oi_fixture(), delay=5
        )

        result = run_dual_horizon_screening(
            frame,
            config={
                **screening_config(tmp_path),
                "development_start": "2025-12-01T00:00:00Z",
                "development_end": "2026-02-01T00:00:00Z",
            },
        )

        generator_index = events.index("__generator__")
        assert set(events[:generator_index]) == {
            "momentum_24",
            "reversal_12",
            "realized_vol_24",
            "volume_surprise_24",
            "amihud_24",
            "funding_zscore",
            "relative_funding_pressure",
            "oi_change",
            "leverage_crowding",
        }
        assert len(result.generated_factor_ids) <= 20

    def test_relative_funding_pressure_diagnostics_recorded_in_development_artifact(
        self, tmp_path: Path
    ) -> None:
        import json

        registry_path = tmp_path / "factor-registry.sqlite"
        config = {
            **screening_config(tmp_path),
            "run_id": "rfp-diagnostics",
            "code_sha": "relative-funding-pressure-1.0.0",
            "factor_registry_path": registry_path,
            "development_start": "2025-12-01T00:00:00Z",
            "development_end": "2026-02-01T00:00:00Z",
        }
        result = run_dual_horizon_screening(multi_asset_pressure_frame(), config=config)

        assert result.artifact_path is not None
        payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
        assert payload["holdout_accessed"] is False
        assert "relative_funding_pressure" in payload["factor_diagnostics"]
        assert (
            "relative_funding_pressure_exclusion_reason"
            in (payload["factor_diagnostics"]["relative_funding_pressure"]["exclusion_evidence"])
        )
        assert payload["planned_lifecycle_states"]["relative_funding_pressure"] in {
            "observed",
            "researching",
        }
