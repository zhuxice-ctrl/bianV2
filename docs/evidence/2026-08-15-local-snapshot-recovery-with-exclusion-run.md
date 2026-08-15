# Local Snapshot Recovery With Permanent Exclusion

## Run identity

- Date: 2026-08-15
- Branch: `codex/relative-funding-pressure-factor`
- Implementation commit: `dd3c2b419b2b01a00a9f87962a3e2777839cdd72`
- Recovery run: `f8fabdda-c540-4d62-8272-5412d8bb7924`
- Code SHA recorded in RunManifest: `e4fc736`
- Source mode: `local-canonical-recovery-v1`

The operation used the previously authorized local-only recovery. No network
download was performed. The permanent exclusion is exactly:

```text
funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00
```

## Recovery result

`RunManifest.status=passed` and both recovery artifacts report
`status=passed`. The canonical input set contains 14,879 eligible parents and
the following hash:

```text
canonical_input_set_sha256=fb6c5d3599dee1bf8018143df7c09a5d2f3cdb6047c091913ce9d7f24bb6f094
excluded_source_ids=[funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00]
holdout_accessed=false
```

Published main research snapshots:

```text
macro-1d-76b8d520bc5c3acd-6011562b602c
macro-4h-dcda79cbf5c2f03a-1755ee98656f
micro-1h-9b0a73ff6d512ae4-fada54591a37
micro-4h-d6e2283451721688-5ef13422a626
```

Published OI delay snapshots:

```text
5m  = metrics-oi-delay-5m-5b46848361938203-9b6f64ab05e6
10m = metrics-oi-delay-10m-d32789722e0a149f-c060125dc1ef
15m = metrics-oi-delay-15m-928dce63edecfeee-6091349312a0
```

Each main snapshot has exactly 14,879 Canonical parents. Each delay snapshot
has exactly the four main snapshot IDs as parents. The four main snapshot
`config_json` values contain the same `excluded_source_ids` identity.

The evidence artifacts are:

```text
var/artifacts/dual-horizon-popular-v1/f8fabdda-c540-4d62-8272-5412d8bb7924/data-acquisition.json
var/artifacts/dual-horizon-popular-v1/f8fabdda-c540-4d62-8272-5412d8bb7924/data-quality.json
```

## Protected-artifact audit

The immutable pre-write baseline was captured at
`%TEMP%/bianv2-tonusdt-funding-baseline.json`:

```text
plan_hash=f306aa6e0344847bd70defcb66410b9f6099572b1aa8aeeae7864982dc738cf4
baseline_files=14888
baseline_map_sha256=b701f88d25e0a68bae760d149d1e0be131501ef30c2ba1fab5cbf8b05b9dd277
```

The final map contained 14,895 files:

```text
added=7
removed=0
changed=2
```

Added paths were the four main research Parquet files and three delay-view
Parquet files listed above. The two changed paths were the expected Catalog
indexes:

```text
var/catalog-popular-v1.sqlite
var/lake/research/dual-horizon-popular-v1/delay_catalog.sqlite
```

There were no changed or removed pre-existing Canonical files, Raw files, or
pre-existing research snapshot files. The two Catalog changes only register
the newly published recovery snapshots.

## Verification gates

Executed on the target Windows workspace on 2026-08-15:

```text
pytest: 60 passed in 212.79s (0:03:32)
ruff check: All checks passed!
ruff format --check: 8 files already formatted
mypy: Success: no issues found in 97 source files
git diff --check: passed (only normal CRLF conversion warnings)
```

The selected pytest command covered source exclusions, source-plan hashing,
local availability repair, snapshot recovery, snapshot contracts, the dual
horizon pipeline, and research operations.

## Safety boundaries

```text
network_downloads=false
development_analysis_called=false
holdout_accessed=false
paper_trading=false
live_trading=false
main_merge=false
remote_push=false
```

No Funding value was imputed and no fallback API was used. The exclusion stays
visible in recovery evidence and snapshot lineage while the Funding data gap
remains missing/gapped for downstream consumers.
