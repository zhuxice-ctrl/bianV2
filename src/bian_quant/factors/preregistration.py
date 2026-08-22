"""Immutable preregistration protocol for proposal-only factor research."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from bian_quant.factors.proposals import FactorProposal

_CLOSED_BAR_TIMES = {"close_time", "bar_close", "available_time", "decision_time"}
_ENTRY_PRICE = "next_continuous_bar_open"
_MISSING_POLICY = "preserve_missing_and_exclude"
_STATUS = "preregistration_only"
_RESEARCH_DECLARATION_FIELDS = (
    "cost_assumption",
    "development_sample_definition",
    "evaluation_horizon",
    "falsification_criteria",
)


class ProposalPreregistration(BaseModel):
    """Frozen preregistration contract copied from a proposal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_identity_sha256: str = Field(min_length=64, max_length=64)
    factor_id: str = Field(min_length=1, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    factor_version: str = Field(min_length=1, pattern=r"^\d+\.\d+\.\d+$")
    research_family: str = Field(min_length=1)
    economic_hypothesis: str = Field(min_length=1)
    formula: str = Field(min_length=1)
    direction: Literal["positive", "negative", "two_sided"]
    signal_time: str = Field(min_length=1)
    decision_time: str = Field(min_length=1)
    entry_price: Literal["next_continuous_bar_open"] = _ENTRY_PRICE
    holding_bars: int = Field(gt=0)
    missing_policy: Literal["preserve_missing_and_exclude"] = _MISSING_POLICY
    q_nominal: float = Field(gt=0.0, le=1.0)
    cost_assumption: str = Field(min_length=1)
    development_sample_definition: str = Field(min_length=1)
    evaluation_horizon: str = Field(min_length=1)
    falsification_criteria: str = Field(min_length=1)
    status: Literal["preregistration_only"] = _STATUS

    @classmethod
    def from_proposal(
        cls,
        proposal: FactorProposal | Mapping[str, Any],
        *,
        q_nominal: float = 0.2,
        holding_bars: int = 4,
        cost_assumption: str = "declare_before_development",
        development_sample_definition: str = "declare_before_development",
        evaluation_horizon: str = "4_bars",
        falsification_criteria: str = "declare_before_development",
    ) -> ProposalPreregistration:
        normalized = (
            proposal
            if isinstance(proposal, FactorProposal)
            else FactorProposal.model_validate(proposal)
        )
        return cls(
            proposal_identity_sha256=normalized.identity_sha256,
            factor_id=normalized.factor_id,
            factor_version=normalized.factor_version,
            research_family=normalized.research_family,
            economic_hypothesis=normalized.economic_hypothesis,
            formula=normalized.formula,
            direction=normalized.direction,
            signal_time=normalized.signal_time,
            decision_time=normalized.decision_time,
            entry_price=normalized.entry_price,
            holding_bars=holding_bars,
            missing_policy=normalized.missing_policy,
            q_nominal=q_nominal,
            cost_assumption=cost_assumption,
            development_sample_definition=development_sample_definition,
            evaluation_horizon=evaluation_horizon,
            falsification_criteria=falsification_criteria,
            status=_STATUS,
        )

    def validated(self) -> ProposalPreregistration:
        """Revalidate a copied instance after updates."""

        return type(self).model_validate(self.model_dump(mode="json"))

    @field_validator(
        "proposal_identity_sha256",
        "factor_id",
        "factor_version",
        "research_family",
        "economic_hypothesis",
        "formula",
        "signal_time",
        "decision_time",
        *_RESEARCH_DECLARATION_FIELDS,
    )
    @classmethod
    def _require_non_blank_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("preregistration text fields must be non-empty")
        return value

    @field_validator("proposal_identity_sha256")
    @classmethod
    def _require_hex_identity(cls, value: str) -> str:
        if len(value) != 64 or any(character not in "0123456789abcdef" for character in value):
            raise ValueError("proposal_identity_sha256 must be a lowercase SHA-256 digest")
        return value

    @field_validator("signal_time", "decision_time")
    @classmethod
    def _require_closed_bar_timing(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in _CLOSED_BAR_TIMES:
            raise ValueError("timing must be declared at a closed-bar boundary")
        return value


class _NoAliasSafeDumper(yaml.SafeDumper):
    def ignore_aliases(self, data: Any) -> bool:  # noqa: ANN401
        return True


def canonical_yaml_bytes(record: ProposalPreregistration) -> bytes:
    """Serialize a preregistration record as canonical UTF-8 YAML."""

    payload = record.model_dump(mode="json")
    rendered = yaml.dump(
        payload,
        Dumper=_NoAliasSafeDumper,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=True,
    )
    return rendered.encode("utf-8")
