from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bian_quant.factors.proposal_artifacts import write_proposal_run
from bian_quant.factors.proposal_audit import ProposalAuditResult
from bian_quant.factors.proposals import FactorProposal
from tests.unit.factors.test_proposals import proposal_payload


def valid_proposal(**overrides: object) -> FactorProposal:
    payload = proposal_payload()
    payload.update(overrides)
    return FactorProposal.model_validate(payload)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _markdown_table_rows(path: Path) -> list[list[str]]:
    table_lines = [
        line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("|")
    ]
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in table_lines[2:]]


def test_write_run_creates_all_required_artifacts(tmp_path: Path) -> None:
    result = write_proposal_run(
        tmp_path,
        proposals=[valid_proposal()],
        run_id="run-1",
        code_sha="abc",
    )

    assert set(result.paths) == {
        "candidate_registry.json",
        "candidate_summary.md",
        "audit_report.md",
        "deduplication_report.md",
        "decision_queue.md",
        "run_manifest.json",
    }
    assert result.run_directory == tmp_path / "run-1"
    assert all(path.exists() for path in result.paths.values())


def test_existing_run_directory_is_never_overwritten(tmp_path: Path) -> None:
    write_proposal_run(tmp_path, proposals=[valid_proposal()], run_id="run-1", code_sha="abc")

    with pytest.raises(FileExistsError):
        write_proposal_run(tmp_path, proposals=[valid_proposal()], run_id="run-1", code_sha="abc")


