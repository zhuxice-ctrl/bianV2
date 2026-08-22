"""Deterministic first-round selection for proposal-only factor research."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from bian_quant.factors.proposal_audit import ProposalAuditResult
from bian_quant.factors.proposals import FactorProposal

SelectionExclusionReason = Literal[
    "AUDIT_NOT_PASS",
    "DIVERSITY_MECHANISM_DUPLICATE",
    "DIVERSITY_FAMILY_CAP",
]


class SelectionRecord(BaseModel):
    """A proposal retained in the first-round selection."""

    model_config = ConfigDict(frozen=True)

    proposal: FactorProposal
    audit: ProposalAuditResult | None = None


class DiversitySelection(BaseModel):
    """Outcome of deterministic first-round diversity selection."""

    model_config = ConfigDict(frozen=True)

    selected: tuple[SelectionRecord, ...] = ()
    exclusions: dict[str, SelectionExclusionReason] = Field(default_factory=dict)


def mechanism_key(proposal: FactorProposal) -> str:
    """Return the stable selection key for a proposal's research mechanism."""

    operator = proposal.formula.split("(", maxsplit=1)[0].strip().lower()
    channels = ",".join(
        sorted(
            column
            for column in proposal.required_columns
            if column not in {"open_time", "available_time", "open"}
        )
    )
    return f"{operator}:{channels}"


def select_first_round(
    records: Sequence[tuple[FactorProposal, ProposalAuditResult | None]],
    *,
    max_per_family: int,
) -> DiversitySelection:
    """Select a diverse first round without touching market or registry state."""

    if max_per_family <= 0:
        raise ValueError("max_per_family must be positive")

    ordered_records = sorted(
        records,
        key=lambda record: (
            record[0].research_family,
            record[0].factor_id,
            record[0].factor_version,
            record[0].identity_sha256,
        ),
    )

    selected: list[SelectionRecord] = []
    exclusions: dict[str, SelectionExclusionReason] = {}
    family_counts: dict[str, int] = {}
    seen_mechanisms: set[tuple[str, str]] = set()

    for proposal, audit in ordered_records:
        identity_sha256 = proposal.identity_sha256
        if audit is None or audit.verdict != "PASS":
            exclusions[identity_sha256] = "AUDIT_NOT_PASS"
            continue

        family = proposal.research_family
        key = (family, mechanism_key(proposal))
        if key in seen_mechanisms:
            exclusions[identity_sha256] = "DIVERSITY_MECHANISM_DUPLICATE"
            continue

        if family_counts.get(family, 0) >= max_per_family:
            exclusions[identity_sha256] = "DIVERSITY_FAMILY_CAP"
            continue

        seen_mechanisms.add(key)
        family_counts[family] = family_counts.get(family, 0) + 1
        selected.append(SelectionRecord(proposal=proposal, audit=audit))

    return DiversitySelection(selected=tuple(selected), exclusions=dict(exclusions))
