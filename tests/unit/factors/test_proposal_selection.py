from __future__ import annotations

from bian_quant.factors.proposal_audit import ProposalAuditResult
from bian_quant.factors.proposal_selection import mechanism_key, select_first_round
from bian_quant.factors.proposals import FactorProposal
from tests.unit.factors.test_proposals import proposal_payload


def valid_proposal(**overrides: object) -> FactorProposal:
    payload = proposal_payload()
    payload.update(overrides)
    return FactorProposal.model_validate(payload)


def volume_mean_proposals(
    *, window_values: tuple[int, int]
) -> tuple[FactorProposal, FactorProposal]:
    first_window, later_window = window_values
    base_payload = proposal_payload()
    first = FactorProposal.model_validate(
        {
            **base_payload,
            "factor_id": f"volume_mean_{first_window:02d}",
            "formula": f"rolling_mean(volume, {first_window})",
            "research_family": "volume_liquidity",
            "required_columns": ["open_time", "volume", "available_time"],
        }
    )
    later = FactorProposal.model_validate(
        {
            **base_payload,
            "factor_id": f"volume_mean_{later_window:02d}",
            "formula": f"rolling_mean(volume, {later_window})",
            "research_family": "volume_liquidity",
            "required_columns": ["open_time", "volume", "available_time"],
        }
    )
    return first, later


def test_repeated_window_variants_keep_only_first_mechanism() -> None:
    first, later = volume_mean_proposals(window_values=(6, 12))
    result = select_first_round(
        [
            (first, ProposalAuditResult(verdict="PASS")),
            (later, ProposalAuditResult(verdict="PASS")),
        ],
        max_per_family=4,
    )

    assert [item.proposal.factor_id for item in result.selected] == [first.factor_id]
    assert result.exclusions[later.identity_sha256] == "DIVERSITY_MECHANISM_DUPLICATE"


def test_non_pass_proposals_are_not_selected() -> None:
    proposal = valid_proposal()
    result = select_first_round(
        [(proposal, ProposalAuditResult(verdict="BLOCKED"))],
        max_per_family=4,
    )

    assert result.selected == ()
    assert result.exclusions[proposal.identity_sha256] == "AUDIT_NOT_PASS"


def test_family_cap_excludes_later_pass_proposals() -> None:
    first = valid_proposal(
        factor_id="alpha_volume",
        research_family="volume_liquidity",
        formula="rolling_mean(volume, 6)",
    )
    second = valid_proposal(
        factor_id="beta_volume",
        research_family="volume_liquidity",
        formula="rolling_std(volume, 6)",
    )
    other_family = valid_proposal(factor_id="gamma_price", research_family="price_dynamics")

    result = select_first_round(
        [
            (other_family, ProposalAuditResult(verdict="PASS")),
            (second, ProposalAuditResult(verdict="PASS")),
            (first, ProposalAuditResult(verdict="PASS")),
        ],
        max_per_family=1,
    )

    assert [item.proposal.factor_id for item in result.selected] == [
        "gamma_price",
        "alpha_volume",
    ]
    assert result.exclusions[second.identity_sha256] == "DIVERSITY_FAMILY_CAP"


def test_mechanism_key_ignores_open_and_available_columns() -> None:
    proposal = valid_proposal(
        formula="rolling_mean(volume, 12)",
        required_columns=["available_time", "open_time", "volume", "open"],
    )

    assert mechanism_key(proposal) == "rolling_mean:volume"
