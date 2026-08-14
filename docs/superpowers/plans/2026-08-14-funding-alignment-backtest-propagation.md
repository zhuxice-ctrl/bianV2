# Funding Alignment Backtest Propagation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make causal Funding-alignment evidence affect ETH single-asset risk multipliers and BTC/ETH/BNB 100U comparisons, while preserving byte-identical behavior without Funding input.

**Architecture:** The reporting composition root builds Funding records once through `data/funding_alignment.py`, then passes the same immutable tuple to pure regime and backtest consumers. `regimes/market_cycle.py` remains the only scorer; backtests never scan Parquet; the dashboard remains API-only and read-only.

**Tech Stack:** Python 3.11, pandas, Pydantic v2, EventEngine, pytest, Ruff, mypy.

---

## Mandatory rules

- [ ] Read `docs/AILY_EXECUTION_RULES.md`, this plan, and `git status --short --branch` before changing files.
- [ ] Preserve `.superpowers/`; do not merge main, download data, access an exchange, open Holdout, or start paper/live trading.
- [ ] Preserve every `research-terminal-v1` field and HTTP-200 endpoint behavior.
- [ ] Never make `backtest/*` read Parquet, `regimes/*` read paths/network, or `dashboard/*` calculate scores.

Data flow:

```text
Canonical Funding Parquet -> data adapter -> immutable FundingAlignmentRecord tuple
-> regimes.classify_market_cycle -> ETH / 100U backtests -> audit artifacts
-> reporting API -> read-only dashboard
```

### Task 1: Add optional Funding input to both backtest consumers

**Files:**

- Modify: `src/bian_quant/backtest/single_asset_strategy.py`
- Modify: `src/bian_quant/backtest/market_cycle_comparison.py`
- Test: `tests/unit/backtest/test_single_asset_strategy.py`
- Test: `tests/unit/backtest/test_market_cycle_comparison.py`

- [ ] **Step 1: Write failing compatibility tests**

```python
without = run_market_cycle_comparison(returns, popular)
explicit_none = run_market_cycle_comparison(returns, popular, funding_alignment=None)
assert comparison_payload(without) == comparison_payload(explicit_none)

eth_without = evaluate_eth_strategy(ohlcv_path=csv_path, popular_records=popular)
eth_none = evaluate_eth_strategy(
    ohlcv_path=csv_path, popular_records=popular, funding_alignment=None
)
assert eth_without.result_sha256 == eth_none.result_sha256
```

Add a valid positive-Funding fixture available before a signal decision. Assert the baseline trades/equity remain identical and only the weighted metrics or multipliers can change. Add a future-only Funding fixture and assert the state/multiplier/trade/equity prefix through the cutoff is unchanged.

- [ ] **Step 2: Run the tests and confirm the signature gap**

```powershell
uv run pytest -p no:cov tests/unit/backtest/test_market_cycle_comparison.py tests/unit/backtest/test_single_asset_strategy.py -q
```

Expected: failure because the public consumers do not yet accept `funding_alignment`.

- [ ] **Step 3: Implement the additive parameter**

Both consumers receive this keyword-only argument:

```python
funding_alignment: tuple[FundingAlignmentRecord, ...] | None = None
```

Add it to `run_market_cycle_comparison`, `build_comparison_from_artifacts`, and `evaluate_eth_strategy`. At every decision use:

```python
state = classify_market_cycle(
    historical_popular, funding_alignment=funding_alignment
)
```

Do not filter Funding in backtests: `classify_market_cycle` owns the point-in-time gate. Add `funding_alignment_source_sha256` to each ETH multiplier audit record and the latest applied source hash to the 100U comparison audit payload.

- [ ] **Step 4: Verify and commit**

```powershell
uv run pytest -p no:cov tests/unit/backtest/test_market_cycle_comparison.py tests/unit/backtest/test_single_asset_strategy.py tests/unit/regimes/test_market_cycle.py -q
uv run ruff check src/bian_quant/backtest/single_asset_strategy.py src/bian_quant/backtest/market_cycle_comparison.py tests/unit/backtest/test_single_asset_strategy.py tests/unit/backtest/test_market_cycle_comparison.py
uv run ruff format --check src/bian_quant/backtest/single_asset_strategy.py src/bian_quant/backtest/market_cycle_comparison.py tests/unit/backtest/test_single_asset_strategy.py tests/unit/backtest/test_market_cycle_comparison.py
uv run mypy src/bian_quant
```

```powershell
git add src/bian_quant/backtest/single_asset_strategy.py src/bian_quant/backtest/market_cycle_comparison.py tests/unit/backtest/test_single_asset_strategy.py tests/unit/backtest/test_market_cycle_comparison.py
git commit -m "feat(backtest): propagate causal funding alignment"
```

### Task 2: Build Funding once and forward it through reporting

**Files:**

- Modify: `src/bian_quant/reporting/research_terminal.py`
- Modify: `src/bian_quant/reporting/single_asset_artifacts.py`
- Test: `tests/unit/reporting/test_research_terminal.py`
- Test: `tests/unit/reporting/test_single_asset_artifacts.py`

- [ ] **Step 1: Write failing composition tests**

Monkeypatch `build_daily_funding_alignment` to return one known tuple. Assert one `build_research_terminal_response` call invokes the adapter once and passes that same tuple to both the ETH artifact builder and 100U comparison builder. When the adapter returns `()` or raises, assert parent run state does not change.

Add canonical-artifact tests that prove Funding input changes the result hash and stores:

```python
"funding_alignment_source_sha256"
"funding_alignment_applied_signal_count"
```

- [ ] **Step 2: Confirm tests fail and implement composition**

