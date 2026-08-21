from __future__ import annotations

from pathlib import Path

import pytest

from bian_quant.factors.proposal_audit import audit_proposal
from tests.unit.factors.test_proposals import proposal_payload

FORBIDDEN_FACTORS = (
    Path(__file__).resolve().parents[3] / "configs" / "factors" / "forbidden_factors.yaml"
)


def test_next_open_execution_passes_closed_bar_timing() -> None:
    result = audit_proposal(
        proposal_payload(),
        available_time_definition="close_time",
        forbidden_factors_path=FORBIDDEN_FACTORS,
    )
    assert result.verdict == "PASS"
    assert result.reason_codes == ()


def test_missing_auxiliary_delay_is_blocked() -> None:
    payload = proposal_payload()
    payload["required_columns"] = ["open_time", "funding_rate", "funding_time", "available_time"]
    result = audit_proposal(
        payload,
        available_time_definition=None,
        forbidden_factors_path=FORBIDDEN_FACTORS,
    )
    assert result.verdict == "BLOCKED"
    assert "MISSING_AVAILABLE_TIME_DEFINITION" in result.reason_codes


def test_missing_available_time_definition_blocks_without_auxiliary_delay() -> None:
    result = audit_proposal(
        proposal_payload(),
        available_time_definition=None,
        forbidden_factors_path=FORBIDDEN_FACTORS,
    )
    assert result.verdict == "BLOCKED"
    assert "MISSING_AVAILABLE_TIME_DEFINITION" in result.reason_codes
    assert "causal_timing:blocked" in result.checks


def test_missing_available_time_definition_remains_blocked_with_invalid_rule() -> None:
    payload = proposal_payload()
    payload["exit_rule"] = ""
    result = audit_proposal(
        payload,
        available_time_definition=None,
        forbidden_factors_path=FORBIDDEN_FACTORS,
    )
    assert result.verdict == "BLOCKED"
    assert {"MISSING_AVAILABLE_TIME_DEFINITION", "MISSING_EXIT_RULE"} <= set(result.reason_codes)


def test_missing_exit_rule_is_rejected() -> None:
    payload = proposal_payload()
    payload["exit_rule"] = ""
    result = audit_proposal(
        payload,
        available_time_definition="close_time",
        forbidden_factors_path=FORBIDDEN_FACTORS,
    )
    assert result.verdict == "REJECTED"
    assert "MISSING_EXIT_RULE" in result.reason_codes


def test_open_time_signal_is_rejected() -> None:
    payload = proposal_payload()
    payload["signal_time"] = "open_time"
    result = audit_proposal(
        payload,
        available_time_definition="close_time",
        forbidden_factors_path=FORBIDDEN_FACTORS,
    )
    assert result.verdict == "BLOCKED"
    assert "SIGNAL_NOT_CLOSED_BAR" in result.reason_codes


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    (
        ("economic_hypothesis", "The idea only matters if it lifts sharpe after costs."),
        ("formula", "rolling_sharpe(volume, 24)"),
    ),
)
def test_empirical_metrics_in_text_fields_are_rejected(
    field_name: str,
    field_value: str,
) -> None:
    payload = proposal_payload()
    payload[field_name] = field_value
    result = audit_proposal(
        payload,
        available_time_definition="close_time",
        forbidden_factors_path=FORBIDDEN_FACTORS,
    )
    assert result.verdict == "REJECTED"
    assert "EMPIRICAL_METRIC_PRESENT" in result.reason_codes


def test_forbidden_factor_overlap_is_deferred() -> None:
    payload = proposal_payload()
    payload["factor_id"] = "funding_zscore"
    payload["research_family"] = "funding_dynamics"
    payload["formula"] = "rolling_zscore(funding_rate, 24)"
    result = audit_proposal(
        payload,
        available_time_definition="funding_available_time",
        forbidden_factors_path=FORBIDDEN_FACTORS,
    )
    assert result.verdict == "DEFERRED"
    assert "FORBIDDEN_FACTOR_OVERLAP" in result.reason_codes


def test_wrapper_pattern_match_is_deferred_without_family_or_channel_match() -> None:
    payload = proposal_payload()
    payload["factor_id"] = "funding_pressure_overlay"
    payload["research_family"] = "volume_liquidity"
    payload["formula"] = "rank(close, 5)"
    result = audit_proposal(
        payload,
        available_time_definition="close_time",
        forbidden_factors_path=FORBIDDEN_FACTORS,
    )
    assert result.verdict == "DEFERRED"
    assert "FORBIDDEN_FACTOR_OVERLAP" in result.reason_codes
