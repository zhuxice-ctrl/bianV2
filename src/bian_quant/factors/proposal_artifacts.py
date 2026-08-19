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


def write_proposal_run(
    root: Path | str,
    *,
    proposals: Sequence[FactorProposal | Mapping[str, Any]],
    run_id: str,
    code_sha: str,
    config_sha256: str = "",
    audits: Mapping[str, ProposalAuditResult | Mapping[str, Any]]
    | Sequence[ProposalAuditResult | Mapping[str, Any]]
    | None = None,
) -> ProposalRunArtifacts:
    """Write one append-only proposal run without touching data or networks."""

    root_path = Path(root)
    root_path.mkdir(parents=True, exist_ok=True)
    run_directory = root_path / run_id
    run_directory.mkdir(parents=False, exist_ok=False)

    ordered_proposals = tuple(sorted(_normalize_proposals(proposals), key=_proposal_sort_key))
    audit_map = _normalize_audits(ordered_proposals, audits)

    registry_payload = {
        "code_sha": code_sha,
        "config_sha256": config_sha256,
        "mode": "proposal_only",
        "proposal_count": len(ordered_proposals),
        "proposals": [
            {
                **proposal.model_dump(mode="json"),
                "audit_reason_codes": list(audit_map[proposal.identity_sha256].reason_codes)
                if proposal.identity_sha256 in audit_map
                else [],
                "audit_verdict": audit_map[proposal.identity_sha256].verdict
                if proposal.identity_sha256 in audit_map
                else "NOT_RUN",
                "identity_sha256": proposal.identity_sha256,
            }
            for proposal in ordered_proposals
        ],
        "run_id": run_id,
    }

    artifact_bytes: dict[str, bytes] = {
        "candidate_registry.json": _canonical_json_bytes(registry_payload),
        "candidate_summary.md": _render_candidate_summary(run_id, code_sha, ordered_proposals),
        "audit_report.md": _render_audit_report(ordered_proposals, audit_map),
        "deduplication_report.md": _render_deduplication_report(ordered_proposals),
        "decision_queue.md": _render_decision_queue(ordered_proposals, audit_map),
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
        "mode": "proposal_only",
        "proposal_count": len(ordered_proposals),
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
) -> dict[str, ProposalAuditResult]:
    if audits is None:
        return {}
    if isinstance(audits, Mapping):
        return {
            str(identity_sha256): _coerce_audit_result(audit_result)
            for identity_sha256, audit_result in audits.items()
        }
    normalized_audits = list(audits)
    if len(normalized_audits) != len(proposals):
        raise ValueError("audit sequence must align with proposal sequence")
    return {
        proposal.identity_sha256: _coerce_audit_result(audit_result)
        for proposal, audit_result in zip(proposals, normalized_audits, strict=True)
    }


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
    proposals: Sequence[FactorProposal],
    audit_map: Mapping[str, ProposalAuditResult],
) -> bytes:
    verdicts = [
        audit_map[proposal.identity_sha256].verdict
        for proposal in proposals
        if proposal.identity_sha256 in audit_map
    ]
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
    for proposal in proposals:
        audit_result = audit_map.get(proposal.identity_sha256)
        verdict = audit_result.verdict if audit_result is not None else "NOT_RUN"
        reason_codes = ", ".join(audit_result.reason_codes) if audit_result else "none"
        lines.append(f"| {proposal.factor_id} | {verdict} | {reason_codes} |")
    return _markdown_bytes(lines)


def _render_deduplication_report(proposals: Sequence[FactorProposal]) -> bytes:
    identity_counts = Counter(proposal.identity_sha256 for proposal in proposals)
    duplicate_identities = tuple(
        identity_sha256 for identity_sha256, count in sorted(identity_counts.items()) if count > 1
    )
    lines = [
        "# Deduplication Report",
        "",
        f"- input_count: `{len(proposals)}`",
        f"- unique_identity_count: `{len(identity_counts)}`",
        f"- duplicate_identity_count: `{len(proposals) - len(identity_counts)}`",
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
    proposals: Sequence[FactorProposal],
    audit_map: Mapping[str, ProposalAuditResult],
) -> bytes:
    lines = [
        "# Decision Queue",
        "",
        "| Queue Rank | Research Family | Factor | Verdict | Identity SHA-256 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for rank, proposal in enumerate(proposals, start=1):
        verdict = audit_map.get(
            proposal.identity_sha256,
            ProposalAuditResult(verdict="PASS"),
        ).verdict
        lines.append(
            f"| {rank} | {proposal.research_family} | {proposal.factor_id} | "
            f"{verdict} | {proposal.identity_sha256} |"
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
