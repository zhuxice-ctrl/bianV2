# Relative Funding Pressure Development Evidence Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development (recommended) or executing-plans task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Use the recovered local research snapshots to produce real development-only evidence for relative_funding_pressure@1.0.0 while ensuring no factor enters Candidate/Approved and no Holdout, paper, live, or network workflow is opened.

**Architecture:** The analysis consumes only the four recovered research snapshots and their three OI-delay views through the existing Catalog resolver. The pure factor remains in factors/, screening remains in research/, and evidence uses the existing reporting packet writer. The recovery snapshots were created with code identity e4fc736, so that exact identity is used for strict resolver and source-evidence matching even though main contains later documentation commits.

**Tech Stack:** Python 3.11, uv, pandas, PyArrow, SQLite, Pydantic v2, pytest, Ruff, mypy.

---

## Non-negotiable boundaries

Before every task, read:

~~~text
docs/AILY_EXECUTION_RULES.md
docs/superpowers/specs/2026-08-14-relative-funding-pressure-factor-design.md
docs/superpowers/plans/2026-08-14-relative-funding-pressure-factor.md
docs/contracts/local-snapshot-recovery-contract.md
docs/evidence/2026-08-15-local-snapshot-recovery-with-exclusion-run.md
~~~

Run this before modifying anything:

~~~powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git status --short --branch
git log --oneline -5
git diff --stat
git diff --check
~~~

Prohibited in this plan:

- network downloads, downloader calls, API keys, exchange clients, or WebSockets;
- recovery, Canonical repair, or any Raw/Catalog input rewrite;
- evaluate_candidate_holdout, Holdout ledger access, Candidate/Approved promotion, paper trading, live trading, or account operations;
- factor parameter searches, model training, or backtest execution;
- direct Parquet reads from factors/, research/dual_horizon.py, reporting, or dashboard code;
- touching .superpowers/ or unrelated formatting cleanup.

The only permitted writer is the existing development evidence path invoked by analyze_cataloged_dual_horizon. If the real run is blocked, record the actual blocker and stop; never synthesize a passing result.

## File map

| File | Responsibility |
|---|---|
| src/bian_quant/research/dual_horizon.py | Prevent development evidence from changing registry state to Candidate. |
| tests/unit/research/test_dual_horizon.py | Regression test for the lifecycle boundary. |
| docs/evidence/2026-08-15-relative-funding-pressure-development-run.md | Actual local development run evidence. |
| docs/implementation-notes.md | Append only measured results and stop boundaries. |

No changes are planned for data/, factors/, reporting/, dashboard/, wire models, or snapshot contents unless a reproducible gate failure proves a narrowly scoped compatibility defect.

### Task 0: Create the isolated development branch

**Files:** No repository files; branch setup only.

- [ ] **Step 1: Start from the merged main and create the feature branch**

~~~powershell
git switch main
git pull --ff-only origin main
git switch -c codex/relative-funding-pressure-development
~~~

Expected: the new branch starts at the same commit as origin/main. Do not modify source files until this branch exists.

### Task 1: Lock the development lifecycle boundary

Files:

- Modify: src/bian_quant/research/dual_horizon.py
- Test: tests/unit/research/test_dual_horizon.py

- [ ] Step 1: Add a failing regression test.

Add a test that registers a factor in RESEARCHING, calls the evidence transition helper with that factor listed as a development candidate, and proves the state becomes OBSERVED, never CANDIDATE:

~~~python
def test_development_evidence_never_promotes_candidate(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "factors.sqlite")
    spec = dual_horizon_factor_specs()[0]
    registry.register(spec, code_sha="test-sha")
    _transition_after_evidence(
        registry,
        {spec.factor_id: spec},
        {spec.factor_id},
        candidates={spec.factor_id},
        evidence_run_id="development-run",
    )
    assert registry.state(spec.factor_id, spec.version) is FactorState.OBSERVED
    registry.close()
~~~

Import Path, FactorRegistry, FactorState, dual_horizon_factor_specs, and _transition_after_evidence using the existing test conventions.

- [ ] Step 2: Run the regression test and confirm the current defect.

~~~powershell
uv run pytest -p no:cov tests/unit/research/test_dual_horizon.py::test_development_evidence_never_promotes_candidate -q
~~~

Expected before the fix: FAIL because the current helper transitions an OBSERVED factor to CANDIDATE when it is in candidates.

- [ ] Step 3: Implement the minimal contract fix.

Change planned_states so completed development factors are represented as observed, not candidate:

~~~python
planned_states = {
    name: FactorState.OBSERVED.value if name in completed_ids else FactorState.RESEARCHING.value
    for name in factor_names
}
~~~

