# Forward Paper Trading and Observability Implementation Plan

> For agentic workers: REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Run an Approved 100U strategy forward in four-hour paper cycles using captured public market data, with no credentials, no order placement, and a complete 30-day audit record.

**Architecture:** This plan consumes, but never changes, an Approved holdout and small-account backtest artifact from the popular-universe plan. A narrow public-data adapter captures the three permitted Binance responses as immutable raw inputs. A deterministic cycle runner validates freshness, applies the approved scoring/risk policy, appends one paper decision, and writes operator-facing artifacts; it has no exchange trading client.

**Tech Stack:** Python 3.11, urllib, Pydantic, SQLite, JSON, Typer, pytest, Binance USD-M public market-data endpoints.

---

## Entry gate and global constraints

1. Start only after Plan A records an APPROVED factor, its exact holdout artifact, a popular-universe artifact ID, and a passing small-account backtest artifact.
2. The only HTTP requests are GET requests to /fapi/v1/klines, /fapi/v1/exchangeInfo, and /fapi/v1/fundingRate. No headers contain an API key.
3. Capture response body, request URL, request timestamp, data/server timestamp, status, and SHA-256 before parsing.
4. Captured public data may not be imported by data, research, evaluate-holdout, Candidate generation, or universe selection.
5. No leverage, live order client, private endpoints, credentials, or automatic real-money transition.
6. A stale, malformed, future-dated, rate-limited, or missing input produces a persisted no-trade decision.
7. Human review needs 30 consecutive calendar days with no timing violation, limit breach, or unexplained missing decision.

## File map

- configs/paper/popular_universe_100u.yaml: references immutable Approved inputs and the four-hour freshness policy.
- src/bian_quant/paper/models.py: cycle, capture, decision, and portfolio-state contracts.
- src/bian_quant/paper/market_data.py: public GET-only capture and parse boundary.
- src/bian_quant/paper/ledger.py: append-only SQLite state and continuity checks.
- src/bian_quant/paper/runner.py: one deterministic paper cycle and risk-policy integration.
- src/bian_quant/paper/reporting.py: cycle artifacts and 30-day review summary.
- src/bian_quant/cli.py: run-paper-cycle and paper-status commands.
- tests/unit/paper and tests/integration/paper: offline contracts and end-to-end fixtures.

### Task 1: Define paper configuration and immutable contracts

**Files:**
- Create: configs/paper/popular_universe_100u.yaml
- Create: src/bian_quant/paper/__init__.py
- Create: src/bian_quant/paper/models.py
- Create: tests/unit/paper/test_models.py

- [ ] **Step 1: Write failing contract tests**

~~~python
config = PaperRunConfig.from_yaml(Path("configs/paper/popular_universe_100u.yaml"))
assert config.interval == timedelta(hours=4)
assert config.minimum_calendar_days == 30
assert config.allowed_endpoints == (
    "/fapi/v1/klines", "/fapi/v1/exchangeInfo", "/fapi/v1/fundingRate",
)
with pytest.raises(ValueError, match="paper run requires approved factor"):
    PaperRunConfig.model_validate({**config.model_dump(), "approved_factor_id": ""})
~~~

- [ ] **Step 2: Confirm RED**

Run: uv run pytest tests/unit/paper/test_models.py -q

Expected: import failure for bian_quant.paper.

- [ ] **Step 3: Implement config and models**

Create frozen Pydantic models ApprovedInputLineage, PaperRunConfig,
MarketDataCapture, PaperDecision, and PaperPortfolioState. ApprovedInputLineage
requires non-empty factor ID, version, holdout artifact path, small-account
artifact path, universe artifact ID, and snapshot IDs. PaperRunConfig fixes the
three endpoint paths, four-hour interval, 30 days, initial equity 100, gross 90,
and the 10/5/20 risk limits. It rejects every base URL except
https://fapi.binance.com.

- [ ] **Step 4: Verify and commit**

Run: uv run pytest tests/unit/paper/test_models.py -q; uv run ruff check src/bian_quant/paper tests/unit/paper/test_models.py; uv run mypy src/bian_quant/paper

Expected: pass.

~~~powershell
git add configs/paper/popular_universe_100u.yaml src/bian_quant/paper tests/unit/paper/test_models.py
git commit -m "feat(paper): define paper run contracts"
~~~

### Task 2: Capture only public market-data responses

