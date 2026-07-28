# Foundation and Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a locked Python environment and package skeleton, reproduce the executable legacy PA baseline, and explicitly classify the unreproducible 165-run artifact as archival evidence.

**Architecture:** New code lives under `src/bian_quant` and treats existing root scripts as frozen legacy inputs. A compatibility runner calls the current PA functions without changing their calculations, while golden tests compare exact metrics from the tracked CSV snapshot.

**Tech Stack:** Python 3.11, uv, Pydantic, Typer, pytest, Ruff, mypy, pandas, NumPy.

---

### Task 1: Create the implementation worktree and preflight record

**Files:**
- Create: `docs/implementation-notes.md`

- [ ] **Step 1: Create the implementation worktree**

Run from the existing repository:

```bash
git worktree add -b codex/research-platform-implementation ../bianV2-research-implementation codex/research-platform-design
cd ../bianV2-research-implementation
```

Expected: `git status --short --branch` prints `## codex/research-platform-implementation` with no changes.

- [ ] **Step 2: Record immutable starting points**

Create `docs/implementation-notes.md` with:

```markdown
# Implementation Notes

## Immutable starting points

- Legacy main: `59e8bcb2876506b0076751def71d95b6ec81b6bc`
- Round 8 archive: `d413eda3df7ae2aca0b29ae732171ea0346b5ec7`
- Approved design: `bcd0cc9`
- Live trading is out of scope.

## Deviations

Record each approved deviation from the implementation plans here with date, task, evidence, and consequence.
```

- [ ] **Step 3: Verify the legacy artifact limitation**

Run:

```bash
git ls-tree -r --name-only 59e8bcb | grep -E 'experiment|backtest'
tar -tf dashboard_v2_1.zip | grep -E 'experiment|backtest' || true
```

Expected: tracked result files exist, but no script that generated the 165-run experiment artifact exists. Record this fact under `## Deviations` as an evidence limitation, not an implementation failure.

- [ ] **Step 4: Commit**

```bash
git add docs/implementation-notes.md
git commit -m "docs: record research platform starting points"
```

### Task 2: Lock Python and project dependencies

**Files:**
- Create: `.python-version`
- Create: `pyproject.toml`
- Create: `uv.lock`
- Modify: `.gitignore`
- Test: `tests/unit/test_package_import.py`

- [ ] **Step 1: Write the failing package import test**

Create `tests/unit/test_package_import.py`:

```python
def test_package_version_is_exposed() -> None:
    import bian_quant

    assert bian_quant.__version__ == "0.1.0"
```

- [ ] **Step 2: Create `.python-version`**

```text
3.11
```

- [ ] **Step 3: Create `pyproject.toml`**

```toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "bian-quant"
version = "0.1.0"
description = "Reproducible crypto quantitative research platform"
requires-python = ">=3.11,<3.12"
dependencies = [
  "duckdb>=1.3,<2",
  "numpy>=2.0,<3",
  "pandas>=2.2,<3",
  "polars>=1.30,<2",
  "pyarrow>=20,<21",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.10,<3",
  "pyyaml>=6.0,<7",
  "rich>=14,<15",
  "scipy>=1.15,<2",
  "typer>=0.16,<1",
]

[project.optional-dependencies]
dashboard = ["fastapi>=0.116,<1", "jinja2>=3.1,<4", "plotly>=6,<7", "uvicorn>=0.35,<1"]
ml = ["lightgbm>=4.6,<5", "scikit-learn>=1.7,<2"]
models = ["einops>=0.8,<1", "huggingface-hub>=0.33,<1", "safetensors>=0.6,<1", "torch>=2.7,<3", "tqdm>=4.67,<5"]
dev = ["hypothesis>=6.135,<7", "mypy>=1.16,<2", "pytest>=8.4,<9", "pytest-cov>=6.2,<7", "ruff>=0.12,<1"]

[project.scripts]
bian-quant = "bian_quant.cli:app"

[tool.hatch.build.targets.wheel]
packages = ["src/bian_quant"]

[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["models: requires optional model dependencies or weights", "network: requires network access"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]

[tool.mypy]
python_version = "3.11"
strict = true
packages = ["bian_quant"]
```

- [ ] **Step 4: Merge ignore rules instead of replacing the legacy file**

Append these rules to `.gitignore`, preserving all existing rules:

```gitignore
.venv/
venv/
.env
.env.*
!.env.example
*.pem
*.key
build/
dist/
.cache/
logs/
var/
*.duckdb
*.duckdb.wal
*.sqlite
*.sqlite-journal
*.safetensors
*.pt
*.pth
```

- [ ] **Step 5: Lock and install**

```bash
uv lock
uv sync --extra dev
uv run pytest tests/unit/test_package_import.py -q
```

Expected: FAIL with `ModuleNotFoundError: No module named 'bian_quant'`.

- [ ] **Step 6: Commit the failing test and environment**

```bash
git add .python-version pyproject.toml uv.lock .gitignore tests/unit/test_package_import.py
git commit -m "build: lock research platform environment"
```

