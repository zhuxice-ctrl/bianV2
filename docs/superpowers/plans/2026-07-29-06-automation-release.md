# Automation and Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the research loop safely on a schedule, isolate failures, generate decision reports, protect locked holdouts, and produce release packets without adding live trading.

**Architecture:** A local stage runner executes explicit idempotent jobs under a SQLite lease. Systemd timers invoke CLI commands in WSL. Automatic work stops at blocking data/model errors or human-decision gates. Release evaluation consumes a named holdout once per strategy version and produces an immutable evidence packet.

**Tech Stack:** Typer, SQLite, systemd timers, existing experiment/artifact/reporting modules, pytest.

---

### Task 1: Define research pipeline stages and outcomes

**Files:**
- Create: `src/bian_quant/automation/__init__.py`
- Create: `src/bian_quant/automation/stages.py`
- Test: `tests/unit/automation/test_stages.py`

- [ ] **Step 1: Write stage-order and blocking tests**

Create `tests/unit/automation/test_stages.py`:

```python
from bian_quant.automation.stages import PipelineStage, next_stage


def test_pipeline_order_is_explicit() -> None:
    assert next_stage(PipelineStage.INGEST) == PipelineStage.DATA_QUALITY
    assert next_stage(PipelineStage.DATA_QUALITY) == PipelineStage.DATASET_BUILD
    assert next_stage(PipelineStage.DATASET_BUILD) == PipelineStage.FACTOR_SCREEN


def test_human_decision_has_no_automatic_successor() -> None:
    assert next_stage(PipelineStage.HUMAN_DECISION) is None
```

- [ ] **Step 2: Implement stages**

Create empty `src/bian_quant/automation/__init__.py` and define:

```python
class PipelineStage(StrEnum):
    INGEST = "ingest"
    DATA_QUALITY = "data_quality"
    DATASET_BUILD = "dataset_build"
    FACTOR_SCREEN = "factor_screen"
    PRECISE_BACKTEST = "precise_backtest"
    REPORT = "report"
    HUMAN_DECISION = "human_decision"
```

Use a constant ordered map. A blocking quality result transitions the run to `blocked` and does not call `next_stage`. A failed candidate/model does not prevent independent candidates from continuing.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/automation/test_stages.py -q
git add src/bian_quant/automation tests/unit/automation
git commit -m "feat: define automated research stages"
```

### Task 2: Add a lease-based single-host job queue

**Files:**
- Create: `src/bian_quant/automation/queue.py`
- Test: `tests/unit/automation/test_queue.py`

- [ ] **Step 1: Write lease tests with a fake clock**

Use a fake UTC clock and create four literal queue tests:

1. Worker `a` acquires a lease until `00:05`; worker `b` at `00:04` receives `None`.
2. Worker `b` at `00:06` acquires the expired job and an event with code `LEASE_RECOVERED` references worker `a`.
3. Enqueueing identity `hash-1` after its first job completed returns the completed job ID and leaves the row count unchanged.
4. A job failed with `MODEL_LOGIC_ERROR` remains failed after the retry scheduler runs and its attempt count stays `1`.

- [ ] **Step 2: Implement queue tables**

Create `jobs` and `job_events` tables. Each job has UUID, identity hash, stage, payload JSON, status, attempt, created time, lease owner, lease expiry, and linked run ID. Use `BEGIN IMMEDIATE` for acquisition. A completed identity may return its previous run ID but never creates duplicate work.

- [ ] **Step 3: Implement retry classes**

Only these errors are retryable, with a maximum of three attempts and exponential delays recorded in the queue:

```text
NETWORK_TIMEOUT
HTTP_429
TEMPORARY_DNS
RESOURCE_BUSY
```

These are never automatically retried:

```text
DATA_QUALITY_BLOCKING
FUTURE_LEAKAGE
ASSERTION_FAILED
MODEL_LOGIC_ERROR
PROMOTION_GATE_FAILED
```

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/automation/test_queue.py -q
git add src/bian_quant/automation/queue.py tests/unit/automation/test_queue.py
git commit -m "feat: add lease-based research queue"
```

