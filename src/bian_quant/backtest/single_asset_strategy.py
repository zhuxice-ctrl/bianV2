"""Causal ETH single-asset strategy evaluator.

Runs two variants of the legacy PA confluence strategy on ETHUSDT 4H data:

* **baseline** — every signal requests a fixed 100 USDT notional.
* **confidence-weighted** — each signal's notional is scaled by a market-cycle
  risk multiplier computed from popular-universe records available *at or
  before* the signal's decision time.

Both variants share identical signal direction, entry, stop, target, fee and
slippage.  The only difference is the notional cap, ensuring any divergence in
equity or metrics is attributable to the cycle multiplier alone.

Causality guarantees
--------------------
1. The cycle multiplier for a signal at decision time *t* uses only
   popular-universe records with ``selection_time <= t``.
2. Signals are emitted by completed bars; the :class:`EventEngine` fills on
   the next bar's open.
3. Both variants consume the same bar/signal sequences — only notional differs.
4. Prefix causality: modifying records after *t* does not change any
   multiplier, trade or equity value at or before *t*.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd

from bian_quant.backtest.engine import BacktestResult, EventEngine
from bian_quant.backtest.events import Bar, BarConflictPolicy, SignalEvent
from bian_quant.regimes.market_cycle import (
    MarketCycleLabel,
    classify_market_cycle,
    load_popular_universe_records,
)
from bian_quant.signals.legacy_pa import adapt_confluence_signals

# --- Fixed cost parameters -------------------------------------------------

INITIAL_EQUITY = Decimal("100")
TAKER_FEE_BPS = Decimal("4")
SLIPPAGE_BPS = Decimal("10")
STOP_ATR_MULTIPLE = Decimal("1.5")
TARGET_RR_RATIO = Decimal("3.0")
HORIZON = "4h"
BAR_DURATION = pd.Timedelta(HORIZON)

# --- Cycle multiplier thresholds ------------------------------------------


def cycle_multiplier(label: str, confidence: float) -> float:
    """Map a market-cycle state to a position-size multiplier.

    Returns 0.0 for risk-off, low-confidence, or insufficient evidence.
    """
    if label == MarketCycleLabel.BULL.value and confidence >= 0.80:
        return 1.0
    if label == MarketCycleLabel.RISK_OFF.value:
        return 0.0
    if label == MarketCycleLabel.INSUFFICIENT_EVIDENCE.value:
        return 0.0
    # neutral or bull below 0.80
    if confidence >= 0.65:
        return 0.70
    if confidence >= 0.50:
        return 0.40
    return 0.0


# --- Result dataclasses ----------------------------------------------------


@dataclass(frozen=True)
class VariantMetrics:
    """Fee-after metrics for a single variant."""

    final_equity: float
    total_return: float
    max_drawdown: float
    win_rate: float | None
    trade_count: int
    fee_paid_net_profit: float
    fees_paid: float


@dataclass(frozen=True)
class EvaluationResult:
    """Full output of a single-asset evaluation run."""

    asset: str
    strategy_id: str
    strategy_version: str
    status: str  # "ok" | "missing" | "error"
    sample_start: str | None
    sample_end: str | None
    runtime_ms: int
    input_sha256: str | None
    result_sha256: str | None
    current_signal: str
    current_signal_time: str | None
    cycle_label: str | None
    cycle_confidence: float | None
    cycle_multiplier: float | None
    cycle_evidence_sha256: str | None
    recommendation_participate: bool
    recommendation_max_invest: float
    recommendation_reason: str
    baseline: VariantMetrics | None
    confidence_weighted: VariantMetrics | None
    error_summary: str | None = None
    raw_metrics: dict[str, Any] = field(default_factory=dict)


def _bars_from_frame(frame: pd.DataFrame) -> list[Bar]:
    """Convert an OHLCV DataFrame to a list of :class:`Bar` objects."""
    bars: list[Bar] = []
    for ts, row in frame.iterrows():
        bars.append(
            Bar(
                timestamp=pd.Timestamp(str(ts)).to_pydatetime(),
                open=Decimal(str(row["open"])),
                high=Decimal(str(row["high"])),
                low=Decimal(str(row["low"])),
                close=Decimal(str(row["close"])),
                volume=Decimal(str(row.get("volume", 0))),
            )
        )
    return bars


def _records_through(
    records: pd.DataFrame, decision_time: datetime
) -> pd.DataFrame:
    """Filter popular-universe records to those at or before *decision_time*."""
    if records.empty:
        return records
    times = pd.to_datetime(records["selection_time"], utc=True)
    dt = pd.Timestamp(decision_time)
    dt = dt.tz_localize("UTC") if dt.tzinfo is None else dt.tz_convert("UTC")
    return records.loc[times <= dt].copy()


def _compute_metrics(
    result: BacktestResult,
    *,
    initial_equity: float,
) -> VariantMetrics:
    """Compute fee-after metrics from an EventEngine BacktestResult."""
    trades = result.trades
    trade_count = len(trades)
    if not result.equity:
        return VariantMetrics(
            final_equity=initial_equity,
            total_return=0.0,
            max_drawdown=0.0,
            win_rate=None,
            trade_count=0,
            fee_paid_net_profit=0.0,
            fees_paid=0.0,
        )
    equity_series = [float(e) for e in result.equity]
    final_equity = equity_series[-1]
    total_return = final_equity / initial_equity - 1.0

    # Max drawdown
    peak = equity_series[0]
    max_dd = 0.0
    for eq in equity_series:
        if eq > peak:
            peak = eq
        dd = (eq - peak) / peak if peak > 0 else 0.0
        if dd < max_dd:
            max_dd = dd

    # Win rate
    if trade_count > 0:
        wins = sum(1 for t in trades if t.pnl > 0)
        win_rate = wins / trade_count
    else:
        win_rate = None

    # Fees and net profit
    fees_paid = sum(float(t.fee_paid) for t in trades)
    gross_pnl = sum(float(t.pnl) + float(t.fee_paid) for t in trades)
    fee_paid_net_profit = gross_pnl - fees_paid

    return VariantMetrics(
        final_equity=round(final_equity, 6),
        total_return=round(total_return, 6),
        max_drawdown=round(max_dd, 6),
        win_rate=round(win_rate, 6) if win_rate is not None else None,
        trade_count=trade_count,
        fee_paid_net_profit=round(fee_paid_net_profit, 6),
        fees_paid=round(fees_paid, 6),
    )


def _canonical_hash(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


def _load_eth_ohlcv(csv_path: Path) -> pd.DataFrame:
    """Load ETHUSDT 4H OHLCV CSV into a tz-aware DatetimeIndex DataFrame."""
    frame = pd.read_csv(csv_path)
    # Try common column name patterns
    time_col = None
    for col in frame.columns:
        if col.lower() in ("timestamp", "open_time", "datetime", "date", "time"):
            time_col = col
            break
    if time_col is None:
        time_col = frame.columns[0]
    # Convert timestamp — handle both ms epoch and ISO strings
    sample = str(frame[time_col].iloc[0])
    if sample.isdigit() and len(sample) >= 10:
        unit = "ms" if len(sample) >= 13 else "s"
        frame[time_col] = pd.to_datetime(  # type: ignore[call-overload]
            frame[time_col], unit=unit, utc=True
        )
    else:
        frame[time_col] = pd.to_datetime(frame[time_col], utc=True)
    frame = frame.set_index(time_col)
    frame.index.name = None
    # Normalize column names
    rename: dict[str, str] = {}
    for col in frame.columns:
        cl = col.lower().strip()
        if cl in ("open", "o", "open_price"):
            rename[col] = "open"
        elif cl in ("high", "h", "high_price"):
            rename[col] = "high"
        elif cl in ("low", "l", "low_price"):
            rename[col] = "low"
        elif cl in ("close", "c", "close_price"):
            rename[col] = "close"
        elif cl in ("volume", "vol", "v"):
            rename[col] = "volume"
    frame = frame.rename(columns=rename)
    # Ensure required columns
    for required in ("open", "high", "low", "close"):
        if required not in frame.columns:
            raise ValueError(f"ETH OHLCV CSV missing required column: {required}")
    if "volume" not in frame.columns:
        frame["volume"] = 0.0
    # Sort and deduplicate
    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="first")]
    # Ensure timezone-aware
    index = pd.DatetimeIndex(frame.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    frame.index = index
    return frame[["open", "high", "low", "close", "volume"]].astype(float)


def evaluate_eth_strategy(
    *,
    ohlcv_path: Path,
    popular_universe_dir: Path | None = None,
    popular_records: pd.DataFrame | None = None,
) -> EvaluationResult:
    """Run the ETH single-asset evaluation.

    Parameters
    ----------
    ohlcv_path:
        Path to ``data/ETHUSDT_4h.csv``.
    popular_universe_dir:
        Directory containing daily popular-universe JSON artifacts.  If
        ``popular_records`` is provided directly, this is ignored.
    popular_records:
        Pre-loaded popular-universe records DataFrame.  Takes precedence over
        ``popular_universe_dir``.

    Returns
    -------
    EvaluationResult
        With ``status`` = ``ok`` on success, ``missing`` when input data is
        absent or insufficient, or ``error`` on unexpected failure.
    """
    start_time = time.monotonic()

    # --- Load input data ------------------------------------------------
    if not ohlcv_path.is_file():
        return _missing_result(
            "ETHUSDT 4H OHLCV data file not found",
            runtime_ms=int((time.monotonic() - start_time) * 1000),
        )

    try:
        frame = _load_eth_ohlcv(ohlcv_path)
    except Exception as exc:
        return _error_result(
            f"Failed to load ETH OHLCV: {exc}",
            runtime_ms=int((time.monotonic() - start_time) * 1000),
        )

    if len(frame) < 200:  # EMA200 warmup
        return _missing_result(
            f"ETH OHLCV has only {len(frame)} bars; need >= 200 for EMA200 warmup",
            runtime_ms=int((time.monotonic() - start_time) * 1000),
        )

    # --- Load popular universe records ---------------------------------
    if popular_records is None and popular_universe_dir is not None:
        popular_records = load_popular_universe_records(popular_universe_dir)

    if popular_records is None:
        popular_records = pd.DataFrame()

    # --- Input hash ----------------------------------------------------
    input_payload = {
        "ohlcv_rows": len(frame),
        "ohlcv_start": str(frame.index[0]),
        "ohlcv_end": str(frame.index[-1]),
        "popular_records": len(popular_records) if not popular_records.empty else 0,
    }
    input_sha = _canonical_hash(input_payload)

    sample_start = str(frame.index[0])
    sample_end = str(frame.index[-1])

    # --- Generate signals ----------------------------------------------
    try:
        signals = adapt_confluence_signals(
            frame, asset="ETHUSDT", horizon=HORIZON
        )
    except Exception as exc:
        return _error_result(
            f"Signal generation failed: {exc}",
            runtime_ms=int((time.monotonic() - start_time) * 1000),
        )

    if not signals:
        return EvaluationResult(
            asset="ETHUSDT",
            strategy_id="legacy.pa_confluence",
            strategy_version="baseline-0",
            status="ok",
            sample_start=sample_start,
            sample_end=sample_end,
            runtime_ms=int((time.monotonic() - start_time) * 1000),
            input_sha256=input_sha,
            result_sha256=None,
            current_signal="flat",
            current_signal_time=None,
            cycle_label=None,
            cycle_confidence=None,
            cycle_multiplier=None,
            cycle_evidence_sha256=None,
            recommendation_participate=False,
            recommendation_max_invest=0.0,
            recommendation_reason="No signals generated in the sample period.",
            baseline=_compute_metrics_from_equity_only(float(INITIAL_EQUITY)),
            confidence_weighted=_compute_metrics_from_equity_only(float(INITIAL_EQUITY)),
        )

    # --- Build ATR lookup for signal stop/target distances -------------
    from strategies.indicators import atr as compute_atr

    atr_series = compute_atr(frame, 14)

    # --- Build bar list ------------------------------------------------
    bars = _bars_from_frame(frame)

    # --- Build signal events for baseline and weighted -----------------
    baseline_events: list[SignalEvent] = []
    weighted_events: list[SignalEvent] = []

    # Track multipliers for audit and current signal
    signal_multipliers: list[dict[str, Any]] = []

    for sig in signals:
        # Get ATR at the signal's decision time
        sig_ts = pd.Timestamp(sig.decision_time)
        sig_ts = sig_ts.tz_localize("UTC") if sig_ts.tzinfo is None else sig_ts.tz_convert("UTC")
        # Find the bar that generated this signal (the completed bar)
        # ATR is indexed by the bar timestamp
        if sig_ts in atr_series.index:
            atr_val = float(atr_series.loc[sig_ts])
        else:
            # Find nearest preceding bar
            preceding = atr_series[atr_series.index <= sig_ts]
            if preceding.empty:
                continue
            atr_val = float(preceding.iloc[-1])

        if atr_val <= 0 or pd.isna(atr_val):
            continue

        stop_dist = STOP_ATR_MULTIPLE * Decimal(str(atr_val))
        target_dist = stop_dist * TARGET_RR_RATIO

        # --- Baseline: fixed 100U ---
        baseline_events.append(
            SignalEvent(
                timestamp=sig.decision_time,
                direction=sig.direction,
                available_time=sig.available_time,
                notional=INITIAL_EQUITY,
                stop_distance=stop_dist,
                target_distance=target_dist,
                asset="ETHUSDT",
            )
        )

        # --- Weighted: 100U × cycle multiplier ---
        # Compute multiplier from records through decision_time
        records_through_t = _records_through(popular_records, sig.decision_time)
        if records_through_t.empty:
            mult = 0.0
            cycle_label = "insufficient_evidence"
            cycle_conf = 0.0
        else:
            try:
                state = classify_market_cycle(records_through_t)
                mult = cycle_multiplier(state.label.value, state.confidence)
                cycle_label = state.label.value
                cycle_conf = state.confidence
            except Exception:
                mult = 0.0
                cycle_label = "insufficient_evidence"
                cycle_conf = 0.0

        signal_multipliers.append(
            {
                "decision_time": sig.decision_time.isoformat(),
                "direction": sig.direction,
                "multiplier": mult,
                "cycle_label": cycle_label,
                "cycle_confidence": cycle_conf,
            }
        )

        weighted_notional = (INITIAL_EQUITY * Decimal(str(mult))).quantize(Decimal("0.01"))
        if weighted_notional > 0:
            weighted_events.append(
                SignalEvent(
                    timestamp=sig.decision_time,
                    direction=sig.direction,
                    available_time=sig.available_time,
                    notional=weighted_notional,
                    stop_distance=stop_dist,
                    target_distance=target_dist,
                    asset="ETHUSDT",
                )
            )

    # --- Run both variants through EventEngine -------------------------
    baseline_engine = EventEngine(
        taker_fee_bps=TAKER_FEE_BPS,
        slippage_bps=SLIPPAGE_BPS,
        initial_equity=INITIAL_EQUITY,
        gross_limit=Decimal("1.0"),
        close_at_end=True,
        bar_conflict_policy=BarConflictPolicy.STOP_FIRST,
    )
    weighted_engine = EventEngine(
        taker_fee_bps=TAKER_FEE_BPS,
        slippage_bps=SLIPPAGE_BPS,
        initial_equity=INITIAL_EQUITY,
        gross_limit=Decimal("1.0"),
        close_at_end=True,
        bar_conflict_policy=BarConflictPolicy.STOP_FIRST,
    )

    baseline_result = baseline_engine.run(bars=bars, signals=baseline_events)
    weighted_result = weighted_engine.run(bars=bars, signals=weighted_events)

    # --- Compute metrics ------------------------------------------------
    baseline_metrics = _compute_metrics(baseline_result, initial_equity=float(INITIAL_EQUITY))
    weighted_metrics = _compute_metrics(weighted_result, initial_equity=float(INITIAL_EQUITY))

    # --- Current signal & recommendation -------------------------------
    last_signal = signals[-1] if signals else None
    if last_signal is not None:
        if last_signal.direction > 0:
            current_signal = "long"
        elif last_signal.direction < 0:
            current_signal = "short"
        else:
            current_signal = "flat"
        current_signal_time = last_signal.decision_time.isoformat()
    else:
        current_signal = "flat"
        current_signal_time = None

    # Latest cycle state for recommendation
    if not popular_records.empty:
        try:
            latest_state = classify_market_cycle(popular_records)
            latest_mult = cycle_multiplier(latest_state.label.value, latest_state.confidence)
            latest_label = latest_state.label.value
            latest_conf = latest_state.confidence
            latest_sha = latest_state.evidence_sha256
        except Exception:
            latest_mult = 0.0
            latest_label = "insufficient_evidence"
            latest_conf = 0.0
            latest_sha = None
    else:
        latest_mult = 0.0
        latest_label = "insufficient_evidence"
        latest_conf = 0.0
        latest_sha = None

    participate = (
        current_signal in ("long", "short")
        and latest_mult > 0
        and latest_label != "insufficient_evidence"
    )
    max_invest = round(float(INITIAL_EQUITY) * latest_mult, 2) if participate else 0.0

    if participate:
        reason = (
            f"当前信号{current_signal}，市场周期{latest_label}"
            f"（置信度{latest_conf:.0%}），建议最多投入{max_invest}U。"
        )
    elif current_signal == "flat":
        reason = "当前无有效信号，不建议参与。"
    elif latest_mult == 0:
        reason = f"市场周期{latest_label}（置信度{latest_conf:.0%}），风险系数为零，不建议参与。"
    else:
        reason = "当前条件不满足参与标准。"

    # --- Result hash ----------------------------------------------------
    result_payload = {
        "baseline": {
            "final_equity": baseline_metrics.final_equity,
            "total_return": baseline_metrics.total_return,
            "max_drawdown": baseline_metrics.max_drawdown,
            "win_rate": baseline_metrics.win_rate,
            "trade_count": baseline_metrics.trade_count,
            "fee_paid_net_profit": baseline_metrics.fee_paid_net_profit,
            "fees_paid": baseline_metrics.fees_paid,
        },
        "confidence_weighted": {
            "final_equity": weighted_metrics.final_equity,
            "total_return": weighted_metrics.total_return,
            "max_drawdown": weighted_metrics.max_drawdown,
            "win_rate": weighted_metrics.win_rate,
            "trade_count": weighted_metrics.trade_count,
            "fee_paid_net_profit": weighted_metrics.fee_paid_net_profit,
            "fees_paid": weighted_metrics.fees_paid,
        },
        "signal_multipliers": signal_multipliers,
    }
    result_sha = _canonical_hash(result_payload)

    runtime_ms = int((time.monotonic() - start_time) * 1000)

    return EvaluationResult(
        asset="ETHUSDT",
        strategy_id="legacy.pa_confluence",
        strategy_version="baseline-0",
        status="ok",
        sample_start=sample_start,
        sample_end=sample_end,
        runtime_ms=runtime_ms,
        input_sha256=input_sha,
        result_sha256=result_sha,
        current_signal=current_signal,
        current_signal_time=current_signal_time,
        cycle_label=latest_label,
        cycle_confidence=latest_conf,
        cycle_multiplier=latest_mult,
        cycle_evidence_sha256=latest_sha,
        recommendation_participate=participate,
        recommendation_max_invest=max_invest,
        recommendation_reason=reason,
        baseline=baseline_metrics,
        confidence_weighted=weighted_metrics,
        raw_metrics=result_payload,
    )


def _compute_metrics_from_equity_only(initial_equity: float) -> VariantMetrics:
    """Return zero-trade metrics when no signals were generated."""
    return VariantMetrics(
        final_equity=initial_equity,
        total_return=0.0,
        max_drawdown=0.0,
        win_rate=None,
        trade_count=0,
        fee_paid_net_profit=0.0,
        fees_paid=0.0,
    )


def _missing_result(message: str, *, runtime_ms: int) -> EvaluationResult:
    return EvaluationResult(
        asset="ETHUSDT",
        strategy_id="legacy.pa_confluence",
        strategy_version="baseline-0",
        status="missing",
        sample_start=None,
        sample_end=None,
        runtime_ms=runtime_ms,
        input_sha256=None,
        result_sha256=None,
        current_signal="unavailable",
        current_signal_time=None,
        cycle_label=None,
        cycle_confidence=None,
        cycle_multiplier=None,
        cycle_evidence_sha256=None,
        recommendation_participate=False,
        recommendation_max_invest=0.0,
        recommendation_reason=message,
        baseline=None,
        confidence_weighted=None,
        error_summary=message,
    )


def _error_result(message: str, *, runtime_ms: int) -> EvaluationResult:
    return EvaluationResult(
        asset="ETHUSDT",
        strategy_id="legacy.pa_confluence",
        strategy_version="baseline-0",
        status="error",
        sample_start=None,
        sample_end=None,
        runtime_ms=runtime_ms,
        input_sha256=None,
        result_sha256=None,
        current_signal="unavailable",
        current_signal_time=None,
        cycle_label=None,
        cycle_confidence=None,
        cycle_multiplier=None,
        cycle_evidence_sha256=None,
        recommendation_participate=False,
        recommendation_max_invest=0.0,
        recommendation_reason=message,
        baseline=None,
        confidence_weighted=None,
        error_summary=message,
    )
