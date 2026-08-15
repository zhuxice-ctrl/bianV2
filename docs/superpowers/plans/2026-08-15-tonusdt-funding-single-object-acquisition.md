# TONUSDT July Funding Single-Object Acquisition Implementation Plan

> **Superseded:** The archive returned HTTP 404. Do not execute the network
> tasks in this document. The implemented path is the data-layer permanent
> exclusion recorded in `docs/evidence/2026-08-15-tonusdt-source-exclusion-run.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` or `executing-plans` task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Under a separate, explicit user authorization, acquire exactly one public TONUSDT July 2026 Funding archive, verify and publish only its Raw and current-plan Canonical lineage, then prove the strict local preflight is `READY` without publishing research snapshots.

**Architecture:** The existing `BinanceDownloader` is the sole network adapter. It obtains the archive and its `.CHECKSUM` sidecar through `download_verified`, which writes an immutable Raw ZIP plus `RawSourceManifest` atomically. `repair_verified_local_canonical_inputs` then consumes that verified Raw through the existing Canonical/Catalog contract; `preflight_local_snapshot_recovery` remains read-only and decides whether the input set is complete. No dashboard, factor, backtest, reporting, Holdout, paper, or live module changes are permitted.

**Tech Stack:** Python 3.11, `uv`, pandas, PyArrow, Pydantic v2, SQLite, pytest, Ruff, mypy, Binance public archive + checksum endpoint.

---

## Authorization and non-negotiable scope

This document is **not** a network authorization. Aily may run only the read-only
Task 1 until the user sends this exact instruction in the same task:

```text
授权下载且仅下载 TONUSDT 2026-07 月度 Funding archive；允许写入 Raw、当前 plan Canonical 和 Catalog，完成 repair 与只读 preflight 后停止。
```

The sole allowed identity and URL are:

```text
identity_key: funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00
archive URL: https://data.binance.vision/data/futures/um/monthly/fundingRate/TONUSDT/TONUSDT-fundingRate-2026-07.zip
checksum URL: https://data.binance.vision/data/futures/um/monthly/fundingRate/TONUSDT/TONUSDT-fundingRate-2026-07.zip.CHECKSUM
```

Never call `prepare_dual_horizon`, `recover_local_dual_horizon_snapshots`,
`analyze_cataloged_dual_horizon`, `evaluate_candidate_holdout`, paper, live,
or any downloader for another source. Do not edit SQLite, Raw sidecars, old
Canonical paths, or `.superpowers/`. Do not merge `main`, delete branches, or
push without a separate user instruction.

## Files and data boundary

| Path | Change allowed | Responsibility |
|---|---:|---|
| `src/bian_quant/data/adapters/binance_archive.py` | No production edit expected | Existing checksummed public downloader |
| `src/bian_quant/data/adapters/raw.py` | No production edit expected | Immutable Raw ZIP and sidecar verification |
| `src/bian_quant/data/local_availability_repair.py` | No production edit expected | Verified Raw → current-plan Canonical/Catalog only |
| `src/bian_quant/data/local_snapshot_recovery.py` | No production edit expected | Read-only strict preflight |
| configured `raw_root/funding/TONUSDT/native/2026-07.zip` | Create only after authorization | Single verified Raw object |
| configured `canonical_root/plan=<current>/funding/TONUSDT/native/2026-07.parquet` | Create only after authorization | Single Canonical partition |
| configured `catalog_path` | One new immutable Canonical row only | Catalog registration through `DatasetCatalog.register` |
| `docs/evidence/2026-08-15-tonusdt-funding-single-object-run.md` | Create after a real run | Real command output and immutable-artifact comparison |
| `docs/implementation-notes.md` | Append after a real run | Concise factual result |

## Task 1: Read-only authorization preflight

**Files:** No file changes.

- [ ] **Step 1: Read required rules and inspect Git state**

  Run:

  ```powershell
  cd F:\bianV2
  git status --short --branch
  git log --oneline -5
  git diff --stat
  git diff --check
  Get-Content -LiteralPath docs\AILY_EXECUTION_RULES.md -Encoding UTF8 -Raw
  Get-Content -LiteralPath docs\contracts\local-data-availability-repair-contract.md -Encoding UTF8 -Raw
  Get-Content -LiteralPath docs\contracts\local-snapshot-recovery-contract.md -Encoding UTF8 -Raw
  Get-Content -LiteralPath docs\evidence\2026-08-15-local-data-availability-repair-run.md -Encoding UTF8 -Raw
  ```

  Expected: branch `codex/relative-funding-pressure-factor`; `.superpowers/`
  may be untracked and must remain untouched; strict preflight evidence shows
  exactly the TONUSDT Raw-lineage blocker.

