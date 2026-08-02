"""Contract tests for paper-trading configuration and immutable models."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from bian_quant.paper.models import (
    ALLOWED_BASE_URL,
    ALLOWED_ENDPOINTS,
    ApprovedInputLineage,
    PaperCycleStatus,
    PaperFactorState,
    PaperRunConfig,
)

CONFIG_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "paper" / "popular_universe_100u.yaml"
)


def _lineage_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "factor_id": "momentum-4h-popular-v1",
        "factor_version": "1.0.0",
        "holdout_artifact_path": Path("var/holdout.json"),
        "small_account_artifact_path": Path("var/backtest.json"),
        "universe_artifact_id": "popular-universe-2026-07-26",
        "snapshot_ids": ("micro-4h-popular-2026-07-26",),
    }
    base.update(overrides)
    return base


def _config_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "run_id": "paper-run-1",
        "approved_factor_id": "momentum-4h-popular-v1",
        "approved_factor_version": "1.0.0",
        "holdout_artifact_path": Path("var/holdout.json"),
        "small_account_artifact_path": Path("var/backtest.json"),
        "universe_artifact_id": "popular-universe-2026-07-26",
        "snapshot_ids": ("micro-4h-popular-2026-07-26",),
        "decision_assets": ("BTCUSDT", "ETHUSDT"),
        "decision_asset": "BTCUSDT",
    }
    base.update(overrides)
    return base


def test_config_loads_locked_values() -> None:
    config = PaperRunConfig.from_yaml(CONFIG_PATH)
    assert config.interval == timedelta(hours=4)
    assert config.minimum_calendar_days == 30
    assert config.allowed_endpoints == (
        "/fapi/v1/klines",
        "/fapi/v1/exchangeInfo",
        "/fapi/v1/fundingRate",
    )
    assert config.base_url == ALLOWED_BASE_URL
    assert config.initial_equity_usdt == Decimal("100")
    assert config.max_gross_notional_usdt == Decimal("90")
    assert config.single_position_risk_usdt == Decimal("10")
    assert config.two_position_risk_usdt == Decimal("5")
    assert config.drawdown_pause_usdt == Decimal("20")


def test_empty_approved_factor_rejected() -> None:
    config = PaperRunConfig.model_validate(_config_kwargs())
    with pytest.raises(ValueError, match="paper run requires approved factor"):
        PaperRunConfig.model_validate({**config.model_dump(), "approved_factor_id": ""})


def test_foreign_base_url_rejected() -> None:
    with pytest.raises(ValueError, match="paper run rejects base_url"):
        PaperRunConfig.model_validate(_config_kwargs(base_url="https://api.binance.com"))


def test_endpoints_immutable() -> None:
    with pytest.raises(ValueError, match="paper run endpoints are immutable"):
        PaperRunConfig.model_validate(_config_kwargs(allowed_endpoints=("/fapi/v1/klines",)))


def test_approved_lineage_requires_non_empty() -> None:
    with pytest.raises(ValueError, match="approved lineage requires non-empty factor_id"):
        ApprovedInputLineage.model_validate(_lineage_kwargs(factor_id=""))
    with pytest.raises(ValueError, match="approved lineage requires non-empty snapshot_ids"):
        ApprovedInputLineage.model_validate(_lineage_kwargs(snapshot_ids=()))


def test_models_are_frozen() -> None:
    config = PaperRunConfig.model_validate(_config_kwargs())
    with pytest.raises(ValidationError):
        config.run_id = "mutated"  # type: ignore[misc]


def test_factor_state_enum() -> None:
    assert PaperFactorState.APPROVED.value == "APPROVED"
    assert PaperCycleStatus.TRADE.value == "TRADE"
    assert ALLOWED_ENDPOINTS == (
        "/fapi/v1/klines",
        "/fapi/v1/exchangeInfo",
        "/fapi/v1/fundingRate",
    )
