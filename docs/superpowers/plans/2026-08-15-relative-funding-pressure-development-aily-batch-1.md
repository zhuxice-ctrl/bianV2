# Relative Funding Pressure Development — Aily Batch 1 Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans task-by-task. Stop after the Batch 1 handoff; do not start later batches unless Codex sends the next instruction.

**Goal:** On a new development branch, add a regression guard so development evidence can never promote a factor to CANDIDATE, then provide Codex with auditable test and Git evidence.

**Architecture:** This batch changes only the development lifecycle adapter in research/dual_horizon.py and its unit test. It preserves the informational candidate_factor_ids list but prohibits the FactorRegistry from leaving RESEARCHING/OBSERVED during development-only work. It does not touch snapshots, Canonical data, Funding calculations, Holdout, reporting, dashboard, paper, or live code.

**Tech Stack:** Python 3.11, uv, pytest, Ruff, mypy, SQLite FactorRegistry.

---

## Mandatory rules

Read these files completely before running any command:

~~~text
docs/AILY_EXECUTION_RULES.md
docs/superpowers/specs/2026-08-14-relative-funding-pressure-factor-design.md
docs/superpowers/plans/2026-08-15-relative-funding-pressure-development.md
docs/contracts/local-snapshot-recovery-contract.md
~~~

The only allowed source/test files in this batch are:

~~~text
src/bian_quant/research/dual_horizon.py
tests/unit/research/test_dual_horizon.py
~~~

Do not touch .superpowers/. Do not run:

~~~text
recover_local_dual_horizon_snapshots
repair_verified_local_canonical_inputs
analyze_cataloged_dual_horizon
evaluate_candidate_holdout
run_small_account_backtest
paper or live commands
network download or downloader code
~~~

Do not push, merge, delete a branch, or run later plan batches. Codex audits this batch before authorizing the next one.

## Task 0: Establish the branch and clean baseline

- [ ] Step 1: Set UTF-8 console encoding and inspect the workspace.

~~~powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git status --short --branch
git log --oneline -5
git diff --stat
git diff --check
~~~

Expected: main is checked out or can be checked out; .superpowers/ may be untracked and must remain untouched. If any tracked file is modified, stop and report the complete status output to Codex.

- [ ] Step 2: Update main without rewriting history, then create the feature branch.

~~~powershell
git switch main
git pull --ff-only origin main
git switch -c codex/relative-funding-pressure-development
~~~

If the feature branch already exists, use:

~~~powershell
git switch codex/relative-funding-pressure-development
git status --short --branch
~~~

Expected: branch name is codex/relative-funding-pressure-development and no tracked working-tree changes exist.

## Task 1: Reproduce the forbidden Candidate transition

**Files:**

- Modify: tests/unit/research/test_dual_horizon.py

- [ ] Step 1: Add the test imports.

Add these imports after the existing future import and factor imports:

~~~python
from pathlib import Path

from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorState
~~~

- [ ] Step 2: Add the failing regression test at the end of tests/unit/research/test_dual_horizon.py.

~~~python
def test_development_evidence_never_promotes_candidate(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "factors.sqlite")
    try:
        spec = dual_horizon_factor_specs()[0]
        registry.register(spec, code_sha="test-sha")
        research._transition_after_evidence(
            registry,
            {spec.factor_id: spec},
            {spec.factor_id},
            {spec.factor_id},
            evidence_run_id="development-run",
        )
        assert registry.state(spec.factor_id, spec.version) is FactorState.OBSERVED
    finally:
        registry.close()
~~~

- [ ] Step 3: Run only the new test before changing production code.

~~~powershell
uv run pytest -p no:cov tests/unit/research/test_dual_horizon.py::test_development_evidence_never_promotes_candidate -q
~~~

Expected before the fix: FAIL because the current implementation transitions the test factor from OBSERVED to CANDIDATE.

If the test does not fail for that reason, stop and provide the full output to Codex. Do not change the production code.

## Task 2: Make the minimal lifecycle repair

**Files:**

- Modify: src/bian_quant/research/dual_horizon.py
- Modify: tests/unit/research/test_dual_horizon.py

- [ ] Step 1: Replace planned lifecycle states.

Replace the existing conditional that selects CANDIDATE for names in candidates with:

~~~python
planned_states = {
    name: FactorState.OBSERVED.value if name in completed_ids else FactorState.RESEARCHING.value
    for name in factor_names
}
~~~

This keeps candidate_factor_ids in the development artifact as an informational list only.

- [ ] Step 2: Remove the Candidate registry transition.

In research._transition_after_evidence, retain the candidates argument to preserve its current private call signature, but remove this complete block:

~~~python
if (
    name in candidates
    and registry.state(spec.factor_id, spec.version) == FactorState.OBSERVED
):
    registry.transition(
        spec.factor_id,
        spec.version,
        FactorState.CANDIDATE,
        evidence_run_id=evidence_run_id,
    )
~~~

The function must only perform RESEARCHING -> OBSERVED. Do not change FactorRegistry legal transitions, Holdout code, Candidate evaluation, gate calculations, BH logic, OI delay logic, or the candidate_factor_ids artifact field.

- [ ] Step 3: Run focused checks.

~~~powershell
uv run pytest -p no:cov tests/unit/research/test_dual_horizon.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_operations.py -q
uv run ruff check src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py
uv run ruff format --check src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py
uv run mypy src/bian_quant
git diff --check
~~~

Expected: all commands exit 0. The new regression test passes and no Holdout ledger exists.

- [ ] Step 4: Inspect the exact diff and commit locally.

~~~powershell
git diff -- src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py
git add src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py
git diff --cached --check
git commit -m "fix(research): keep development factors out of candidate state"
git status --short --branch
~~~

Expected: exactly two tracked files are in the commit. Do not include .superpowers/ or any data artifact.

## Mandatory stop and report

Stop immediately after Task 2. Do not push or merge.

Send Codex one report containing all of the following:

~~~text
1. Current branch and git status output before and after the work.
2. New commit SHA.
3. Full output from the failing test before the repair.
4. Full output from every focused pytest, Ruff, format, mypy, and git diff check after the repair.
5. git show --stat --oneline <commit-SHA>.
6. git diff HEAD^..HEAD -- src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py
7. Confirmation that no download, recovery, analysis, Holdout, paper, live, push, or merge command was run.
~~~

Codex will audit the code and outputs, repair any defect directly, then issue Batch 2: read-only snapshot preflight.
