# ETH 市场周期加权单币策略 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver one end-to-end, read-only ETHUSDT 4H price-action evaluation comparing fixed-notional and market-cycle-confidence-weighted results from 100U, exposed through the existing research API and page without breaking `research-terminal-v1`.

**Architecture:** Add a generic single-asset evaluation seam behind a new optional response list. A pure evaluator turns OHLCV bars, fixed legacy PA signals, and point-in-time market-cycle states into two EventEngine runs; an artifact writer records canonical inputs/results and hashes; the terminal aggregator discovers the latest ETH artifact defensively; the page renders only the contract node. Future assets/strategies register another evaluator and list item without changing existing cycle, allocation, or comparison fields.

**Tech Stack:** Python 3.11, pandas, Decimal, Pydantic v2, existing EventEngine and legacy PA adapter, pytest, FastAPI, vanilla HTML/CSS/JavaScript.

---

### Task 1: Freeze the single-asset wire contract and compatibility defaults

**Files:**
- Modify: `src/bian_quant/reporting/research_protocol.py`
- Modify: `src/bian_quant/reporting/research_terminal.py`
- Modify: `dashboard/server.py`
- Modify: `docs/contracts/research-terminal-ui-contract.md`
- Test: `tests/unit/reporting/test_research_protocol.py` (create if absent)
- Test: `tests/unit/reporting/test_research_terminal.py`

- [ ] **Step 1: Write contract tests first**

Add tests that construct a `ResearchTerminalResponse` with `single_asset_strategy_evaluations=[]`, serialize it with `model_dump(mode="json")`, and assert the new list is present while all existing v1 keys remain. Add a test for a populated ETH item asserting enum values, nullable win rate, current signal, recommendation, audit hashes and both metric blocks. Add an exception-path server fixture/assertion that the fallback response still contains `market_cycle`, `allocation`, `backtest_comparison`, `partial_availability_impact`, and the new empty list.

- [ ] **Step 2: Run focused tests and confirm failure**

Run:

```powershell
pytest tests/unit/reporting/test_research_protocol.py tests/unit/reporting/test_research_terminal.py -q
```

Expected: FAIL because the response model and fallback do not yet expose the new node.

- [ ] **Step 3: Add immutable Pydantic models**

Define frozen models in `research_protocol.py`:

```python
class SingleAssetStatus(StrEnum):
    OK = "ok"
    MISSING = "missing"
    ERROR = "error"

class CurrentSignal(StrEnum):
    LONG = "long"
    SHORT = "short"
    FLAT = "flat"
    UNAVAILABLE = "unavailable"

class StrategyMetrics(BaseModel):
    final_equity: float
    total_return: float
    max_drawdown: float
    win_rate: float | None
    trade_count: int
    net_profit_after_fees: float
    fees_paid: float

class SingleAssetStrategyEvaluation(BaseModel):
    asset: str
    strategy_id: str
    strategy_version: str
    status: SingleAssetStatus
    sample_start: str | None
    sample_end: str | None
    generated_at: str | None
    runtime_ms: float | None
    input_artifact_sha256: str | None
    result_artifact_sha256: str | None
    artifact_path: str | None
    current_signal: CurrentSignal
    current_signal_time: str | None
    market_cycle: MarketCycle
    risk_multiplier: float
    recommendation_participate: bool
    recommended_cap_usdt: float
    recommendation_reason: str
    baseline: StrategyMetrics
    confidence_weighted: StrategyMetrics
    error_code: str | None
    error_message: str | None
```

Add `single_asset_strategy_evaluations: list[SingleAssetStrategyEvaluation] = Field(default_factory=list)` to `ResearchTerminalResponse`. Update the TypeScript contract with the same required list and exact enum/nullable fields. Keep `schema_version` equal to `research-terminal-v1`; do not make old fields optional or rename them.

- [ ] **Step 4: Make empty and exception responses contract-complete**

Create a shared empty evaluation factory returning an empty list for runs with no ETH input. Update `_empty_response` and `dashboard/server.py`'s catch fallback to include every current response field plus the new list. Do not change HTTP status behavior.

- [ ] **Step 5: Run focused tests and commit**

Run the focused pytest command again, then:

```powershell
git add src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py dashboard/server.py docs/contracts/research-terminal-ui-contract.md tests/unit/reporting/test_research_protocol.py tests/unit/reporting/test_research_terminal.py
git commit -m "feat(research): add single-asset evaluation contract"
```

Expected: all focused tests pass and the serialized response retains all v1 fields.

### Task 2: Build the causal ETH evaluator as a reusable vertical-slice core

**Files:**
- Create: `src/bian_quant/backtest/single_asset_strategy.py`
- Test: `tests/unit/backtest/test_single_asset_strategy.py`

- [ ] **Step 1: Define test fixtures and failing behavior**

