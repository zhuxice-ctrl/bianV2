# Local Canonical Snapshot Recovery — Real Preflight Evidence

## Run identity

| Item | Actual value |
|---|---|
| Branch | `codex/relative-funding-pressure-factor` |
| Recovery implementation content | commit `623c1bc` (the same working-tree content was used for the preflight) |
| UTC date | 2026-08-14 |
| Configuration | `configs/experiments/popular_universe_100u.yaml` |
| Scope | local Canonical preflight only; no snapshot recovery was invoked |

## Actual command

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
print(f"blocked_reasons_count={len(result.blocked_reasons)}")
print(result.blocked_reasons[:20])
'@ | uv run python -
```

Actual output:

```text
status=blocked
inputs=14879
parents=0
input_set_sha256=None
blocked_reasons_count=17
```

The 17 stable blockers are:

- `CANONICAL_INPUT_MISSING:ohlcv|<asset>|1d|daily|2026-07-26T00:00:00+00:00` for each configured asset: ADAUSDT, APTUSDT, AVAXUSDT, BCHUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, LTCUSDT, NEARUSDT, SOLUSDT, SUIUSDT, TONUSDT, TRXUSDT and XRPUSDT.
- `RAW_LINEAGE_MISSING:funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00`.

The preflight selected Canonical inputs only when all four identities agreed:

1. current source-plan namespaced Canonical path;
2. source `identity_key`;
3. Raw manifest `content_sha256`; and
4. Canonical manifest `raw_sha256`.

This prevents historical Catalog copies from being selected as a substitute for
the current local lineage. The full scan read and validated 14,879 matching
Canonical inputs before returning the 17 blockers.

## Stopping result

No recovery function was called after the blocked preflight. Therefore there
are no new main or OI-delay snapshot IDs, no recovery run ID, no development
analysis run ID, no factor metrics and no candidate list to report.

```text
network_downloads=false
recovery_snapshot_publisher_called=false
holdout_accessed=false
paper_trading=false
live_trading=false
old_artifacts_hash_compared=false (a pre-run byte baseline was not captured)
```

The code-level preflight side-effect test verifies that the read-only function
does not create or rewrite Catalog, Canonical or research files. This real run
does not by itself prove a byte-for-byte before/after comparison, so no such
claim is made here.

## Final code gates

The following final command was actually run after the recovery implementation,
lineage fix and evidence updates:

```powershell
uv run pytest -p no:cov tests/unit/data/test_snapshots.py tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_dual_horizon_pipeline.py tests/integration/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_dual_horizon.py -q
uv run ruff check src/bian_quant/data/popular_universe_artifacts.py src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/data/dual_horizon.py src/bian_quant/research/operations.py tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py
uv run ruff format --check src/bian_quant/data/popular_universe_artifacts.py src/bian_quant/data/local_snapshot_recovery.py src/bian_quant/data/dual_horizon.py src/bian_quant/research/operations.py tests/unit/data/test_local_snapshot_recovery.py tests/integration/data/test_local_snapshot_recovery.py tests/unit/research/test_operations.py
uv run mypy src/bian_quant
git diff --check
```

Actual result: `81 passed` in 222.54 seconds; Ruff passed; all seven task files
were already formatted; mypy passed for 95 source files; and `git diff --check`
passed.

## Historical conclusion

This was the correct conclusion for the 2026-08-14 source-plan semantics. It
was superseded on 2026-08-15 after a causal input-selection correction: the
sixteen unclosed daily 1d bars are not Canonical inputs at this cutoff. The
remaining stop gate is only the missing TONUSDT Raw lineage; see
`docs/evidence/2026-08-15-local-data-availability-repair-run.md`.
