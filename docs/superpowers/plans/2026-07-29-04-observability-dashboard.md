# Observability and Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every research run traceable through structured logs, immutable artifacts, readable daily/weekly reports, a local Dashboard, and an append-only human decision ledger.

**Architecture:** Research code emits structured events and writes artifacts atomically. Reporting reads persisted metrics and creates Markdown/JSON summaries. FastAPI serves read-only research endpoints plus one explicit decision-write endpoint; the browser never computes research metrics.

**Tech Stack:** Python logging/JSON, Pydantic, SQLite, Parquet, Jinja2, FastAPI, Plotly, psutil, pytest.

---

### Task 1: Add structured run logging with secret redaction

**Files:**
- Create: `src/bian_quant/reporting/__init__.py`
- Create: `src/bian_quant/reporting/logging.py`
- Modify: `pyproject.toml`
- Test: `tests/unit/reporting/test_logging.py`

- [ ] **Step 1: Add resource dependency**

Add `"psutil>=7,<8"` to base dependencies in `pyproject.toml`, then run:

```bash
uv lock
uv sync --extra dev
```

- [ ] **Step 2: Write failing JSON and redaction tests**

Create `tests/unit/reporting/test_logging.py`:

```python
import json
from pathlib import Path

from bian_quant.reporting.logging import RunLogger


def test_log_contains_trace_fields_and_redacts_secrets(tmp_path: Path) -> None:
    logger = RunLogger(tmp_path / "run.jsonl", run_id="run-1")
    logger.info(
        "download",
        stage="data",
        dataset_id="legacy-v1",
        api_key="secret-value",
    )

    event = json.loads((tmp_path / "run.jsonl").read_text(encoding="utf-8"))
    assert event["run_id"] == "run-1"
    assert event["stage"] == "data"
    assert event["api_key"] == "[REDACTED]"
```

- [ ] **Step 3: Implement JSONL logger**

Create empty `src/bian_quant/reporting/__init__.py` and create `src/bian_quant/reporting/logging.py`:

```python
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SECRET_KEYS = {"api_key", "secret", "token", "password", "authorization"}


class RunLogger:
    def __init__(self, path: Path, *, run_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.run_id = run_id

    def info(self, event: str, **fields: Any) -> None:
        self._write("INFO", event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._write("ERROR", event, fields)

    def _write(self, level: str, event: str, fields: dict[str, Any]) -> None:
        safe = {
            key: "[REDACTED]" if key.lower() in SECRET_KEYS else value
            for key, value in fields.items()
        }
        payload = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": level,
            "event": event,
            "run_id": self.run_id,
            **safe,
        }
        with self.path.open("a", encoding="utf-8", newline="\n") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
```

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/reporting/test_logging.py -q
git add pyproject.toml uv.lock src/bian_quant/reporting tests/unit/reporting
git commit -m "feat(reporting): add structured redacted run logs"
```

### Task 2: Write artifacts atomically with a required manifest

**Files:**
- Create: `src/bian_quant/experiments/artifacts.py`
- Test: `tests/unit/experiments/test_artifacts.py`

- [ ] **Step 1: Write atomicity tests**

Create `tests/unit/experiments/test_artifacts.py`:

```python
from pathlib import Path

import pytest

from bian_quant.experiments.artifacts import ArtifactBundle


def test_incomplete_bundle_is_not_published(tmp_path: Path) -> None:
    bundle = ArtifactBundle(tmp_path, run_id="run-1")
    bundle.begin()
    bundle.write_json("manifest.json", {"run_id": "run-1"})

    with pytest.raises(ValueError, match="required artifact"):
        bundle.publish(required={"manifest.json", "metrics.parquet", "report.md"})

    assert not (tmp_path / "run-1").exists()
```

- [ ] **Step 2: Implement temporary-directory publication**

`ArtifactBundle.begin()` creates `<root>/.run-1.tmp` with exclusive semantics. `write_json`, `write_markdown`, and `write_parquet` write inside it. `publish(required)` verifies all names, writes `checksums.json`, fsyncs files where supported, then atomically renames the directory to `<root>/run-1`. Refuse overwrite if either temporary or final directory exists.

- [ ] **Step 3: Add required artifact schema**

Every research run must publish:

```text
manifest.json
environment.json
metrics.parquet
fold_metrics.parquet
diagnostics.json
report.md
checksums.json
```

Backtest runs additionally require `trades.parquet`, `fills.parquet`, and `equity.parquet`.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/experiments/test_artifacts.py -q
git add src/bian_quant/experiments/artifacts.py tests/unit/experiments/test_artifacts.py
git commit -m "feat(reporting): publish atomic experiment artifacts"
```

### Task 3: Capture environment and resource telemetry

**Files:**
- Create: `src/bian_quant/reporting/environment.py`
- Create: `src/bian_quant/reporting/resources.py`
- Test: `tests/unit/reporting/test_environment.py`

