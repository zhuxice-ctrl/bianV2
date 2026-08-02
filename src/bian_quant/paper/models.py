"""Paper-trading configuration and immutable cycle/decision contracts.

Every model is frozen so a paper run cannot be mutated in place after it has
been recorded.  Monetary values use :class:`~decimal.Decimal` for reproducible
fixtures, mirroring the small-account backtest module.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

#: The only base URL a paper run may fetch from.
ALLOWED_BASE_URL = "https://fapi.binance.com"

#: The three public USD-M market-data endpoints permitted for paper capture.
ALLOWED_ENDPOINTS: tuple[str, ...] = (
    "/fapi/v1/klines",
    "/fapi/v1/exchangeInfo",
    "/fapi/v1/fundingRate",
)


class PaperCycleStatus(StrEnum):
    """Outcome of one four-hour paper cycle."""

    TRADE = "TRADE"
    NO_TRADE = "NO_TRADE"


class PaperFactorState(StrEnum):
    """Plan-A factor gate state visible to the paper runner."""

    OBSERVED = "OBSERVED"
    CANDIDATE = "CANDIDATE"
    APPROVED = "APPROVED"


class ApprovedInputLineage(BaseModel):
    """Immutable reference to the Approved Plan-A artifacts a paper run consumes.

    Every field must be non-empty; a paper run may never start from a missing
    or un-approved lineage.
    """

    model_config = ConfigDict(frozen=True)

    factor_id: str
    factor_version: str
    factor_state: PaperFactorState = PaperFactorState.APPROVED
    holdout_artifact_path: Path
    small_account_artifact_path: Path
    universe_artifact_id: str
    snapshot_ids: tuple[str, ...]

    @model_validator(mode="after")
    def _require_non_empty(self) -> ApprovedInputLineage:
        for name, value in (
            ("factor_id", self.factor_id),
            ("factor_version", self.factor_version),
            ("universe_artifact_id", self.universe_artifact_id),
        ):
            if not str(value).strip():
                raise ValueError(f"approved lineage requires non-empty {name}")
        if not self.snapshot_ids or any(not str(s).strip() for s in self.snapshot_ids):
            raise ValueError("approved lineage requires non-empty snapshot_ids")
        return self


class PaperRunConfig(BaseModel):
    """Locked configuration for one forward paper-trading run.

    The three endpoint paths, the four-hour interval, the 30-day review window,
    the 100 USDT initial equity, the 90 USDT gross cap, and the 10/5/20 risk
    limits are fixed by this contract.  Any base URL other than
    ``https://fapi.binance.com`` is rejected.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    base_url: str = ALLOWED_BASE_URL
    allowed_endpoints: tuple[str, ...] = ALLOWED_ENDPOINTS
    interval: timedelta = timedelta(hours=4)
    minimum_calendar_days: int = 30
    grace_period: timedelta = timedelta(minutes=5)

    initial_equity_usdt: Decimal = Decimal("100")
    max_gross_notional_usdt: Decimal = Decimal("90")
    max_positions: int = 2
    single_position_risk_usdt: Decimal = Decimal("10")
    two_position_risk_usdt: Decimal = Decimal("5")
    daily_loss_pause_usdt: Decimal = Decimal("10")
    drawdown_pause_usdt: Decimal = Decimal("20")

    # Approved Plan-A lineage consumed by every cycle.
    approved_factor_id: str
    approved_factor_version: str
    approved_factor_state: PaperFactorState = PaperFactorState.APPROVED
    holdout_artifact_path: Path
    small_account_artifact_path: Path
    universe_artifact_id: str
    snapshot_ids: tuple[str, ...]

    # Universe / decision inputs.
    decision_assets: tuple[str, ...]
    decision_asset: str
    stop_distance_pct: Decimal = Decimal("0.02")
    target_distance_pct: Decimal = Decimal("0.04")
    kline_limit: int = 200

    artifact_root: Path = Path("var/artifacts/paper")

    @field_validator("base_url")
    @classmethod
    def _only_binance_futures(cls, value: str) -> str:
        if value != ALLOWED_BASE_URL:
            raise ValueError(f"paper run rejects base_url: {value}")
        return value

    @field_validator("approved_factor_id")
    @classmethod
    def _require_approved_factor(cls, value: str) -> str:
        if not str(value).strip():
            raise ValueError("paper run requires approved factor")
        return value

    @model_validator(mode="after")
    def _require_lineage(self) -> PaperRunConfig:
        for name, value in (
            ("approved_factor_version", self.approved_factor_version),
            ("universe_artifact_id", self.universe_artifact_id),
        ):
            if not str(value).strip():
                raise ValueError(f"paper run requires non-empty {name}")
        if not self.snapshot_ids or any(not str(s).strip() for s in self.snapshot_ids):
            raise ValueError("paper run requires non-empty snapshot_ids")
        if not self.decision_assets or self.decision_asset not in self.decision_assets:
            raise ValueError("decision_asset must be one of decision_assets")
        if self.allowed_endpoints != ALLOWED_ENDPOINTS:
            raise ValueError("paper run endpoints are immutable")
        return self

    @classmethod
    def from_yaml(cls, path: Path | str) -> PaperRunConfig:
        """Load a locked paper-run configuration from a YAML file."""
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("paper config must be a YAML mapping")
        return cls.model_validate(data)


class MarketDataCapture(BaseModel):
    """One captured public market-data response, persisted before parsing."""

    model_config = ConfigDict(frozen=True)

    endpoint: str
    url: str
    request_time: datetime
    server_time: datetime | None
    data_time: datetime | None
    status: int
    body_sha256: str
    body_size: int
    parsed: Any = None


class PaperDecision(BaseModel):
    """One four-hour paper decision, append-only once recorded."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    scheduled_time: datetime
    decision_time: datetime
    status: PaperCycleStatus
    reason_code: str
    asset: str | None = None
    side: str | None = None
    quantity: Decimal | None = None
    entry: Decimal | None = None
    stop: Decimal | None = None
    target: Decimal | None = None
    notional: Decimal | None = None
    stop_risk: Decimal | None = None
    equity_before: Decimal
    equity_after: Decimal
    captures: tuple[MarketDataCapture, ...] = ()
    timing_violation: bool = False
    risk_breach: bool = False


class PaperPosition(BaseModel):
    """A simulated open paper position."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    scheduled_time: datetime
    asset: str
    side: str
    quantity: Decimal
    entry: Decimal
    stop: Decimal
    target: Decimal
    notional: Decimal
    stop_risk: Decimal


class PaperPortfolioState(BaseModel):
    """Reconstructable portfolio state for one paper run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    equity: Decimal
    high_water_mark: Decimal
    positions: tuple[PaperPosition, ...] = ()
    daily_loss: Decimal = Decimal("0")
    daily_reset_time: datetime | None = None
    pause_until: datetime | None = None

    def is_paused(self, now: datetime) -> bool:
        """True when the daily-loss / drawdown pause is still active at *now*."""
        return self.pause_until is not None and self.pause_until > now
