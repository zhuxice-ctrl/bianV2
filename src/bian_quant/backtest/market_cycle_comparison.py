"""Offline 100U comparison for confidence-capped three-coin exposure."""

from __future__ import annotations

import hashlib
import json
import zipfile
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from bian_quant.backtest.confidence_allocation import (
    THREE_COIN_UNIVERSE,
    allocate_confidence_cap,
)
from bian_quant.data.funding_alignment import FundingAlignmentRecord
from bian_quant.regimes.market_cycle import (
    MarketCycleState,
    classify_market_cycle,
    load_popular_universe_records,
    market_cycle_payload,
)


@dataclass(frozen=True)
class BacktestMetrics:
    final_equity: float
    total_return: float
    annualized_volatility: float
    max_drawdown: float
    sharpe_like: float
    trade_count: int


@dataclass(frozen=True)
class MarketCycleComparison:
    baseline: BacktestMetrics
    confidence_weighted: BacktestMetrics
    latest_cycle: MarketCycleState
    latest_allocation: dict[str, object]
    artifact_sha256: str
    funding_alignment_source_sha256: str | None = None
    funding_alignment_applied_signal_count: int | None = None


def run_market_cycle_comparison(
    returns: pd.DataFrame,
    popular_records: pd.DataFrame,
    *,
    initial_equity_usdt: Decimal = Decimal("100"),
    funding_alignment: tuple[FundingAlignmentRecord, ...] | None = None,
) -> MarketCycleComparison:
    """Compare fixed 100U exposure with confidence-capped exposure.

    When *funding_alignment* is ``None`` (default) the output is byte-identical
    to the pre-funding behaviour.  When provided, ``classify_market_cycle``
    applies the point-in-time funding evidence to the weighted variant only;
    the baseline (equal-weight) variant is never affected.
    """
    if returns.empty:
        latest_cycle = classify_market_cycle(popular_records, funding_alignment=funding_alignment)
        empty_payload = {
            "baseline": _metrics_payload(_empty_metrics(float(initial_equity_usdt))),
            "confidence_weighted": _metrics_payload(_empty_metrics(float(initial_equity_usdt))),
            "latest_cycle": market_cycle_payload(latest_cycle),
            "latest_allocation": {},
        }
        return MarketCycleComparison(
            baseline=_empty_metrics(float(initial_equity_usdt)),
            confidence_weighted=_empty_metrics(float(initial_equity_usdt)),
            latest_cycle=latest_cycle,
            latest_allocation={},
            artifact_sha256=_hash(empty_payload),
        )

    frame = _prepare_returns(returns)
    baseline_equity: list[float] = []
    weighted_equity: list[float] = []
    base_equity = float(initial_equity_usdt)
    conf_equity = float(initial_equity_usdt)
    latest_state = classify_market_cycle(popular_records, funding_alignment=funding_alignment)
    latest_allocation: dict[str, object] = {}
    funding_source_sha: str | None = None
    funding_applied_count = 0

    for idx, row in frame.iterrows():
        date = pd.Timestamp(str(idx)).to_pydatetime()
        historical_popular = _records_through(popular_records, date)
        state = classify_market_cycle(historical_popular, funding_alignment=funding_alignment)
        # Track funding evidence applied at this decision point
        raw_state_funding_sha = state.evidence.get("funding_alignment_source_sha256")
        state_funding_sha = (
            raw_state_funding_sha if isinstance(raw_state_funding_sha, str) else None
        )
        if state_funding_sha is not None:
            funding_source_sha = state_funding_sha
            funding_applied_count += 1
        # The comparison has no independent entry signal. Use a fixed equal-weight
        # BTC/ETH/BNB basket so realized returns cannot leak into the position
        # weights (which would square gains and discard losses).
        weights = {asset: 1.0 for asset in THREE_COIN_UNIVERSE}
        baseline_cap = _normalize_weights(weights, 1.0)
        allocation = allocate_confidence_cap(state, weights, capital_usdt=initial_equity_usdt)
        weighted_cap = {
            asset: float(allocation.per_asset_caps_usdt.get(asset, Decimal("0")))
            / float(initial_equity_usdt)
            for asset in THREE_COIN_UNIVERSE
        }
        base_equity *= 1.0 + _portfolio_return(row, baseline_cap, 1.0)
        conf_equity *= 1.0 + _portfolio_return(row, weighted_cap, 1.0)
        baseline_equity.append(base_equity)
        weighted_equity.append(conf_equity)
        latest_state = state
        latest_allocation = {
            "total_cap_usdt": float(allocation.total_cap_usdt),
            "per_asset_caps_usdt": weighted_cap,
            "selected_assets": list(allocation.selected_assets),
            "reason": allocation.reason,
        }

    baseline = _metrics_from_equity(baseline_equity, float(initial_equity_usdt))
    weighted = _metrics_from_equity(weighted_equity, float(initial_equity_usdt))
    result_payload: dict[str, Any] = {
        "baseline": _metrics_payload(baseline),
        "confidence_weighted": _metrics_payload(weighted),
        "latest_cycle": market_cycle_payload(latest_state),
        "latest_allocation": latest_allocation,
    }
    # Only include funding audit fields when funding was actually applied,
    # preserving byte-identical output when funding_alignment is None.
    if funding_source_sha is not None:
        result_payload["funding_alignment_source_sha256"] = funding_source_sha
        result_payload["funding_alignment_applied_signal_count"] = funding_applied_count
    return MarketCycleComparison(
        baseline=baseline,
        confidence_weighted=weighted,
        latest_cycle=latest_state,
        latest_allocation=latest_allocation,
        artifact_sha256=_hash(result_payload),
        funding_alignment_source_sha256=funding_source_sha,
        funding_alignment_applied_signal_count=funding_applied_count
        if funding_source_sha is not None
        else None,
    )


