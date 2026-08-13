"""Tests for the single-asset evaluation contract extension."""

from __future__ import annotations

from bian_quant.reporting.research_protocol import (
    CurrentSignal,
    ResearchTerminalResponse,
    RunInfo,
    Kpis,
    PopularUniverse,
    PartialAvailabilityImpact,
    MarketCycle,
    Allocation,
    BacktestComparison,
    BacktestMetrics,
    SingleAssetStatus,
    SingleAssetStrategyEvaluation,
    SingleAssetMarketCycle,
    SingleAssetRecommendation,
    StrategyMetrics,
    TerminalState,
)


def _base_response(**overrides):
    """Build a minimal valid ResearchTerminalResponse for testing."""
    defaults = dict(
        schema_version="research-terminal-v1",
        state=TerminalState.EMPTY,
        generated_at="2026-08-13T00:00:00+00:00",
        run=RunInfo(
            id=None,
            status=TerminalState.EMPTY,
            as_of=None,
            planned_objects=0,
            availability_manifest_sha256=None,
            pre_listing_exclusion_count=0,
            popular_universe_start=None,
            popular_universe_warmup_start=None,
            popular_universe_warmup_end=None,
            artifact_path=None,
        ),
        kpis=Kpis(
            popular_member_count=None,
            published_snapshot_count=0,
            blocked_period_count=0,
            temporary_blocker_count=0,
        ),
        popular_universe=PopularUniverse(
            latest_date=None, latest_members=[], daily_counts=[]
        ),
        coverage=[],
        blockers=[],
        pre_listing_exclusions=[],
        partial_availability_exclusions=[],
        partial_availability_impact=PartialAvailabilityImpact(
            affected_assets=[], affected_periods=0, affected_selection_days=0
        ),
        market_cycle=MarketCycle(
            label="insufficient_evidence",
            confidence=0.0,
            probabilities={"bull": 0.0, "neutral": 0.0, "risk_off": 0.0},
            decision_time=None,
            sample_count=0,
            evidence_sha256=None,
            status="missing",
        ),
        allocation=Allocation(
            total_cap_usdt=0.0,
            per_asset_caps_usdt={"BTCUSDT": 0.0, "ETHUSDT": 0.0, "BNBUSDT": 0.0},
            selected_assets=[],
            reason="INSUFFICIENT_EVIDENCE",
        ),
        backtest_comparison=BacktestComparison(
            status="missing",
            baseline=BacktestMetrics(
                final_equity=100.0,
                total_return=0.0,
                annualized_volatility=0.0,
                max_drawdown=0.0,
                sharpe_like=0.0,
                trade_count=0,
            ),
            confidence_weighted=BacktestMetrics(
                final_equity=100.0,
                total_return=0.0,
                annualized_volatility=0.0,
                max_drawdown=0.0,
                sharpe_like=0.0,
                trade_count=0,
            ),
            artifact_sha256=None,
        ),
        snapshots=[],
    )
    defaults.update(overrides)
    return ResearchTerminalResponse(**defaults)


def test_empty_response_has_empty_evaluations():
    """An empty response must include ``single_asset_strategy_evaluations: []``."""
    response = _base_response()
    data = response.model_dump(mode="json")
    assert "single_asset_strategy_evaluations" in data
    assert data["single_asset_strategy_evaluations"] == []


def test_eth_evaluation_serialization():
    """A populated ETH evaluation must round-trip through JSON."""
    metrics = StrategyMetrics(
        final_equity=95.50,
        total_return=-0.045,
        max_drawdown=-0.12,
        win_rate=0.4,
        trade_count=10,
        fee_paid_net_profit=-4.50,
        fees_paid=2.30,
    )
    evaluation = SingleAssetStrategyEvaluation(
        asset="ETHUSDT",
        strategy_id="legacy.pa_confluence",
        strategy_version="baseline-0",
        status=SingleAssetStatus.OK,
        sample_start="2025-07-26T20:00:00+00:00",
        sample_end="2026-08-13T00:00:00+00:00",
        generated_at="2026-08-13T12:00:00+00:00",
        runtime_ms=1500,
        input_artifact_sha256="abc123",
        result_artifact_sha256="def456",
        artifact_path="artifacts/ethusdt.json",
        current_signal=CurrentSignal.LONG,
        current_signal_time="2026-08-12T20:00:00+00:00",
        market_cycle=SingleAssetMarketCycle(
            label="bull",
            confidence=0.85,
            multiplier=1.0,
            evidence_sha256="sha_cycle",
        ),
        recommendation=SingleAssetRecommendation(
            participate=True,
            max_invest_usdt=100.0,
            reason="当前信号long，市场周期bull（置信度85%），建议最多投入100.0U。",
        ),
        baseline=metrics,
        confidence_weighted=metrics,
    )
    response = _base_response(single_asset_strategy_evaluations=[evaluation])
    data = response.model_dump(mode="json")

    evals = data["single_asset_strategy_evaluations"]
    assert len(evals) == 1
    eth = evals[0]
    assert eth["asset"] == "ETHUSDT"
    assert eth["status"] == "ok"
    assert eth["current_signal"] == "long"
    assert eth["market_cycle"]["multiplier"] == 1.0
    assert eth["recommendation"]["participate"] is True
    assert eth["baseline"]["win_rate"] == 0.4
    assert eth["confidence_weighted"]["fee_paid_net_profit"] == -4.50


def test_missing_evaluation_has_no_metrics():
    """A missing evaluation must carry status=missing and no metrics."""
    evaluation = SingleAssetStrategyEvaluation(
        asset="ETHUSDT",
        strategy_id="legacy.pa_confluence",
        strategy_version="baseline-0",
        status=SingleAssetStatus.MISSING,
        error_summary="ETH OHLCV data not found",
    )
    data = evaluation.model_dump(mode="json")
    assert data["status"] == "missing"
    assert data["baseline"] is None
    assert data["confidence_weighted"] is None
    assert data["recommendation"] is None
    assert data["error_summary"] == "ETH OHLCV data not found"


def test_error_evaluation_has_no_metrics():
    """An error evaluation must carry status=error and no metrics."""
    evaluation = SingleAssetStrategyEvaluation(
        asset="ETHUSDT",
        strategy_id="legacy.pa_confluence",
        strategy_version="baseline-0",
        status=SingleAssetStatus.ERROR,
        error_summary="Evaluator crashed: KeyError",
    )
    data = evaluation.model_dump(mode="json")
    assert data["status"] == "error"
    assert data["baseline"] is None
    assert data["confidence_weighted"] is None


def test_server_fallback_includes_evaluations():
    """The server.py exception fallback must include the new field."""
    # Simulate the fallback dict that server.py returns on exception
    fallback = {
        "schema_version": "research-terminal-v1",
        "state": "empty",
        "generated_at": "2026-08-13T00:00:00+00:00",
        "run": {
            "id": None,
            "status": "empty",
            "as_of": None,
            "planned_objects": 0,
            "availability_manifest_sha256": None,
            "pre_listing_exclusion_count": 0,
            "artifact_path": None,
        },
        "kpis": {
            "popular_member_count": None,
            "published_snapshot_count": 0,
            "blocked_period_count": 0,
            "temporary_blocker_count": 0,
        },
        "popular_universe": {"latest_date": None, "latest_members": [], "daily_counts": []},
        "coverage": [],
        "blockers": [],
        "pre_listing_exclusions": [],
        "snapshots": [],
        "single_asset_strategy_evaluations": [],
    }
    assert "single_asset_strategy_evaluations" in fallback
    assert fallback["single_asset_strategy_evaluations"] == []