Create a deterministic timezone-aware 4H OHLCV fixture with at least 260 rows, a 30+ row popular-universe fixture, and tests asserting: empty input returns `missing`; fixed and weighted runs both start at 100U; weighted signals never exceed baseline notional; signal fills occur only on the next bar; changing a future popular record does not change any earlier multiplier or equity prefix; and repeated runs return identical metrics and hashes.

Run:

```powershell
pytest tests/unit/backtest/test_single_asset_strategy.py -q
```

Expected: FAIL because the evaluator module does not exist.

- [ ] **Step 2: Add explicit evaluator dataclasses and helpers**

Implement frozen dataclasses `StrategyRunMetrics`, `SingleAssetRun`, and `CycleMultiplierPolicy`. Use `Decimal("100")` as the default initial equity, `Decimal("4")` taker fee, `Decimal("10")` slippage, `gross_limit=Decimal("1")`, and `STOP_FIRST`. `StrategyRunMetrics` must compute final equity, total return, annualized volatility (4H periods `365*6`), max drawdown, nullable win rate, trade count, total net PnL from `Trade.pnl`, and fees from `Trade.fee_paid`.

- [ ] **Step 3: Convert OHLCV to existing events without future leakage**

Require a sorted unique UTC `DatetimeIndex` with `open/high/low/close/volume`. Convert each row to `Bar(timestamp=close_time, ...)`, call `adapt_confluence_signals(frame, asset="ETHUSDT", horizon="4h")`, and derive ATR stop/target distances from the same signal bar using `strategies.price_action.confluence_signals`. Build `SignalEvent(timestamp=decision_time, available_time=decision_time, direction, stop_distance=1.5*ATR, target_distance=3*stop_distance)`; never use the next bar’s close to construct a signal.

- [ ] **Step 4: Apply cycle multiplier only to weighted signal notionals**

For each signal decision timestamp, call `classify_market_cycle(_records_through(records, decision_time))`. Map `(label, confidence)` to `1.0`, `0.70`, `0.40`, or `0.0` using the fixed thresholds in the design. Baseline signals use `notional=Decimal("100")`; weighted signals use `notional=Decimal("100") * multiplier`. Keep direction, stop distance, target distance, fee and slippage identical. Return the latest signal and cycle state separately for page recommendation mapping.

- [ ] **Step 5: Run focused tests and commit**

Run the focused test command. If one causal test fails, make no more than three targeted attempts; after the third, record the failure, impact, reproduction and next step in the final handoff. On success:

```powershell
git add src/bian_quant/backtest/single_asset_strategy.py tests/unit/backtest/test_single_asset_strategy.py
git commit -m "feat(research): add causal ETH strategy evaluator"
```

### Task 3: Persist and discover auditable ETH artifacts

**Files:**
- Create: `src/bian_quant/reporting/single_asset_artifacts.py`
- Modify: `src/bian_quant/reporting/research_terminal.py`
- Test: `tests/unit/reporting/test_single_asset_artifacts.py`
- Test: `tests/unit/reporting/test_research_terminal.py`

- [ ] **Step 1: Write artifact and discovery tests**

Test canonical JSON hashing is invariant to dictionary insertion order; writing then loading an artifact preserves the result hash; a missing artifact maps to `status="missing"`; malformed JSON maps to `status="error"` with `error_code="SINGLE_ASSET_ARTIFACT_INVALID"`; and an ETH artifact is selected from `<run_dir>/single-asset-strategies/ethusdt-legacy-pa-confluence.json` without changing a passed parent run.

- [ ] **Step 2: Implement canonical artifact helpers**

Add `canonical_json_bytes(payload)`, `canonical_sha256(payload)`, `write_single_asset_artifact(path, payload)`, and `load_single_asset_artifact(path)`. Canonicalize with sorted keys, compact separators, UTF-8, and no synthetic data. The payload must include contract version, asset/strategy identifiers, fixed cost and signal parameters, sample bounds, input OHLCV hash, market-cycle evidence hash, runtime, recommendation, both metrics, and result hash.

- [ ] **Step 3: Add the ETH evaluator adapter and defensive mapper**

Add `build_eth_single_asset_evaluation(run_dir, repo_root, raw_root, popular_artifacts_dir)` to locate `data/ETHUSDT_4h.csv` first, then any canonical/raw 4H ETH source already present; never download. Run the core evaluator, write the artifact atomically, and map it to `SingleAssetStrategyEvaluation`. If no valid source exists, return a complete `missing` item with 100U zero metrics and a human-readable reason. If evaluation or parsing raises, return `error` with stable error code and no recommendation.

- [ ] **Step 4: Wire the adapter into the terminal aggregator**

Call the adapter inside `build_research_terminal_response` after cycle/allocation/backtest assembly. Keep it isolated from `_run_status_to_state`: a single-asset error must not turn `passed` into `blocked`. For no run, return `[]`; for a passed run with the checked-in ETH CSV, return exactly one ETH item. Store the relative artifact path and both SHA-256 values.

