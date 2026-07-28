# Quant Research Platform Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve bianV2 from a single Price Action backtest into a reproducible, point-in-time-correct quantitative research platform with factor discovery, nested walk-forward validation, high-fidelity backtesting, decision reports, and an isolated Kronos evaluation track.

**Architecture:** Keep `main@59e8bcb` reproducible as Baseline-0, then add a `src/bian_quant` package whose modules communicate through explicit data, signal, experiment, and artifact contracts. Raw data is immutable, research datasets are point-in-time queries, all signals share one validation/backtest path, and the Dashboard reads persisted artifacts rather than recomputing research metrics.

**Tech Stack:** Python 3.11, uv, Parquet, DuckDB, SQLite, Pydantic, Typer, pandas/Polars, NumPy/SciPy, pytest/Hypothesis, scikit-learn/LightGBM, optional PyTorch/Kronos, FastAPI/Plotly, WSL2.

---

## Executor contract

This plan bundle is intended for Kimi or another implementation agent. The executor must obey these rules:

1. Start from the `codex/research-platform-design` plan-bundle commit named in the handoff. Verify `bcd0cc9` is an ancestor; do not work on `main` or `round8-archive`.
2. Create an implementation branch and dedicated worktree:

```bash
git worktree add -b codex/research-platform-implementation ../bianV2-research-implementation codex/research-platform-design
cd ../bianV2-research-implementation
```

Expected: clean worktree on `codex/research-platform-implementation`.

3. Read the approved design before changing code:

```bash
sed -n '1,320p' docs/superpowers/specs/2026-07-29-quant-research-platform-design.md
```

4. Execute the child plans in numerical order. Do not begin a later plan while the prior plan's exit gate is red.
5. Use TDD for behavioral code: failing test, minimal implementation, passing test, focused commit.
6. Never replace historical evidence. A rerun creates a new `run_id`; raw data and locked reports are append-only.
7. Do not download model weights, paid data, or large historical datasets until the corresponding smoke-test task is reached.
8. Do not add live exchange order placement, API-key storage, or real-money execution.
9. If a command or dependency differs in the current environment, record the exact deviation in the plan checkbox and `docs/implementation-notes.md`; do not silently improvise.

## Plan bundle and exit gates

| Order | Plan | Deliverable | Exit gate |
|---|---|---|---|
| 00 | [Foundation and Baseline](2026-07-29-00-foundation-baseline.md) | Locked environment, package skeleton, Baseline-0 replay | Old PA results reproduce; all new foundation tests pass |
| 01 | [Point-in-Time Data Platform](2026-07-29-01-data-platform.md) | Raw/Canonical/Research lake, catalog, QA, importers | Legacy data imports deterministically; leakage sentinel passes |
| 02 | [Validation and Backtest](2026-07-29-02-validation-backtest.md) | Signal contract, nested WF, vector/event engines, costs | Golden fills/costs/splits pass; promotion gate rejects weak baseline |
| 03 | [Factors and Regimes](2026-07-29-03-factor-regime.md) | Factor registry, initial library, evaluation, lifecycle | Factor report is reproducible; redundant/unstable factors are rejected |
| 04 | [Observability and Dashboard](2026-07-29-04-observability-dashboard.md) | Structured logs, artifact reports, read APIs, decisions | One run is fully traceable and reviewable through UI/API |
| 05 | [Models and Kronos](2026-07-29-05-models-kronos.md) | Naive/ML baselines and isolated Kronos adapter | Kronos comparison cannot bypass baseline or leakage gates |
| 06 | [Automation and Release](2026-07-29-06-automation-release.md) | Scheduled research loop, daily/weekly reports, release gate | Idempotent scheduled run completes; release packet is generated |

## Locked repository layout

The implementation must converge on this layout. Child plans may create only the files assigned to their phase unless a test fixture requires a sibling file.

```text
bianV2/
├── pyproject.toml
├── uv.lock
├── .python-version
├── configs/
│   ├── base.yaml
│   ├── universe/core.yaml
│   ├── experiments/baseline_pa.yaml
│   ├── models/kronos_zero_shot.yaml
│   └── reporting.yaml
├── src/bian_quant/
│   ├── cli.py
│   ├── config.py
│   ├── paths.py
│   ├── data/
│   ├── experiments/
│   ├── signals/
│   ├── validation/
│   ├── backtest/
│   ├── factors/
│   ├── regimes/
│   ├── models/
│   ├── reporting/
│   └── dashboard/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── golden/
│   └── fixtures/
├── data/                  # Existing tracked legacy CSVs remain untouched
├── var/                   # Ignored local lake, registries, logs, artifacts
├── dashboard/             # Existing static assets retained during migration
└── docs/
```

## Cross-plan public contracts

Later plans must import these types rather than creating incompatible duplicates:

```python
# src/bian_quant/data/contracts.py
class MarketRecord(BaseModel):
    asset: str
    event_time: datetime
    available_time: datetime
    ingested_at: datetime
    source: str

# src/bian_quant/signals/protocol.py
class SignalRecord(BaseModel):
    asset: str
    decision_time: datetime
    available_time: datetime
    horizon: str
    value: float
    confidence: float | None
    factor_id: str
    factor_version: str

# src/bian_quant/experiments/models.py
class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
```

Any signature change to a public contract requires updating all child-plan consumers and adding a migration note.

## Global quality commands

Run these before every phase exit commit:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/bian_quant
uv run pytest -q
git diff --check
```

Expected: all commands exit 0. Tests that require the optional `models` group must be marked `@pytest.mark.models` and excluded from the default suite.

Run the model suite only after Plan 05 installs its group:

```bash
uv sync --extra models
uv run pytest -q -m models
```

## Evidence and commit policy

Each task ends with one focused commit. Use these prefixes:

- `build:` environment and dependency changes
- `test:` fixtures or regression coverage without behavior changes
- `feat(data):`, `feat(validation):`, `feat(backtest):`, `feat(factors):`, `feat(reporting):`, `feat(models):`
- `fix:` behavior corrections found by a failing test
- `docs:` operator and decision documentation

Never commit `var/`, downloaded model weights, private credentials, transient logs, `.venv`, DuckDB/SQLite journals, or generated Dashboard screenshots.

## Final definition of done

- [ ] All seven child-plan exit gates are green.
- [ ] `uv run pytest -q` passes from a clean clone without network access.
- [ ] Baseline-0 is reproducible and clearly labeled as legacy evidence.
- [ ] A fresh legacy CSV import creates deterministic catalog and Parquet hashes.
- [ ] A known future-leakage fixture is rejected.
- [ ] A sample factor travels through registry, nested walk-forward, costs, artifacts, report, Dashboard API, and human decision storage.
- [ ] The PA baseline fails or passes only according to the new gates; no special exemption exists.
- [ ] Kronos results are compared with naive and ML baselines under identical folds.
- [ ] Daily and weekly reports explain failures as well as successes.
- [ ] No live-trading code or secrets exist in the implementation branch.
- [ ] `docs/operations.md` explains install, data update, experiment execution, report review, recovery, and disk cleanup.
