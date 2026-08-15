# Local Data Availability Repair — Actual Offline Run

## Run identity

| Item | Actual value |
|---|---|
| Branch | `codex/relative-funding-pressure-factor` |
| Config | `configs/experiments/popular_universe_100u.yaml` |
| Cutoff | `2026-07-26T19:59:59.999000+00:00` |
| Repair adapter | `38b7bce` |
| Causal Canonical-input fix | `ea1ffe6` |

## Cause and correction

The initial offline repair correctly rejected all sixteen missing daily 1d
OHLCV objects: their only bar is available at `2026-07-26T23:59:59.999Z`,
after the configured cutoff. Publishing them would have violated the Canonical
time contract.

The correction keeps the Raw acquisition plan and its hash stable, while
`canonical_input_sources(...)` excludes only an unclosed daily 1d archive from
Canonical repair and strict preflight. Intraday daily archives remain eligible
because they contain earlier closed bars. This avoids both future-data leakage
and a needless re-namespacing of the existing 14,879 Canonical inputs.

## Actual offline repair

```text
status=blocked
repaired_snapshot_ids=()
blocked_reasons=(
  'RAW_ARTIFACT_INCOMPLETE:funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00',
)
cutoff_evidence=[]
```

No Canonical partition was written. The remaining TONUSDT Funding ZIP and
sidecar are absent and were not downloaded.

## Actual strict preflight

```text
status=blocked
inputs=14879
parents=0
input_set_sha256=None
blocked_reasons=(
  'RAW_LINEAGE_MISSING:funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00',
)
```

No recovery publisher was called because the preflight is not `READY`.

## Immutable artifact comparison

The compared scope was the current-plan Canonical directory, primary Catalog,
and `research_root`.

```text
baseline_files=14888
final_files=14888
unchanged=True
baseline_map_sha256=b701f88d25e0a68bae760d149d1e0be131501ef30c2ba1fab5cbf8b05b9dd277
current_map_sha256=b701f88d25e0a68bae760d149d1e0be131501ef30c2ba1fab5cbf8b05b9dd277
added=0
removed=0
changed=0
```

```text
network_downloads=false
research_snapshot_publisher_called=false
development_analysis_called=false
holdout_accessed=false
paper_trading=false
live_trading=false
```

## Final code gates

The following focused final suite was run after the causal input-selection fix
and evidence updates:

```powershell
uv run pytest -p no:cov tests/unit/data/test_local_availability_repair.py tests/unit/data/test_local_snapshot_recovery.py tests/unit/data/test_snapshots.py tests/integration/data/test_dual_horizon_pipeline.py tests/integration/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py -q
uv run ruff check src/bian_quant/data/acquisition.py src/bian_quant/data/dual_horizon.py src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/data/local_availability_repair.py tests/unit/data/test_source_plan.py tests/unit/data/test_local_availability_repair.py tests/unit/data/test_local_snapshot_recovery.py
uv run ruff format --check src/bian_quant/data/acquisition.py src/bian_quant/data/dual_horizon.py src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/data/local_availability_repair.py tests/unit/data/test_source_plan.py tests/unit/data/test_local_availability_repair.py tests/unit/data/test_local_snapshot_recovery.py
uv run mypy src/bian_quant
git diff --check
```

Actual result: `40 passed in 220.49s`; Ruff passed; all seven checked files
were already formatted; mypy passed for 96 source files; and `git diff --check`
passed.

## Stop gate

The only remaining action is a separately authorized, single-object network
slice for the TONUSDT July 2026 Funding archive. This run does not authorize
that download, snapshot recovery, development analysis, Holdout, paper trading
or live trading.

This stop gate was superseded on 2026-08-15 by the permanent source exclusion
contract and the path-A run recorded in
`docs/evidence/2026-08-15-tonusdt-source-exclusion-run.md`.
