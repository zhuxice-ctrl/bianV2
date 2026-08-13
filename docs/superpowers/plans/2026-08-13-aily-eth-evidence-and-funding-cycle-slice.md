# ETH Evidence and Funding-Aligned Market Cycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce real, reproducible ETH 4H evaluation evidence and extend the causal market-cycle service with Funding alignment, while preserving the read-only research boundary and existing v1 API compatibility.

**Architecture:** Work in two independently releasable vertical slices. Slice A validates and records the existing ETH evaluation end to end without changing strategy rules. Slice B introduces a narrow Funding-alignment read model and extends the market-cycle contract additively; adapters own disk reads, the pure regime service owns scoring, consumers only consume the stable state contract, and the terminal only renders persisted/read-only evidence.

**Tech Stack:** Python 3.11, uv, pandas, pyarrow, Pydantic v2, FastAPI, vanilla JavaScript, pytest, Ruff, mypy.

---

## Operating Contract

- Work only on `codex/eth-cycle-weighted-strategy`; do not switch to `main`.
- Preserve the untracked `.superpowers/` directory. Do not add it to Git.
- Never use exchange credentials, private endpoints, order routes, leverage, websocket code, or data downloads.
- Do not modify frozen legacy code under `backtest/`, `strategies/`, `dashboard/generate.py`, or `run_backtest.py`.
- Preserve `GET /api/research/latest` HTTP 200 behavior and every existing `research-terminal-v1` field. Additive fields require a default and a contract test.
- All market inputs are point-in-time: only records with `available_time <= decision_time` may influence a decision. A later record must not change any earlier result.
- Each run must create a new artifact or update only the explicit evidence document. Do not overwrite historical acquisition, canonical, or research data.
- After three failed attempts at the same defect, stop modifying code and document the command, error, impact, and next action in the evidence document.

## Dependency Boundaries

```text
canonical Funding parquet / popular-universe JSON
  -> data/funding_alignment.py        disk format adapter, immutable daily records
  -> regimes/market_cycle.py          pure causal scoring, evidence hash
  -> backtest/* and reporting/*       consume MarketCycleState only
  -> dashboard/research.html          renders API payload only
```

Forbidden dependency directions: `dashboard -> data/backtest`, `regimes -> reporting/dashboard`, `backtest -> reporting/dashboard`, and `reporting -> exchange/network`.

## Task 0: Establish a clean verification baseline

**Files:** no code changes.

- [ ] **Step 1: Confirm branch and local state**

```powershell
git branch --show-current
git status --short --branch
git log --oneline --decorate -4
```

Expected: branch is `codex/eth-cycle-weighted-strategy`; `2235eb6` is HEAD; only `.superpowers/` may be untracked.

- [ ] **Step 2: Run the currently required ETH gates**

```powershell
uv run pytest -p no:cov tests/unit/reporting/test_research_protocol.py tests/unit/reporting/test_research_terminal.py tests/unit/backtest/test_single_asset_strategy.py tests/unit/reporting/test_single_asset_artifacts.py tests/integration/dashboard/test_research_page.py -q
uv run ruff check src/bian_quant/backtest/single_asset_strategy.py src/bian_quant/reporting/single_asset_artifacts.py src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py
uv run mypy src/bian_quant
git diff --check
```

Expected: focused pytest passes, Ruff and mypy pass, and `git diff --check` exits 0. Record the exact result in the Task 1 evidence document.

## Task 1: ETH real-data evidence and API/browser acceptance slice

**Files:**
- Modify: `docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md`
- Test: `tests/unit/backtest/test_single_asset_strategy.py`
- Test: `tests/unit/reporting/test_single_asset_artifacts.py`
- Test: `tests/unit/reporting/test_research_terminal.py`
- Test: `tests/integration/dashboard/test_research_page.py`

- [ ] **Step 1: Add a real-data evidence test that is skipped only when the tracked CSV is absent**

Add this test to `tests/unit/backtest/test_single_asset_strategy.py`:

```python
def test_checked_in_eth_csv_evaluates_deterministically() -> None:
    repo_root = Path(__file__).resolve().parents[3]
    source = repo_root / "data" / "ETHUSDT_4h.csv"
    if not source.is_file():
        pytest.skip("checked-in ETH 4H source is unavailable")
    result_one = evaluate_eth_strategy(ohlcv_path=source, popular_universe_dir=repo_root / "var" / "artifacts" / "dual-horizon-popular-v1" / "popular-universe")
    result_two = evaluate_eth_strategy(ohlcv_path=source, popular_universe_dir=repo_root / "var" / "artifacts" / "dual-horizon-popular-v1" / "popular-universe")
    assert result_one.status == "ok"
    assert result_one.result_sha256 == result_two.result_sha256
    assert result_one.baseline is not None
    assert result_one.confidence_weighted is not None
```