### Task 3: Add the package skeleton, settings, paths, and CLI

**Files:**
- Create: `src/bian_quant/__init__.py`
- Create: `src/bian_quant/cli.py`
- Create: `src/bian_quant/config.py`
- Create: `src/bian_quant/paths.py`
- Create: `configs/base.yaml`
- Test: `tests/unit/test_config.py`
- Test: `tests/unit/test_paths.py`

- [ ] **Step 1: Write failing settings and path tests**

Create `tests/unit/test_config.py`:

```python
from pathlib import Path

from bian_quant.config import AppConfig, load_config


def test_load_base_config_resolves_repo_relative_paths(tmp_path: Path) -> None:
    config_file = tmp_path / "base.yaml"
    config_file.write_text("var_dir: var\ntimezone: UTC\n", encoding="utf-8")

    config = load_config(config_file, repo_root=tmp_path)

    assert config == AppConfig(var_dir=tmp_path / "var", timezone="UTC")
```

Create `tests/unit/test_paths.py`:

```python
from pathlib import Path

from bian_quant.paths import ProjectPaths


def test_project_paths_have_separate_evidence_directories(tmp_path: Path) -> None:
    paths = ProjectPaths.from_var_dir(tmp_path / "var")

    assert paths.raw == tmp_path / "var" / "lake" / "raw"
    assert paths.canonical == tmp_path / "var" / "lake" / "canonical"
    assert paths.research == tmp_path / "var" / "lake" / "research"
    assert paths.artifacts == tmp_path / "var" / "artifacts"
```

- [ ] **Step 2: Confirm both tests fail**

```bash
uv run pytest tests/unit/test_config.py tests/unit/test_paths.py -q
```

Expected: import errors for missing modules.

- [ ] **Step 3: Implement the package files**

Create `src/bian_quant/__init__.py`:

```python
__version__ = "0.1.0"
```

Create `src/bian_quant/config.py`:

```python
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class AppConfig(BaseModel):
    var_dir: Path
    timezone: str = "UTC"


def load_config(path: Path, *, repo_root: Path) -> AppConfig:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    var_dir = Path(raw["var_dir"])
    if not var_dir.is_absolute():
        var_dir = repo_root / var_dir
    return AppConfig(var_dir=var_dir, timezone=raw.get("timezone", "UTC"))
```

Create `src/bian_quant/paths.py`:

```python
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    var: Path
    raw: Path
    canonical: Path
    research: Path
    artifacts: Path
    logs: Path
    registry: Path

    @classmethod
    def from_var_dir(cls, var: Path) -> "ProjectPaths":
        return cls(
            var=var,
            raw=var / "lake" / "raw",
            canonical=var / "lake" / "canonical",
            research=var / "lake" / "research",
            artifacts=var / "artifacts",
            logs=var / "logs",
            registry=var / "registry.sqlite",
        )

    def create(self) -> None:
        for path in (self.raw, self.canonical, self.research, self.artifacts, self.logs):
            path.mkdir(parents=True, exist_ok=True)
```

Create `src/bian_quant/cli.py`:

```python
from pathlib import Path

import typer

from bian_quant import __version__
from bian_quant.config import load_config
from bian_quant.paths import ProjectPaths

app = typer.Typer(no_args_is_help=True)


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def init(config: Path = Path("configs/base.yaml")) -> None:
    repo_root = Path.cwd()
    settings = load_config(config, repo_root=repo_root)
    paths = ProjectPaths.from_var_dir(settings.var_dir)
    paths.create()
    typer.echo(str(paths.var))
```

Create `configs/base.yaml`:

```yaml
var_dir: var
timezone: UTC
```

- [ ] **Step 4: Run tests and CLI smoke test**

```bash
uv run pytest tests/unit/test_package_import.py tests/unit/test_config.py tests/unit/test_paths.py -q
uv run bian-quant version
uv run bian-quant init
```

Expected: tests pass, version is `0.1.0`, and ignored `var/` directories are created.

- [ ] **Step 5: Commit**

```bash
git add src/bian_quant configs/base.yaml tests/unit
git commit -m "feat: add research platform package skeleton"
```

### Task 4: Freeze and reproduce the executable PA baseline

**Files:**
- Create: `src/bian_quant/legacy/__init__.py`
- Create: `src/bian_quant/legacy/pa_baseline.py`
- Create: `tests/golden/baseline_summary.json`
- Create: `tests/integration/test_legacy_pa_baseline.py`
- Create: `docs/evidence/baseline-0.md`

- [ ] **Step 1: Copy the tracked expected summary into the golden fixture**

```bash
mkdir -p tests/golden docs/evidence
cp results/summary.json tests/golden/baseline_summary.json
```

Do not regenerate the expected file from the code under test.

- [ ] **Step 2: Write the failing baseline replay test**

Create `tests/integration/test_legacy_pa_baseline.py`:

```python
import json
from pathlib import Path

from bian_quant.legacy.pa_baseline import replay_all


def test_legacy_pa_metrics_match_tracked_golden() -> None:
    repo = Path(__file__).parents[2]
    expected = json.loads((repo / "tests/golden/baseline_summary.json").read_text(encoding="utf-8"))

    actual = replay_all(repo)

    assert actual == expected
```

- [ ] **Step 3: Confirm failure**

```bash
uv run pytest tests/integration/test_legacy_pa_baseline.py -q
```

Expected: missing `bian_quant.legacy.pa_baseline`.

- [ ] **Step 4: Implement the compatibility runner without changing legacy math**

Create `src/bian_quant/legacy/__init__.py` as an empty module.

Create `src/bian_quant/legacy/pa_baseline.py`:

```python
from pathlib import Path
from typing import Any

import pandas as pd


def replay_all(repo_root: Path) -> dict[str, Any]:
    from backtest.engine import run_backtest
    from strategies.price_action import confluence_signals

    results: dict[str, dict[str, Any]] = {}
    for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        path = repo_root / "data" / f"{symbol}_4h.csv"
        frame = pd.read_csv(path, parse_dates=["datetime"]).set_index("datetime").sort_index()
        signals = confluence_signals(frame)
        metrics = run_backtest(signals, initial_capital=10_000.0, risk_pct=0.02)["metrics"]
        results[symbol] = {
            "total_return_pct": metrics["total_return_pct"],
            "win_rate_pct": metrics["win_rate_pct"],
            "profit_factor": metrics["profit_factor"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "total_trades": metrics["total_trades"],
            "final_equity": metrics["final_equity"],
        }
    return {
        "strategy": "价格行为学融合策略 (Price Action Confluence)",
        "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
        "interval": "4h",
        "initial_capital": 10_000.0,
        "risk_per_trade": 0.02,
        "fee": 0.0004,
        "results": results,
    }
```

- [ ] **Step 5: Run the replay test**

```bash
uv run pytest tests/integration/test_legacy_pa_baseline.py -q
```

Expected: PASS. If it fails, inspect the exact metric delta and fix import/data handling only; do not change golden values or legacy strategy math.

- [ ] **Step 6: Document evidence status**

Create `docs/evidence/baseline-0.md`:

```markdown
# Baseline-0 Evidence Status

## Reproducible

The BTC/ETH/BNB 4h Price Action baseline is replayed from the tracked CSV snapshot and compared with `tests/golden/baseline_summary.json`.

## Archival only

`results/experiments.json` and `results/experiments_summary.md` describe 165 historical runs, but `main@59e8bcb` and `dashboard_v2_1.zip` do not contain the generator script. These files are useful negative evidence, especially the failed OOS results, but are not treated as reproducible experiment outputs.

## Consequence

The new validation engine must rebuild the anti-overfitting protocol from explicit code and manifests. It must not claim numerical continuity with the archival 165-run report.
```

- [ ] **Step 7: Commit**

```bash
git add src/bian_quant/legacy tests/golden tests/integration docs/evidence
git commit -m "test: freeze executable PA baseline evidence"
```

### Task 5: Add global quality checks and operator entry points

**Files:**
- Create: `scripts/check.sh`
- Create: `scripts/check.ps1`
- Modify: `README.md`

- [ ] **Step 1: Create Linux/WSL quality script**

Create `scripts/check.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail
uv run ruff check .
uv run ruff format --check .
uv run mypy src/bian_quant
uv run pytest -q
git diff --check
```

- [ ] **Step 2: Create PowerShell quality script**

Create `scripts/check.ps1`:

```powershell
$ErrorActionPreference = "Stop"
uv run ruff check .
uv run ruff format --check .
uv run mypy src/bian_quant
uv run pytest -q
git diff --check
```

- [ ] **Step 3: Update README without deleting the legacy description**

Add a new top section containing:

```markdown
## Research platform development

The reproducible research platform is being built alongside the frozen PA baseline. The PA system remains Baseline-0; new data, factors, models and backtests must use the common contracts under `src/bian_quant`.

```bash
uv sync --extra dev
uv run bian-quant init
bash scripts/check.sh
```

See `docs/superpowers/specs/2026-07-29-quant-research-platform-design.md` for approved scope.
```

- [ ] **Step 4: Run all foundation checks**

```bash
bash scripts/check.sh
git status --short
```

Expected: all checks pass; only intended files are modified; `var/` is ignored.

- [ ] **Step 5: Commit**

```bash
git add scripts README.md
git commit -m "build: add reproducible quality entry points"
```

## Plan 00 exit gate

- [ ] Clean install succeeds with `uv sync --extra dev`.
- [ ] `uv run bian-quant init` creates only ignored local state.
- [ ] PA baseline replay exactly matches tracked metrics.
- [ ] The 165-run report is labeled archival-only, not falsely reproducible.
- [ ] Linux/WSL and PowerShell quality scripts pass.
- [ ] Working tree is clean.