- [ ] **Step 2: Resolve the sole source and prove the Raw object is absent**

  Run this read-only command. It must not import or instantiate a downloader.

  ```powershell
  @'
  from pathlib import Path
  from bian_quant.data.acquisition import DualHorizonAcquisition, build_source_plan_audit

  root = Path.cwd()
  config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
  identity = "funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00"
  matches = [item for item in build_source_plan_audit(config).objects if item.identity_key == identity]
  assert len(matches) == 1, matches
  source = matches[0]
  raw_path = config.raw_root / source.relative_path
  manifest_path = raw_path.with_suffix(f"{raw_path.suffix}.manifest.json")
  print(f"identity={source.identity_key}")
  print(f"url={source.url}")
  print(f"raw_path={raw_path}")
  print(f"raw_exists={raw_path.exists()}")
  print(f"manifest_exists={manifest_path.exists()}")
  '@ | uv run python -
  ```

  Expected: identity and URL exactly match this plan; both existence flags are
  `False`. If either is `True`, stop: do not delete, overwrite, repair, or
  download. Return the exact paths and status to Codex for audit.

- [ ] **Step 3: Capture a pre-write immutable baseline**

  Run this read-only command. It writes a comparison map only to `%TEMP%`, not
  the repository or any data artifact.

  ```powershell
  @'
  import hashlib, json, os
  from pathlib import Path
  from bian_quant.data.acquisition import DualHorizonAcquisition, build_source_plan_audit, source_plan_hash

  root = Path.cwd()
  config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
  plan_hash = source_plan_hash(build_source_plan_audit(config))
  targets = (config.canonical_root / f"plan={plan_hash[:16]}", config.catalog_path, config.research_root)
  files = []
  for target in targets:
      paths = (target,) if target.is_file() else (item for item in target.rglob("*") if item.is_file()) if target.exists() else ()
      for path in paths:
          files.append([str(path.resolve().relative_to(root.resolve())), hashlib.sha256(path.read_bytes()).hexdigest()])
  payload = {"plan_hash": plan_hash, "files": sorted(files)}
  output = Path(os.environ["TEMP"]) / "bianv2-tonusdt-funding-baseline.json"
  output.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")
  print(f"plan_hash={plan_hash}")
  print(f"baseline_files={len(files)}")
  print(f"baseline_map_sha256={hashlib.sha256(output.read_bytes()).hexdigest()}")
  print(f"baseline_path={output}")
  '@ | uv run python -
  ```

  Expected: a non-empty current plan hash and a baseline map. Record the four
  printed lines verbatim; do not claim byte comparison until Task 3 completes.

- [ ] **Step 4: Stop and request the explicit authorization**

  Do not proceed to Task 2 until the exact authorization in this document is
  present. The allowed response at this point is the read-only evidence only.

## Task 2: Single checksummed Raw acquisition

**Files:** Create only the single Raw ZIP and its adjacent manifest through the
existing adapter. No source-code change is expected.

- [ ] **Step 1: Reconfirm the authorization and source identity**

  Re-run Task 1 Step 2. If the user authorization text is absent, stop. If the
  Raw ZIP or sidecar now exists, stop and return the observed state; never
  overwrite or reconstruct it.

- [ ] **Step 2: Download only the authorized archive and checksum**

  Run exactly this command after authorization:

  ```powershell
  @'
  from pathlib import Path
  from bian_quant.data.acquisition import DualHorizonAcquisition, build_source_plan_audit
  from bian_quant.data.dual_horizon import BinanceDownloader
  from bian_quant.data.adapters.raw import reuse_verified_artifact

  root = Path.cwd()
  config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
  identity = "funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00"
  matches = [item for item in build_source_plan_audit(config).objects if item.identity_key == identity]
  assert len(matches) == 1, matches
  source = matches[0]
  raw_path = config.raw_root / source.relative_path
  manifest_path = raw_path.with_suffix(f"{raw_path.suffix}.manifest.json")
  assert not raw_path.exists() and not manifest_path.exists(), (raw_path, manifest_path)
  result = BinanceDownloader().acquire(source, config)
  verified = reuse_verified_artifact(raw_path, expected=source.raw_identity)
  assert result.status == "downloaded", result
  assert verified.manifest.content_sha256 == result.manifest.content_sha256
  assert verified.manifest.upstream_sha256 == result.manifest.upstream_sha256
  assert verified.manifest.byte_count == raw_path.stat().st_size
  print(f"status={result.status}")
  print(f"identity={source.identity_key}")
  print(f"archive_url={source.url}")
  print(f"raw_path={raw_path}")
  print(f"content_sha256={verified.manifest.content_sha256}")
  print(f"upstream_sha256={verified.manifest.upstream_sha256}")
  print(f"byte_count={verified.manifest.byte_count}")
  '@ | uv run python -
  ```

  Expected: `status=downloaded`, matching local and upstream SHA-256 values,
  and a positive byte count. The existing downloader fetches exactly the archive
  URL and its `.CHECKSUM` URL. If HTTP, TLS, checksum, identity, or write
  verification fails, preserve the original exception output, do not retry with
  another URL, and stop.

