# Implementation Notes

## Immutable starting points
- Legacy main: `59e8bcb2876506b0076751def71d95b6ec81b6bc`
- Round 8 archive: `d413eda3df7ae2aca0b29ae732171ea0346b5ec7`
- Approved design: `bcd0cc9`
- Upstream plan commit: `25a950836c8a1d86e7bfcd25dffcdee86e91ca98`
- Live trading is out of scope.

## Deviations
Record each approved deviation from the implementation plans here with date, task, evidence, and consequence.

### 2026-07-29 — Task 1, Step 1: Worktree creation via tarball
**Evidence:** `git clone` failed with `gnutls_handshake() failed: An unexpected TLS packet was received` in the sandbox environment. Repository was downloaded as a tarball via the GitHub codeload API and initialized as a fresh git repository.
**Impact:** The original implementation branch had disconnected history even though its base file tree matched upstream plan commit `25a9508`.
**Resolution:** The Plan 00 implementation was rebased onto the real `codex/research-platform-design` branch. `git merge-base --is-ancestor 25a9508 HEAD` is a required release check.

### 2026-07-29 — Task 5: pytest-cov plugin causes hang in sandbox
**Evidence:** `pytest-cov` auto-load causes `uv run pytest -q` to hang indefinitely during collection in the sandbox environment. The `sitecustomize.py` at `/opt/sitecustomize/` fails with `ModuleNotFoundError: No module named 'matplotlib'`, which may interact with the plugin.
**Impact:** The sandbox used `-p no:cov` only as a local command-line workaround.
**Resolution:** Project configuration does not disable coverage globally. The default pytest command is verified on Windows and WSL2 and excludes only tests marked `network`.

### 2026-07-29 — Task 5: Ruff excludes legacy code
**Evidence:** The plan specifies `uv run ruff check .` which checks all files, but 152 lint errors exist in frozen legacy code (`backtest/`, `strategies/`, `dashboard/`, `run_backtest.py`, etc.).
**Impact:** Added `exclude` list to `[tool.ruff]` in `pyproject.toml` for legacy files and `docs/` directory.
**Consequence:** Ruff checks only apply to new code under `src/bian_quant`, `tests/`, `scripts/`, and `configs/`. Legacy code remains frozen and unmodified.

### 2026-07-29 — Task 5: mypy requires --verbose flag in sandbox
**Evidence:** `uv run mypy src/bian_quant` hangs without the `--verbose` flag in the sandbox environment.
**Impact:** Verified mypy passes using `mypy --verbose src/bian_quant`.
**Consequence:** Type checking passes with no errors. In the target WSL2 environment, standard `mypy src/bian_quant` should work without `--verbose`.

### 2026-07-29 — Plan 00 portability repair
**Evidence:** Independent verification found missing frozen legacy packages in built wheels, absent pandas/PyYAML stubs, non-propagating PowerShell failures, and unstable shell line endings.
**Impact:** Added `backtest` and `strategies` to the wheel, restored strict typing stubs and legacy import boundaries, propagated PowerShell exit codes, and enforced LF for Shell plus CRLF for PowerShell.
**Consequence:** Windows and native WSL2 quality entry points must both pass before a plan exits.

### 2026-07-29 — Plan 01 independent verification repair
**Evidence:** Clean verification of remote `12679c2` found duplicate TOML keys, default network tests, Binance fixtures that did not match the live archive schema, cross-asset resampling, and migration-universe filters that admitted future observations.
**Impact:** Repaired configuration and packaging, verified live Binance checksums and schemas, added immutable Raw manifests, grouped resampling and quality checks by asset, and enforced `available_time <= selection_time` throughout universe construction.
**Consequence:** Plan 01 approval depends on offline Windows/WSL2 suites, explicit live network contract tests, and regression tests for these failure modes.

### 2026-07-30 — Plan 02 independent verification repair
**Evidence:** Clean verification of remote `159d560` found an out-of-scope commit that deleted the tracked data, dashboard, plans, specifications, results, and baseline evidence. The full suite also failed because `events.py` was absent and test packages collided. The submitted PA report contained no measured values or pass/fail result.
**Impact:** Reverted the unauthorized deletion, restored the approved signal/run/split/vector/cost contracts, added the missing event types, made terminal run states irreversible, and added a reproducible PA evaluator with dataset hashes, locked-holdout boundaries, stress evidence, and stable promotion reasons.
**Consequence:** Baseline PA is recorded as `FAIL`: positive-fold ratio `0.50`, median Sharpe `-0.7852`, Sharpe CI lower bound `-3.2369`, and locked-holdout return `-4.80%`. It receives no promotion exemption.