### Task 3: Implement the idempotent pipeline runner

**Files:**
- Create: `src/bian_quant/automation/pipeline.py`
- Modify: `src/bian_quant/cli.py`
- Test: `tests/integration/automation/test_pipeline.py`

- [ ] **Step 1: Write an end-to-end fake pipeline test**

Use fake stage handlers and assert:

- Successful stages run once in order.
- Reinvoking the same identity reuses completed evidence.
- Blocking data stops before factor computation.
- One failed model candidate does not stop a separate factor candidate.
- A promotion-ready candidate ends at `HUMAN_DECISION`, not `approved`.

- [ ] **Step 2: Implement handler protocol**

```python
class StageHandler(Protocol):
    def __call__(self, context: RunContext) -> StageResult:
        raise NotImplementedError

class StageResult(BaseModel):
    status: Literal["passed", "failed", "blocked", "decision_required"]
    artifact_paths: list[Path]
    reason_codes: list[str]
```

The runner stores a stage event before and after each handler and samples resources at both points.

- [ ] **Step 3: Add CLI commands**

```bash
bian-quant pipeline enqueue --config configs/pipelines/daily.yaml
bian-quant pipeline worker --once
bian-quant pipeline status
```

`worker --once` acquires one job and exits with nonzero status only for infrastructure/logic failure; a correctly evaluated rejected factor is a successful job with a failed promotion decision.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/integration/automation/test_pipeline.py -q
git add src/bian_quant/automation src/bian_quant/cli.py tests/integration/automation
git commit -m "feat: run idempotent research pipeline"
```

### Task 4: Add daily and weekly pipeline configurations

**Files:**
- Create: `configs/pipelines/daily.yaml`
- Create: `configs/pipelines/weekly.yaml`
- Test: `tests/unit/automation/test_pipeline_config.py`

- [ ] **Step 1: Create strict config models and tests**

Reject unknown keys, missing dataset IDs, missing seeds, unbounded candidate counts, and schedules without UTC timezone. Assert the weekly plan cannot include locked-holdout evaluation.

- [ ] **Step 2: Create daily config**

```yaml
name: daily-research
timezone: UTC
max_candidates: 20
seed: 7
stages:
  - ingest
  - data_quality
  - dataset_build
  - factor_screen
  - report
models:
  kronos_enabled: false
resource_limits:
  max_ram_percent: 85
  min_disk_free_gb: 50
```

- [ ] **Step 3: Create weekly config**

```yaml
name: weekly-research
timezone: UTC
max_candidates: 50
seed: 7
stages:
  - data_quality
  - dataset_build
  - factor_screen
  - precise_backtest
  - report
  - human_decision
models:
  kronos_enabled: false
resource_limits:
  max_ram_percent: 90
  min_disk_free_gb: 50
```

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/automation/test_pipeline_config.py -q
git add configs/pipelines tests/unit/automation
git commit -m "feat: configure daily and weekly research loops"
```

### Task 5: Add WSL systemd services and timers

**Files:**
- Create: `deploy/systemd/bian-quant-worker.service`
- Create: `deploy/systemd/bian-quant-daily.service`
- Create: `deploy/systemd/bian-quant-daily.timer`
- Create: `deploy/systemd/bian-quant-weekly.service`
- Create: `deploy/systemd/bian-quant-weekly.timer`
- Create: `scripts/install-systemd.sh`
- Test: `tests/unit/automation/test_systemd_files.py`

- [ ] **Step 1: Write static deployment tests**

Assert services contain `WorkingDirectory`, absolute `ExecStart`, `NoNewPrivileges=true`, restart only for worker infrastructure failure, and no environment secrets. Assert timers declare `Persistent=true` and explicit UTC calendar expressions.