- [ ] **Step 3: Run existing Raw-adapter regression tests**

  ```powershell
  uv run pytest -p no:cov tests/unit/data/adapters/test_binance_archive.py tests/unit/data/adapters/test_resumable_raw.py tests/unit/data/adapters/test_binance_derivatives.py -q
  uv run ruff check src/bian_quant/data/adapters/binance_archive.py src/bian_quant/data/adapters/raw.py src/bian_quant/data/dual_horizon.py tests/unit/data/adapters/test_binance_archive.py tests/unit/data/adapters/test_resumable_raw.py tests/unit/data/adapters/test_binance_derivatives.py
  uv run ruff format --check src/bian_quant/data/adapters/binance_archive.py src/bian_quant/data/adapters/raw.py src/bian_quant/data/dual_horizon.py tests/unit/data/adapters/test_binance_archive.py tests/unit/data/adapters/test_resumable_raw.py tests/unit/data/adapters/test_binance_derivatives.py
  ```

  Expected: all selected tests, Ruff, and format checks pass. A test or lint
  failure blocks Task 3; report original output to Codex before changing code.

## Task 3: Verified Canonical publication and strict preflight

**Files:** One new current-plan Canonical Parquet partition and one immutable
Catalog row may be created by existing adapters. No research file may change.

- [ ] **Step 1: Publish only from verified local Raw**

  ```powershell
  @'
  from pathlib import Path
  from bian_quant.data.acquisition import DualHorizonAcquisition
  from bian_quant.data.local_availability_repair import repair_verified_local_canonical_inputs

  root = Path.cwd()
  config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
  result = repair_verified_local_canonical_inputs(config)
  print(f"status={result.status}")
  print(f"repaired_snapshot_ids={result.repaired_snapshot_ids}")
  print(f"blocked_reasons={result.blocked_reasons}")
  print(f"cutoff_evidence={[item.model_dump(mode='json') for item in result.cutoff_evidence]}")
  '@ | uv run python -
  ```

  Expected: `status=repaired`, exactly one repaired snapshot ID, no blockers,
  and cutoff evidence for the TONUSDT Funding source. If any other source is
  repaired, any blocker remains, or the result is non-deterministic on a second
  run, stop and provide raw output to Codex.

- [ ] **Step 2: Re-run the repair to prove idempotency**

  Run the same command again. Expected: `status=repaired`,
  `repaired_snapshot_ids=()`, and `blocked_reasons=()`. Do not modify the
  Canonical file or Catalog row between runs.

- [ ] **Step 3: Run strict read-only preflight and stop at READY**

  ```powershell
  @'
  from pathlib import Path
  from bian_quant.data.acquisition import DualHorizonAcquisition
  from bian_quant.data.local_snapshot_recovery import preflight_local_snapshot_recovery

  root = Path.cwd()
  config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
  result = preflight_local_snapshot_recovery(config)
  print(f"status={result.status}")
  print(f"inputs={len(result.inputs)}")
  print(f"parents={len(result.parent_snapshot_ids)}")
  print(f"input_set_sha256={result.input_set_sha256}")
  print(f"blocked_reasons={result.blocked_reasons}")
  '@ | uv run python -
  ```

  Expected: `status=ready`, `inputs=14880`, `parents=14880`, a non-empty
  `input_set_sha256`, and `blocked_reasons=()`. `READY` is a stop point for
  this plan: do not call snapshot recovery, development analysis, Holdout,
  paper, or live code without a new user authorization.

## Task 4: Immutability evidence, gates, and handoff

**Files:** Create `docs/evidence/2026-08-15-tonusdt-funding-single-object-run.md`;
append `docs/implementation-notes.md` only with actual results.

