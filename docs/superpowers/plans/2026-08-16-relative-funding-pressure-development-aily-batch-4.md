# Relative Funding Pressure Development Evidence and Final Gates — Aily Batch 4

> **For agentic workers:** REQUIRED SUB-SKILL: Use `executing-plans` task-by-task. Stop after the Batch 4 handoff; do not push, merge, access Holdout, start another analysis, or perform recovery/data writes.

**Goal:** Record the single audited development-only result for `relative_funding_pressure@1.0.0`, prove it remains observed rather than a Candidate, and complete all gates before Codex reviews integration.

**Architecture:** The batch only reads existing run `9b0831fd-828c-40cf-9be8-5c21d999ab71` and its lifecycle evidence. It adds a factual evidence document and implementation-note entry; it never recomputes analysis or mutates Raw, Canonical, Catalog, research snapshots, registries, or artifacts.

**Tech Stack:** Python 3.11, uv, pytest, Ruff, mypy, Git, UTF-8 Markdown and JSON.

---

## Mandatory boundaries

Read completely before acting:

```text
docs/AILY_EXECUTION_RULES.md
docs/superpowers/plans/2026-08-15-relative-funding-pressure-development.md
docs/superpowers/plans/2026-08-16-relative-funding-pressure-development-aily-batch-3.md
docs/contracts/local-snapshot-recovery-contract.md
docs/evidence/2026-08-15-local-snapshot-recovery-with-exclusion-run.md
```

Work on `codex/relative-funding-pressure-development` only. Preserve the user-owned untracked `.superpowers/` directory. Use UTF-8 explicitly when reading or editing Markdown.

The only permitted repository edits are:

```text
docs/evidence/2026-08-16-relative-funding-pressure-development-run.md
docs/implementation-notes.md
```

Never call, retry, or wrap `analyze_cataloged_dual_horizon`, `recover_local_dual_horizon_snapshots`, `repair_verified_local_canonical_inputs`, `evaluate_candidate_holdout`, `run_small_account_backtest`, a downloader, a paper/live command, or any API/network/account/order/WebSocket command. Do not write any `var/` data, stage/commit any file except the two permitted documents, push, merge, delete, or clean files.

The evidence must preserve these immutable facts:

```text
analysis run ID: 9b0831fd-828c-40cf-9be8-5c21d999ab71
analysis code SHA: 9f201be9eeecdd1aa09da9d0f73251fd6b5e19e9
snapshot code SHA: e4fc736
input-set SHA-256: fb6c5d3599dee1bf8018143df7c09a5d2f3cdb6047c091913ce9d7f24bb6f094
permanent exclusion: funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00
development window: 2024-07-01T00:00:00+00:00 through 2026-01-01T00:00:00+00:00 (end exclusive)
```

The four main snapshots are `macro-1d-76b8d520bc5c3acd-6011562b602c`, `macro-4h-dcda79cbf5c2f03a-1755ee98656f`, `micro-1h-9b0a73ff6d512ae4-fada54591a37`, and `micro-4h-d6e2283451721688-5ef13422a626`. The OI-delay snapshots are `metrics-oi-delay-5m-5b46848361938203-9b6f64ab05e6`, `metrics-oi-delay-10m-d32789722e0a149f-c060125dc1ef`, and `metrics-oi-delay-15m-928dce63edecfeee-6091349312a0`.

### Task 1: Establish the final documentation baseline

**Files:** No repository file changes.

- [ ] **Step 1: Verify branch, prior commits, and the clean tracked worktree.**

```powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git status --short --branch
git log --oneline -8
git diff --stat
git diff --check
```

Expected: `codex/relative-funding-pressure-development`; the audit-plan correction plus `9f201be`, `cfb2eb6`, `dcd0bb3`, and `50d3c21` are visible; only `.superpowers/` is untracked; no tracked file is modified. Otherwise stop and report.

- [ ] **Step 2: Inspect the existing decision packet and lifecycle artifact read-only.**

