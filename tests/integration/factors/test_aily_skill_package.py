from __future__ import annotations

from pathlib import Path

import yaml

from bian_quant.factors.proposals import FactorProposal

SKILL_ROOT = Path(__file__).resolve().parents[3] / "skills" / "quant-factor-research-factory"
SKILL_FILE = SKILL_ROOT / "SKILL.md"
SCHEMA_FILE = SKILL_ROOT / "schemas" / "factor_proposal.yaml"
PREREGISTRATION_SCHEMA = SKILL_ROOT / "schemas" / "preregistration.yaml"
AUDIT_RULES_FILE = SKILL_ROOT / "configs" / "audit_rules.yaml"
STOP_CONDITIONS_FILE = SKILL_ROOT / "configs" / "stop_conditions.yaml"


def _load_yaml(path: Path) -> dict[str, object]:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path} must contain a YAML mapping"
    return loaded


def _valid_worker_payload() -> dict[str, object]:
    return {
        "factor_id": "price_volume.confirmed_breakout",
        "factor_version": "1.0.0",
        "research_family": "price_volume",
        "economic_hypothesis": "Joint price and volume expansion may confirm continuation.",
        "formula": "multiply(percent_change(close, 24), zscore(volume, 24))",
        "direction": "positive",
        "required_columns": ["open_time", "close", "volume", "available_time", "open"],
        "signal_time": "close_time",
        "decision_time": "close_time",
        "entry_price": "next_continuous_bar_open",
        "holding_rule": "hold_for_4_bars",
        "exit_rule": "time_exit_or_invalid_execution_bar",
        "missing_policy": "preserve_missing_and_exclude",
        "parent_factors": ["price.momentum", "volume.trend"],
        "source_type": "registered_template",
        "proposal_status": "proposal_only",
    }


def test_aily_skill_package_fixture_is_consistent() -> None:
    schema = _load_yaml(SCHEMA_FILE)
    audit_rules = _load_yaml(AUDIT_RULES_FILE)
    stop_conditions = _load_yaml(STOP_CONDITIONS_FILE)

    prompt_refs = audit_rules["prompt_files"]
    assert isinstance(prompt_refs, dict)
    for relative_path in prompt_refs.values():
        assert isinstance(relative_path, str)
        assert (SKILL_ROOT / relative_path).is_file(), f"missing prompt file: {relative_path}"

    skill_text = SKILL_FILE.read_text(encoding="utf-8")
    for required_text in (
        "proposal_only",
        "Holdout",
        "Paper",
        "Live",
        "no external trading",
    ):
        assert required_text in skill_text

    expected_required_fields = {
        name for name, field_info in FactorProposal.model_fields.items() if field_info.is_required()
    }
    schema_required = schema["required"]
    assert isinstance(schema_required, list)
    assert set(schema_required) == expected_required_fields

    schema_properties = schema["properties"]
    assert isinstance(schema_properties, dict)
    assert expected_required_fields <= set(schema_properties)

    structured_output = audit_rules["structured_output"]
    assert isinstance(structured_output, dict)
    assert structured_output["schema"] == "schemas/factor_proposal.yaml"
    assert structured_output["proposal_status"] == "proposal_only"

    family_dispatch = audit_rules["family_dispatch"]
    assert isinstance(family_dispatch, dict)
    assert len(family_dispatch) == 5

    hard_caps = stop_conditions["hard_caps"]
    assert isinstance(hard_caps, dict)
    assert hard_caps["max_total_proposals"] == 20

    payload = _valid_worker_payload()
    proposal = FactorProposal.model_validate(payload)
    assert set(payload) == expected_required_fields
    assert proposal.proposal_status == "proposal_only"


def test_skill_package_includes_preregistration_contract() -> None:
    preregistration = yaml.safe_load(PREREGISTRATION_SCHEMA.read_text(encoding="utf-8"))
    assert preregistration["required"] == [
        "proposal_identity_sha256",
        "factor_id",
        "factor_version",
        "research_family",
        "economic_hypothesis",
        "formula",
        "direction",
        "signal_time",
        "decision_time",
        "entry_price",
        "q_nominal",
        "holding_bars",
        "missing_policy",
        "cost_assumption",
        "development_sample_definition",
        "evaluation_horizon",
        "falsification_criteria",
        "status",
    ]
    properties = preregistration["properties"]
    assert properties["entry_price"]["const"] == "next_continuous_bar_open"
    assert properties["holding_bars"]["const"] == 4
    assert properties["missing_policy"]["const"] == "preserve_missing_and_exclude"
    assert properties["q_nominal"]["const"] == 0.2
    assert properties["status"]["const"] == "preregistration_only"
    assert "preregistration_only" in SKILL_FILE.read_text(encoding="utf-8")
