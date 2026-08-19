from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from bian_quant.factors.proposal_artifacts import write_proposal_run
from bian_quant.factors.proposals import FactorProposal
from tests.unit.factors.test_proposals import proposal_payload


def valid_proposal(**overrides: object) -> FactorProposal:
    payload = proposal_payload()
    payload.update(overrides)
    return FactorProposal.model_validate(payload)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


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
