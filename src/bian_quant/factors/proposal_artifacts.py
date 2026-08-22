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

from bian_quant.factors.proposal_audit import ProposalAuditResult
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
            ordered_records,
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
        "run_id": run_id,
    }
    artifact_bytes["run_manifest.json"] = _canonical_json_bytes(manifest_payload)

    artifact_paths: dict[str, Path] = {}
    artifact_sha256: dict[str, str] = {}
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
    records: Sequence[_AuditedProposal],
    *,
    max_queue_size: int | None = None,
) -> bytes:
    lines = [
        "# Decision Queue",
        "",
        "| Queue Rank | Research Family | Factor | Verdict | Identity SHA-256 |",
        "| --- | --- | --- | --- | --- |",
    ]
    seen_identities: set[str] = set()
    queue_records: list[_AuditedProposal] = []
    for record in records:
        identity_sha256 = record.proposal.identity_sha256
        if identity_sha256 in seen_identities:
            continue
        seen_identities.add(identity_sha256)
        queue_records.append(record)
        if max_queue_size is not None and len(queue_records) >= max_queue_size:
            break
    for rank, record in enumerate(queue_records, start=1):
        verdict = record.audit.verdict if record.audit is not None else "PASS"
        lines.append(
            f"| {rank} | {record.proposal.research_family} | {record.proposal.factor_id} | "
            f"{verdict} | {record.proposal.identity_sha256} |"
        )
    return _markdown_bytes(lines)


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