### 2026-07-29 — Task 1, Step 3: 165-run experiment artifact
**Evidence:** `run_backtest.py` generates `results/summary.json` and `results/backtest_*.json` for 3 symbols only. `dashboard/generate.py` reads `results/experiments.json` but does not generate it. No script in the repository produces the 165-run experiment artifact.
**Impact:** `results/experiments.json` and `results/experiments_summary.md` are archival evidence only.
**Consequence:** The new validation engine must rebuild the anti-overfitting protocol from explicit code. It must not claim numerical continuity with the archival 165-run report.

### 2026-07-30 — Plan 03.5 Task 4: Canonical parsers migration
**Evidence:** `parse_metrics` in `binance_derivatives.py` gained an optional `publication_delay` parameter (default 5 minutes) while preserving the existing five-minute default. Assumption labels are now `BINANCE_METRICS_DELAY_5M`, `BINANCE_METRICS_DELAY_10M`, and `BINANCE_METRICS_DELAY_15M`.
**Impact:** `RawArtifactManifest`, `DatasetManifest`, `MarketRecord`, and existing callers remain source compatible. The new `canonicalize.py` module wraps the existing parsers with point-in-time DataFrame conversion and Zstd Parquet partition writing.

### 2026-07-30 — Plan 03.5 Tasks 5-9: Dual-horizon pipeline, regimes, holdout, reporting
**Evidence:**
- Task 5: `derivatives_quality.py` (CoverageReport, inspect_coverage/funding/metrics/ohlcv) and `snapshots.py` (publish_snapshot, build_macro/micro_snapshots, build_delay_views) with causal aggregation and deterministic snapshot IDs. 13 tests pass.
- Task 6: `dual_horizon.py` (DualHorizonStatus, DualHorizonResult, Downloader Protocol, BinanceDownloader, FixtureDownloader, prepare_dual_horizon) with dry-run support. CLI commands prepare-dual-horizon, analyze-dual-horizon, evaluate-holdout. Offline pipeline test passes.
- Task 7: `regimes/macro.py` (MacroState, ComparableEpisodeSummary, MacroRegimeEvidence, classify_macro_history, summarize_comparable_episodes, write_macro_evidence) with expanding-window classification preserving prefix invariance. 14 tests pass.
- Task 8: `experiments/holdout.py` (HoldoutLedger with append-only SQLite triggers, DualHorizonWindows, partition_dual_horizon_windows) and `factors/dual_horizon.py` (8 interpretable factor specs, build_derivatives_factor_frame with causal funding/OI joins and delay invariance, run_dual_horizon_screening). 19 tests pass.
- Task 9: `reporting/artifacts.py` (ArtifactWriter with exclusive run dirs, atomic JSON writes, finite-value check) and `reporting/decision.py` (write_decision_packet with 7 required artifacts, 4 status types, zero-candidate = NO_PROMOTION). 14 tests pass.
**Impact:** Complete dual-horizon pipeline from data acquisition through factor screening to decision packet generation. All 71 Plan 03.5 tests pass.
**Consequence:** Tasks 10-11 (real data acquisition, cross-platform gates) are BLOCKED by sandbox network and TLS limitations. Patch file generated for application on the target environment.

## 2026-07-31 Funding monthly-tail amendment

- The evidence cutoff remains `2026-07-26T19:59:59.999Z`.
- Funding now uses monthly archives through the cutoff month; the source plan
  contains 3,117 objects and no Funding daily objects.
- A cutoff-month HTTP 404 is persisted as
  `FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE` and is resumable.
- Canonical outputs are clipped by both event and availability time and live
  below a `plan=` directory named by the first 16 source-plan hash characters;
  prior blocked canonical files remain immutable.
- REST Funding, imputation, changed assets, changed windows, and changed holdout
  boundaries remain out of scope.
