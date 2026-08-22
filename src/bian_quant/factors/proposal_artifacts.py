"""Deterministic, append-only proposal artifact writer."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from bian_quant.factors.preregistration import ProposalPreregistration, canonical_yaml_bytes
from bian_quant.factors.proposal_audit import ProposalAuditResult
from bian_quant.factors.proposal_selection import SelectionRecord, select_first_round
from bian_quant.factors.proposals import FactorProposal

_ARTIFACT_FILENAMES = (
    "candidate_registry.json",
    "candidate_summary.md",
    "audit_report.md",
    "deduplication_report.md",
    "decision_queue.md",
    "run_manifest.json",
)
_BOUNDARY_ASSERTIONS = {
    "data_read": False,
    "holdout_accessed": False,
    "live_trading": False,
    "network_access": False,
    "paper_trading": False,
}


@dataclass(frozen=True)
class ProposalRunArtifacts:
    """Written run artifacts and their stable identities."""

    run_directory: Path
    paths: dict[str, Path]
    artifact_sha256: dict[str, str]


@dataclass(frozen=True)
class _AuditedProposal:
    proposal: FactorProposal
    audit: ProposalAuditResult | None


@dataclass(frozen=True)
class _PreregistrationArtifact:
    proposal_identity_sha256: str
    preregistration_identity_sha256: str
    path: str
    payload: bytes


def write_proposal_run(
    root: Path | str,
    *,
    proposals: Sequence[FactorProposal | Mapping[str, Any]],
    run_id: str,
    code_sha: str,
    config_sha256: str = "",
    original_input_count: int | None = None,
    duplicate_identity_count: int | None = None,
    audits: Mapping[str, ProposalAuditResult | Mapping[str, Any]]
    | Sequence[ProposalAuditResult | Mapping[str, Any]]
    | None = None,
    max_review_queue: int | None = None,
    max_proposals_per_family: int | None = None,
    q_nominal: float = 0.2,
    holding_bars: int = 4,
    cost_assumption: str = "declare_before_development",
    development_sample_definition: str = "declare_before_development",
    evaluation_horizon: str = "4_bars",
    falsification_criteria: str = "declare_before_development",
) -> ProposalRunArtifacts:
    """Write one append-only proposal run without touching data or networks."""

    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    run_directory = root_path / run_id
    run_directory.mkdir(parents=False, exist_ok=False)

    normalized_proposals = tuple(_normalize_proposals(proposals))
    normalized_audits = _normalize_audits(normalized_proposals, audits)
    ordered_records = tuple(
        sorted(
            (
                _AuditedProposal(proposal=proposal, audit=audit)
                for proposal, audit in zip(normalized_proposals, normalized_audits, strict=True)
            ),
            key=lambda record: _proposal_sort_key(record.proposal),
        )
    )
    ordered_proposals = tuple(record.proposal for record in ordered_records)
    selection = select_first_round(
        [
            (
                record.proposal,
                record.audit if record.audit is not None else ProposalAuditResult(verdict="PASS"),
            )
            for record in ordered_records
        ],
        max_per_family=_resolved_max_proposals_per_family(
            max_proposals_per_family,
            proposal_count=len(ordered_records),
        ),
    )
    preregistration_artifacts = _build_preregistration_artifacts(
        selection.selected,
        q_nominal=q_nominal,
        holding_bars=holding_bars,
        cost_assumption=cost_assumption,
        development_sample_definition=development_sample_definition,
        evaluation_horizon=evaluation_horizon,
        falsification_criteria=falsification_criteria,
    )
    preregistration_paths_by_identity = {
        artifact.proposal_identity_sha256: artifact.path for artifact in preregistration_artifacts
    }
    selected_proposal_identities = {
        record.proposal.identity_sha256 for record in selection.selected
    }
    deduplicated_count = len(ordered_proposals)
    input_count = deduplicated_count if original_input_count is None else original_input_count
    duplicate_count = (
        max(0, input_count - deduplicated_count)
        if duplicate_identity_count is None
        else duplicate_identity_count
    )

    registry_payload = {
        "code_sha": code_sha,
        "config_sha256": config_sha256,
        "mode": "proposal_only",
        "proposal_count": deduplicated_count,
        "proposals": [
            {
                **record.proposal.model_dump(mode="json"),
                "audit_reason_codes": list(record.audit.reason_codes)
                if record.audit is not None
                else [],
                "audit_verdict": record.audit.verdict if record.audit is not None else "NOT_RUN",
                "identity_sha256": record.proposal.identity_sha256,
                "preregistration_path": preregistration_paths_by_identity.get(
                    record.proposal.identity_sha256
                ),
                "selection_reason": selection.exclusions.get(
                    record.proposal.identity_sha256,
                    "SELECTED"
                    if record.proposal.identity_sha256 in selected_proposal_identities
                    else None,
                ),
            }
            for record in ordered_records
        ],
        "run_id": run_id,
    }

    artifact_bytes: dict[str, bytes] = {
        "candidate_registry.json": _canonical_json_bytes(registry_payload),
        "candidate_summary.md": _render_candidate_summary(run_id, code_sha, ordered_proposals),
        "audit_report.md": _render_audit_report(ordered_records),
        "deduplication_report.md": _render_deduplication_report(
            ordered_proposals,
            input_count=input_count,
            duplicate_count=duplicate_count,
        ),
        "decision_queue.md": _render_decision_queue(
            selection.selected,
            preregistration_paths_by_identity=preregistration_paths_by_identity,
            max_queue_size=max_review_queue,
        ),
    }

    manifest_payload = {
        "artifacts": {
            name: {
                "bytes": len(payload),
                "sha256": _sha256_bytes(payload),
            }
            for name, payload in sorted(artifact_bytes.items())
        },
        "boundary_assertions": dict(_BOUNDARY_ASSERTIONS),
        "code_sha": code_sha,
        "config_sha256": config_sha256,
        "deduplication": {
            "deduplicated_count": deduplicated_count,
            "duplicate_identity_count": duplicate_count,
            "input_count": input_count,
        },
        "mode": "proposal_only",
        "proposal_count": deduplicated_count,
        "proposal_identities": [proposal.identity_sha256 for proposal in ordered_proposals],
        "preregistrations": {
            artifact.preregistration_identity_sha256: {
                "bytes": len(artifact.payload),
                "path": artifact.path,
                "sha256": _sha256_bytes(artifact.payload),
            }
            for artifact in preregistration_artifacts
        },
        "run_id": run_id,
        "selection": {
            "excluded_count": len(ordered_records) - len(selection.selected),
            "selected_count": len(selection.selected),
        },
    }
    artifact_bytes["run_manifest.json"] = _canonical_json_bytes(manifest_payload)

    artifact_paths: dict[str, Path] = {}
    artifact_sha256: dict[str, str] = {}
    preregistration_directory = run_directory / "preregistration"
    if preregistration_artifacts:
        preregistration_directory.mkdir(parents=False, exist_ok=False)
        for artifact in preregistration_artifacts:
            _atomic_write(run_directory / artifact.path, artifact.payload)
    for artifact_name in _ARTIFACT_FILENAMES:
        target = run_directory / artifact_name
        payload = artifact_bytes[artifact_name]
        _atomic_write(target, payload)
        artifact_paths[artifact_name] = target
        artifact_sha256[artifact_name] = _sha256_bytes(payload)

    return ProposalRunArtifacts(
        run_directory=run_directory,
        paths=artifact_paths,
        artifact_sha256=artifact_sha256,
    )


def _normalize_proposals(
    proposals: Sequence[FactorProposal | Mapping[str, Any]],
) -> list[FactorProposal]:
    return [
        proposal
        if isinstance(proposal, FactorProposal)
        else FactorProposal.model_validate(dict(proposal))
        for proposal in proposals
    ]


def _normalize_audits(
    proposals: Sequence[FactorProposal],
    audits: Mapping[str, ProposalAuditResult | Mapping[str, Any]]
    | Sequence[ProposalAuditResult | Mapping[str, Any]]
    | None,
) -> tuple[ProposalAuditResult | None, ...]:
    if audits is None:
        return tuple(None for _ in proposals)
    if isinstance(audits, Mapping):
        normalized_by_identity = {
            str(identity_sha256): _coerce_audit_result(audit_result)
            for identity_sha256, audit_result in audits.items()
        }
        return tuple(normalized_by_identity.get(proposal.identity_sha256) for proposal in proposals)
    normalized_audits = list(audits)
    if len(normalized_audits) != len(proposals):
        raise ValueError("audit sequence must align with proposal sequence")
    return tuple(_coerce_audit_result(audit_result) for audit_result in normalized_audits)


def _coerce_audit_result(
    audit_result: ProposalAuditResult | Mapping[str, Any],
) -> ProposalAuditResult:
    if isinstance(audit_result, ProposalAuditResult):
        return audit_result
    if isinstance(audit_result, BaseModel):
        return ProposalAuditResult.model_validate(audit_result.model_dump(mode="json"))
    return ProposalAuditResult.model_validate(dict(audit_result))


def _proposal_sort_key(proposal: FactorProposal) -> tuple[str, str, str, str]:
    return (
        proposal.research_family,
        proposal.factor_id,
        proposal.factor_version,
        proposal.identity_sha256,
    )


def _render_candidate_summary(
    run_id: str,
    code_sha: str,
    proposals: Sequence[FactorProposal],
) -> bytes:
    lines = [
        "# Candidate Summary",
        "",
        f"- run_id: `{run_id}`",
        f"- code_sha: `{code_sha}`",
        "- mode: `proposal_only`",
        f"- proposal_count: `{len(proposals)}`",
        "",
        "| Rank | Research Family | Factor | Version | Direction |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {rank} | {proposal.research_family} | {proposal.factor_id} | "
        f"{proposal.factor_version} | {proposal.direction} |"
        for rank, proposal in enumerate(proposals, start=1)
    )
    return _markdown_bytes(lines)


def _render_audit_report(
    records: Sequence[_AuditedProposal],
) -> bytes:
    verdicts = [record.audit.verdict for record in records if record.audit is not None]
    verdict_counts = Counter(verdicts)
    lines = [
        "# Audit Report",
        "",
        f"- audited_proposals: `{len(verdicts)}`",
        f"- pass_count: `{verdict_counts.get('PASS', 0)}`",
        f"- blocked_count: `{verdict_counts.get('BLOCKED', 0)}`",
        f"- deferred_count: `{verdict_counts.get('DEFERRED', 0)}`",
        f"- rejected_count: `{verdict_counts.get('REJECTED', 0)}`",
        "",
        "| Factor | Verdict | Reason Codes |",
        "| --- | --- | --- |",
    ]
    for record in records:
        verdict = record.audit.verdict if record.audit is not None else "NOT_RUN"
        reason_codes = ", ".join(record.audit.reason_codes) if record.audit else "none"
        lines.append(f"| {record.proposal.factor_id} | {verdict} | {reason_codes} |")
    return _markdown_bytes(lines)


def _render_deduplication_report(
    proposals: Sequence[FactorProposal],
    *,
    input_count: int | None = None,
    duplicate_count: int | None = None,
) -> bytes:
    identity_counts = Counter(proposal.identity_sha256 for proposal in proposals)
    duplicate_identities = tuple(
        identity_sha256 for identity_sha256, count in sorted(identity_counts.items()) if count > 1
    )
    deduplicated_count = len(identity_counts)
    resolved_input_count = deduplicated_count if input_count is None else input_count
    resolved_duplicate_count = (
        max(0, resolved_input_count - deduplicated_count)
        if duplicate_count is None
        else duplicate_count
    )
    lines = [
        "# Deduplication Report",
        "",
        f"- input_count: `{resolved_input_count}`",
        f"- deduplicated_count: `{deduplicated_count}`",
        f"- unique_identity_count: `{deduplicated_count}`",
        f"- duplicate_identity_count: `{resolved_duplicate_count}`",
    ]
    if duplicate_identities:
        lines.extend(["", "| Identity SHA-256 | Count |", "| --- | --- |"])
        lines.extend(
            f"| {identity_sha256} | {identity_counts[identity_sha256]} |"
            for identity_sha256 in duplicate_identities
        )
    else:
        lines.extend(["", "No duplicate proposal identities were supplied in this run."])
    return _markdown_bytes(lines)


def _render_decision_queue(
    records: Sequence[Any],
    *,
    preregistration_paths_by_identity: Mapping[str, str],
    max_queue_size: int | None = None,
) -> bytes:
    lines = [
        "# Decision Queue",
        "",
        (
            "| Queue Rank | Research Family | Factor | Verdict | Selection | "
            "Identity SHA-256 | Preregistration |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    queue_records = list(records[:max_queue_size] if max_queue_size is not None else records)
    for rank, record in enumerate(queue_records, start=1):
        verdict = record.audit.verdict if record.audit is not None else "PASS"
        lines.append(
            f"| {rank} | {record.proposal.research_family} | {record.proposal.factor_id} | "
            f"{verdict} | SELECTED | {record.proposal.identity_sha256} | "
            f"{preregistration_paths_by_identity[record.proposal.identity_sha256]} |"
        )
    return _markdown_bytes(lines)


def _resolved_max_proposals_per_family(
    max_proposals_per_family: int | None, *, proposal_count: int
) -> int:
    if max_proposals_per_family is not None:
        return max_proposals_per_family
    return max(1, proposal_count)


def _build_preregistration_artifacts(
    selected_records: Sequence[SelectionRecord],
    *,
    q_nominal: float,
    holding_bars: int,
    cost_assumption: str,
    development_sample_definition: str,
    evaluation_horizon: str,
    falsification_criteria: str,
) -> tuple[_PreregistrationArtifact, ...]:
    artifacts: list[_PreregistrationArtifact] = []
    for record in selected_records:
        preregistration = ProposalPreregistration.from_proposal(
            record.proposal,
            q_nominal=q_nominal,
            holding_bars=holding_bars,
            cost_assumption=cost_assumption,
            development_sample_definition=development_sample_definition,
            evaluation_horizon=evaluation_horizon,
            falsification_criteria=falsification_criteria,
        )
        relative_path = (
            Path("preregistration") / f"{preregistration.proposal_identity_sha256}.yaml"
        ).as_posix()
        artifacts.append(
            _PreregistrationArtifact(
                proposal_identity_sha256=record.proposal.identity_sha256,
                preregistration_identity_sha256=preregistration.proposal_identity_sha256,
                path=relative_path,
                payload=canonical_yaml_bytes(preregistration),
            )
        )
    return tuple(artifacts)


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _markdown_bytes(lines: Sequence[str]) -> bytes:
    return ("\n".join(lines) + "\n").encode("utf-8")


def _atomic_write(target: Path, payload: bytes) -> None:
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