**Files:**
- Create: src/bian_quant/paper/market_data.py
- Create: tests/unit/paper/test_market_data.py
- Create: tests/network/test_paper_market_data.py

- [ ] **Step 1: Write offline failure-mode tests**

Inject a byte reader. Assert every accepted response produces a capture with a
body SHA-256; HTTP 429, non-JSON, future timestamps, incomplete four-hour bars,
and an endpoint outside the allowlist raise stable errors.

~~~python
capture = client.capture_klines("BTCUSDT", decision_time)
assert capture.endpoint == "/fapi/v1/klines"
assert capture.body_sha256 == hashlib.sha256(payload).hexdigest()
with pytest.raises(PaperDataBlocked, match="PAPER_DATA_RATE_LIMITED"):
    client.capture_exchange_info()
~~~

- [ ] **Step 2: Confirm RED**

Run: uv run pytest tests/unit/paper/test_market_data.py -q

Expected: import failure.

- [ ] **Step 3: Implement GET-only adapter**

Implement PublicPaperMarketDataClient with a dependency-injected
byte_reader(url) -> bytes. Its only public methods are capture_klines(symbol,
decision_time), capture_exchange_info(), and capture_funding(symbol, start_time,
end_time). Build URLs from the fixed base URL and allowlist; never accept
caller-supplied headers. Map HTTP 429 to PAPER_DATA_RATE_LIMITED, other HTTP
failures to PAPER_DATA_UNAVAILABLE, malformed JSON to PAPER_DATA_MALFORMED, and
future data to PAPER_DATA_FUTURE_TIMESTAMP. Persist bodies before returning
parsed values.

- [ ] **Step 4: Add a fixed network compatibility test**

Request one BTCUSDT four-hour kline, exchange info, and Funding-history range;
assert no credentials are used and each response has a valid timestamp. Mark
the test network; it must never request the full universe.

- [ ] **Step 5: Verify and commit**

Run: uv run pytest tests/unit/paper/test_market_data.py -q; uv run pytest tests/network/test_paper_market_data.py -q -m network; uv run ruff check src/bian_quant/paper tests/unit/paper tests/network/test_paper_market_data.py; uv run mypy src/bian_quant/paper

Expected: pass.

~~~powershell
git add src/bian_quant/paper/market_data.py tests/unit/paper/test_market_data.py tests/network/test_paper_market_data.py
git commit -m "feat(paper): capture public market data"
~~~

### Task 3: Add append-only paper state and continuity checks

**Files:**
- Create: src/bian_quant/paper/ledger.py
- Create: tests/unit/paper/test_ledger.py

- [ ] **Step 1: Write failing ledger tests**

Test that decisions are unique by run ID and scheduled time, cannot be updated or
deleted, and a missing four-hour slot is reported after the grace period.

~~~python
ledger.record(decision)
with pytest.raises(sqlite3.IntegrityError):
    ledger.record(decision)
assert ledger.missing_slots(start, end) == (start + timedelta(hours=4),)
~~~

- [ ] **Step 2: Confirm RED**

Run: uv run pytest tests/unit/paper/test_ledger.py -q

Expected: import failure.

- [ ] **Step 3: Implement SQLite ledger**

Create tables paper_runs, paper_decisions, paper_captures, and paper_positions;
use append-only triggers rejecting UPDATE and DELETE. Make scheduled time unique
per run. Implement record_cycle, load_state, missing_slots, and review_readiness.
Review readiness is false before 30 days, on any missing slot, or on any timing
violation or risk-limit breach.

- [ ] **Step 4: Verify and commit**

Run: uv run pytest tests/unit/paper/test_ledger.py -q; uv run ruff check src/bian_quant/paper/ledger.py tests/unit/paper/test_ledger.py; uv run mypy src/bian_quant/paper/ledger.py

Expected: pass.

~~~powershell
git add src/bian_quant/paper/ledger.py tests/unit/paper/test_ledger.py
git commit -m "feat(paper): persist append-only paper ledger"
~~~

### Task 4: Run one safe four-hour paper cycle

**Files:**
- Create: src/bian_quant/paper/runner.py
- Create: tests/integration/paper/test_paper_cycle.py
- Modify: src/bian_quant/backtest/small_account.py

- [ ] **Step 1: Write failing end-to-end tests**

Use an injected clock, Approved fixture lineage, fixture client, and empty ledger.
Assert an on-time cycle records a decision; stale klines record
NO_TRADE:PAPER_DATA_STALE; an observed-factor lineage raises
PAPER_APPROVAL_REQUIRED; and a 10-USDT stop pauses later decisions.

