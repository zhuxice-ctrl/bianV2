from __future__ import annotations

from pathlib import Path

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