- [ ] **Step 1: Write stable schema tests**

Assert `capture_environment(repo_root)` contains Python, platform, package lock hash, code SHA, dirty-worktree flag, CPU count, total RAM, CUDA availability, and GPU names. Mock `subprocess.run` so absence of `nvidia-smi` produces `gpus=[]` rather than failing the run.

- [ ] **Step 2: Implement capture**

Use `platform`, `sys`, `hashlib`, `git rev-parse`, `git status --porcelain`, `psutil`, and optional `nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits`. Apply a timeout of five seconds and store the command error in diagnostics.

- [ ] **Step 3: Implement resource sampler**

`ResourceSampler.sample()` returns timestamp, process RSS, system memory percent, CPU percent, disk free bytes under `var/`, and GPU used/total MiB when available. The runner samples at stage boundaries, not every log line.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/reporting/test_environment.py -q
git add src/bian_quant/reporting tests/unit/reporting
git commit -m "feat(reporting): capture environment and resources"
```

### Task 4: Generate decision-oriented run reports

**Files:**
- Create: `src/bian_quant/reporting/run_report.py`
- Create: `src/bian_quant/reporting/templates/run_report.md.j2`
- Test: `tests/unit/reporting/test_run_report.py`

- [ ] **Step 1: Write report-content tests**

Create a failed-run fixture and assert the rendered report contains:

```text
结论：未通过
失败门槛
影响
建议动作
数据快照
代码提交
```

Create a passed-but-decision-required fixture and assert the report says `等待人工裁决`, not `已批准`.

- [ ] **Step 2: Create the template**

The template must render these sections in order:

1. One-sentence conclusion.
2. What changed versus approved version.
3. Evidence summary and confidence.
4. Failed gates and reason codes.
5. Performance by fold, asset, year, and regime.
6. Cost and stress sensitivity.
7. Concentration and redundancy.
8. Resource use.
9. Suggested action and whether a human decision is required.
10. Reproduction command and artifact checksums.

- [ ] **Step 3: Implement renderer**

`render_run_report(manifest, metrics, diagnostics, comparison) -> str` accepts persisted objects only. It must not import factor functions, backtest engines, or data adapters. Add an import-boundary test scanning its imports.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/reporting/test_run_report.py -q
git add src/bian_quant/reporting tests/unit/reporting
git commit -m "feat(reporting): explain experiment decisions"
```

### Task 5: Add append-only human decision ledger

**Files:**
- Create: `src/bian_quant/experiments/decisions.py`
- Test: `tests/unit/experiments/test_decisions.py`

- [ ] **Step 1: Write immutable decision tests**

Create `tests/unit/experiments/test_decisions.py`:

```python
from pathlib import Path

import pytest

from bian_quant.experiments.decisions import Decision, DecisionLedger, DecisionOutcome


def test_decision_cannot_be_overwritten(tmp_path: Path) -> None:
    ledger = DecisionLedger(tmp_path / "registry.sqlite")
    decision = Decision.create(
        run_id="run-1",
        subject_type="factor",
        subject_id="price.momentum@1.0.0",
        outcome=DecisionOutcome.OBSERVE,
        note="evidence is directional but confidence interval crosses zero",
        actor="owner",
    )
    ledger.append(decision)

    with pytest.raises(ValueError, match="decision_id already exists"):
        ledger.append(decision)
```

- [ ] **Step 2: Implement ledger**

