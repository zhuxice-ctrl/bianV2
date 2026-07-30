"""Integration tests for the decision packet."""

from __future__ import annotations

from pathlib import Path

from bian_quant.reporting.decision import (
    REQUIRED_ARTIFACTS,
    write_decision_packet,
    zero_candidate_evidence,
)


class TestDecisionPacket:
    def test_zero_candidate_packet_still_contains_all_artifacts(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run-1"
        paths = write_decision_packet(zero_candidate_evidence(), run_dir)
        assert {path.name for path in paths} == REQUIRED_ARTIFACTS

    def test_summary_contains_engineering_status(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run-1"
        write_decision_packet(zero_candidate_evidence(), run_dir)
        summary = (run_dir / "decision-summary.md").read_text(encoding="utf-8")
        assert "Engineering status: PASSED" in summary

    def test_summary_contains_candidate_count(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run-1"
        write_decision_packet(zero_candidate_evidence(), run_dir)
        summary = (run_dir / "decision-summary.md").read_text(encoding="utf-8")
        assert "Candidate factors: 0" in summary

    def test_summary_contains_four_statuses(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run-1"
        write_decision_packet(zero_candidate_evidence(), run_dir)
        summary = (run_dir / "decision-summary.md").read_text(encoding="utf-8")
        assert "Engineering status:" in summary
        assert "Data status:" in summary
        assert "Factor status:" in summary
        assert "Human decision:" in summary

    def test_zero_candidates_is_no_promotion_not_failure(self, tmp_path: Path) -> None:
        run_dir = tmp_path / "run-1"
        evidence = zero_candidate_evidence()
        write_decision_packet(evidence, run_dir)
        summary = (run_dir / "decision-summary.md").read_text(encoding="utf-8")
        assert "NO_PROMOTION" in summary
        assert "FAILED" not in summary

    def test_all_json_files_are_valid(self, tmp_path: Path) -> None:
        import json

        run_dir = tmp_path / "run-1"
        paths = write_decision_packet(zero_candidate_evidence(), run_dir)
        for path in paths:
            if path.suffix == ".json":
                data = json.loads(path.read_text(encoding="utf-8"))
                assert isinstance(data, dict)