def build_comparison_from_artifacts(
    artifacts_dir: Path,
    *,
    raw_root: Path,
    returns_path: Path | None = None,
    funding_alignment: tuple[FundingAlignmentRecord, ...] | None = None,
) -> MarketCycleComparison:
    """Build comparison from local artifacts.

    When no returns file is available, the comparison returns empty 100U metrics
    but still reports the latest market-cycle state from popular artifacts.
    """
    popular = load_popular_universe_records(artifacts_dir)
    returns = (
        _load_returns(returns_path)
        if returns_path is not None
        else _load_returns_from_raw_root(raw_root)
    )
    return run_market_cycle_comparison(returns, popular, funding_alignment=funding_alignment)


def comparison_payload(comparison: MarketCycleComparison) -> dict[str, object]:
    payload: dict[str, object] = {
        "baseline": _metrics_payload(comparison.baseline),
        "confidence_weighted": _metrics_payload(comparison.confidence_weighted),
        "latest_cycle": market_cycle_payload(comparison.latest_cycle),
        "latest_allocation": comparison.latest_allocation,
        "artifact_sha256": comparison.artifact_sha256,
    }
    # Only include funding audit fields when they were actually set,
    # preserving byte-identical output for the no-funding case.
    if comparison.funding_alignment_source_sha256 is not None:
        payload["funding_alignment_source_sha256"] = comparison.funding_alignment_source_sha256
        payload["funding_alignment_applied_signal_count"] = (
            comparison.funding_alignment_applied_signal_count
        )
    return payload


def write_comparison_artifact(comparison: MarketCycleComparison, path: Path) -> str:
    payload = comparison_payload(comparison)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return _hash(payload)


def _prepare_returns(returns: pd.DataFrame) -> pd.DataFrame:
    frame = returns.copy()
    if "date" in frame.columns:
        frame["date"] = pd.to_datetime(frame["date"], utc=True)
        frame = frame.set_index("date")
    frame = frame.sort_index()
    for asset in THREE_COIN_UNIVERSE:
        if asset not in frame:
            frame[asset] = 0.0
    return frame[list(THREE_COIN_UNIVERSE)].fillna(0.0)


def _records_through(records: pd.DataFrame, decision_time: datetime) -> pd.DataFrame:
    if records.empty:
        return records
    times = pd.to_datetime(records["selection_time"], utc=True)
    return records.loc[times <= pd.Timestamp(decision_time).tz_convert("UTC")].copy()


def _positive_weights(row: Mapping[str, float]) -> dict[str, float]:
    return {asset: max(0.0, float(row.get(asset, 0.0))) for asset in THREE_COIN_UNIVERSE}