Define outcomes `APPROVE`, `REJECT`, `OBSERVE`. Each row contains decision UUID, run ID, subject type/ID, outcome, note, actor, UTC timestamp, evidence checksums, and supersedes ID. Corrections append a new decision referencing `supersedes`; they never update the original row.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/experiments/test_decisions.py -q
git add src/bian_quant/experiments/decisions.py tests/unit/experiments/test_decisions.py
git commit -m "feat(reporting): add append-only decision ledger"
```

### Task 6: Build Dashboard read APIs and decision endpoint

**Files:**
- Create: `src/bian_quant/dashboard/__init__.py`
- Create: `src/bian_quant/dashboard/app.py`
- Create: `src/bian_quant/dashboard/schemas.py`
- Create: `src/bian_quant/dashboard/repository.py`
- Test: `tests/integration/dashboard/test_api.py`

- [ ] **Step 1: Write API tests**

Using FastAPI `TestClient` and a temporary repository fixture, implement these exact assertions:

1. `GET /api/health` returns 200 and keys `data_freshness`, `queue`, `disk`, `memory`, and `gpu`.
2. After publishing fixture run `run-1`, `GET /api/runs/run-1` returns its persisted manifest checksum and fold metrics.
3. `GET /api/runs/missing` returns 404 with reason code `RUN_NOT_FOUND`.
4. `POST /api/decisions` with an empty note returns 422; the same request with unknown run ID returns 404; a valid request returns 201 and decision UUID.
5. Monkeypatch `builtins.__import__` to fail on `bian_quant.backtest` and `bian_quant.factors`; `GET /api/runs/run-1` must still return 200, proving the API reads artifacts rather than recalculating metrics.

- [ ] **Step 2: Implement repository**

The repository reads the experiment/decision SQLite tables and artifact files. It exposes `list_runs`, `get_run`, `list_factors`, `get_factor`, `list_decisions`, and `system_health`. It does not calculate Sharpe, IC, drawdown, or PnL.

- [ ] **Step 3: Implement API routes**

Create:

```text
GET  /api/health
GET  /api/runs
GET  /api/runs/{run_id}
GET  /api/factors
GET  /api/factors/{factor_id}/{version}
GET  /api/regimes/summary
GET  /api/decisions
POST /api/decisions
```

The POST body contains run ID, subject, outcome, note, and actor. Validate evidence exists and append through `DecisionLedger`.

- [ ] **Step 4: Add CLI server command**

Add `bian-quant dashboard --host 127.0.0.1 --port 8787`. Default host must remain loopback; exposing to the LAN requires an explicit flag.

- [ ] **Step 5: Run and commit**

```bash
uv sync --extra dashboard --extra dev
uv run pytest tests/integration/dashboard/test_api.py -q
git add src/bian_quant/dashboard src/bian_quant/cli.py tests/integration/dashboard
git commit -m "feat(reporting): expose research dashboard API"
```

### Task 7: Build the local research Dashboard

**Files:**
- Create: `dashboard/research.html`
- Create: `dashboard/research.js`
- Create: `dashboard/research.css`
- Test: `tests/integration/dashboard/test_static_ui.py`

- [ ] **Step 1: Write static contract tests**

Assert the HTML has navigation targets for health, research funnel, runs, factors, regimes, and decisions; has no hard-coded metric values; and loads only local assets plus `/api/*` data.

- [ ] **Step 2: Implement six views**

Use semantic HTML and local JavaScript. Every metric card shows data snapshot, run ID, and last update. Failed gates are visually distinct from negative returns. Decision controls appear only when `decision_required=true` and require a note before submit.

- [ ] **Step 3: Add safe rendering**

Use `textContent`, not `innerHTML`, for API-provided strings. Charts consume already-computed series. A missing artifact renders an explicit unavailable state and reason code.

- [ ] **Step 4: Run server and verify manually**

```bash
uv run bian-quant dashboard
```

Open `http://127.0.0.1:8787/research.html`, load fixture runs for passed, failed, blocked, and waiting-decision states, and record results in `docs/implementation-notes.md`.

- [ ] **Step 5: Commit**

```bash
git add dashboard tests/integration/dashboard docs/implementation-notes.md
git commit -m "feat(reporting): add local research dashboard"
```

### Task 8: Generate daily and weekly research summaries

**Files:**
- Create: `src/bian_quant/reporting/periodic.py`
- Create: `src/bian_quant/reporting/templates/daily.md.j2`
- Create: `src/bian_quant/reporting/templates/weekly.md.j2`
- Create: `configs/reporting.yaml`
- Test: `tests/unit/reporting/test_periodic.py`

- [ ] **Step 1: Write period-boundary tests**

Use fixed UTC timestamps. Assert daily report includes only runs completed in the target day, weekly report includes state transitions and decisions in the target ISO week, and no-run periods produce a valid `无新增实验` report.

- [ ] **Step 2: Implement summaries**

Daily sections: task health, new evidence, failed/blocked runs, data anomalies, decision queue, resource use. Weekly sections: factor funnel, changed evidence, regime performance, approved/rejected/observed decisions, repeated failures, next queued experiments.

- [ ] **Step 3: Add CLI commands**

```bash
bian-quant report daily --date 2026-07-29
bian-quant report weekly --week 2026-W31
```

Write to `var/reports/daily/` and `var/reports/weekly/` with atomic publication.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/reporting/test_periodic.py -q
git add src/bian_quant/reporting configs/reporting.yaml src/bian_quant/cli.py tests/unit/reporting
git commit -m "feat(reporting): generate daily and weekly summaries"
```

## Plan 04 exit gate

- [ ] JSONL events contain run/stage IDs and redact secret-like fields.
- [ ] Incomplete artifact bundles never appear as published runs.
- [ ] Environment and resources are captured without requiring NVIDIA tools.
- [ ] Reports explain evidence, failures, impact, and suggested action.
- [ ] Decisions are append-only and cite evidence.
- [ ] Dashboard API never recomputes research metrics.
- [ ] UI has passed, failed, blocked, and decision-required states.
- [ ] Daily and weekly reports are deterministic for fixed periods.
