"""Integration test: backtest-small-account command gates on Approved factor."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from bian_quant.factors.spec import FactorSpec, FactorState


def _spec(factor_id: str = "momentum_24") -> FactorSpec:
    return FactorSpec(
        factor_id=factor_id,
        version="0.1.0",
        formula="test",
        direction="two_sided",
        hypothesis="A sufficiently descriptive test hypothesis.",
        required_columns=["close", "volume"],
        horizon="4h",
        missing_policy="preserve",
        winsor_limits=(0.01, 0.99),
        valid_regimes=["trending_up", "trending_down", "ranging"],
        failure_conditions=["test"],
        parent_factors=[],
    )


class TestSmallAccountBacktestGate:
    """Tests that run_small_account_backtest enforces APPROVED state."""

    def test_non_approved_factor_raises_permission_error(self, tmp_path: Path) -> None:
        from bian_quant.research.operations import run_small_account_backtest

        # Create a minimal factor registry with a CANDIDATE factor.
        registry_path = tmp_path / "factors.sqlite"
        from bian_quant.factors.registry import FactorRegistry

        spec = _spec()
        with FactorRegistry(registry_path) as registry:
            registry.register(spec, code_sha="a" * 40)
            registry.transition(
                spec.factor_id, spec.version, FactorState.OBSERVED, evidence_run_id="run-1"
            )
            registry.transition(
                spec.factor_id, spec.version, FactorState.CANDIDATE, evidence_run_id="run-1"
            )

        # Create a minimal config.
        config = _minimal_config(tmp_path, registry_path)

        with pytest.raises(PermissionError, match="BACKTEST_ACCESS_DENIED"):
            run_small_account_backtest(
                config,
                factor_id=spec.factor_id,
                factor_version=spec.version,
                snapshot_id="snap-1",
                backtest_config_path=tmp_path / "backtest.yaml",
            )

    def test_approved_factor_proceeds_to_backtest(self, tmp_path: Path) -> None:
        from bian_quant.research.operations import run_small_account_backtest

        registry_path = tmp_path / "factors.sqlite"
        from bian_quant.factors.registry import FactorRegistry

        spec = _spec()
        with FactorRegistry(registry_path) as registry:
            registry.register(spec, code_sha="a" * 40)
            registry.transition(
                spec.factor_id, spec.version, FactorState.OBSERVED, evidence_run_id="run-1"
            )
            registry.transition(
                spec.factor_id, spec.version, FactorState.CANDIDATE, evidence_run_id="run-1"
            )
            registry.transition(
                spec.factor_id, spec.version, FactorState.APPROVED, evidence_run_id="run-1"
            )

        config = _minimal_config(tmp_path, registry_path)

        # Create a minimal snapshot catalog entry.
        _create_minimal_snapshot(config, factor_id=spec.factor_id)

        # Create backtest config.
        backtest_config = tmp_path / "backtest.yaml"
        backtest_config.write_text(
            "initial_equity_usdt: 100\n"
            "max_gross_notional_usdt: 90\n"
            "max_positions: 2\n"
            "single_position_risk_usdt: 10\n"
            "two_position_risk_usdt: 5\n"
            "daily_loss_pause_usdt: 10\n"
            "drawdown_pause_usdt: 20\n"
            "taker_fee_bps: 4\n"
            "slippage_bps: 10\n"
            "interval: 4h\n",
            encoding="utf-8",
        )

        result = run_small_account_backtest(
            config,
            factor_id=spec.factor_id,
            factor_version=spec.version,
            snapshot_id="micro-4h-snap-1",
            backtest_config_path=backtest_config,
        )
        assert result.status == "completed"
        assert result.factor_id == spec.factor_id
        assert result.artifact_path.exists()
        payload = json.loads(result.artifact_path.read_text(encoding="utf-8"))
        assert payload["status"] == "completed"


def _minimal_config(tmp_path: Path, registry_path: Path):
    from bian_quant.data.acquisition import DualHorizonAcquisition

    return DualHorizonAcquisition(
        assets=("BTCUSDT", "ETHUSDT", "BNBUSDT"),
        macro_start=datetime(2026, 7, 1, tzinfo=UTC),
        micro_start=datetime(2026, 7, 1, tzinfo=UTC),
        as_of=datetime(2026, 7, 3, 23, 59, 59, 999000, tzinfo=UTC),
        macro_intervals=("1d", "4h"),
        micro_intervals=("1h", "4h"),
        oi_delay_minutes=(5, 10, 15),
        funding_tail_strategy="monthly_archive_after_period_close",
        parent_snapshot_ids=(),
        raw_root=tmp_path / "raw",
        canonical_root=tmp_path / "canonical",
        research_root=tmp_path / "research",
        artifact_root=tmp_path / "artifacts",
        catalog_path=tmp_path / "catalog.sqlite",
        experiment_registry_path=tmp_path / "experiments.sqlite",
        factor_registry_path=registry_path,
        download_attempts=1,
        max_workers=1,
        disk_warn_gb=10,
        disk_block_gb=5,
        coverage={"ohlcv": 0.01, "funding": 0.01, "metrics_oi": 0.01},
        factor_protocol={
            "primary_interval": "4h",
            "sensitivity_interval": "1h",
            "development_months": 18,
            "holdout_months": 6,
            "development_start": "2026-07-01T00:00:00Z",
            "development_end_exclusive": "2026-07-02T00:00:00Z",
            "holdout_start": "2026-07-03T00:00:00Z",
            "holdout_end": "2026-07-03T23:59:59.999Z",
            "bh_alpha": 0.05,
            "minimum_inference_samples": 30,
            "max_candidates": 20,
            "cost_bps": [5, 10],
        },
    )


def _create_minimal_snapshot(config, factor_id: str = "test_factor") -> None:
    """Create a minimal micro-4h snapshot with enough data for backtesting."""
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq

    from bian_quant.data.catalog import DatasetCatalog
    from bian_quant.data.contracts import DatasetLayer, DatasetManifest

    catalog = DatasetCatalog(config.catalog_path)

    # Create a minimal snapshot with 4h bars for 2 assets over 3 days.
    timestamps = pd.date_range("2026-07-01", periods=18, freq="4h", tz="UTC")
    rows = []
    for asset in ("BTCUSDT", "ETHUSDT"):
        for i, ts in enumerate(timestamps):
            price = 50000 + i * 10 if asset == "BTCUSDT" else 3000 + i * 5
            rows.append(
                {
                    "asset": asset,
                    "event_time": ts,
                    "available_time": ts,
                    "open": float(price),
                    "high": float(price + 50),
                    "low": float(price - 50),
                    "close": float(price + 5),
                    "volume": float(1000 + i),
                    "quote_volume": float(50000000 + i * 1000),
                    "funding_rate": 0.0001,
                    "funding_available_time": ts,
                    "sum_open_interest": 100000.0,
                    "sum_open_interest_value": 5000000000.0,
                    "oi_available_time": ts,
                    "availability_assumption": "observed",
                }
            )
    frame = pd.DataFrame(rows)

    # Write parquet.
    snapshot_dir = config.research_root / "micro-4h"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    parquet_path = snapshot_dir / "snap-1.parquet"
    table = pa.Table.from_pandas(frame)
    pq.write_table(table, parquet_path)

    import hashlib

    content_sha = hashlib.sha256(parquet_path.read_bytes()).hexdigest()

    manifest = DatasetManifest(
        snapshot_id="micro-4h-snap-1",
        layer=DatasetLayer.RESEARCH,
        name="micro-4h",
        content_sha256=content_sha,
        row_count=len(frame),
        min_event_time=frame["event_time"].min(),
        max_event_time=frame["event_time"].max(),
        min_available_time=frame["available_time"].min(),
        max_available_time=frame["available_time"].max(),
        parent_snapshot_ids=("parent-1",),
        config_json=json.dumps(
            {
                "assets": list(config.assets),
                "macro_start": config.macro_start.isoformat(),
                "micro_start": config.micro_start.isoformat(),
                "as_of": config.as_of.isoformat(),
                "code_sha": "a" * 40,
            },
            sort_keys=True,
            separators=(",", ":"),
        ),
    )
    catalog.register(manifest, path=parquet_path)