- [ ] **Step 2: Run the test to establish the current outcome**

```powershell
uv run pytest -p no:cov tests/unit/backtest/test_single_asset_strategy.py::test_checked_in_eth_csv_evaluates_deterministically -q
```

Expected: PASS with a deterministic result, or SKIP only when the CSV is absent. Any `missing`/`error` result with an existing CSV is a defect; fix the evaluator before proceeding.

- [ ] **Step 3: Run the evaluation through the same public aggregator used by the API**

```powershell
@'
from pathlib import Path
from bian_quant.reporting.research_terminal import build_research_terminal_response

root = Path.cwd()
response = build_research_terminal_response(
    root / "configs" / "experiments" / "popular_universe_100u.yaml",
    repo_root=root,
)
item = response.single_asset_strategy_evaluations[0]
assert item.asset == "ETHUSDT"
assert item.status.value == "ok"
assert item.result_artifact_sha256
assert item.artifact_path
print(item.model_dump_json(indent=2))
'@ | uv run python -
```

Expected: one `ok` ETH item, an artifact under the latest run directory, populated sample bounds, hashes, recommendation, and both metric blocks. Do not manually construct the artifact payload.

- [ ] **Step 4: Add and run byte-level prefix causality coverage using the real artifact shape**

Add a test that evaluates the fixture twice, changes only popular-universe rows with `selection_time > cutoff`, and asserts the JSON-normalized `signal_multipliers`, baseline trades, weighted trades, and both equity prefixes through `cutoff` are identical. The test must explicitly assert every entry fill is later than its signal decision time.

```powershell
uv run pytest -p no:cov tests/unit/backtest/test_single_asset_strategy.py -q
```

Expected: all evaluator tests pass; future evidence changes cannot alter any prior output.

- [ ] **Step 5: Verify HTTP and rendered page without starting research work**

Start the server in a hidden background process, then query it:

```powershell
$server = Start-Process -FilePath "uv" -ArgumentList "run", "python", "dashboard/server.py" -WorkingDirectory $PWD -WindowStyle Hidden -PassThru
try {
  Start-Sleep -Seconds 2
  $api = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/api/research/latest
  if ($api.StatusCode -ne 200) { throw "API status $($api.StatusCode)" }
  $payload = $api.Content | ConvertFrom-Json
  if ($payload.schema_version -ne "research-terminal-v1") { throw "schema regression" }
  if ($payload.single_asset_strategy_evaluations.Count -ne 1) { throw "missing ETH evaluation" }
  $page = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8787/research
  if ($page.StatusCode -ne 200 -or $page.Content -notmatch "ETH 单币策略对比") { throw "ETH panel absent" }
} finally {
  Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue
}
```

Expected: both endpoints return 200; API state is unchanged by GET; page contains the ETH panel and no new order/run/download control.

- [ ] **Step 6: Record measured evidence and commit**

Replace stale sandbox-language in `docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md` with the actual Python version, command results, HEAD SHA, artifact path, input/result hashes, exact sample start/end, both metrics, recommendation, API state, HTTP results, and prefix-causality result. Keep an explicit `Not approved for paper/live trading` conclusion.

```powershell
git add tests/unit/backtest/test_single_asset_strategy.py docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md
git commit -m "test(research): verify ETH evaluation on local evidence"
```

## Task 2: Freeze the Funding-alignment contract

**Files:**
- Create: `src/bian_quant/data/funding_alignment.py`
- Create: `tests/unit/data/test_funding_alignment.py`
- Modify: `src/bian_quant/regimes/market_cycle.py`
- Modify: `tests/unit/regimes/test_market_cycle.py`
- Modify: `docs/contracts/research-terminal-ui-contract.md`

- [ ] **Step 1: Write failing data-contract tests**

Create immutable model tests for the following contract:

```python
@dataclass(frozen=True)
class FundingAlignmentRecord:
    decision_time: datetime
    available_time: datetime
    member_count: int
    positive_rate_share: float
    median_rate: float
    coverage_ratio: float
    source_sha256: str
```

Tests must reject naive timestamps, `available_time > decision_time`, shares/coverage outside `[0, 1]`, negative member count, and non-64-character lowercase SHA-256. A loader fixture with a future `available_time` must exclude that row at an earlier decision time.

- [ ] **Step 2: Implement the narrow canonical Funding adapter**

`src/bian_quant/data/funding_alignment.py` may read only local canonical Funding Parquet under the configured `canonical_root`. It must accept an explicit `as_of` and optional asset list, discard records with `available_time > as_of`, group by UTC date, calculate member count, share of positive funding rates, median funding rate, coverage ratio, and a deterministic SHA-256 of included file content hashes. It must never read the dashboard, strategy, exchange, or network modules.

