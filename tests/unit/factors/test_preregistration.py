from __future__ import annotations

import hashlib

import pytest
import yaml
from pydantic import ValidationError

from bian_quant.factors.preregistration import (
    ProposalPreregistration,
    canonical_yaml_bytes,
)
from tests.unit.factors.test_proposals import proposal_payload


def valid_proposal() -> dict[str, object]:
    return proposal_payload()


def test_preregistration_has_fixed_research_defaults() -> None:
    record = ProposalPreregistration.from_proposal(valid_proposal())
    assert record.status == "preregistration_only"
    assert record.q_nominal == 0.2
    assert record.holding_bars == 4
    assert record.entry_price == "next_continuous_bar_open"
    assert record.missing_policy == "preserve_missing_and_exclude"


def test_blank_falsification_criterion_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProposalPreregistration.from_proposal(valid_proposal()).model_copy(
            update={"falsification_criteria": ""}
        ).validated()


def test_invalid_q_nominal_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProposalPreregistration.from_proposal(valid_proposal(), q_nominal=0.0)


def test_invalid_holding_bars_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProposalPreregistration.from_proposal(valid_proposal(), holding_bars=0)


def test_non_closed_bar_signal_time_is_rejected() -> None:
    payload = valid_proposal()
    payload["signal_time"] = "open_time"
    with pytest.raises(ValidationError):
        ProposalPreregistration.from_proposal(payload)


def test_invalid_entry_price_is_rejected() -> None:
    payload = valid_proposal()
    payload["entry_price"] = "close"
    with pytest.raises(ValidationError):
        ProposalPreregistration.from_proposal(payload)


def test_invalid_missing_policy_is_rejected() -> None:
    payload = valid_proposal()
    payload["missing_policy"] = "dropna"
    with pytest.raises(ValidationError):
        ProposalPreregistration.from_proposal(payload)


def test_canonical_yaml_is_sorted_utf8_and_alias_free() -> None:
    record = ProposalPreregistration.from_proposal(valid_proposal())
    payload = canonical_yaml_bytes(record)

    assert payload == canonical_yaml_bytes(record)
    assert payload.endswith(b"\n")
    text = payload.decode("utf-8")
    assert "&id" not in text
    assert "*" not in text

    loaded = yaml.safe_load(text)
    assert loaded["proposal_identity_sha256"] == record.proposal_identity_sha256
    assert list(loaded) == sorted(loaded)
    assert hashlib.sha256(payload).hexdigest()