```powershell
@'
from pathlib import Path
import json
import sqlite3
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorState
from bian_quant.reporting.decision import REQUIRED_ARTIFACTS

root = Path.cwd()
run_id = "9b0831fd-828c-40cf-9be8-5c21d999ab71"
run_dir = root / "var" / "artifacts" / "dual-horizon-popular-v1" / run_id
stage = root / "var" / "artifacts" / "dual-horizon-popular-v1" / "factor-stages" / f"{run_id}.lifecycle.json"
assert {p.name for p in run_dir.iterdir() if p.is_file()} == REQUIRED_ARTIFACTS
screening = json.loads((run_dir / "factor-screening.json").read_text(encoding="utf-8"))
lifecycle = json.loads(stage.read_text(encoding="utf-8"))
assert lifecycle["run_id"] == run_id
assert lifecycle["states"] == screening["planned_lifecycle_states"]
assert lifecycle["gates"] == screening["gates"]
assert screening["holdout_accessed"] is False
assert screening["candidate_factor_ids"] == []
diagnostics = screening["factor_diagnostics"]["relative_funding_pressure"]
assert diagnostics["exclusion_evidence"] == {"relative_funding_pressure_exclusion_reason": {"ZERO_CROSS_SECTIONAL_MAD": 5328}}
assert screening["planned_lifecycle_states"]["relative_funding_pressure"] == "observed"
with sqlite3.connect(root / "var" / "experiments-popular-v1.sqlite") as con:
    status, code_sha, config_json = con.execute("SELECT status, code_sha, config_json FROM runs WHERE run_id=?", (run_id,)).fetchone()
assert status == "passed"
assert code_sha == "9f201be9eeecdd1aa09da9d0f73251fd6b5e19e9"
assert json.loads(config_json)["snapshot_code_sha"] == "e4fc736"
with FactorRegistry(root / "var" / "factors-popular-v1.sqlite") as registry:
    state = registry.state("relative_funding_pressure", "1.0.0")
assert state is FactorState.OBSERVED
print("research_decision_packet=verified")
print(f"lifecycle_artifact={stage.relative_to(root)}")
print(f"run_status={status}")
print(f"relative_funding_pressure_state={state.value}")
print(f"candidate_factor_ids={screening['candidate_factor_ids']}")
print(f"relative_exclusion_evidence={diagnostics['exclusion_evidence']}")
'@ | uv run python -
```

Expected: all assertions pass, with state `observed`. This is artifact inspection only, not a new analysis.

- [ ] **Step 3: Recheck the no-Holdout filesystem boundary.**

```powershell
if (Test-Path var/artifacts/dual-horizon-popular-v1/holdout-access.sqlite) { throw "artifact Holdout ledger exists" }
if (Test-Path var/lake/research/dual-horizon-popular-v1/holdout-access.sqlite) { throw "research Holdout ledger exists" }
Write-Output "holdout_ledgers=absent"
```

Expected: `holdout_ledgers=absent`.

### Task 2: Record factual development evidence

**Files:**

- Create: `docs/evidence/2026-08-16-relative-funding-pressure-development-run.md`
- Modify: `docs/implementation-notes.md`

- [ ] **Step 1: Create the UTF-8 evidence document with `apply_patch`.**

The document must contain these facts exactly: the Task 1 run identity; all four main and three delay snapshots; the permanent TONUSDT exclusion; `status=passed`, `candidate_factor_ids=[]`, `holdout_accessed=false`; `relative_funding_pressure@1.0.0` lifecycle state `observed`; and no Candidate/Approved/paper/live claim.

Record this complete measured factor result: 103 eligible slices, 53 direction-consistent slices, direction agreement `0.5145631067961165`, no BH survivors, no supported assets, target direction `-1.0`, one-hour direction `-1.0`, final-fold incremental returns `6.273401484413655e-05` at 5 bps and `6.142853181541593e-05` at 10 bps. State that it failed exactly these six development gates:

```text
BH_SURVIVING_SLICES_LT_2
INDEPENDENT_SLICES_LT_2
DIRECTION_AGREEMENT_LT_60PCT
ASSETS_LT_2
ASSET_SUPPORT_CONCENTRATION_GT_50PCT
REGIME_SUPPORT_CONCENTRATION_GT_50PCT
```

Record `ZERO_CROSS_SECTIONAL_MAD=5328` as a missing-value reason, never a zero factor value. Explain the independently verified cause: after popular-universe membership filtering, 444 timestamps had 12 valid assets, at least 7 assets at the `0.0001` median despite non-identical rates, so median absolute deviation was zero and the conservative exclusion was correct.

State that the packet at `var/artifacts/dual-horizon-popular-v1/9b0831fd-828c-40cf-9be8-5c21d999ab71/` contains exactly `data-acquisition.json`, `data-quality.json`, `macro-regime.json`, `macro-regime.md`, `factor-screening.json`, `factor-screening.md`, and `decision-summary.md`. State that `var/artifacts/dual-horizon-popular-v1/factor-stages/9b0831fd-828c-40cf-9be8-5c21d999ab71.lifecycle.json` has the same run ID, states, and gates as `factor-screening.json`.

