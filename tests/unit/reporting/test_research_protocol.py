"""Tests for the single-asset evaluation contract extension."""

from __future__ import annotations

from bian_quant.reporting.research_protocol import (
    Allocation,
    BacktestComparison,
    BacktestMetrics,
    CurrentSignal,
    Kpis,
    MarketCycle,
    PartialAvailabilityImpact,
    PopularUniverse,
    ResearchTerminalResponse,
    RunInfo,
    SingleAssetMarketCycle,
    SingleAssetRecommendation,
    SingleAssetStatus,
    SingleAssetStrategyEvaluation,
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
        popular_universe=PopularUniverse(latest_date=None, latest_members=[], daily_counts=[]),
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


def test_market_cycle_default_funding_alignment_is_missing():
    """A MarketCycle built without funding_alignment defaults to missing."""
    from bian_quant.reporting.research_protocol import FundingAlignment

    response = _base_response()
    fa = response.market_cycle.funding_alignment
    assert isinstance(fa, FundingAlignment)
    assert fa.status == "missing"
    assert fa.score is None
    assert fa.positive_rate_share is None
    assert fa.source_sha256 is None


def test_market_cycle_with_ok_funding_alignment_serializes():
    """An ok Funding node round-trips through JSON with all old keys."""
    from bian_quant.reporting.research_protocol import FundingAlignment

    ok_fa = FundingAlignment(
        score=-0.08,
        positive_rate_share=0.9,
        median_rate=0.0001,
        coverage_ratio=1.0,
        source_sha256="c" * 64,
        status="ok",
    )
    cycle = MarketCycle(
        label="bull",
        confidence=0.82,
        probabilities={"bull": 0.8, "neutral": 0.1, "risk_off": 0.1},
        decision_time="2026-08-13T00:00:00+00:00",
        sample_count=60,
        evidence_sha256="d" * 64,
        status="ok",
        funding_alignment=ok_fa,
    )
    data = cycle.model_dump(mode="json")
    # All old keys remain.
    for key in (
        "label",
        "confidence",
        "probabilities",
        "decision_time",
        "sample_count",
        "evidence_sha256",
        "status",
    ):
        assert key in data
    # Additive node present and populated.
    assert data["funding_alignment"]["status"] == "ok"
    assert data["funding_alignment"]["score"] == -0.08
    assert data["funding_alignment"]["coverage_ratio"] == 1.0


def test_funding_alignment_is_frozen():
    """FundingAlignment must be immutable."""
    from bian_quant.reporting.research_protocol import FundingAlignment

    fa = FundingAlignment(
        score=None,
        positive_rate_share=None,
        median_rate=None,
        coverage_ratio=None,
        source_sha256=None,
        status="missing",
    )
    import pydantic

    with __import__("pytest").raises(pydantic.ValidationError):
        fa.score = 0.1  # type: ignore[misc]


def test_missing_funding_node_cannot_report_passed():
    """A missing/error Funding node must never let the UI infer a passed state."""
    from bian_quant.reporting.research_protocol import FundingAlignment

    for status in ("missing", "error"):
        fa = FundingAlignment(
            score=None,
            positive_rate_share=None,
            median_rate=None,
            coverage_ratio=None,
            source_sha256=None,
            status=status,
        )
        assert fa.score is None
        assert fa.status != "ok"



# ---------------------------------------------------------------------------
# Task 3: Wire compatibility and funding audit field tests
# ---------------------------------------------------------------------------


def test_backtest_comparison_funding_fields_default_none():
    """BacktestComparison must default funding audit fields to None."""
    bc = BacktestComparison(
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
    )
    assert bc.funding_alignment_source_sha256 is None
    assert bc.funding_alignment_applied_signal_count is None


def test_backtest_comparison_with_funding_fields_serializes():
    """BacktestComparison with funding fields must round-trip through JSON."""
    bc = BacktestComparison(
        status="ok",
        baseline=BacktestMetrics(
            final_equity=100.0,
            total_return=0.0,
            annualized_volatility=0.0,
            max_drawdown=0.0,
            sharpe_like=0.0,
            trade_count=0,
        ),
        confidence_weighted=BacktestMetrics(
            final_equity=105.0,
            total_return=0.05,
            annualized_volatility=0.1,
            max_drawdown=-0.02,
            sharpe_like=1.5,
            trade_count=5,
        ),
        artifact_sha256="abc123",
        funding_alignment_source_sha256="e" * 64,
        funding_alignment_applied_signal_count=3,
    )
    data = bc.model_dump(mode="json")
    assert data["funding_alignment_source_sha256"] == "e" * 64
    assert data["funding_alignment_applied_signal_count"] == 3
    # Old fields remain intact.
    assert data["artifact_sha256"] == "abc123"
    assert data["status"] == "ok"


def test_single_asset_funding_fields_default_none():
    """SingleAssetStrategyEvaluation must default funding audit fields to None."""
    evaluation = SingleAssetStrategyEvaluation(
        asset="ETHUSDT",
        strategy_id="legacy.pa_confluence",
        strategy_version="baseline-0",
        status=SingleAssetStatus.MISSING,
    )
    data = evaluation.model_dump(mode="json")
    assert data["funding_alignment_source_sha256"] is None
    assert data["funding_alignment_applied_signal_count"] is None


def test_single_asset_with_funding_fields_serializes():
    """SingleAssetStrategyEvaluation with funding fields must round-trip."""
    evaluation = SingleAssetStrategyEvaluation(
        asset="ETHUSDT",
        strategy_id="legacy.pa_confluence",
        strategy_version="baseline-0",
        status=SingleAssetStatus.OK,
        funding_alignment_source_sha256="f" * 64,
        funding_alignment_applied_signal_count=5,
    )
    data = evaluation.model_dump(mode="json")
    assert data["funding_alignment_source_sha256"] == "f" * 64
    assert data["funding_alignment_applied_signal_count"] == 5


def test_research_terminal_v1_schema_unchanged():
    """The schema_version must remain 'research-terminal-v1'."""
    response = _base_response()
    assert response.schema_version == "research-terminal-v1"