def test_candidate_registry_is_sorted_and_canonical_json(tmp_path: Path) -> None:
    first = valid_proposal(factor_id="zeta_factor", research_family="volume_liquidity")
    second = valid_proposal(factor_id="alpha_factor", research_family="price_dynamics")

    result = write_proposal_run(
        tmp_path,
        proposals=[first, second],
        run_id="run-1",
        code_sha="abc",
        config_sha256="cfg123",
    )

    registry_path = result.paths["candidate_registry.json"]
    registry_text = registry_path.read_text(encoding="utf-8")
    registry_payload = json.loads(registry_text)

    assert registry_payload["proposals"][0]["factor_id"] == "alpha_factor"
    assert registry_payload["proposals"][1]["factor_id"] == "zeta_factor"
    assert registry_text == json.dumps(
        registry_payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def test_manifest_records_boundary_assertions_and_artifact_hashes(tmp_path: Path) -> None:
    result = write_proposal_run(
        tmp_path,
        proposals=[valid_proposal()],
        run_id="run-1",
        code_sha="abc",
        config_sha256="cfg123",
    )

    manifest_path = result.paths["run_manifest.json"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    assert manifest["mode"] == "proposal_only"
    assert manifest["boundary_assertions"] == {
        "data_read": False,
        "holdout_accessed": False,
        "live_trading": False,
        "network_access": False,
        "paper_trading": False,
    }
    assert manifest["deduplication"] == {
        "deduplicated_count": 1,
        "duplicate_identity_count": 0,
        "input_count": 1,
    }
    assert set(manifest["artifacts"]) == {
        "audit_report.md",
        "candidate_registry.json",
        "candidate_summary.md",
        "decision_queue.md",
        "deduplication_report.md",
    }
    for artifact_name, artifact_meta in manifest["artifacts"].items():
        assert artifact_meta["sha256"] == _sha256(result.paths[artifact_name])
        assert artifact_meta["bytes"] == result.paths[artifact_name].stat().st_size


def test_positional_audits_stay_paired_with_unsorted_proposals(tmp_path: Path) -> None:
    zeta = valid_proposal(factor_id="zeta_factor", research_family="volume_liquidity")
    alpha = valid_proposal(factor_id="alpha_factor", research_family="price_dynamics")

    result = write_proposal_run(
        tmp_path,
        proposals=[zeta, alpha],
        run_id="run-1",
        code_sha="abc",
        audits=[
            ProposalAuditResult(verdict="BLOCKED", reason_codes=("ZETA_ONLY",)),
            ProposalAuditResult(verdict="REJECTED", reason_codes=("ALPHA_ONLY",)),
        ],
    )

    registry_payload = json.loads(
        result.paths["candidate_registry.json"].read_text(encoding="utf-8")
    )

    assert [proposal["factor_id"] for proposal in registry_payload["proposals"]] == [
        "alpha_factor",
        "zeta_factor",
    ]
    assert registry_payload["proposals"][0]["audit_verdict"] == "REJECTED"
    assert registry_payload["proposals"][0]["audit_reason_codes"] == ["ALPHA_ONLY"]
    assert registry_payload["proposals"][1]["audit_verdict"] == "BLOCKED"
    assert registry_payload["proposals"][1]["audit_reason_codes"] == ["ZETA_ONLY"]


def test_selection_writes_only_selected_preregistration_and_registry_metadata(
    tmp_path: Path,
) -> None:
    selected = valid_proposal(
        factor_id="alpha_volume",
        research_family="volume_liquidity",
        formula="rolling_mean(volume, 6)",
        required_columns=["open_time", "volume", "available_time"],
    )
    same_mechanism = valid_proposal(
        factor_id="beta_volume",
        research_family="volume_liquidity",
        formula="rolling_mean(volume, 12)",
        required_columns=["open_time", "volume", "available_time"],
    )
    blocked = valid_proposal(
        factor_id="gamma_price",
        research_family="price_dynamics",
        formula="rolling_std(close, 24)",
        required_columns=["open_time", "close", "available_time"],
    )

    result = write_proposal_run(
        tmp_path,
        proposals=[same_mechanism, blocked, selected],
        run_id="run-1",
        code_sha="abc",
        audits=[
            ProposalAuditResult(verdict="PASS"),
            ProposalAuditResult(verdict="BLOCKED", reason_codes=("NO_TIMING",)),
            ProposalAuditResult(verdict="PASS"),
        ],
        max_proposals_per_family=4,
    )

    preregistration_paths = sorted((result.run_directory / "preregistration").glob("*.yaml"))
    registry_payload = json.loads(
        result.paths["candidate_registry.json"].read_text(encoding="utf-8")
    )
    queue_rows = _markdown_table_rows(result.paths["decision_queue.md"])
    proposals_by_id = {
        proposal["factor_id"]: proposal for proposal in registry_payload["proposals"]
    }
    selected_path = preregistration_paths[0].relative_to(result.run_directory).as_posix()

    assert len(preregistration_paths) == 1
    assert proposals_by_id["alpha_volume"]["selection_reason"] == "SELECTED"
    assert proposals_by_id["alpha_volume"]["preregistration_path"] == selected_path
    assert proposals_by_id["beta_volume"]["selection_reason"] == "DIVERSITY_MECHANISM_DUPLICATE"
    assert proposals_by_id["beta_volume"]["preregistration_path"] is None
    assert proposals_by_id["gamma_price"]["selection_reason"] == "AUDIT_NOT_PASS"
    assert proposals_by_id["gamma_price"]["preregistration_path"] is None
    assert queue_rows == [
        [
            "1",
            "volume_liquidity",
            "alpha_volume",
            "PASS",
            "SELECTED",
            proposals_by_id["alpha_volume"]["identity_sha256"],
            selected_path,
        ]
    ]


def test_decision_queue_caps_at_max_review_queue(tmp_path: Path) -> None:
    unique_proposals = [
        valid_proposal(
            factor_id=f"factor_{index}",
            research_family="price_dynamics",
            formula=f"signal_{index}(volume, 24)",
        )
        for index in range(6)
    ]
    inputs = [
        unique_proposals[5],
        unique_proposals[2],
        unique_proposals[4],
        unique_proposals[2],
        unique_proposals[1],
        unique_proposals[3],
        unique_proposals[0],
    ]

    result = write_proposal_run(
        tmp_path,
        proposals=inputs,
        run_id="run-1",
        code_sha="abc",
        max_review_queue=5,
    )

    registry_payload = json.loads(
        result.paths["candidate_registry.json"].read_text(encoding="utf-8")
    )
    queue_rows = _markdown_table_rows(result.paths["decision_queue.md"])

    assert len(registry_payload["proposals"]) == len(inputs)
    assert len(queue_rows) == 5
    assert [row[2] for row in queue_rows] == [
        "factor_0",
        "factor_1",
        "factor_2",
        "factor_3",
        "factor_4",
    ]
    assert len({row[5] for row in queue_rows}) == 5


def test_decision_queue_shows_all_when_no_cap(tmp_path: Path) -> None:
    unique_proposals = [
        valid_proposal(
            factor_id=f"factor_{index}",
            research_family="price_dynamics",
            formula=f"signal_{index}(volume, 24)",
        )
        for index in range(6)
    ]

    result = write_proposal_run(
        tmp_path,
        proposals=unique_proposals,
        run_id="run-1",
        code_sha="abc",
    )

    queue_rows = _markdown_table_rows(result.paths["decision_queue.md"])

    assert len(queue_rows) == 6
    assert [row[2] for row in queue_rows] == [
        "factor_0",
        "factor_1",
        "factor_2",
        "factor_3",
        "factor_4",
        "factor_5",
    ]


def test_deduplication_report_can_record_original_input_counts(tmp_path: Path) -> None:
    proposal = valid_proposal()

    result = write_proposal_run(
        tmp_path,
        proposals=[proposal],
        run_id="run-1",
        code_sha="abc",
        original_input_count=3,
        duplicate_identity_count=2,
    )

    report = result.paths["deduplication_report.md"].read_text(encoding="utf-8")
    manifest = json.loads(result.paths["run_manifest.json"].read_text(encoding="utf-8"))

    assert "- input_count: `3`" in report
    assert "- deduplicated_count: `1`" in report
    assert "- duplicate_identity_count: `2`" in report
    assert manifest["deduplication"] == {
        "deduplicated_count": 1,
        "duplicate_identity_count": 2,
        "input_count": 3,
    }
