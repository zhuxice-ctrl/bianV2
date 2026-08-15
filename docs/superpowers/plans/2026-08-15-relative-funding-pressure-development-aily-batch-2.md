# Relative Funding Pressure Development — Aily Batch 2 Read-Only Preflight

> **For agentic workers:** REQUIRED SUB-SKILL: Use executing-plans task-by-task. Stop after the Batch 2 handoff; do not start real development analysis unless Codex sends Batch 3.

**Goal:** Independently prove that the recovered local snapshots, exclusion lineage, and strict resolver are ready for development-only screening without creating, updating, downloading, or registering anything.

**Architecture:** This batch calls only read-only preflight and strict resolution APIs. It uses the recovery identity e4fc736 because the four local research snapshots and their passed acquisition evidence were created under that identity. The analysis function is deliberately not called in this batch.

**Tech Stack:** Python 3.11, uv, SQLite read-only Catalog access, pytest not required because no source is modified.

---

## Mandatory rules

Read these files before any command:

~~~text
docs/AILY_EXECUTION_RULES.md
docs/superpowers/plans/2026-08-15-relative-funding-pressure-development.md
docs/contracts/local-snapshot-recovery-contract.md
docs/evidence/2026-08-15-local-snapshot-recovery-with-exclusion-run.md
~~~

Remain on:

~~~text
codex/relative-funding-pressure-development
~~~

Do not edit, stage, commit, push, merge, delete, format, or clean any file in this batch. Do not touch .superpowers/.

Do not run any of these:

~~~text
analyze_cataloged_dual_horizon
recover_local_dual_horizon_snapshots
repair_verified_local_canonical_inputs
evaluate_candidate_holdout
run_small_account_backtest
any downloader, paper, live, or network command
~~~

## Task 1: Verify Git and safety baseline

- [ ] Step 1: Inspect the branch and worktree.

~~~powershell
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
git status --short --branch
git log --oneline -4
git diff --stat
git diff --check
~~~

Expected: branch is codex/relative-funding-pressure-development; commits dcd0bb3 and 50d3c21 are visible; only .superpowers/ is untracked. If any tracked file is modified, stop and report before continuing.

- [ ] Step 2: Verify no Holdout ledger exists.

~~~powershell
if (Test-Path var/artifacts/dual-horizon-popular-v1/holdout-access.sqlite) { throw "artifact Holdout ledger exists" }
if (Test-Path var/lake/research/dual-horizon-popular-v1/holdout-access.sqlite) { throw "research Holdout ledger exists" }
~~~

Expected: no output and exit code 0.

## Task 2: Execute strict read-only recovery preflight

- [ ] Step 1: Run the exact preflight and strict resolver command.

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
print(f"blocked_reasons={preflight.blocked_reasons}")
print(f"snapshot_ids={snapshots.snapshot_ids}")
print(f"delay_minutes={sorted(snapshots.oi_delay_entries)}")
'@ | uv run python -
~~~

Expected exact preflight values:

~~~text
preflight_status=ready
inputs=14879
parents=14879
input_set_sha256=fb6c5d3599dee1bf8018143df7c09a5d2f3cdb6047c091913ce9d7f24bb6f094
excluded_source_ids=('funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00',)
blocked_reasons=()
delay_minutes=[5, 10, 15]
~~~

The four snapshot IDs must exactly match the recovery evidence document. If preflight or resolver raises, stop and return the complete traceback; do not invoke recovery or analysis.

## Task 3: Audit lineage and exclusion propagation without writing

- [ ] Step 1: Read the four main snapshot manifests and all delay manifests from the Catalog.

~~~powershell
@'
import json
from pathlib import Path
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.data.catalog import DatasetCatalog
from bian_quant.research.operations import resolve_dual_horizon_snapshots

root = Path.cwd()
config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
snapshots = resolve_dual_horizon_snapshots(config, code_sha="e4fc736")
catalog = DatasetCatalog(config.catalog_path)
excluded = ["funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00"]
main_ids = set(snapshots.snapshot_ids)
for name, entry in sorted(snapshots.entries.items()):
    config_json = json.loads(entry.manifest.config_json)
    assert len(entry.manifest.parent_snapshot_ids) == 14879, name
    assert config_json["excluded_source_ids"] == excluded, name
    print(f"main={name}|snapshot={entry.manifest.snapshot_id}|parents={len(entry.manifest.parent_snapshot_ids)}")
for delay, entry in sorted(snapshots.oi_delay_entries.items()):
    assert set(entry.manifest.parent_snapshot_ids) == main_ids, delay
    print(f"delay={delay}|snapshot={entry.manifest.snapshot_id}|parents={len(entry.manifest.parent_snapshot_ids)}")
print("lineage=verified")
'@ | uv run python -
~~~

Expected: four main lines with parents=14879, three delay lines with parents=4, then lineage=verified.

- [ ] Step 2: Verify the passed source evidence contains the same exclusion.

~~~powershell
@'
import json
from pathlib import Path

run_id = "f8fabdda-c540-4d62-8272-5412d8bb7924"
root = Path.cwd()
run_dir = root / "var/artifacts/dual-horizon-popular-v1" / run_id
expected = ["funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00"]
for name in ("data-acquisition.json", "data-quality.json"):
    payload = json.loads((run_dir / name).read_text(encoding="utf-8"))
    assert payload["status"] == "passed", name
    assert payload["excluded_source_ids"] == expected, name
    assert len(payload["canonical_input_snapshot_ids"]) == 14879, name
    assert payload["holdout_accessed"] is False, name
    print(f"{name}=passed|inputs={len(payload['canonical_input_snapshot_ids'])}|excluded={payload['excluded_source_ids']}")
'@ | uv run python -
~~~

Expected: two passed lines, each with inputs=14879 and the one TONUSDT exclusion identity.

## Mandatory stop and report

Stop after Task 3. Do not run real analysis.

Send Codex a report containing:

~~~text
1. Complete Task 1 Git status and log output.
2. Complete Task 2 output or traceback.
3. Complete Task 3 lineage and source-evidence output or traceback.
4. A statement that no source file, artifact, Catalog, snapshot, registry, Raw file, Holdout ledger, network resource, remote branch, or main branch was written.
5. Final git status --short --branch output.
~~~

Codex will audit the evidence. Only after the audit passes will Codex send Batch 3, which is the first batch allowed to run real development-only analysis.