- [ ] **Step 2: Create units**

Worker service runs `uv run bian-quant pipeline worker --once`. Daily service enqueues `configs/pipelines/daily.yaml`; weekly service enqueues `configs/pipelines/weekly.yaml`. Timers use `OnCalendar=*-*-* 01:15:00 UTC` daily and `OnCalendar=Sun *-*-* 02:00:00 UTC` weekly.

- [ ] **Step 3: Create installer**

The installer accepts repo path and user systemd directory, renders absolute paths, runs `systemd-analyze verify`, then installs with `install -m 0644`. It prints enable commands but does not automatically enable timers.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/unit/automation/test_systemd_files.py -q
systemd-analyze verify deploy/systemd/*.service deploy/systemd/*.timer
git add deploy/systemd scripts/install-systemd.sh tests/unit/automation/test_systemd_files.py
git commit -m "feat: schedule research jobs in WSL"
```

### Task 6: Protect locked holdout evaluation

**Files:**
- Create: `src/bian_quant/validation/holdout.py`
- Test: `tests/unit/validation/test_holdout.py`

- [ ] **Step 1: Write one-consumption tests**

Create three holdout tests:

1. Reserve `strategy-a@1.0.0` with `holdout-v1`, complete it, then assert a second reservation raises `HOLDOUT_ALREADY_CONSUMED`.
2. Complete `strategy-a@1.0.0` as failed, assert the same version still cannot reserve again, then assert `strategy-a@1.0.1` can reserve only with a new approval decision.
3. During a running evaluation, `get_public_result()` returns status and start time but no metrics; after atomic completion it returns the final artifact checksum and metrics location.

- [ ] **Step 2: Implement holdout ledger**

Store strategy ID/version, holdout snapshot ID, registered code SHA, config hash, approval decision ID, evaluation run ID, start/completion time, and result checksum. `reserve()` requires a prior decision approving evaluation. A uniqueness constraint on strategy version plus holdout snapshot prevents reruns.

- [ ] **Step 3: Implement blind execution**

The evaluation worker receives the holdout snapshot ID but does not expose interim metrics. It publishes the complete atomic artifact bundle only after all scenarios finish; failure publishes diagnostics without partial performance tables.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/validation/test_holdout.py -q
git add src/bian_quant/validation/holdout.py tests/unit/validation/test_holdout.py
git commit -m "feat(validation): protect locked holdout evidence"
```

### Task 7: Generate immutable release candidate packets

**Files:**
- Create: `src/bian_quant/reporting/release.py`
- Create: `src/bian_quant/reporting/templates/release.md.j2`
- Test: `tests/integration/reporting/test_release_packet.py`

- [ ] **Step 1: Write completeness tests**

Assert release generation fails unless it has approved decision ID, successful holdout run, all scenario results, baseline comparison, concentration report, data-quality report, environment, checksums, and known limitations.

- [ ] **Step 2: Implement release packet**

Publish:

```text
release_manifest.json
release_report.md
strategy_config.yaml
factor_versions.json
dataset_manifests.json
fold_metrics.parquet
scenario_metrics.parquet
trades.parquet
equity.parquet
decisions.json
environment.json
checksums.json
```

The report begins with research-only status and explicitly says it is not authorized for live trading.

- [ ] **Step 3: Add CLI**

```bash
bian-quant release build --strategy <id>@<version> --holdout-run <run-id>
```

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/integration/reporting/test_release_packet.py -q
git add src/bian_quant/reporting tests/integration/reporting
git commit -m "feat(reporting): build research release packets"
```

### Task 8: Add historical stream replay without order execution

**Files:**
- Create: `src/bian_quant/replay/__init__.py`
- Create: `src/bian_quant/replay/historical.py`
- Test: `tests/unit/replay/test_historical.py`

- [ ] **Step 1: Write replay causality tests**

Assert rows arrive in `available_time` order, simulated clock never moves backward, late data is labeled late rather than reordered into the past, and replay exposes no exchange/order API.

- [ ] **Step 2: Implement replay source**

`HistoricalReplay` yields immutable `ReplayEvent(simulated_time, record, late_by)` from a fixed dataset snapshot. It supports speed multiplier and pause/resume but never calls a network adapter.

- [ ] **Step 3: Document paper-trading boundary**

Add a module docstring: replay validates streaming state and reporting only. Paper portfolio simulation may consume signals through the existing event engine; real exchange placement remains absent.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/replay/test_historical.py -q
git add src/bian_quant/replay tests/unit/replay
git commit -m "feat: replay historical data as a causal stream"
```

### Task 9: Add safe backup, retention, and cleanup operations

**Files:**
- Create: `src/bian_quant/operations/retention.py`
- Create: `src/bian_quant/operations/backup.py`
- Test: `tests/unit/operations/test_retention.py`

- [ ] **Step 1: Write protection tests**

Assert cleanup never deletes Raw manifests, approved/candidate evidence, decision-linked runs, locked holdouts, release packets, or the most recent failed diagnostic for each reason code. Dry-run returns exact paths and bytes without mutation.

- [ ] **Step 2: Implement retention classes**

Classify artifacts as `protected`, `recomputable`, or `temporary`. Only temporary files older than seven days and recomputable non-decision artifacts older than configured retention are eligible. Require `--apply` plus an exact cleanup plan checksum to mutate.

- [ ] **Step 3: Implement backup manifest**

Backup SQLite with its online backup API, copy manifests/decisions/release packets, calculate hashes, and write a restore manifest. Large Raw/Parquet data is represented by content hash and source URI unless explicitly requested.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/operations/test_retention.py -q
git add src/bian_quant/operations tests/unit/operations
git commit -m "feat: protect research evidence during cleanup"
```

### Task 10: Write operations manual and run final rehearsal

**Files:**
- Create: `docs/operations.md`
- Create: `tests/integration/test_full_research_rehearsal.py`

- [ ] **Step 1: Write operations manual**

Include exact commands for WSL install, `uv sync`, initialization, legacy import, data QA, factor evaluation, model comparison, Dashboard, decisions, scheduling, holdout approval, release build, backup, cleanup dry-run, log diagnosis, and recovery from expired lease. Include current hardware guidance and disk thresholds.

- [ ] **Step 2: Write full offline rehearsal test**

Using small fixtures only:

1. Import legacy-like OHLCV.
2. Pass data QA.
3. Register two factors, one valid and one leaked.
4. Reject leaked factor.
5. Run anchored folds and event backtest.
6. Reject a weak candidate at promotion gate.
7. Publish atomic artifacts and report.
8. Expose run through Dashboard API.
9. Append an `OBSERVE` decision.
10. Generate daily and weekly summaries.

- [ ] **Step 3: Run full quality suite**

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src/bian_quant
uv run pytest -q
git diff --check
```

Expected: all pass without network, model weights, or GPU.

- [ ] **Step 4: Commit**

```bash
git add docs/operations.md tests/integration/test_full_research_rehearsal.py
git commit -m "docs: add research platform operations rehearsal"
```

## Plan 06 exit gate

- [ ] Queue leases prevent concurrent duplicate work.
- [ ] Only transient infrastructure errors retry automatically.
- [ ] Daily/weekly configs are bounded and do not consume holdouts.
- [ ] Systemd units validate and remain disabled until operator enables them.
- [ ] Promotion-ready work stops for human decision.
- [ ] Locked holdout can be consumed once per strategy version.
- [ ] Release packet is complete, immutable, and marked research-only.
- [ ] Historical replay has no order-placement interface.
- [ ] Cleanup protects decision-linked evidence.
- [ ] Full offline rehearsal and global quality suite pass.
