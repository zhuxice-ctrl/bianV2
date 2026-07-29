"""Decision packet writer for dual-horizon research outputs.

Produces all required artifacts in an exclusive run directory and renders
a fixed decision summary answering:
1. What data changed
2. What was unavailable/excluded
3. Current regime and evidence
4. Passed, failed, and observed factors
5. Requested human decision

Displays four separate statuses: Engineering, Data, Factors, and Human Decision.
Zero candidates maps to Factor status NO_PROMOTION, not failure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from bian_quant.reporting.artifacts import ArtifactWriter, RunDirectory

REQUIRED_ARTIFACTS = {
    "data-acquisition.json",
    "data-quality.json",
    "macro-regime.json",
    "macro-regime.md",
    "factor-screening.json",
    "factor-screening.md",
    "decision-summary.md",
}


@dataclass
class DecisionEvidence:
    """Evidence inputs for the decision packet."""

    acquisition: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, Any] = field(default_factory=dict)
    macro_regime: dict[str, Any] = field(default_factory=dict)
    macro_regime_md: str = ""
    factor_screening: dict[str, Any] = field(default_factory=dict)
    factor_screening_md: str = ""
    engineering_status: str = "PASSED"
    data_status: str = "COMPLETE"
    factor_status: str = "NO_PROMOTION"
    human_decision: str = "NONE_REQUIRED"
    candidate_factor_ids: tuple[str, ...] = ()
    excluded_factors: list[str] = field(default_factory=list)
    current_regime: str = "unknown"
    passed_factors: list[str] = field(default_factory=list)
    failed_factors: list[str] = field(default_factory=list)
    observed_factors: list[str] = field(default_factory=list)


def zero_candidate_evidence() -> DecisionEvidence:
    """Return evidence for a zero-candidate run."""
    return DecisionEvidence(
        acquisition={"status": "completed", "assets": [], "periods": 0},
        quality={"status": "passed", "coverage": {}},
        macro_regime={"current_label": "unknown"},
        macro_regime_md="# Macro Regime\n\nNo regime data available.",
        factor_screening={"candidates": 0, "factors": []},
        factor_screening_md="# Factor Screening\n\nNo candidates promoted.",
        engineering_status="PASSED",
        data_status="COMPLETE",
        factor_status="NO_PROMOTION",
        human_decision="NONE_REQUIRED",
        candidate_factor_ids=(),
    )


def write_decision_packet(
    evidence: DecisionEvidence,
    run_dir: Path,
) -> list[Path]:
    """Write all required artifacts into *run_dir*.

    Returns the list of paths to all written artifacts.
    """
    writer = ArtifactWriter(run_dir.parent)
    run = RunDirectory(path=run_dir, name=run_dir.name)

    # If run dir doesn't exist yet, create it
    if not run_dir.exists():
        runDir = writer.create_run(run.name)
        run = runDir

    paths: list[Path] = []

    # data-acquisition.json
    paths.append(
        writer.write_json(run, "data-acquisition.json", evidence.acquisition)
    )

    # data-quality.json
    paths.append(
        writer.write_json(run, "data-quality.json", evidence.quality)
    )

    # macro-regime.json
    paths.append(
        writer.write_json(run, "macro-regime.json", evidence.macro_regime)
    )

    # macro-regime.md
    paths.append(
        writer.write_text(run, "macro-regime.md", evidence.macro_regime_md)
    )

    # factor-screening.json
    paths.append(
        writer.write_json(run, "factor-screening.json", evidence.factor_screening)
    )

    # factor-screening.md
    paths.append(
        writer.write_text(run, "factor-screening.md", evidence.factor_screening_md)
    )

    # decision-summary.md
    summary = _render_decision_summary(evidence)
    paths.append(
        writer.write_text(run, "decision-summary.md", summary)
    )

    return paths


def _render_decision_summary(evidence: DecisionEvidence) -> str:
    """Render the fixed decision summary markdown."""
    lines = [
        "# Dual-Horizon Research Decision Summary",
        "",
        "## Status Overview",
        "",
        f"Engineering status: {evidence.engineering_status}",
        f"Data status: {evidence.data_status}",
        f"Factor status: {evidence.factor_status}",
        f"Human decision: {evidence.human_decision}",
        "",
        "## Data Changes",
        "",
        f"Acquisition status: {evidence.acquisition.get('status', 'unknown')}",
        f"Quality status: {evidence.quality.get('status', 'unknown')}",
        "",
        "## Unavailable or Excluded Data",
        "",
    ]

    if evidence.excluded_factors:
        for f in evidence.excluded_factors:
            lines.append(f"- {f}")
    else:
        lines.append("- None")

    lines.extend([
        "",
        "## Current Regime and Evidence",
        "",
        f"Current regime: {evidence.current_regime}",
        "",
        "## Factor Results",
        "",
        f"Passed: {', '.join(evidence.passed_factors) if evidence.passed_factors else 'None'}",
        f"Failed: {', '.join(evidence.failed_factors) if evidence.failed_factors else 'None'}",
        f"Observed: {', '.join(evidence.observed_factors) if evidence.observed_factors else 'None'}",
        f"Candidate factors: {len(evidence.candidate_factor_ids)}",
        "",
        "## Requested Human Decision",
        "",
        evidence.human_decision,
        "",
    ])

    return "\n".join(lines)