- [ ] **Step 1: Compare the protected artifact baseline**

  Run:

  ```powershell
  @'
  import hashlib, json, os
  from pathlib import Path
  from bian_quant.data.acquisition import DualHorizonAcquisition, build_source_plan_audit, source_plan_hash

  root = Path.cwd()
  config = DualHorizonAcquisition.from_yaml(root / "configs/experiments/popular_universe_100u.yaml")
  plan_hash = source_plan_hash(build_source_plan_audit(config))
  targets = (config.canonical_root / f"plan={plan_hash[:16]}", config.catalog_path, config.research_root)
  files = []
  for target in targets:
      paths = (target,) if target.is_file() else (item for item in target.rglob("*") if item.is_file()) if target.exists() else ()
      for path in paths:
          files.append([str(path.resolve().relative_to(root.resolve())), hashlib.sha256(path.read_bytes()).hexdigest()])
  current = {"plan_hash": plan_hash, "files": sorted(files)}
  baseline = json.loads((Path(os.environ["TEMP"]) / "bianv2-tonusdt-funding-baseline.json").read_text(encoding="utf-8"))
  before, after = dict(baseline["files"]), dict(current["files"])
  print(f"baseline_files={len(before)}")
  print(f"final_files={len(after)}")
  print(f"added={sorted(after.keys() - before.keys())}")
  print(f"removed={sorted(before.keys() - after.keys())}")
  print(f"changed={sorted(path for path, digest in after.items() if before.get(path) != digest)}")
  print(f"research_unchanged={all(path.startswith(str(config.research_root.resolve().relative_to(root.resolve()))) is False or before.get(path) == digest for path, digest in after.items())}")
  '@ | uv run python -
  ```

  Expected: exactly one new current-plan TONUSDT Funding Parquet path; the
  Catalog file is the only changed protected pre-existing file; no paths are
  removed; every `research_root` file is byte-identical. If any other path is
  added or changed, stop and do not write evidence claiming success.

- [ ] **Step 2: Write factual evidence**

  The evidence file must include the authorization text, archive/checksum URLs,
  raw local/upstream SHA-256 values, byte count, repair outputs from both runs,
  preflight output, baseline comparison, exact gate output, commit SHA, and:

  ```text
  network_downloads=true (one checksummed public archive only)
  research_snapshot_publisher_called=false
  development_analysis_called=false
  holdout_accessed=false
  paper_trading=false
  live_trading=false
  ```

  Do not record expected values as actual values. If Task 2 or 3 stopped,
  create evidence only for commands that actually ran and preserve the failure.

- [ ] **Step 3: Run final gates**

  ```powershell
  uv run pytest -p no:cov tests/unit/data/adapters/test_binance_archive.py tests/unit/data/adapters/test_resumable_raw.py tests/unit/data/adapters/test_binance_derivatives.py tests/unit/data/test_local_availability_repair.py tests/unit/data/test_local_snapshot_recovery.py tests/unit/data/test_snapshots.py tests/integration/data/test_dual_horizon_pipeline.py tests/integration/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py -q
  uv run ruff check src/bian_quant/data/acquisition.py src/bian_quant/data/adapters/binance_archive.py src/bian_quant/data/adapters/raw.py src/bian_quant/data/dual_horizon.py src/bian_quant/data/local_availability_repair.py src/bian_quant/data/local_snapshot_recovery.py tests/unit/data/test_source_plan.py tests/unit/data/test_local_availability_repair.py tests/unit/data/test_local_snapshot_recovery.py
  uv run ruff format --check src/bian_quant/data/acquisition.py src/bian_quant/data/adapters/binance_archive.py src/bian_quant/data/adapters/raw.py src/bian_quant/data/dual_horizon.py src/bian_quant/data/local_availability_repair.py src/bian_quant/data/local_snapshot_recovery.py tests/unit/data/test_source_plan.py tests/unit/data/test_local_availability_repair.py tests/unit/data/test_local_snapshot_recovery.py
  uv run mypy src/bian_quant
  git diff --check
  ```

  Expected: all commands pass. Do not report only partial success.

- [ ] **Step 4: Commit documentation only and stop**

  Do not add Raw ZIPs, sidecars, Parquet, SQLite files, `.superpowers/`, or any
  unrelated file. After all gates pass:

  ```powershell
  git add docs/evidence/2026-08-15-tonusdt-funding-single-object-run.md docs/implementation-notes.md
  git diff --cached --check
  git commit -m "docs(data): record TONUSDT funding acquisition"
  git status --short --branch
  ```

  Stop after returning the commit SHA, raw command output, exact changed-path
  list, and proof that preflight is `READY`. Do not push or merge without a
  distinct user instruction.

## Aily final handoff checklist

- [ ] Explicit single-object network authorization was present before Task 2.
- [ ] Only the TONUSDT July 2026 Funding archive and `.CHECKSUM` URL were read.
- [ ] `download_verified` produced a verified Raw ZIP plus immutable sidecar.
- [ ] No Raw/sidecar/Catalog/Canonical artifact was manually edited or overwritten.
- [ ] Repair produced exactly one new Canonical snapshot and was idempotent.
- [ ] Strict preflight is `READY` with 14,880 inputs and no blockers.
- [ ] No recovery publisher, analysis, Holdout, paper, live, main merge, branch deletion, or unapproved push occurred.
- [ ] Evidence contains only actual outputs and the baseline comparison allows only the one Funding Canonical path plus the Catalog update.
- [ ] Pytest, Ruff, format, mypy, and `git diff --check` passed before the documentation commit.