Use a public function with this exact signature:

```python
def build_daily_funding_alignment(
    canonical_root: Path,
    *,
    assets: tuple[str, ...],
    as_of: datetime,
) -> tuple[FundingAlignmentRecord, ...]:
```

- [ ] **Step 3: Run data-contract tests**

```powershell
uv run pytest -p no:cov tests/unit/data/test_funding_alignment.py -q
uv run ruff check src/bian_quant/data/funding_alignment.py tests/unit/data/test_funding_alignment.py
uv run mypy src/bian_quant/data/funding_alignment.py
```

Expected: all pass. Commit this adapter independently.

```powershell
git add src/bian_quant/data/funding_alignment.py tests/unit/data/test_funding_alignment.py
git commit -m "feat(data): add causal funding alignment adapter"
```

## Task 3: Extend market-cycle scoring additively

**Files:**
- Modify: `src/bian_quant/regimes/market_cycle.py`
- Modify: `tests/unit/regimes/test_market_cycle.py`
- Modify: `tests/unit/backtest/test_market_cycle_comparison.py`
- Modify: `tests/unit/backtest/test_single_asset_strategy.py`

- [ ] **Step 1: Write failing regime tests before changing scoring**

Add tests that pass `funding_alignment: tuple[FundingAlignmentRecord, ...] | None` to `classify_market_cycle`. Require these outcomes:

```python
state = classify_market_cycle(popular, funding_alignment=funding)
assert "funding_alignment" in state.evidence
assert state.evidence["funding_alignment"] == expected_score
assert state.evidence_sha256 != without_funding.evidence_sha256
```

The tests must also prove: no Funding input preserves current outputs; insufficient Funding coverage yields `funding_alignment=None` without blocking cycle classification; adding future Funding rows cannot change a prefix state; strongly positive, broad Funding reduces bullish confidence or raises risk-off probability; strongly negative, broad Funding increases bullish evidence only when breadth/OI inputs are not risk-off.

- [ ] **Step 2: Implement a backwards-compatible scoring extension**

Change the exact public signature to:

```python
def classify_market_cycle(
    records: pd.DataFrame,
    *,
    funding_alignment: tuple[FundingAlignmentRecord, ...] | None = None,
    min_observations: int = 30,
    lookback_days: int = 30,
) -> MarketCycleState:
```

For matching `decision_time`, include only alignment records whose `available_time <= decision_time`. Compute an alignment score in `[-1, 1]`: broad positive funding is crowding/risk-off pressure; broad negative funding is a contrarian bullish input; low coverage is missing. Add at most `0.10` absolute score contribution, record the numeric contribution and source SHA in `evidence`, and include it in the deterministic evidence hash. Preserve labels, confidence range, existing probabilities, and all callers when `funding_alignment=None`.

- [ ] **Step 3: Wire the adapter at the composition root only**

Only `src/bian_quant/reporting/research_terminal.py` and the explicit CLI/backtest composition functions may build alignment records. Pass the records into the regime service; do not make `market_cycle.py` read Parquet directly. If the adapter fails, pass `None`, retain the existing market state, and expose `funding_alignment=null` in evidence rather than changing the parent research state.

- [ ] **Step 4: Run causal consumers and commit**

```powershell
uv run pytest -p no:cov tests/unit/data/test_funding_alignment.py tests/unit/regimes/test_market_cycle.py tests/unit/backtest/test_market_cycle_comparison.py tests/unit/backtest/test_single_asset_strategy.py tests/unit/reporting/test_research_terminal.py -q
uv run ruff check src/bian_quant/data/funding_alignment.py src/bian_quant/regimes/market_cycle.py src/bian_quant/reporting/research_terminal.py
uv run mypy src/bian_quant
```

Expected: all pass. Existing ETH and three-coin consumers produce the same result for `funding_alignment=None`; only supplied causal Funding evidence changes the state.

```powershell
git add src/bian_quant/regimes/market_cycle.py src/bian_quant/reporting/research_terminal.py tests/unit/regimes/test_market_cycle.py tests/unit/backtest/test_market_cycle_comparison.py tests/unit/backtest/test_single_asset_strategy.py
git commit -m "feat(regimes): score causal funding alignment"
```

## Task 4: Additive wire contract and read-only terminal slice

**Files:**
- Modify: `src/bian_quant/reporting/research_protocol.py`
- Modify: `src/bian_quant/reporting/research_terminal.py`
- Modify: `dashboard/server.py`
- Modify: `dashboard/research.html`
- Modify: `docs/contracts/research-terminal-ui-contract.md`
- Modify: `tests/unit/reporting/test_research_protocol.py`
- Modify: `tests/unit/reporting/test_research_terminal.py`
- Modify: `tests/integration/dashboard/test_research_page.py`

