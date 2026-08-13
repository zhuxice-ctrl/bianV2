"""Auditable single-asset evaluation artifacts.

Provides canonical JSON serialization, SHA-256 hashing, atomic write/read, and
a high-level builder that integrates the ETH evaluator with the research
terminal aggregator.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from bian_quant.reporting.research_protocol import (
    CurrentSignal,
    SingleAssetMarketCycle,
    SingleAssetRecommendation,
    SingleAssetStatus,
    SingleAssetStrategyEvaluation,
    StrategyMetrics,
)


# --- Canonical JSON / hashing ----------------------------------------------


def canonical_json_bytes(payload: object) -> bytes:
    """Serialize *payload* to canonical JSON bytes (sorted keys, compact, UTF-8)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def canonical_sha256(payload: object) -> str:
    """Compute SHA-256 of the canonical JSON serialization of *payload*."""
    import hashlib

    return hashlib.sha256(canonical_json_bytes(payload)).hexdigest()


# --- Atomic write / read ---------------------------------------------------


def write_single_asset_artifact(payload: dict[str, Any], path: Path) -> str:
    """Atomically write *payload* as canonical JSON to *path*; return SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = canonical_json_bytes(payload)
    sha = _sha256_bytes(data)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return sha


def load_single_asset_artifact(path: Path) -> dict[str, Any]:
    """Load a single-asset artifact JSON file; raise on missing/corrupt."""
    if not path.is_file():
        raise FileNotFoundError(f"artifact not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"artifact is not a JSON object: {path}")
    return data


# --- High-level builder ----------------------------------------------------


_CONTRACT_VERSION = "single-asset-v1"


def build_eth_single_asset_evaluation(
    *,
    artifact_dir: Path | None = None,
    ohlcv_path: Path | None = None,
    popular_universe_dir: Path | None = None,
    popular_records: Any = None,
) -> SingleAssetStrategyEvaluation:
    """Build a :class:`SingleAssetStrategyEvaluation` for ETHUSDT.

    This is the entry point called by the research terminal aggregator.  It
    defensively handles missing data, corrupted artifacts, and evaluator
    exceptions — always returning a contract-conformant model.
    """
    # Lazy import to avoid circular dependency
    from bian_quant.backtest.single_asset_strategy import evaluate_eth_strategy

    # Resolve OHLCV path
    if ohlcv_path is None:
        # Try common locations relative to repo root
        candidates = [
            Path("data/ETHUSDT_4h.csv"),
            Path("../data/ETHUSDT_4h.csv"),
        ]
        for c in candidates:
            if c.is_file():
                ohlcv_path = c
                break
        else:
            ohlcv_path = Path("data/ETHUSDT_4h.csv")  # will trigger missing

    try:
        result = evaluate_eth_strategy(
            ohlcv_path=ohlcv_path,
            popular_universe_dir=popular_universe_dir,
            popular_records=popular_records,
        )
    except Exception as exc:
        return _error_evaluation(f"Evaluator raised: {exc}")

    # --- Build artifact and persist ------------------------------------
    artifact_path_str: str | None = None
    result_sha: str | None = result.result_sha256

    if artifact_dir is not None and result.status == "ok":
        artifact_payload = _build_artifact_payload(result)
        artifact_path = artifact_dir / "ethusdt-legacy-pa-confluence.json"
        try:
            result_sha = write_single_asset_artifact(artifact_payload, artifact_path)
            artifact_path_str = str(artifact_path)
        except Exception:
            # Persist failure doesn't change the evaluation status
            pass

    # --- Map to contract model -----------------------------------------
    if result.status == "missing":
        return SingleAssetStrategyEvaluation(
            asset=result.asset,
            strategy_id=result.strategy_id,
            strategy_version=result.strategy_version,
            status=SingleAssetStatus.MISSING,
            error_summary=result.error_summary,
        )

    if result.status == "error":
        return SingleAssetStrategyEvaluation(
            asset=result.asset,
            strategy_id=result.strategy_id,
            strategy_version=result.strategy_version,
            status=SingleAssetStatus.ERROR,
            error_summary=result.error_summary,
        )

    # status == "ok"
    baseline = _metrics_to_model(result.baseline) if result.baseline else None
    weighted = _metrics_to_model(result.confidence_weighted) if result.confidence_weighted else None

    market_cycle = None
    if result.cycle_label is not None:
        market_cycle = SingleAssetMarketCycle(
            label=result.cycle_label,
            confidence=result.cycle_confidence or 0.0,
            multiplier=result.cycle_multiplier or 0.0,
            evidence_sha256=result.cycle_evidence_sha256,
        )

    recommendation = SingleAssetRecommendation(
        participate=result.recommendation_participate,
        max_invest_usdt=result.recommendation_max_invest,
        reason=result.recommendation_reason,
    )

    try:
        current_signal = CurrentSignal(result.current_signal)
    except ValueError:
        current_signal = CurrentSignal.UNAVAILABLE

    return SingleAssetStrategyEvaluation(
        asset=result.asset,
        strategy_id=result.strategy_id,
        strategy_version=result.strategy_version,
        status=SingleAssetStatus.OK,
        sample_start=result.sample_start,
        sample_end=result.sample_end,
        generated_at=datetime.now(UTC).isoformat(),
        runtime_ms=result.runtime_ms,
        input_artifact_sha256=result.input_sha256,
        result_artifact_sha256=result_sha,
        artifact_path=artifact_path_str,
        current_signal=current_signal,
        current_signal_time=result.current_signal_time,
        market_cycle=market_cycle,
        recommendation=recommendation,
        baseline=baseline,
        confidence_weighted=weighted,
    )


# --- Helpers ---------------------------------------------------------------


def _sha256_bytes(data: bytes) -> str:
    import hashlib

    return hashlib.sha256(data).hexdigest()


def _metrics_to_model(metrics) -> StrategyMetrics:
    return StrategyMetrics(
        final_equity=metrics.final_equity,
        total_return=metrics.total_return,
        max_drawdown=metrics.max_drawdown,
        win_rate=metrics.win_rate,
        trade_count=metrics.trade_count,
        fee_paid_net_profit=metrics.fee_paid_net_profit,
        fees_paid=metrics.fees_paid,
    )


def _build_artifact_payload(result) -> dict[str, Any]:
    """Build the canonical artifact JSON payload from an EvaluationResult."""
    payload: dict[str, Any] = {
        "contract_version": _CONTRACT_VERSION,
        "asset": result.asset,
        "strategy_id": result.strategy_id,
        "strategy_version": result.strategy_version,
        "status": result.status,
        "sample_start": result.sample_start,
        "sample_end": result.sample_end,
        "generated_at": datetime.now(UTC).isoformat(),
        "runtime_ms": result.runtime_ms,
        "input_artifact_sha256": result.input_sha256,
        "current_signal": result.current_signal,
        "current_signal_time": result.current_signal_time,
        "market_cycle": {
            "label": result.cycle_label,
            "confidence": result.cycle_confidence,
            "multiplier": result.cycle_multiplier,
            "evidence_sha256": result.cycle_evidence_sha256,
        },
        "recommendation": {
            "participate": result.recommendation_participate,
            "max_invest_usdt": result.recommendation_max_invest,
            "reason": result.recommendation_reason,
        },
        "cost_parameters": {
            "initial_equity_usdt": "100.00",
            "taker_fee_bps": 4,
            "slippage_bps": 10,
            "stop_atr_multiple": "1.5",
            "target_rr_ratio": "3.0",
            "bar_conflict_policy": "STOP_FIRST",
            "close_at_end": True,
        },
    }
    if result.baseline is not None:
        payload["baseline"] = {
            "final_equity": result.baseline.final_equity,
            "total_return": result.baseline.total_return,
            "max_drawdown": result.baseline.max_drawdown,
            "win_rate": result.baseline.win_rate,
            "trade_count": result.baseline.trade_count,
            "fee_paid_net_profit": result.baseline.fee_paid_net_profit,
            "fees_paid": result.baseline.fees_paid,
        }
    if result.confidence_weighted is not None:
        payload["confidence_weighted"] = {
            "final_equity": result.confidence_weighted.final_equity,
            "total_return": result.confidence_weighted.total_return,
            "max_drawdown": result.confidence_weighted.max_drawdown,
            "win_rate": result.confidence_weighted.win_rate,
            "trade_count": result.confidence_weighted.trade_count,
            "fee_paid_net_profit": result.confidence_weighted.fee_paid_net_profit,
            "fees_paid": result.confidence_weighted.fees_paid,
        }
    if result.raw_metrics:
        payload["signal_multipliers"] = result.raw_metrics.get("signal_multipliers", [])
    return payload


def _error_evaluation(message: str) -> SingleAssetStrategyEvaluation:
    return SingleAssetStrategyEvaluation(
        asset="ETHUSDT",
        strategy_id="legacy.pa_confluence",
        strategy_version="baseline-0",
        status=SingleAssetStatus.ERROR,
        error_summary=message,
    )