Change _transition_after_evidence so it transitions only RESEARCHING -> OBSERVED. Retain the existing candidates parameter for call-site compatibility but ignore it; delete the OBSERVED -> CANDIDATE transition. Keep candidate_factor_ids as an informational “requires later human Holdout authorization” list; it must not alter registry state. The regression test continues passing candidates and proves that this former promotion input is ignored.

- [ ] Step 4: Run focused lifecycle and screening tests.

~~~powershell
uv run pytest -p no:cov tests/unit/research/test_dual_horizon.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_operations.py -q
~~~

Expected: all selected tests pass; every development lifecycle assertion remains observed or researching; no Holdout ledger is created.

- [ ] Step 5: Commit the boundary fix.

~~~powershell
git add src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py
git diff --cached --check
git commit -m "fix(research): keep development factors out of candidate state"
~~~

### Task 2: Perform read-only snapshot and evidence preflight

Files: No repository files; read-only verification only.

- [ ] Step 1: Resolve the recovered snapshots with the exact recovery code identity.

~~~powershell
@'
from pathlib import Path
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.local_snapshot_recovery import preflight_local_snapshot_recovery
from bian_quant.research.operations import resolve_dual_horizon_snapshots

root = Path.cwd()
config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
preflight = preflight_local_snapshot_recovery(config)
snapshots = resolve_dual_horizon_snapshots(config, code_sha="e4fc736")
print(f"preflight_status={preflight.status}")
print(f"inputs={len(preflight.inputs)}")
print(f"parents={len(preflight.parent_snapshot_ids)}")
print(f"input_set_sha256={preflight.input_set_sha256}")
print(f"excluded_source_ids={preflight.excluded_source_ids}")
print(f"snapshot_ids={snapshots.snapshot_ids}")
print(f"delay_snapshot_ids={sorted(snapshots.oi_delay_entries)}")
print(f"blocked_reasons={preflight.blocked_reasons}")
'@ | uv run python -
~~~

Expected actual values:

~~~text
preflight_status=ready
inputs=14879
parents=14879
input_set_sha256=fb6c5d3599dee1bf8018143df7c09a5d2f3cdb6047c091913ce9d7f24bb6f094
excluded_source_ids=('funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00',)
blocked_reasons=()
~~~

The four main snapshot IDs must match the recovery evidence. If any value differs, stop and record the exact output; do not recover or rewrite snapshots.

- [ ] Step 2: Verify the no-Holdout filesystem boundary.

~~~powershell
if (Test-Path var/artifacts/dual-horizon-popular-v1/holdout-access.sqlite) { throw "holdout ledger exists" }
if (Test-Path var/lake/research/dual-horizon-popular-v1/holdout-access.sqlite) { throw "research holdout ledger exists" }
~~~

Expected: both paths are absent.

### Task 3: Run real development-only screening

Files: Development artifacts under var/artifacts/dual-horizon-popular-v1/<analysis-run-id>/; no Raw, Canonical, or research snapshot writes.

- [ ] Step 1: Invoke only the existing cataloged analysis entry point.

Use the current commit as code_sha and e4fc736 only as snapshot_code_sha:

~~~powershell
@'
import subprocess
from pathlib import Path
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.research.operations import analyze_cataloged_dual_horizon

root = Path.cwd()
config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
analysis_code_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
result = analyze_cataloged_dual_horizon(
    config,
    code_sha=analysis_code_sha,
    snapshot_code_sha="e4fc736",
)
print(f"analysis_code_sha={analysis_code_sha}")
print("snapshot_code_sha=e4fc736")
print(f"run_id={result.run_id}")
print(f"status={result.status}")
print(f"snapshot_ids={result.snapshot_ids}")
print(f"candidate_factor_ids={result.candidate_factor_ids}")
print(f"artifact_dir={result.artifact_dir}")
print(f"error_code={result.error_code}")
'@ | uv run python -
~~~

- [ ] Step 2: Apply the stop rule to the real result.

If status=blocked, record the exact error_code, artifact paths, and missing coverage in the evidence document, then stop. A blocked result is a valid research outcome.

If status=passed, continue to Task 4. A non-empty candidate_factor_ids is only a pending research list; it does not authorize Holdout or any lifecycle promotion.

### Task 4: Audit the generated development artifacts

Files: Read only the returned analysis artifact directory.

- [ ] Step 1: Inspect required artifact files.

The returned directory must contain factor-screening.json, factor-screening.md, decision.json, and, when registry evidence is produced, the lifecycle artifact referenced by the screening result. Read them with UTF-8 JSON parsing; do not edit them.

- [ ] Step 2: Assert factor-specific evidence.

The audit must prove:

~~~text
factor_diagnostics.relative_funding_pressure exists
factor_diagnostics.relative_funding_pressure.exclusion_evidence exists
planned_lifecycle_states.relative_funding_pressure ∈ {observed, researching}
holdout_accessed == false
~~~

The exclusion evidence must preserve the real reason codes (FUNDING_UNAVAILABLE_OR_GAPPED, INSUFFICIENT_PEER_COVERAGE, or ZERO_CROSS_SECTIONAL_MAD) and must not convert missing values to zero. The artifact must include the two micro snapshot IDs, the actual analysis code SHA, development window 2024-07-01T00:00:00+00:00 through 2026-01-01T00:00:00+00:00, and no Holdout ledger path. The analysis RunManifest config must separately record snapshot_code_sha=e4fc736.

- [ ] Step 3: Check registry state independently.

Read the factor registry through FactorRegistry and assert:

~~~python
state = registry.state("relative_funding_pressure", "1.0.0")
assert state in {FactorState.RESEARCHING, FactorState.OBSERVED}
assert state not in {FactorState.CANDIDATE, FactorState.APPROVED}
~~~

If this assertion fails, stop and fix the lifecycle boundary before accepting any development evidence.

### Task 5: Write factual evidence and implementation notes

Files:

- Create: docs/evidence/2026-08-15-relative-funding-pressure-development-run.md
- Modify: docs/implementation-notes.md

- [ ] Step 1: Record only actual outputs.

The evidence document must include branch, commit SHA, UTC timestamp, exact command, preflight values, recovery snapshot IDs, analysis run ID, artifact paths, result status, candidate list, factor diagnostics, exclusion counts, lifecycle states, and all gate outputs.

It must explicitly state:

~~~text
network_downloads=false
canonical_repair_called=false
holdout_accessed=false
paper_trading=false
live_trading=false
~~~

If blocked, document the blocker and stop. If passed, state that candidates remain pending separate human authorization and were not evaluated on Holdout.

- [ ] Step 2: Append one dated implementation-note entry.

Mention the actual analysis run, recovered input-set hash, Funding exclusion identity, lifecycle state, and any unresolved issue. Do not rewrite historical entries or claim a performance conclusion.

- [ ] Step 3: Commit evidence separately.

~~~powershell
git add docs/evidence/2026-08-15-relative-funding-pressure-development-run.md docs/implementation-notes.md
git diff --cached --check
git commit -m "docs(research): record funding pressure development run"
~~~

### Task 6: Final gates, self-review, push, and merge

- [ ] Step 1: Run focused and full gates.

~~~powershell
uv run pytest -p no:cov tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_dual_horizon.py tests/unit/research/test_operations.py tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_local_snapshot_recovery.py -q
uv run ruff check src/bian_quant tests
uv run ruff format --check src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py tests/integration/factors/test_dual_horizon_screening.py
uv run mypy src/bian_quant
git diff --check
~~~

Then run the full suite:

~~~powershell
uv run pytest -p no:cov -q
~~~

Expected: selected tests and full tests pass with only the repository’s known skips/deselections, Ruff and mypy pass, and no new format or diff error is introduced.

- [ ] Step 2: Self-review the final diff.

~~~powershell
git diff --stat origin/main...HEAD
git diff --name-status origin/main...HEAD
git diff --check origin/main...HEAD
git merge-tree --write-tree origin/main HEAD
~~~

Reject the merge if any changed file touches prohibited modules, if Candidate/Approved appears in the registry, if Holdout artifacts exist, or if evidence contains expected values instead of actual outputs.

- [ ] Step 3: Push and merge after the audit passes.

~~~powershell
git push -u origin codex/relative-funding-pressure-development
git switch main
git pull --ff-only origin main
git merge --ff-only codex/relative-funding-pressure-development
git push origin main
~~~

The standing project instruction authorizes automatic merge after this self-review. Do not delete the feature branch unless separately requested.

## Acceptance checklist

- [ ] Development lifecycle never becomes CANDIDATE or APPROVED.
- [ ] Strict resolver uses exact recovered code identity e4fc736 and the 14,879-input hash.
- [ ] relative_funding_pressure diagnostics and exclusion evidence are present.
- [ ] Prefix-causality, Funding interval, peer coverage, zero-MAD, and missing/gapped semantics remain covered by existing tests.
- [ ] No Canonical/Raw/research snapshot rewrite occurs.
- [ ] No Holdout ledger, paper run, live run, network request, or account operation occurs.
- [ ] Actual development evidence and implementation notes are committed.
- [ ] Focused tests, full tests, Ruff, format, mypy, and diff checks pass.
- [ ] Self-review is complete before push and fast-forward merge.