In `build_research_terminal_response`, call `_build_funding_alignment_safe` once using configured canonical root, assets, and `as_of`; pass its tuple to `_build_cycle_allocation_backtest` and `_build_single_asset_evaluations`. Forward it through `build_eth_single_asset_evaluation` to `evaluate_eth_strategy`.

`None` means adapter failure and `()` means no data. Both must map to the existing missing/error Funding node without changing the parent research state. The artifact builder must never receive a canonical path or call the adapter itself.

- [ ] **Step 3: Verify and commit**

```powershell
uv run pytest -p no:cov tests/unit/reporting/test_research_terminal.py tests/unit/reporting/test_single_asset_artifacts.py tests/unit/backtest/test_single_asset_strategy.py -q
uv run ruff check src/bian_quant/reporting/research_terminal.py src/bian_quant/reporting/single_asset_artifacts.py tests/unit/reporting/test_research_terminal.py tests/unit/reporting/test_single_asset_artifacts.py
uv run ruff format --check src/bian_quant/reporting/research_terminal.py src/bian_quant/reporting/single_asset_artifacts.py tests/unit/reporting/test_research_terminal.py tests/unit/reporting/test_single_asset_artifacts.py
uv run mypy src/bian_quant
```

```powershell
git add src/bian_quant/reporting/research_terminal.py src/bian_quant/reporting/single_asset_artifacts.py tests/unit/reporting/test_research_terminal.py tests/unit/reporting/test_single_asset_artifacts.py
git commit -m "feat(reporting): share funding evidence with evaluators"
```

### Task 3: Preserve wire compatibility and explain applied evidence

**Files:**

- Modify: `docs/contracts/research-terminal-ui-contract.md`
- Modify: `dashboard/research.html`
- Modify: `tests/unit/reporting/test_research_protocol.py`
- Modify: `tests/integration/dashboard/test_research_page.py`

- [ ] **Step 1: Write compatibility tests**

Assert `research-terminal-v1` remains unchanged, `market_cycle.funding_alignment` remains additive, and existing single-asset entries remain structurally compatible. An applied Funding hash/count appears only in audit details; missing Funding renders `—` and cannot claim the strategy was changed.

- [ ] **Step 2: Update docs and renderer**

Document that Funding alignment is now a causal input to weighted ETH and 100U comparisons. Render the source-hash prefix and applied-signal count through `escapeHtml`; add no run/download/order/approval control.

- [ ] **Step 3: Verify and commit**

```powershell
uv run pytest -p no:cov tests/unit/reporting/test_research_protocol.py tests/unit/reporting/test_research_terminal.py tests/integration/dashboard/test_research_page.py -q
uv run ruff check tests/unit/reporting/test_research_protocol.py tests/integration/dashboard/test_research_page.py
uv run ruff format --check tests/unit/reporting/test_research_protocol.py tests/integration/dashboard/test_research_page.py
uv run mypy src/bian_quant
```

```powershell
git add docs/contracts/research-terminal-ui-contract.md dashboard/research.html tests/unit/reporting/test_research_protocol.py tests/integration/dashboard/test_research_page.py
git commit -m "docs(research): expose applied funding evidence"
```

### Task 4: Real-data evidence and stop gate

**Files:**

- Modify: `docs/evidence/2026-08-13-funding-aligned-market-cycle-run.md`
- Modify: `docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md`
- Modify: `docs/implementation-notes.md`

- [ ] **Step 1: Run local aggregation and record facts**

```powershell
@'
from pathlib import Path
from bian_quant.reporting.research_terminal import build_research_terminal_response
root = Path.cwd()
r = build_research_terminal_response(root / "configs" / "experiments" / "popular_universe_100u.yaml", repo_root=root)
print(r.model_dump_json(indent=2))
'@ | uv run python -
```

Record actual state, Funding status/hash, applied count, ETH artifact hashes, sample bounds, baseline/weighted metrics, 100U metrics and every command result. Record `missing` if no eligible local Funding data exists; never invent values.

- [ ] **Step 2: Run final gates**

```powershell
uv run pytest -p no:cov tests/unit/data/test_funding_alignment.py tests/unit/regimes/test_market_cycle.py tests/unit/backtest/test_market_cycle_comparison.py tests/unit/backtest/test_single_asset_strategy.py tests/unit/reporting/test_research_protocol.py tests/unit/reporting/test_single_asset_artifacts.py tests/unit/reporting/test_research_terminal.py tests/integration/dashboard/test_research_page.py -q
uv run ruff check src/bian_quant/data/funding_alignment.py src/bian_quant/regimes/market_cycle.py src/bian_quant/backtest/market_cycle_comparison.py src/bian_quant/backtest/single_asset_strategy.py src/bian_quant/reporting/research_terminal.py src/bian_quant/reporting/single_asset_artifacts.py
uv run mypy src/bian_quant
git diff --check
```

Only report the global test/format suites as passed if those exact commands exit 0.

- [ ] **Step 3: Commit, push, and stop for review**

```powershell
git add docs/evidence/2026-08-13-funding-aligned-market-cycle-run.md docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md docs/implementation-notes.md
git commit -m "docs(research): record propagated funding evidence"
git push
```

Stop and report merge readiness. Do not merge to main automatically.

## Acceptance Checklist

- [ ] No Funding input is byte-identical to existing output.
- [ ] Funding changes only weighted strategy outputs, never ETH baseline outputs.
- [ ] Future Funding cannot alter an earlier state, multiplier, trade or equity prefix.
- [ ] The data adapter is called once per terminal response and the same immutable tuple reaches both consumers.
- [ ] Result hashes change only when applied Funding evidence changes.
- [ ] The endpoint remains read-only and v1-compatible.
- [ ] No Holdout, paper, live, or main-merge boundary is crossed.
