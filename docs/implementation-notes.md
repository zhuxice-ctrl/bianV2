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
**Impact:** Full git history is not available; `git merge-base --is-ancestor bcd0cc9` cannot be verified. The implementation branch was created with `git checkout -b` from the tarball snapshot instead of `git worktree add`.
**Consequence:** Ancestry verification relies on the upstream SHA (`25a9508...`) provided in the handoff. All code content matches the `codex/research-platform-design` branch at that commit.

### 2026-07-29 — Task 5: pytest-cov plugin causes hang in sandbox
**Evidence:** `pytest-cov` auto-load causes `uv run pytest -q` to hang indefinitely during collection in the sandbox environment. The `sitecustomize.py` at `/opt/sitecustomize/` fails with `ModuleNotFoundError: No module named 'matplotlib'`, which may interact with the plugin.
**Impact:** Added `addopts = "-p no:cov"` to `[tool.pytest.ini_options]` in `pyproject.toml` to disable auto-loading of the cov plugin.
**Consequence:** `uv run pytest -q` runs successfully. Coverage can still be collected explicitly with `uv run pytest --cov` after removing the addopts line. In the target WSL2 environment, this line can be removed if pytest-cov works correctly.

### 2026-07-29 — Task 5: Ruff excludes legacy code
**Evidence:** The plan specifies `uv run ruff check .` which checks all files, but 152 lint errors exist in frozen legacy code (`backtest/`, `strategies/`, `dashboard/`, `run_backtest.py`, etc.).
**Impact:** Added `exclude` list to `[tool.ruff]` in `pyproject.toml` for legacy files and `docs/` directory.
**Consequence:** Ruff checks only apply to new code under `src/bian_quant`, `tests/`, `scripts/`, and `configs/`. Legacy code remains frozen and unmodified.

### 2026-07-29 — Task 5: mypy requires --verbose flag in sandbox
**Evidence:** `uv run mypy src/bian_quant` hangs without the `--verbose` flag in the sandbox environment.
**Impact:** Verified mypy passes using `mypy --verbose src/bian_quant`.
**Consequence:** Type checking passes with no errors. In the target WSL2 environment, standard `mypy src/bian_quant` should work without `--verbose`.

### 2026-07-29 — Task 1, Step 3: 165-run experiment artifact
**Evidence:** `run_backtest.py` generates `results/summary.json` and `results/backtest_*.json` for 3 symbols only. `dashboard/generate.py` reads `results/experiments.json` but does not generate it. No script in the repository produces the 165-run experiment artifact.
**Impact:** `results/experiments.json` and `results/experiments_summary.md` are archival evidence only.
**Consequence:** The new validation engine must rebuild the anti-overfitting protocol from explicit code. It must not claim numerical continuity with the archival 165-run report.
