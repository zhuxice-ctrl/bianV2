# Relative Funding Pressure Development Run — 2026-08-16

This document records the single audited development-only analysis result for `relative_funding_pressure@1.0.0` on the `dual-horizon-popular-v1` catalog. It is a factual evidence record only; no new analysis, recovery, data write, Holdout access, or trading action was performed while producing this document.

## Run identity

```text
analysis run ID: 9b0831fd-828c-40cf-9be8-5c21d999ab71
analysis code SHA: 9f201be9eeecdd1aa09da9d0f73251fd6b5e19e9
snapshot code SHA: e4fc736
input-set SHA-256: fb6c5d3599dee1bf8018143df7c09a5d2f3cdb6047c091913ce9d7f24bb6f094
permanent exclusion: funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00
development window: 2024-07-01T00:00:00+00:00 through 2026-01-01T00:00:00+00:00 (end exclusive)
```

The two code identities are intentionally separated: `analysis code SHA` is the version of the code that actually executed the analysis (the current HEAD at run time, `9f201be…`); `snapshot code SHA` (`e4fc736`) is the immutable identity used strictly to match the recovery snapshots and collected evidence. Development products, the RunManifest, and the first factor registration never disguise new code as old recovery code.

## Snapshots

Four main snapshots:

```text
macro-1d-76b8d520bc5c3acd-6011562b602c
macro-4h-dcda79cbf5c2f03a-1755ee98656f
micro-1h-9b0a73ff6d512ae4-fada54591a37
micro-4h-d6e2283451721688-5ef13422a626
```

Three OI-delay snapshots:

```text
metrics-oi-delay-5m-5b46848361938203-9b6f64ab05e6
metrics-oi-delay-10m-d32789722e0a149f-c060125dc1ef
metrics-oi-delay-15m-928dce63edecfeee-6091349312a0
```

## Lifecycle outcome

- `status` = `passed`
- `candidate_factor_ids` = `[]`
- `holdout_accessed` = `false`
- `relative_funding_pressure@1.0.0` lifecycle state = `observed`

The factor remains `observed`. It was not promoted to `CANDIDATE` or `APPROVED`. No Holdout ledger was created or accessed. No paper-trading or live-trading claim is made.

## Measured factor result

```text
eligible_slice_count: 103
direction_consistent_slice_count: 53
direction_agreement: 0.5145631067961165
bh_survivors: []
asset_coverage: []
target_direction: -1.0
one_hour_direction: -1.0
final_fold_incremental_return_5bps: 6.273401484413655e-05
final_fold_incremental_return_10bps: 6.142853181541593e-05
```

No BH survivors and no supported assets were produced. The factor failed exactly these six development gates:

```text
BH_SURVIVING_SLICES_LT_2
INDEPENDENT_SLICES_LT_2
DIRECTION_AGREEMENT_LT_60PCT
ASSETS_LT_2
ASSET_SUPPORT_CONCENTRATION_GT_50PCT
REGIME_SUPPORT_CONCENTRATION_GT_50PCT
```

## Missing-value exclusion reason

`ZERO_CROSS_SECTIONAL_MAD=5328` is recorded as a missing-value reason, never a zero factor value. No missing value was imputed or converted to zero.

The independently verified cause: after popular-universe membership filtering, 444 timestamps had 12 valid assets. At least 7 of those assets sat at the `0.0001` median despite non-identical individual rates, so the cross-sectional median absolute deviation was zero and the conservative exclusion was correct. This is a real data phenomenon, not data duplication.

## Artifact packet

The packet at `var/artifacts/dual-horizon-popular-v1/9b0831fd-828c-40cf-9be8-5c21d999ab71/` contains exactly these seven files:

```text
data-acquisition.json
data-quality.json
macro-regime.json
macro-regime.md
factor-screening.json
factor-screening.md
decision-summary.md
```

The lifecycle artifact at `var/artifacts/dual-horizon-popular-v1/factor-stages/9b0831fd-828c-40cf-9be8-5c21d999ab71.lifecycle.json` has the same run ID, `states`, and `gates` as `factor-screening.json`.

## Safety boundary

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

## Verification gates

All gates were run in `F:\bianV2` on branch `codex/relative-funding-pressure-development` after the two documentation files were written. Outputs are preserved verbatim.

### Focused regression suite

Command: `uv run pytest -p no:cov tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_dual_horizon.py tests/unit/research/test_operations.py tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_local_snapshot_recovery.py -q`

```
.....................................................................    [100%]
69 passed in 207.75s (0:03:27)
```

exitCode=0. PASS.

### Ruff check

Command: `uv run ruff check src/bian_quant tests`

```
All checks passed!
```

exitCode=0. PASS.

### Ruff format --check

Command: `uv run ruff format --check src/bian_quant tests`

```
2 files would be reformatted, 171 files already formatted
```

exitCode=1. FAIL — two pre-existing source files (`src/bian_quant/data/archive_availability.py`, `tests/unit/data/test_archive_availability.py`) require reformatting. These files were not created or modified by Batch 4; Batch 4 only wrote the two permitted Markdown documents. The formatting issue predates this batch.

### mypy

Command: `uv run mypy src/bian_quant`

```
Success: no issues found in 97 source files
```

exitCode=0. PASS.

### Full test suite

Command: `uv run pytest -p no:cov -q`

```
..sssssss............................................................... [ 13%]
........................................................................ [ 27%]
........................................................................ [ 40%]
........................................................................ [ 54%]
........................................................................ [ 68%]
........................................................................ [ 81%]
........................................................................ [ 95%]
.......................                                                  [100%]
520 passed, 7 skipped, 7 deselected in 333.74s (0:05:33)
```

exitCode=0. PASS.

### Protected inputs and Holdout boundary

Command: protected-inputs check (reads `bianv2-rfp-batch3-protected.json` baseline from TEMP)

```
protected_changed=[]
protected_missing=[]
holdout_ledgers=absent
```

exitCode=0. PASS.

### git diff --check

`git diff --check` could not be executed via the MCP bridge (blocked by the git-confirmation gate). An equivalent whitespace scan of both documentation files was performed instead: no trailing whitespace, no conflict markers.

```
whitespace_check=clean
files_checked=2
```