- [ ] **Step 2: Confirm RED**

Run: uv run pytest tests/integration/paper/test_paper_cycle.py -q

Expected: import failure.

- [ ] **Step 3: Implement run_paper_cycle**

The public function signature is
run_paper_cycle(config, *, scheduled_time, client, ledger) -> PaperDecision.

Reject a time not divisible by four UTC hours. Require every Approved input
artifact to exist and to contain matching factor/version/universe/snapshot
lineage. Capture before parsing; require the most recent closed kline and settled
Funding not later than scheduled_time. Reuse Plan A size_order and
RiskPauseState. Persist a no-trade decision for every blocked condition. The
module must not import a private endpoint, a trading adapter, or urllib request
headers.

- [ ] **Step 4: Verify and commit**

Run: uv run pytest tests/integration/paper/test_paper_cycle.py tests/unit/paper -q; uv run mypy src/bian_quant/paper src/bian_quant/backtest/small_account.py

Expected: pass.

~~~powershell
git add src/bian_quant/paper/runner.py src/bian_quant/backtest/small_account.py tests/integration/paper/test_paper_cycle.py
git commit -m "feat(paper): run guarded four hour cycle"
~~~

### Task 5: Publish paper artifacts and operator commands

**Files:**
- Create: src/bian_quant/paper/reporting.py
- Modify: src/bian_quant/cli.py
- Create: tests/unit/paper/test_reporting.py
- Create: tests/integration/paper/test_paper_cli.py

- [ ] **Step 1: Write failing reporting tests**

Assert an exclusive cycle directory contains decision.json, captures.json,
orders.json, fills.json, equity.json, risk.json, and summary.md. Assert the
30-day summary reports every missing slot and never labels a run ready if any
decision has a timing violation.

- [ ] **Step 2: Confirm RED**

Run: uv run pytest tests/unit/paper/test_reporting.py tests/integration/paper/test_paper_cli.py -q

Expected: import/command failure.

- [ ] **Step 3: Implement reporting and CLI**

Use ArtifactWriter for exclusive cycle directories under
var/artifacts/paper/run-id/scheduled-time. Add commands:
- bian-quant run-paper-cycle --config PATH --scheduled-time ISO8601
- bian-quant paper-status --config PATH

The first prints decision path and status. The second prints run ID, completed
days, missing slots, current equity, pause state, and review readiness. Neither
accepts credentials, API-key flags, or order arguments.

- [ ] **Step 4: Verify and commit**

Run: uv run pytest tests/unit/paper tests/integration/paper -q; uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy src/bian_quant; git diff --check

Expected: offline suite passes.

~~~powershell
git add src/bian_quant/paper/reporting.py src/bian_quant/cli.py tests/unit/paper/test_reporting.py tests/integration/paper/test_paper_cli.py
git commit -m "feat(paper): report forward paper cycles"
~~~

### Task 6: Validate no-live-order boundary and operating contract

**Files:**
- Create: tests/unit/paper/test_security_boundary.py
- Modify: docs/implementation-notes.md

- [ ] **Step 1: Write failing boundary tests**

Use ast.parse over every source file below src/bian_quant/paper. Fail when an
import or string contains /fapi/v1/order, /fapi/v1/leverage, X-MBX-APIKEY,
api_secret, api_key, websocket, or a private endpoint prefix. Assert the public
allowlist is exactly the three documented paths.

- [ ] **Step 2: Confirm RED**

Run: uv run pytest tests/unit/paper/test_security_boundary.py -q

Expected: failure until the explicit boundary test exists.

- [ ] **Step 3: Document and run gates**

Append a dated implementation note that paper cycles use public capture-first
inputs only, are isolated from research, cannot place orders, and need 30
complete days for human review. Run:

~~~powershell
uv run pytest -q
uv run pytest -q -m network
powershell -ExecutionPolicy Bypass -File scripts/check.ps1
uv build
~~~

Expected: all commands exit 0. If Plan A produces no Approved artifact, stop
before creating a paper run and report PAPER_APPROVAL_REQUIRED; implementation
fixtures remain valid.

- [ ] **Step 4: Commit**

~~~powershell
git add tests/unit/paper/test_security_boundary.py docs/implementation-notes.md
git commit -m "docs: record paper trading boundary"
~~~
