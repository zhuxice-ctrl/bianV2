# Relative Funding Pressure Development — Aily Batch 3 Execution Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans task-by-task. Stop after the Batch 3 handoff; do not write repository evidence, commit, push, merge, access Holdout, or start any later task.

**Goal:** Run exactly one real development-only cataloged analysis from the validated recovered snapshots, then prove the artifact uses the current analysis code identity while retaining the immutable snapshot identity e4fc736.

**Architecture:** Batch 3 calls analyze_cataloged_dual_horizon once with two identities: the current Git HEAD as code_sha for the executed analysis and e4fc736 as snapshot_code_sha for strict snapshot/source-evidence resolution. The only permitted writes are the existing analysis RunManifest, factor registry, factor-stage artifact, and decision packet below var/artifacts. No Raw, Canonical, Catalog, or research snapshot writer is authorized.

**Tech Stack:** Python 3.11, uv, pandas, SQLite, immutable research snapshots, pytest not required because no source code is changed.

---

## Mandatory boundaries

Read completely before acting:

~~~text
docs/AILY_EXECUTION_RULES.md
docs/superpowers/plans/2026-08-15-relative-funding-pressure-development.md
docs/contracts/local-snapshot-recovery-contract.md
docs/evidence/2026-08-15-local-snapshot-recovery-with-exclusion-run.md
~~~

Stay on codex/relative-funding-pressure-development.

Do not modify, format, stage, commit, push, merge, delete, or clean repository files. Do not touch .superpowers/.

Do not call:

~~~text
recover_local_dual_horizon_snapshots
repair_verified_local_canonical_inputs
evaluate_candidate_holdout
run_small_account_backtest
BinanceDownloader or any downloader
paper or live commands
any API, network, account, order, or WebSocket command
~~~

Do not call analyze_cataloged_dual_horizon more than once. Its one permitted invocation is in Task 2.

## Task 1: Establish the protected baseline

- [ ] Step 1: Verify branch and safety state.

~~~powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git status --short --branch
git log --oneline -5
git diff --stat
git diff --check
~~~

Expected: codex/relative-funding-pressure-development; cfb2eb6, dcd0bb3, and 50d3c21 are visible; only .superpowers/ is untracked. If any tracked file is modified, stop and report.

- [ ] Step 2: Capture SHA-256 for immutable research inputs and the primary Catalog.

This writes only a temporary JSON file under the operating-system TEMP directory, never the repository.

~~~powershell
@'
import hashlib
import json
import os
from pathlib import Path
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.research.operations import resolve_dual_horizon_snapshots

root = Path.cwd()
config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
snapshots = resolve_dual_horizon_snapshots(config, code_sha="e4fc736")
paths = [config.catalog_path]
paths.extend(entry.path for entry in snapshots.entries.values())
paths.extend(entry.path for entry in snapshots.oi_delay_entries.values())
payload = {
    "paths": {
        str(path.resolve().relative_to(root.resolve())): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(paths)
    }
}
output = Path(os.environ["TEMP"]) / "bianv2-rfp-batch3-protected.json"
output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
print(f"baseline_path={output}")
print(f"protected_file_count={len(payload['paths'])}")
print(f"protected_map_sha256={hashlib.sha256(output.read_bytes()).hexdigest()}")
'@ | uv run python -
~~~

Expected: protected_file_count=8 (primary Catalog plus 4 main and 3 delay snapshots). Preserve all three output lines for Codex.

- [ ] Step 3: Verify Holdout remains absent.

~~~powershell
if (Test-Path var/artifacts/dual-horizon-popular-v1/holdout-access.sqlite) { throw "artifact Holdout ledger exists" }
if (Test-Path var/lake/research/dual-horizon-popular-v1/holdout-access.sqlite) { throw "research Holdout ledger exists" }
~~~

Expected: no output and exit code 0.

## Task 2: Run one real development-only analysis

- [ ] Step 1: Invoke the analysis once with separate execution and snapshot identities.

~~~powershell
@'
import json
import os
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
output = Path(os.environ["TEMP"]) / "bianv2-rfp-batch3-result.json"
output.write_text(
    json.dumps(
        {
            "analysis_code_sha": analysis_code_sha,
            "artifact_dir": str(result.artifact_dir),
            "run_id": result.run_id,
            "status": result.status,
        },
        sort_keys=True,
    ),
    encoding="utf-8",
)
print(f"analysis_code_sha={analysis_code_sha}")
print("snapshot_code_sha=e4fc736")
print(f"run_id={result.run_id}")
print(f"status={result.status}")
print(f"snapshot_ids={result.snapshot_ids}")
print(f"candidate_factor_ids={result.candidate_factor_ids}")
print(f"artifact_dir={result.artifact_dir}")
print(f"error_code={result.error_code}")
print(f"result_path={output}")
'@ | uv run python -
~~~

This is the only permitted analysis invocation. Preserve complete raw output. A blocked result is valid; do not retry, recover, download, or alter data.

