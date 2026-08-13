# Market Cycle Confidence and 100U Allocation Implementation Plan

> **For agentic workers:** This plan is executed inline in one session. Each task is independently testable; failures are attempted at most three times before being recorded in the final issue list.

**Goal:** Complete the next five research slices: start the valid popular-universe sample at 2024-12-28, calculate a causal market-cycle confidence, cap the shared BTC/ETH/BNB exposure, run a 100U comparison backtest, and expose the result in the research terminal.

**Architecture:** Keep acquisition history from 2024-07-01, but exclude the pre-warmup dates from popular-universe publication. Add a pure, deterministic cycle-confidence service consuming daily universe artifacts and market breadth evidence. Apply its confidence-to-cap mapping to a shared three-asset portfolio allocator, compare baseline versus confidence-weighted results in an offline backtest, and expose only read-only evidence through the existing API/page.

**Tech Stack:** Python 3.11, pandas, Pydantic v2, pytest, FastAPI, vanilla HTML/CSS/JavaScript.

### Task 1: Valid popular-universe start and audit

**Files:** modify `src/bian_quant/data/acquisition.py`, `src/bian_quant/data/dual_horizon.py`, `configs/experiments/popular_universe_100u.yaml`; test `tests/unit/data/test_acquisition.py`, `tests/integration/data/test_dual_horizon_pipeline.py`.

- [ ] Add `popular_universe_start` as an optional timezone-aware config field, defaulting to `macro_start`, and validate it is not earlier than `micro_start`.
- [ ] Set production config `popular_universe_start: 2024-12-28T00:00:00Z`.
- [ ] Start daily popular-universe iteration at this boundary while preserving raw/canonical acquisition from `macro_start`.
- [ ] Persist `popular_universe_start`, excluded warmup date range, and exact daily coverage in both artifacts and terminal run metadata.
- [ ] Test that 2024-07 through 2024-12-27 are warmup-only, 2024-12-28 is evaluated, and a later shortage still blocks.
- [ ] Run focused tests and commit.

### Task 2: Causal market-cycle confidence

**Files:** create `src/bian_quant/regimes/market_cycle.py`; test `tests/unit/regimes/test_market_cycle.py`.

- [ ] Define immutable `MarketCycleState(label, confidence, evidence, decision_time, sample_count)` with labels `bull`, `neutral`, `risk_off` and confidence in `[0,1]`.
- [ ] Calculate daily breadth, median 30-day quote-volume rank, open-interest participation, and funding alignment from the existing popular artifacts; score the three labels with a transparent weighted rule and normalize to probabilities.
- [ ] Require at least 30 valid daily observations; otherwise return `insufficient_evidence` with confidence 0.
- [ ] Guarantee prefix causality: state at date t uses only artifacts through t; write JSON-safe output and a deterministic SHA-256 evidence hash.
- [ ] Test bull, neutral, risk-off, insufficient-data, probability sum, and prefix invariance cases.
- [ ] Run focused tests and commit.

### Task 3: Shared BTC/ETH/BNB confidence-weighted allocation

**Files:** create `src/bian_quant/backtest/confidence_allocation.py`; test `tests/unit/backtest/test_confidence_allocation.py`.

- [ ] Define immutable `AllocationDecision` for `total_cap`, per-asset caps, selected assets, and reasons.
- [ ] Map confidence `>=.80/.65/.50/<.50` to total caps `1.0/.70/.40/0.0` of configured capital.
- [ ] Allocate only across BTCUSDT, ETHUSDT, BNBUSDT using positive per-asset signal weights; normalize weights and guarantee the sum never exceeds the shared cap.
- [ ] Return no new exposure for `risk_off` or confidence below .50; never place orders or access exchange/private-key code.
- [ ] Test exact threshold boundaries, one/two/three selected assets, zero signals, and 100U conservation.
- [ ] Run focused tests and commit.

### Task 4: 100U comparison backtest

**Files:** create `src/bian_quant/backtest/market_cycle_comparison.py`; test `tests/unit/backtest/test_market_cycle_comparison.py`; modify `configs/backtests/popular_universe_100u.yaml`.

- [ ] Consume daily BTC/ETH/BNB returns plus causal cycle states and run three deterministic variants: signal-only baseline, confidence-weighted cap, and no-trade-under-50%.
- [ ] Output immutable metrics for total return, annualized volatility, max drawdown, Sharpe-like ratio, trade count, and final equity.
- [ ] Preserve 100U initial capital and write a comparison artifact with config/code/data hashes.
- [ ] Add fixture-based tests covering deterministic output, no lookahead, non-negative equity, and cap conservation.
- [ ] Run focused tests and commit.

### Task 5: Read-only API and research page visualization

**Files:** modify `src/bian_quant/reporting/research_protocol.py`, `src/bian_quant/reporting/research_terminal.py`, `dashboard/research.html`, `docs/contracts/research-terminal-ui-contract.md`; tests `tests/unit/reporting/test_research_terminal.py`.

- [ ] Add `market_cycle` and `allocation` contract models with label, confidence, total cap, per-asset caps, evidence hash, and backtest comparison summary.
- [ ] Aggregate the newest valid artifacts defensively; missing artifacts produce empty/insufficient evidence, never a false passed state.
- [ ] Render a plain-language cycle card, confidence percentage, shared three-coin cap, per-coin allocation, and baseline-versus-weighted metrics. Keep all controls read-only.
- [ ] Test passed, blocked, empty, and malformed-artifact responses.
- [ ] Run full focused gates, browser smoke check, and commit.

### Final acceptance

- [ ] Run the production Slice 1 with the warmup boundary and inspect new artifacts.
- [ ] Report whether snapshots were published; if not, list blockers and stop before backtest/paper/live trading.
- [ ] Push all commits and provide a concise evidence table plus unresolved issues.

