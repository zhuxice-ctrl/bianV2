"""Static proposal audits for causal timing and forbidden overlap."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from bian_quant.factors.proposals import FactorProposal

AuditVerdict = Literal["PASS", "BLOCKED", "DEFERRED", "REJECTED"]

DEFAULT_FORBIDDEN_FACTORS_PATH = (
    Path(__file__).resolve().parents[3] / "configs" / "factors" / "forbidden_factors.yaml"
)

_EXECUTION_FIELD_REASONS = {
    "required_columns": "MISSING_REQUIRED_COLUMNS",
    "signal_time": "MISSING_SIGNAL_TIME",
    "decision_time": "MISSING_DECISION_TIME",
    "entry_price": "MISSING_ENTRY_PRICE_RULE",
    "holding_rule": "MISSING_HOLDING_RULE",
    "exit_rule": "MISSING_EXIT_RULE",
    "missing_policy": "MISSING_MISSING_POLICY",
}
_KNOWN_TIME_ORDER = {
    "event_time": 0,
    "open_time": 10,
    "bar_open": 10,
    "funding_time": 20,
    "oi_time": 20,
    "close_time": 30,
    "bar_close": 30,
    "available_time": 30,
    "funding_available_time": 30,
    "oi_available_time": 30,
    "decision_time": 30,
    "next_continuous_bar_open": 40,
}
_AUXILIARY_DELAY_COLUMNS = {
    "funding_rate",
    "funding_time",
    "funding_available_time",
    "funding_interval_hours",
    "open_interest",
    "sum_open_interest",
    "sum_open_interest_value",
    "oi_available_time",
    "quote_volume",
    "taker_buy_base",
    "taker_buy_quote",
}
_EMPIRICAL_METRIC_TOKENS = (
    "alpha",
    "auc",
    "drawdown",
    "hit_rate",
    "ic",
    "pnl",
    "precision",
    "recall",
    "return",
    "returns",
    "sharpe",
    "win_rate",
)


class ProposalAuditResult(BaseModel):
    """Immutable static audit result for a factor proposal."""

    model_config = ConfigDict(frozen=True)

    verdict: AuditVerdict
    reason_codes: tuple[str, ...] = ()
    checks: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


class ForbiddenFactorEntry(BaseModel):
    """One archived factor that future proposals may not wrap or rename around."""

    model_config = ConfigDict(frozen=True)

    factor_id: str
    factor_version: str
    research_family: str
    formula_summary: str
    required_input_channels: tuple[str, ...]
    prohibited_wrapper_patterns: tuple[str, ...]


class ForbiddenFactorArchive(BaseModel):
    """Validated static archive of forbidden factor overlaps."""

    model_config = ConfigDict(frozen=True)

    factors: tuple[ForbiddenFactorEntry, ...]


def audit_proposal(
    proposal: FactorProposal | Mapping[str, Any],
    *,
    available_time_definition: str | None,
    forbidden_factors_path: Path | str = DEFAULT_FORBIDDEN_FACTORS_PATH,
) -> ProposalAuditResult:
    """Audit a proposal without touching datasets, registries, or networks."""

    payload = _raw_payload(proposal)
    required_columns = _required_columns(payload)
    reason_codes: list[str] = []
    warnings: list[str] = []
    checks = [
        "required_execution_fields:pass",
        "causal_timing:pass",
        "entry_execution_wording:pass",
        "auxiliary_delay_declarations:pass",
        "forbidden_factor_overlap:clear",
        "empirical_metrics:clear",
    ]

    execution_reasons = _missing_execution_field_reasons(payload)
    if execution_reasons:
        reason_codes.extend(execution_reasons)
        checks[0] = "required_execution_fields:fail"

    if "available_time" not in required_columns:
        reason_codes.append("MISSING_AVAILABLE_TIME_COLUMN")
        checks[0] = "required_execution_fields:fail"

    normalized_available_time_definition = str(available_time_definition or "").strip()
    if normalized_available_time_definition:
        timing_reason = _timing_reason(
            normalized_available_time_definition,
            str(payload.get("decision_time", "")),
        )
        if timing_reason is not None:
            reason_codes.append(timing_reason)
            checks[1] = "causal_timing:fail"
    else:
        reason_codes.append("MISSING_AVAILABLE_TIME_DEFINITION")
        checks[1] = "causal_timing:blocked"
        if _requires_auxiliary_delay_definition(required_columns):
            checks[3] = "auxiliary_delay_declarations:blocked"

    if str(payload.get("entry_price", "")).strip() != "next_continuous_bar_open":
        reason_codes.append("INVALID_NEXT_CONTINUOUS_BAR_OPEN")
        checks[2] = "entry_execution_wording:fail"

    empirical_reason = _empirical_metric_reason(payload)
    if empirical_reason is not None:
        reason_codes.append(empirical_reason)
        checks[5] = "empirical_metrics:fail"

    protocol_reasons = _protocol_validation_reasons(payload)
    if protocol_reasons:
        reason_codes.extend(protocol_reasons)
        checks[0] = "required_execution_fields:fail"

    archive = _load_forbidden_factors(forbidden_factors_path)
    if _has_forbidden_overlap(payload, archive):
        reason_codes.append("FORBIDDEN_FACTOR_OVERLAP")
        warnings.append("Document an independent mechanism before resubmitting this proposal.")
        checks[4] = "forbidden_factor_overlap:deferred"

    deduped_reason_codes = tuple(dict.fromkeys(reason_codes))
    verdict = _verdict_for_reasons(deduped_reason_codes)
    return ProposalAuditResult(
        verdict=verdict,
        reason_codes=deduped_reason_codes,
        checks=tuple(checks),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _raw_payload(proposal: FactorProposal | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(proposal, FactorProposal):
        return proposal.model_dump(mode="json")
    return dict(proposal)


def _required_columns(payload: Mapping[str, Any]) -> tuple[str, ...]:
    columns = payload.get("required_columns", ())
    if isinstance(columns, (list, tuple)):
        return tuple(str(item).strip() for item in columns if str(item).strip())
    return ()


def _missing_execution_field_reasons(payload: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field_name, reason_code in _EXECUTION_FIELD_REASONS.items():
        value = payload.get(field_name)
        if field_name == "required_columns":
            if not _required_columns(payload):
                reasons.append(reason_code)
            continue
        if not isinstance(value, str) or not value.strip():
            reasons.append(reason_code)
    return reasons


def _timing_reason(available_time_definition: str, decision_time: str) -> str | None:
    available_key = available_time_definition.strip().lower()
    decision_key = decision_time.strip().lower()
    if not available_key or not decision_key:
        return "UNKNOWN_AVAILABLE_TIME_ORDER"
    if available_key == decision_key:
        return None
    available_rank = _KNOWN_TIME_ORDER.get(available_key)
    decision_rank = _KNOWN_TIME_ORDER.get(decision_key)
    if available_rank is None or decision_rank is None:
        return "UNKNOWN_AVAILABLE_TIME_ORDER"
    if available_rank > decision_rank:
        return "AVAILABLE_TIME_AFTER_DECISION_TIME"
    return None


def _requires_auxiliary_delay_definition(required_columns: tuple[str, ...]) -> bool:
    return any(column_name in _AUXILIARY_DELAY_COLUMNS for column_name in required_columns)


def _empirical_metric_reason(payload: Mapping[str, Any]) -> str | None:
    known_protocol_fields = {field_name.lower() for field_name in FactorProposal.model_fields}
    for key, value in payload.items():
        normalized_key = str(key).strip().lower()
        if normalized_key not in known_protocol_fields and _contains_empirical_metric(str(key)):
            return "EMPIRICAL_METRIC_PRESENT"
        if _payload_contains_empirical_metric(value):
            return "EMPIRICAL_METRIC_PRESENT"
    return None


def _protocol_validation_reasons(payload: Mapping[str, Any]) -> list[str]:
    try:
        FactorProposal.model_validate(dict(payload))
    except ValidationError as error:
        reasons: list[str] = []
        for issue in error.errors():
            loc = str(issue["loc"][0]) if issue.get("loc") else ""
            if loc in _EXECUTION_FIELD_REASONS:
                reasons.append(_EXECUTION_FIELD_REASONS[loc])
            elif loc == "parent_factors":
                reasons.append("MISSING_PARENT_FACTORS")
            elif loc == "proposal_status":
                reasons.append("INVALID_PROPOSAL_STATUS")
            elif loc == "direction":
                reasons.append("INVALID_DIRECTION")
            else:
                reasons.append("INVALID_PROPOSAL_PROTOCOL")
        return list(dict.fromkeys(reasons))
    return []


def _load_forbidden_factors(path: Path | str) -> ForbiddenFactorArchive:
    payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError("forbidden factors archive must be a YAML mapping")
    return ForbiddenFactorArchive.model_validate(payload)


def _has_forbidden_overlap(
    payload: Mapping[str, Any],
    archive: ForbiddenFactorArchive,
) -> bool:
    formula = _normalize_text(str(payload.get("formula", "")))
    factor_id = _normalize_text(str(payload.get("factor_id", "")))
    family = _normalize_text(str(payload.get("research_family", "")))
    required_columns = {_normalize_text(item) for item in _required_columns(payload)}

    for entry in archive.factors:
        family_match = family == _normalize_text(entry.research_family)
        direct_name_match = factor_id == _normalize_text(entry.factor_id)
        channel_match = any(
            _normalize_text(channel) in formula or _normalize_text(channel) in required_columns
            for channel in entry.required_input_channels
        )
        wrapper_match = any(
            _normalize_text(pattern) in formula or _normalize_text(pattern) in factor_id
            for pattern in entry.prohibited_wrapper_patterns
        )
        if direct_name_match or wrapper_match or (channel_match and family_match):
            return True
    return False


def _normalize_text(value: str) -> str:
    return "".join(value.lower().split())


def _contains_empirical_metric(value: str) -> bool:
    lowered_value = value.lower()
    for token in _EMPIRICAL_METRIC_TOKENS:
        pattern = (
            r"(?<![a-z0-9])"
            + r"[\s_]*".join(re.escape(part) for part in token.split("_"))
            + r"(?![a-z0-9])"
        )
        if re.search(pattern, lowered_value):
            return True
    return False


def _payload_contains_empirical_metric(value: Any) -> bool:
    if isinstance(value, str):
        return _contains_empirical_metric(value)
    if isinstance(value, Mapping):
        return any(_payload_contains_empirical_metric(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_payload_contains_empirical_metric(item) for item in value)
    return False


def _verdict_for_reasons(reason_codes: tuple[str, ...]) -> AuditVerdict:
    if not reason_codes:
        return "PASS"
    blocked_reasons = {
        "AVAILABLE_TIME_AFTER_DECISION_TIME",
        "MISSING_AVAILABLE_TIME_DEFINITION",
        "UNKNOWN_AVAILABLE_TIME_ORDER",
    }
    rejected_reasons = set(_EXECUTION_FIELD_REASONS.values()) | {
        "EMPIRICAL_METRIC_PRESENT",
        "INVALID_DIRECTION",
        "INVALID_PROPOSAL_PROTOCOL",
        "INVALID_PROPOSAL_STATUS",
        "MISSING_AVAILABLE_TIME_COLUMN",
        "MISSING_PARENT_FACTORS",
    }
    if any(code in blocked_reasons for code in reason_codes):
        return "BLOCKED"
    if any(code in rejected_reasons for code in reason_codes):
        return "REJECTED"
    if "FORBIDDEN_FACTOR_OVERLAP" in reason_codes:
        return "DEFERRED"
    return "REJECTED"