End with this safety block:

```text
network_downloads=false
canonical_repair_called=false
research_snapshot_write=false
holdout_accessed=false
paper_trading=false
live_trading=false
remote_push=false
main_merge=false
second_analysis_invocation=false
```

Create a `## Verification gates` heading and, only after Task 3 succeeds, append each command's exact stdout and exit status below it. Do not call a gate passed until it has actually completed.

- [ ] **Step 2: Append the measured outcome with `apply_patch`.**

Append a dated `## 2026-08-16 — Relative Funding Pressure development evidence` entry to `docs/implementation-notes.md`. It must state: the single run ID and both code identities; the 14,879-input hash and TONUSDT exclusion; observed state and zero candidates with no Holdout; all six gates failed; and that `ZERO_CROSS_SECTIONAL_MAD=5328` means missing because 444 valid 12-asset timestamp groups had a majority at the `0.0001` median, with no imputation or zero conversion. Do not change historical entries.

- [ ] **Step 3: Review factual documentation before gates.**

```powershell
git diff --check
git diff -- docs/evidence/2026-08-16-relative-funding-pressure-development-run.md docs/implementation-notes.md
rg -n "candidate|approved|Holdout|ZERO_CROSS_SECTIONAL_MAD|5328|9b0831fd|e4fc736|9f201be" docs/evidence/2026-08-16-relative-funding-pressure-development-run.md docs/implementation-notes.md
```

Expected: no whitespace errors and all required facts are present. Correct only the two documents if a fact differs from the immutable artifact.

### Task 3: Run final gates and commit documentation

**Files:** The two Task 2 documentation files only.

- [ ] **Step 1: Run the focused regression suite.**

```powershell
uv run pytest -p no:cov tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_dual_horizon.py tests/unit/research/test_operations.py tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_local_snapshot_recovery.py -q
```

Expected: all selected tests pass. Preserve exact output; a failure is a stop condition and does not authorize changing code in this batch.

- [ ] **Step 2: Run static and formatting gates.**

```powershell
uv run ruff check src/bian_quant tests
uv run ruff format --check src/bian_quant tests
uv run mypy src/bian_quant
git diff --check
```

Expected: all pass. Preserve each complete output and append it verbatim to the evidence document's Verification gates section with `apply_patch`.

- [ ] **Step 3: Run the full test suite once.**

```powershell
uv run pytest -p no:cov -q
```

Expected: full suite passes, allowing only its already-reported skips/deselections. Preserve and append its exact summary. Do not retry analysis if it fails.

- [ ] **Step 4: Verify protected inputs and safety after all gates.**

```powershell
@'
from pathlib import Path
import hashlib
import json
import os

root = Path.cwd().resolve()
baseline = json.loads((Path(os.environ["TEMP"]) / "bianv2-rfp-batch3-protected.json").read_text(encoding="utf-8"))["paths"]
current = {relative: hashlib.sha256((root / relative).read_bytes()).hexdigest() for relative in sorted(baseline)}
changed = sorted(path for path, digest in current.items() if baseline[path] != digest)
missing = sorted(path for path in baseline if not (root / path).is_file())
assert not changed
assert not missing
assert not (root / "var/artifacts/dual-horizon-popular-v1/holdout-access.sqlite").exists()
assert not (root / "var/lake/research/dual-horizon-popular-v1/holdout-access.sqlite").exists()
print("protected_changed=[]")
print("protected_missing=[]")
print("holdout_ledgers=absent")
'@ | uv run python -
```

Expected: all three printed lines. If the earlier temporary baseline is unavailable, stop; do not recreate it after the analysis.

- [ ] **Step 5: Commit the two factual documents, then stop.**

```powershell
git add docs/evidence/2026-08-16-relative-funding-pressure-development-run.md docs/implementation-notes.md
git diff --cached --check
git diff --cached --name-only
git commit -m "docs(research): record funding pressure development run"
git status --short --branch
```

Expected: exactly the two documentation files are staged and committed; final status shows only `.superpowers/` untracked. Do not push or merge.

## Mandatory stop and report

Stop after Task 3 and provide Codex: initial branch/status; Task 1 audit output; the documentation diff; all focused/full pytest, Ruff, format, mypy, and diff-check outputs; protected-input/Holdout output; commit SHA and final Git status; and a statement that no second analysis, recovery, data/snapshot/registry write, Holdout access, paper/live action, network request, push, or merge occurred. Codex will audit before any integration action.