- [ ] **Step 5: Run tests and commit**

Run:

```powershell
pytest tests/unit/reporting/test_single_asset_artifacts.py tests/unit/reporting/test_research_terminal.py -q
```

Then commit the artifact and aggregator changes after all tests pass.

### Task 4: Render the ETH comparison in the read-only research page

**Files:**
- Modify: `dashboard/research.html`
- Test: `tests/unit/reporting/test_research_terminal.py` (payload assertions)
- Test: `tests/integration/dashboard/test_research_page.py` (create if absent)

- [ ] **Step 1: Add a page smoke fixture/test**

Serve a representative response containing an `ok` ETH item and assert the HTML contains `ETH 单币策略对比`, `当前是否建议参与`, `原始策略`, `置信度加权`, `胜率`, `手续费后净利润`, and `READ-ONLY · RESEARCH ONLY · NO LIVE TRADING`. Add blocked/missing fixtures and assert no order/run/download controls appear.

- [ ] **Step 2: Add a renderer after the market-cycle section**

Implement `renderSingleAssetEvaluations(data)` in the existing vanilla renderer. For each item, show plain-language recommendation first, then current signal/cycle/multiplier, a two-column metrics table, sample bounds and audit metadata. Use green only for available positive outcomes, red for losses/errors, amber for warnings, and `—` for null win rate. Escape all API text via the existing `escapeHtml` helper.

- [ ] **Step 3: Add missing/error and responsive states**

Render a clear “当前无法评估” card with `error_message` and no suggested amount when status is `missing` or `error`. Reuse existing panel/table CSS and add only a small responsive rule so the metric table scrolls on 390px screens. Keep refresh as a GET-only API reload.

- [ ] **Step 4: Run page tests and commit**

Run the integration smoke test and any existing dashboard checks, then:

```powershell
git add dashboard/research.html tests/integration/dashboard/test_research_page.py tests/unit/reporting/test_research_terminal.py
git commit -m "feat(research): show ETH strategy comparison"
```

### Task 5: End-to-end verification, causal audit and handoff

**Files:**
- Modify: `docs/contracts/research-terminal-ui-contract.md` (only if implementation reveals a precise contract correction)
- Create: `docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md`

- [ ] **Step 1: Run focused quality gates**

Run:

```powershell
pytest tests/unit/backtest/test_single_asset_strategy.py tests/unit/reporting/test_single_asset_artifacts.py tests/unit/reporting/test_research_terminal.py tests/integration/dashboard/test_research_page.py -q
ruff check src/bian_quant/backtest/single_asset_strategy.py src/bian_quant/reporting/single_asset_artifacts.py src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py
mypy src/bian_quant/backtest/single_asset_strategy.py src/bian_quant/reporting/single_asset_artifacts.py src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py
```

Expected: all focused tests, Ruff and mypy pass. Do not alter unrelated `src/bian_quant/backtest/vector.py` line-width history.

- [ ] **Step 2: Validate the API and page without triggering research work**

Start `dashboard/server.py` only if needed, GET `/api/research/latest`, and assert HTTP 200, unchanged v1 fields, one ETH evaluation (or explicit missing/error), `state` unchanged, and artifact hashes present when status is `ok`. Load `/research` and verify the ETH panel and read-only footer. Refresh must issue only another GET.

- [ ] **Step 3: Perform the prefix-causality audit**

Run the evaluator fixture twice: once with records through t and once with arbitrary records after t changed. Assert all multipliers, signal notionals, trades and equity values through t are byte-for-byte equal. Assert the first fill timestamp is strictly later than its signal decision timestamp.

- [ ] **Step 4: Write the evidence handoff and stop at paper-only boundary**

Record commit SHA, run time, sample start/end, input/result/artifact hashes, cost parameters, both metric sets, current recommendation, exact API response state, commands run, and any unresolved issue. If a single issue survives three attempts, record cause, impact, reproduction and next step; do not continue into live or paper order execution.

- [ ] **Step 5: Final commit**

```powershell
git add docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md docs/contracts/research-terminal-ui-contract.md
git commit -m "docs(research): record ETH evaluation evidence"
```

---

## Self-review checklist

- Contract additions are isolated to a default-empty list and preserve every existing v1 key.
- The evaluator changes only signal notional; strategy direction, stops, targets, fill timing and costs remain shared.
- Cycle states are prefix-filtered at each decision timestamp, so future data cannot affect earlier results.
- Missing or malformed ETH inputs are visible as single-asset degradation, never a false passed result or a parent-run blocker.
- Tests cover deterministic hashes, no lookahead, 100U conservation, compatibility, UI text and read-only behavior.
- No step invokes downloads, API keys, order routes or parameter optimization.