def _normalize_weights(weights: Mapping[str, float], cap: float) -> dict[str, float]:
    total = sum(v for v in weights.values() if v > 0)
    if total <= 0:
        return {asset: 0.0 for asset in THREE_COIN_UNIVERSE}
    return {
        asset: cap * max(0.0, float(weights.get(asset, 0.0))) / total
        for asset in THREE_COIN_UNIVERSE
    }


def _portfolio_return(row: pd.Series, caps: Mapping[str, float], cap_base: float) -> float:
    if cap_base <= 0:
        return 0.0
    exposure_return = sum(
        float(caps.get(asset, 0.0)) * float(row[asset]) for asset in THREE_COIN_UNIVERSE
    )
    return exposure_return / cap_base


def _metrics_from_equity(equity: list[float], initial: float) -> BacktestMetrics:
    if not equity:
        return _empty_metrics(initial)
    series = pd.Series(equity, dtype=float)
    returns = series.pct_change().fillna(series.iloc[0] / initial - 1.0)
    total_return = series.iloc[-1] / initial - 1.0
    annualized_vol = float(returns.std(ddof=0) * (365**0.5))
    sharpe = 0.0 if annualized_vol == 0 else float((returns.mean() * 365) / annualized_vol)
    high_water = series.cummax()
    drawdown = (series / high_water - 1.0).min()
    trade_count = int((returns.abs() > 0).sum())
    return BacktestMetrics(
        final_equity=round(float(series.iloc[-1]), 6),
        total_return=round(float(total_return), 6),
        annualized_volatility=round(annualized_vol, 6),
        max_drawdown=round(float(drawdown), 6),
        sharpe_like=round(sharpe, 6),
        trade_count=trade_count,
    )


def _empty_metrics(initial: float) -> BacktestMetrics:
    return BacktestMetrics(
        final_equity=initial,
        total_return=0.0,
        annualized_volatility=0.0,
        max_drawdown=0.0,
        sharpe_like=0.0,
        trade_count=0,
    )


def _metrics_payload(metrics: BacktestMetrics) -> dict[str, object]:
    return {
        "final_equity": metrics.final_equity,
        "total_return": metrics.total_return,
        "annualized_volatility": metrics.annualized_volatility,
        "max_drawdown": metrics.max_drawdown,
        "sharpe_like": metrics.sharpe_like,
        "trade_count": metrics.trade_count,
    }


def _load_returns(path: Path | None) -> pd.DataFrame:
    if path is None or not path.is_file():
        return pd.DataFrame()
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path)
    return pd.read_json(path)


def _load_returns_from_raw_root(raw_root: Path) -> pd.DataFrame:
    base = raw_root / "ohlcv"
    rows: list[pd.DataFrame] = []
    for asset in THREE_COIN_UNIVERSE:
        asset_dir = base / asset / "1d"
        if not asset_dir.is_dir():
            continue
        for path in sorted(asset_dir.glob("*.zip")):
            try:
                frame = _read_daily_zip(path, asset)
            except Exception:
                continue
            if not frame.empty:
                rows.append(frame)
    if not rows:
        return pd.DataFrame()
    frame = pd.concat(rows, ignore_index=True)
    pivot = frame.pivot_table(index="date", columns="asset", values="daily_return", aggfunc="last")
    return pivot.reset_index()


def _read_daily_zip(path: Path, asset: str) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        member = next((name for name in zf.namelist() if name.lower().endswith(".csv")), None)
        if member is None:
            return pd.DataFrame()
        data = zf.read(member).decode("utf-8").splitlines()
    if not data:
        return pd.DataFrame()
    rows: list[dict[str, Any]] = []
    for line in data:
        parts = line.split(",")
        if len(parts) < 6:
            continue
        try:
            open_ts = pd.to_datetime(int(parts[0]), unit="ms", utc=True)
            open_price = float(parts[1])
            close_price = float(parts[4])
        except Exception:
            continue
        if open_price <= 0:
            continue
        rows.append(
            {
                "date": open_ts.normalize(),
                "asset": asset,
                "daily_return": close_price / open_price - 1.0,
            }
        )
    return pd.DataFrame(rows)


def _hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()
