"""Run the proposal-only quant factor research factory locally."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

from bian_quant.factors.generator import generate_proposals
from bian_quant.factors.proposal_artifacts import ProposalRunArtifacts, write_proposal_run
from bian_quant.factors.proposal_audit import (
    DEFAULT_FORBIDDEN_FACTORS_PATH,
    ProposalAuditResult,
    audit_proposal,
)
from bian_quant.factors.proposals import FactorProposal

REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class FactoryRunResult:
    """Completed local proposal-factory run."""

    status: Literal["completed"]
    mode: Literal["proposal_only"]
    run_id: str
    run_directory: Path
    artifact_paths: dict[str, Path]
    artifact_sha256: dict[str, str]
    config_sha256: str
    proposal_count: int
    deduplicated_count: int
    audit_verdict_counts: dict[str, int]
    holdout_accessed: bool
    paper_trading: bool
    live_trading: bool
    data_read: bool
    network_access: bool


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--code-sha", required=True)
    return parser.parse_args(argv)


def run_factory(
    config_path: Path | str,
    output_root: Path | str,
    code_sha: str,
) -> FactoryRunResult:
    """Generate, audit, deduplicate, and persist proposal-only factor artifacts."""

    resolved_config_path = _resolve_repo_path(config_path)
    factory_config = _load_factory_config(resolved_config_path)
    config_sha256 = _config_sha256(factory_config)
    run_id = _build_run_id(config_sha256=config_sha256, code_sha=code_sha)

    proposals = generate_proposals(resolved_config_path, code_sha=code_sha)
    forbidden_factors_path = _forbidden_factors_path(factory_config)
    available_time_definition = str(
        factory_config.get("available_time_definition", "close_time")
    ).strip()
    if not available_time_definition:
        raise ValueError("available_time_definition must be non-empty when provided")

    audits_by_identity: dict[str, ProposalAuditResult] = {}
    for proposal in proposals:
        audits_by_identity[proposal.identity_sha256] = audit_proposal(
            proposal,
            available_time_definition=available_time_definition,
            forbidden_factors_path=forbidden_factors_path,
        )

    deduplicated_proposals = _deduplicate_proposals(proposals)
    artifacts = write_proposal_run(
        output_root,
        proposals=deduplicated_proposals,
        run_id=run_id,
        code_sha=code_sha,
        config_sha256=config_sha256,
        audits=audits_by_identity,
    )

    return _build_result(
        run_id=run_id,
        config_sha256=config_sha256,
        proposals=proposals,
        deduplicated_proposals=deduplicated_proposals,
        audits_by_identity=audits_by_identity,
        artifacts=artifacts,
    )


def _resolve_repo_path(path_value: Path | str) -> Path:
    candidate = Path(path_value)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def _load_factory_config(config_path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("factory config must be a YAML mapping")
    if payload.get("mode", "proposal_only") != "proposal_only":
        raise ValueError("factory config must set mode=proposal_only")
    return {str(key): value for key, value in payload.items()}


def _config_sha256(factory_config: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        factory_config,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _forbidden_factors_path(factory_config: Mapping[str, Any]) -> Path:
    raw_path = str(factory_config.get("forbidden_archive_path", "")).strip()
    if not raw_path:
        return DEFAULT_FORBIDDEN_FACTORS_PATH
    return _resolve_repo_path(raw_path)


def _deduplicate_proposals(proposals: list[FactorProposal]) -> list[FactorProposal]:
    deduplicated: list[FactorProposal] = []
    seen_identities: set[str] = set()
    for proposal in proposals:
        if proposal.identity_sha256 in seen_identities:
            continue
        seen_identities.add(proposal.identity_sha256)
        deduplicated.append(proposal)
    return deduplicated


def _build_run_id(*, config_sha256: str, code_sha: str) -> str:
    normalized_code_sha = re.sub(r"[^a-zA-Z0-9._-]+", "-", code_sha.strip()) or "unknown"
    return f"proposal-factory-{config_sha256[:12]}-{normalized_code_sha[:16]}"


def _build_result(
    *,
    run_id: str,
    config_sha256: str,
    proposals: list[FactorProposal],
    deduplicated_proposals: list[FactorProposal],
    audits_by_identity: Mapping[str, ProposalAuditResult],
    artifacts: ProposalRunArtifacts,
) -> FactoryRunResult:
    verdict_counts = Counter(
        audits_by_identity[proposal.identity_sha256].verdict for proposal in deduplicated_proposals
    )
    return FactoryRunResult(
        status="completed",
        mode="proposal_only",
        run_id=run_id,
        run_directory=artifacts.run_directory,
        artifact_paths=artifacts.paths,
        artifact_sha256=artifacts.artifact_sha256,
        config_sha256=config_sha256,
        proposal_count=len(proposals),
        deduplicated_count=len(deduplicated_proposals),
        audit_verdict_counts=dict(sorted(verdict_counts.items())),
        holdout_accessed=False,
        paper_trading=False,
        live_trading=False,
        data_read=False,
        network_access=False,
    )


def _result_payload(result: FactoryRunResult) -> dict[str, Any]:
    return {
        "artifact_paths": {
            name: path.as_posix() for name, path in sorted(result.artifact_paths.items())
        },
        "artifact_sha256": dict(sorted(result.artifact_sha256.items())),
        "audit_verdict_counts": dict(sorted(result.audit_verdict_counts.items())),
        "config_sha256": result.config_sha256,
        "data_read": result.data_read,
        "deduplicated_count": result.deduplicated_count,
        "holdout_accessed": result.holdout_accessed,
        "live_trading": result.live_trading,
        "mode": result.mode,
        "network_access": result.network_access,
        "paper_trading": result.paper_trading,
        "proposal_count": result.proposal_count,
        "run_directory": result.run_directory.as_posix(),
        "run_id": result.run_id,
        "status": result.status,
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        result = run_factory(
            config_path=args.config,
            output_root=args.output_root,
            code_sha=args.code_sha,
        )
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f"factor factory failed: {error}", file=sys.stderr)
        return 1

    print(json.dumps(_result_payload(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