- [ ] **Step 1: Freeze an additive `FundingAlignment` wire model**

Add this frozen Pydantic model:

```python
class FundingAlignment(BaseModel):
    model_config = ConfigDict(frozen=True)
    score: float | None
    positive_rate_share: float | None
    median_rate: float | None
    coverage_ratio: float | None
    source_sha256: str | None
    status: str  # "ok" | "missing" | "error"
```

Add `funding_alignment: FundingAlignment` to `MarketCycle`. Its empty/fallback value is `score=None`, all data fields `None`, `source_sha256=None`, `status="missing"`. Keep schema version as `research-terminal-v1`.

- [ ] **Step 2: Write compatibility and fallback tests**

Tests must serialize an old-style response with a default-missing Funding node, an `ok` node, and a server exception fallback. Assert all old keys remain and no value allows the UI to report a false `passed` state.

- [ ] **Step 3: Render evidence without creating a control**

Update `renderMarketCycle` to show Funding alignment only when `status="ok"`: positive-rate share, coverage, and a neutral/amber risk interpretation. When missing/error, show `—` in audit details and no strategy recommendation change. Escape all API text through `escapeHtml`; do not add buttons except the existing GET refresh control.

- [ ] **Step 4: Verify API and page**

```powershell
uv run pytest -p no:cov tests/unit/reporting/test_research_protocol.py tests/unit/reporting/test_research_terminal.py tests/integration/dashboard/test_research_page.py -q
uv run ruff check src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py
uv run mypy src/bian_quant
```

Run the Task 1 HTTP script again. Expected: HTTP 200, `schema_version="research-terminal-v1"`, an additive `market_cycle.funding_alignment` node, and no order/run/download UI.

- [ ] **Step 5: Commit the vertical slice**

```powershell
git add src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py dashboard/server.py dashboard/research.html docs/contracts/research-terminal-ui-contract.md tests/unit/reporting/test_research_protocol.py tests/unit/reporting/test_research_terminal.py tests/integration/dashboard/test_research_page.py
git commit -m "feat(research): expose funding-aligned cycle evidence"
```

## Task 5: Evidence, complete gates, and merge readiness

**Files:**
- Modify: `docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md`
- Create: `docs/evidence/2026-08-13-funding-aligned-market-cycle-run.md`
- Modify: `docs/implementation-notes.md`

- [ ] **Step 1: Create Funding evidence document**

Record the implementation SHA, canonical Funding file count, asset count, date range, `as_of`, any excluded records with reasons, adapter source SHA, latest cycle evidence hash before/after Funding, latest label/confidence/probabilities, all test/gate commands, and a clear statement that this is research evidence, not a trading approval.

- [ ] **Step 2: Run complete offline quality gates**

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy src/bian_quant
uv run pytest -p no:cov -q
git diff --check
```

Expected: every command exits 0. If the full suite hits the known Windows output failure, rerun with `-p no:cov`, capture the exact failure, then run the repository test groups separately. Do not claim the full suite passed unless the command itself exits 0.

- [ ] **Step 3: Update implementation notes and commit evidence**

Add a dated `Implementation Notes` entry documenting the actual result and any intentional contract deviation. Do not revise historical evidence.

```powershell
git add docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md docs/evidence/2026-08-13-funding-aligned-market-cycle-run.md docs/implementation-notes.md
git commit -m "docs(research): record funding-aligned cycle evidence"
```

- [ ] **Step 4: Review merge conditions, then stop for human approval**

```powershell
git log --oneline main..HEAD
git diff --stat main...HEAD
git status --short --branch
```

Merge is permitted only when Task 1 real-data evidence is `ok`, all relevant tests/Ruff/mypy/diff gates pass, API/page smoke checks pass, no security-boundary code changed, and the evidence explicitly says the result is not a paper/live approval. Do not merge automatically. Push the branch and report the evidence paths, gate outputs, unresolved items, and merge recommendation for human approval.

## Explicit Non-goals

- No BTC/BNB single-asset evaluators in this plan.
- No parameter search, strategy optimization, model training, Kronos integration, factor promotion, or holdout opening.
- No changes to the current 100U shared allocation thresholds.
- No paper-order execution or live trading.

## Self-review Checklist

- Every new cross-cutting capability has a data contract, a pure service boundary, a composition root, an additive wire model, and focused tests.
- Funding readers never live in `regimes`, `backtest`, `reporting`, or `dashboard`.
- All state changes preserve prefix causality and deterministic hashes.
- Each vertical slice can be tested and committed independently.
- Missing Funding evidence degrades gracefully; it never fabricates a passing research result.
- The branch is left ready for review, not automatically merged.