## Task 3: Audit the single analysis result

- [ ] Step 1: Inspect artifact and identity facts.

Read the temporary Task 2 result file. It is outside the repository and is the
only handoff input to this audit command.

~~~powershell
@'
import json
import os
import sqlite3
from pathlib import Path
from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorState

result = json.loads(
    (Path(os.environ["TEMP"]) / "bianv2-rfp-batch3-result.json").read_text(encoding="utf-8")
)
run_id = result["run_id"]
artifact_dir = Path(result["artifact_dir"])
analysis_code_sha = result["analysis_code_sha"]
snapshot_code_sha = "e4fc736"

with sqlite3.connect("var/experiments-popular-v1.sqlite") as connection:
    row = connection.execute(
        "SELECT status, code_sha, config_json FROM runs WHERE run_id=?",
        (run_id,),
    ).fetchone()
assert row is not None
status, recorded_code_sha, config_json = row
run_config = json.loads(config_json)
assert recorded_code_sha == analysis_code_sha
assert run_config["snapshot_code_sha"] == snapshot_code_sha
print(f"run_manifest_status={status}")
print(f"run_manifest_code_sha={recorded_code_sha}")
print(f"run_manifest_snapshot_code_sha={run_config['snapshot_code_sha']}")

if status == "passed":
    screening_path = artifact_dir / "factor-screening.json"
    payload = json.loads(screening_path.read_text(encoding="utf-8"))
    assert payload["code_sha"] == analysis_code_sha
    assert "relative_funding_pressure" in payload["factor_diagnostics"]
    assert "relative_funding_pressure" in payload["planned_lifecycle_states"]
    state = payload["planned_lifecycle_states"]["relative_funding_pressure"]
    assert state in {"observed", "researching"}
    diagnostics = payload["factor_diagnostics"]["relative_funding_pressure"]
    assert "exclusion_evidence" in diagnostics
    with FactorRegistry("var/factors-popular-v1.sqlite") as registry:
        registry_state = registry.state("relative_funding_pressure", "1.0.0")
    assert registry_state in {FactorState.RESEARCHING, FactorState.OBSERVED}
    assert registry_state not in {FactorState.CANDIDATE, FactorState.APPROVED}
    print(f"factor_screening_code_sha={payload['code_sha']}")
    print(f"relative_funding_pressure_state={state}")
    print(f"registry_state={registry_state.value}")
    print(f"candidate_factor_ids={payload['candidate_factor_ids']}")
    print(f"relative_exclusion_evidence={diagnostics['exclusion_evidence']}")
else:
    print("analysis_blocked=true")
    print(f"blocked_artifacts={sorted(path.name for path in artifact_dir.iterdir())}")
'@ | uv run python -
~~~

Expected for both passed and blocked outcomes: RunManifest code SHA equals the Task 2 current HEAD; snapshot_code_sha equals e4fc736. A passed outcome must satisfy every factor and registry assertion. A blocked outcome must not be retried.

- [ ] Step 2: Compare protected inputs against the pre-analysis baseline.

~~~powershell
@'
import hashlib
import json
import os
from pathlib import Path

root = Path.cwd().resolve()
baseline_path = Path(os.environ["TEMP"]) / "bianv2-rfp-batch3-protected.json"
baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["paths"]
current = {}
for relative_path in sorted(baseline):
    path = root / relative_path
    current[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
changed = sorted(path for path, digest in current.items() if baseline[path] != digest)
missing = sorted(path for path in baseline if not (root / path).is_file())
print(f"protected_changed={changed}")
print(f"protected_missing={missing}")
assert not changed
assert not missing
'@ | uv run python -
~~~

Expected:

~~~text
protected_changed=[]
protected_missing=[]
~~~

- [ ] Step 3: Verify no Holdout ledger was created and inspect final Git state.

~~~powershell
if (Test-Path var/artifacts/dual-horizon-popular-v1/holdout-access.sqlite) { throw "artifact Holdout ledger created" }
if (Test-Path var/lake/research/dual-horizon-popular-v1/holdout-access.sqlite) { throw "research Holdout ledger created" }
git status --short --branch
git diff --check
~~~

Expected: both Holdout paths absent; Git shows only .superpowers/ untracked; diff check has no output.

## Mandatory stop and report

Stop after Task 3. Do not write repository evidence, commit, push, merge, or run any more analysis.

Send Codex one report containing:

~~~text
1. Task 1 status/log, protected baseline output, and Holdout check output.
2. Complete Task 2 raw output, including both SHA identities and run ID.
3. Complete Task 3 identity/audit output, including candidate list or blocker artifacts.
4. Protected baseline comparison output.
5. Final Git status and git diff --check output.
6. Explicit statement that no recovery, Canonical/Raw/Catalog/research snapshot write, Holdout, paper, live, network, push, merge, or second analysis invocation occurred.
~~~

Codex will audit all artifacts, verify the actual outcome, repair any defect, and then issue the evidence/final-gates batch.
