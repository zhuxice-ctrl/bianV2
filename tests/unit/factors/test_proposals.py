from pydantic import ValidationError
import pytest

from bian_quant.factors.proposals import FactorProposal


def proposal_payload() -> dict[str, object]:
    return {
        "factor_id": "volume_surge_breakout",
        "factor_version": "1.0.0",
        "research_family": "volume_liquidity",
        "economic_hypothesis": "Abnormal volume confirms a price breakout and increases continuation probability.",
        "formula": "zscore(volume, 24)",
        "direction": "positive",
        "required_columns": ["open_time", "close", "volume", "available_time"],
        "signal_time": "close_time",
        "decision_time": "close_time",
        "entry_price": "next_continuous_bar_open",
        "holding_rule": "hold_for_4_bars",
        "exit_rule": "time_exit_or_invalid_execution_bar",
        "missing_policy": "preserve_missing_and_exclude",
        "parent_factors": [],
        "source_type": "registered_template",
        "proposal_status": "proposal_only",
    }


def test_valid_proposal_is_immutable() -> None:
    proposal = FactorProposal.model_validate(proposal_payload())
    assert proposal.proposal_status == "proposal_only"
    with pytest.raises(ValidationError):
        proposal.factor_id = "changed"  # type: ignore[misc]


def test_promotion_state_is_rejected() -> None:
    payload = proposal_payload()
    payload["proposal_status"] = "candidate"
    with pytest.raises(ValidationError):
        FactorProposal.model_validate(payload)


def test_missing_parent_factors_is_rejected() -> None:
    payload = proposal_payload()
    payload.pop("parent_factors")
    with pytest.raises(ValidationError):
        FactorProposal.model_validate(payload)


def test_missing_proposal_status_is_rejected() -> None:
    payload = proposal_payload()
    payload.pop("proposal_status")
    with pytest.raises(ValidationError):
        FactorProposal.model_validate(payload)


def test_required_columns_and_execution_fields_are_non_empty() -> None:
    payload = proposal_payload()
    payload["required_columns"] = []
    with pytest.raises(ValidationError):
        FactorProposal.model_validate(payload)


def test_canonical_identity_is_stable() -> None:
    first = FactorProposal.model_validate(proposal_payload())
    second = FactorProposal.model_validate(dict(reversed(list(proposal_payload().items()))))
    assert first.identity_sha256 == second.identity_sha256
