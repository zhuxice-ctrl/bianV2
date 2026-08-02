# Popular-Universe Research and 100U Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (\`- [ ]\`) syntax for tracking.

**Goal:** Build a point-in-time popular USD-M perpetual universe, preserve Candidate/holdout gates, and run only Approved decisions through a deterministic 100 USDT event backtest.

**Architecture:** A new configuration acquires a committed seed pool into separate lake roots. An immutable daily universe artifact chooses the top twelve eligible symbols using cutoff-valid 30-day volume and OI rankings; analysis joins membership before screening and records its ID in snapshots and decisions. A separate small-account portfolio simulator consumes an Approved decision and immutable snapshots, never live market responses.

**Tech Stack:** Python 3.11, Pydantic, pandas, PyArrow/Parquet, SQLite, Typer, pytest, Binance USD-M archive adapters.

---

## Global constraints

1. Work only on \`codex/research-platform-implementation\`; retain every existing \`var/\` object.
2. The completed three-asset Plan 03.5 config and evidence remain byte-for-byte unchanged.
3. Research and holdout remain archive-backed; every accepted input satisfies both event and availability cutoff predicates.
4. The seed pool is exactly \`ADAUSDT, APTUSDT, AVAXUSDT, BCHUSDT, BNBUSDT, BTCUSDT, DOGEUSDT, ETHUSDT, LINKUSDT, LTCUSDT, NEARUSDT, SOLUSDT, SUIUSDT, TONUSDT, TRXUSDT, XRPUSDT\`.
5. Each daily universe has at most 12 symbols and blocks with \`POPULAR_UNIVERSE_INSUFFICIENT\` below eight.
6. Never call \`evaluate-holdout\` before \`CANDIDATE\`; never run the 100U backtest before \`APPROVED\`.
7. No leverage. Gross notional is at most 90 USDT; one position risks at most 10 USDT; two positions together risk at most 10 USDT and each at most 5 USDT.

## File map

- \`configs/experiments/popular_universe_100u.yaml\`: independent acquisition and factor configuration.
- \`configs/backtests/popular_universe_100u.yaml\`: 100U portfolio and cost policy.
- \`src/bian_quant/data/popular_universe.py\`: daily membership selection and payload.
- \`src/bian_quant/data/acquisition.py\`: configuration validation and seed-pool source plan.
- \`src/bian_quant/data/dual_horizon.py\`: universe publication and lineage propagation.
- \`src/bian_quant/research/operations.py\` and \`src/bian_quant/research/dual_horizon.py\`: membership-aware screening and holdout lineage.
- \`src/bian_quant/backtest/small_account.py\`: exchange filters, sizing, and pause policy.
- \`src/bian_quant/backtest/portfolio.py\`: deterministic one/two-position replay.
- \`src/bian_quant/cli.py\`: \`backtest-small-account\` command.

### Task 1: Add the independent popular-universe configuration

**Files:**
- Create: \`configs/experiments/popular_universe_100u.yaml\`
- Create: \`configs/backtests/popular_universe_100u.yaml\`
- Modify: \`src/bian_quant/data/acquisition.py\`
- Test: \`tests/unit/data/test_acquisition.py\`

- [ ] **Step 1: Write the failing config test**

\`\`\`python
def test_popular_config_locks_seed_pool_and_limits() -> None:
    config = DualHorizonAcquisition.from_yaml(
        Path("configs/experiments/popular_universe_100u.yaml")
    )
    assert len(config.assets) == 16
    assert config.universe_policy is not None
    assert config.universe_policy.max_selected == 12
    assert config.universe_policy.min_selected == 8
    assert config.universe_policy.minimum_listing_days == 180
\`\`\`

- [ ] **Step 2: Confirm RED**

Run: \`uv run pytest tests/unit/data/test_acquisition.py -q\`

Expected: failure because \`universe_policy\` and the popular configuration do not exist.

- [ ] **Step 3: Add the model and YAML**

Add this frozen model before \`DualHorizonAcquisition\`:

\`\`\`python
class PopularUniversePolicy(BaseModel):
    model_config = ConfigDict(frozen=True)

    rule_version: Literal["popular-usdm-v1"]
    minimum_listing_days: Literal[180]
    trailing_days: Literal[30]
    max_selected: Literal[12]
    min_selected: Literal[8]
    seed_assets: tuple[str, ...]

    @model_validator(mode="after")
    def validate_seed_assets(self) -> "PopularUniversePolicy":
        if len(self.seed_assets) != 16 or len(set(self.seed_assets)) != 16:
            raise ValueError("popular universe requires exactly 16 unique seed assets")
        if tuple(sorted(self.seed_assets)) != self.seed_assets:
            raise ValueError("popular seed assets must be lexicographically sorted")
        return self
\`\`\`

Add \`universe_policy: PopularUniversePolicy | None = None\`. Preserve the legacy
three-asset restriction only when it is \`None\`; otherwise require
\`assets == universe_policy.seed_assets\`. Populate the experiment YAML with the
exact seed list, existing time/coverage values, and separate roots ending
\`-popular-v1\`. Populate the backtest YAML exactly:

\`\`\`yaml
initial_equity_usdt: 100
max_gross_notional_usdt: 90
max_positions: 2
single_position_risk_usdt: 10
two_position_risk_usdt: 5
daily_loss_pause_usdt: 10
drawdown_pause_usdt: 20
taker_fee_bps: 4
slippage_bps: 10
interval: 4h
\`\`\`

- [ ] **Step 4: Verify and commit**

Run: \`uv run pytest tests/unit/data/test_acquisition.py -q && uv run mypy src/bian_quant/data/acquisition.py\`

Expected: pass.

\`\`\`powershell
git add configs/experiments/popular_universe_100u.yaml configs/backtests/popular_universe_100u.yaml src/bian_quant/data/acquisition.py tests/unit/data/test_acquisition.py
git commit -m "feat(data): configure popular universe research"
\`\`\`

### Task 2: Build daily point-in-time membership artifacts

**Files:**
- Create: \`src/bian_quant/data/popular_universe.py\`
- Create: \`tests/unit/data/test_popular_universe.py\`

- [ ] **Step 1: Write failing selection tests**

Create fixtures proving: a 179-day listing is excluded; a future volume spike cannot
change historical rank; a missing Funding or OI day excludes a symbol; composite
rank uses both median quote volume and median OI value; equal scores break by
symbol; seven otherwise eligible symbols raise \`POPULAR_UNIVERSE_INSUFFICIENT\`.

\`\`\`python
artifact = build_popular_universe(selection_time, listing, ohlcv, funding, metrics, policy)
assert [member.asset for member in artifact.members] == ["ALPHAUSDT", "BETAUSDT"]
assert artifact.members[0].rank == 1
assert all(member.selection_time == selection_time for member in artifact.members)
assert artifact.selector_config_hash
\`\`\`

- [ ] **Step 2: Confirm RED**

Run: \`uv run pytest tests/unit/data/test_popular_universe.py -q\`

Expected: import failure.

- [ ] **Step 3: Implement selection and payloads**

Create frozen \`PopularUniverseMember\` (selection time, asset, rank, median quote
volume, median OI value, rule version) and \`PopularUniverseArtifact\` (artifact
ID, members, exclusions, source hashes, selector config hash). Implement:

The public function signature is
build_popular_universe(selection_time, listing_metadata, ohlcv, funding,
metrics, policy) -> PopularUniverseArtifact.

For every seed symbol require metadata available by the selection time, listing
age at least 180 days, and 30 distinct daily rows from each input where
\`event_time < selection_time\` and \`available_time <= selection_time\`.
Compute the sum of descending ranks for median \`quote_volume\` and median
\`sum_open_interest_value\`; sort \`(score, asset)\`; retain 12. Canonical JSON
uses sorted keys and compact separators for hashes. Persist all exclusion reasons.

- [ ] **Step 4: Verify and commit**

Run: \`uv run pytest tests/unit/data/test_popular_universe.py -q; uv run ruff check src/bian_quant/data/popular_universe.py tests/unit/data/test_popular_universe.py; uv run ruff format --check src/bian_quant/data/popular_universe.py tests/unit/data/test_popular_universe.py; uv run mypy src/bian_quant/data/popular_universe.py\`

Expected: all pass.

\`\`\`powershell
git add src/bian_quant/data/popular_universe.py tests/unit/data/test_popular_universe.py
git commit -m "feat(data): select point-in-time popular universe"
\`\`\`

### Task 3: Bind acquisition, snapshots, and screening to membership lineage

**Files:**
- Modify: \`src/bian_quant/data/dual_horizon.py\`
- Modify: \`src/bian_quant/research/operations.py\`
- Modify: \`src/bian_quant/research/dual_horizon.py\`
- Modify: \`tests/integration/data/test_dual_horizon_pipeline.py\`
- Modify: \`tests/unit/research/test_operations.py\`

- [ ] **Step 1: Write failing lineage tests**

Use a sixteen-symbol miniature archive. Assert the acquisition artifact includes
\`popular_universe_artifact_id\`, every research snapshot config includes the
same value, and a membership selected after a bar's availability time cannot
enter screening.

- [ ] **Step 2: Confirm RED**

Run: \`uv run pytest tests/integration/data/test_dual_horizon_pipeline.py tests/unit/research/test_operations.py -q\`

Expected: missing lineage fields and unfiltered membership.

- [ ] **Step 3: Publish and consume membership**

After canonical clipping but before research snapshots, build one artifact per UTC
daily boundary; write it exclusively under \`artifact_root / "popular-universe"\`.
Include its ID and selector hash in acquisition/quality JSON and snapshot
\`config_json\`. For legacy config, omit new fields and preserve existing output.

Add \`eligibility_frame: pd.DataFrame | None\` to
\`run_dual_horizon_screening\`. Join by asset and UTC day before the development
split; require membership selection time no later than each bar's
\`available_time\`; fail on duplicate or absent membership. In
\`analyze_cataloged_dual_horizon\`, load the exact artifact named by snapshot
config, pass the frame, and add its ID to \`RunManifest.config\` and holdout
payloads.

- [ ] **Step 4: Verify and commit**

Run: \`uv run pytest tests/integration/data/test_dual_horizon_pipeline.py tests/unit/research/test_operations.py tests/unit/data/test_popular_universe.py -q; uv run mypy src/bian_quant/data/dual_horizon.py src/bian_quant/research/operations.py src/bian_quant/research/dual_horizon.py\`

Expected: pass; future or missing membership blocks analysis.

\`\`\`powershell
git add src/bian_quant/data/dual_horizon.py src/bian_quant/research/operations.py src/bian_quant/research/dual_horizon.py tests/integration/data/test_dual_horizon_pipeline.py tests/unit/research/test_operations.py
git commit -m "feat(research): bind screening to popular universe lineage"
\`\`\`

### Task 4: Implement 100U sizing, filters, and pause rules

**Files:**
- Create: \`src/bian_quant/backtest/small_account.py\`
- Create: \`tests/unit/backtest/test_small_account.py\`

- [ ] **Step 1: Write failing risk tests**

\`\`\`python
rules = ContractRules("ALPHAUSDT", Decimal("0.01"), Decimal("0.1"), Decimal("0.1"), Decimal("5"))
limits = SmallAccountLimits.from_yaml(Path("configs/backtests/popular_universe_100u.yaml"))
order = size_order(Decimal("20"), Decimal("18"), Decimal("100"), (), (), rules, limits)
assert order.notional == Decimal("90")
assert order.stop_risk == Decimal("9.0")
second = size_order(Decimal("20"), Decimal("18"), Decimal("100"), (Decimal("5"),), (), rules, limits)
assert second.stop_risk <= Decimal("5")
assert reject.reason == "MIN_NOTIONAL_OR_STEP_CONFLICT"
\`\`\`

Also assert a 9.50-USDT stop pauses until next UTC day and a 20-USDT
high-water-mark drawdown requires human review.

- [ ] **Step 2: Confirm RED**

Run: \`uv run pytest tests/unit/backtest/test_small_account.py -q\`

Expected: import failure.

- [ ] **Step 3: Implement exact sizing**

Create frozen \`ContractRules\`, \`SmallAccountLimits\`, \`SizedOrder\`, and
\`RiskPauseState\`. \`size_order\` computes
\`risk_budget / abs(entry - stop)\`, floors it to \`step_size\`, rejects below
\`min_qty\` or \`min_notional\`, then caps by remaining 90-USDT gross capacity.
Budget is 10 USDT with no position and the minimum of 5 USDT/remaining aggregate
risk with one position. Never round upward.

- [ ] **Step 4: Verify and commit**

Run: \`uv run pytest tests/unit/backtest/test_small_account.py -q; uv run ruff check src/bian_quant/backtest/small_account.py tests/unit/backtest/test_small_account.py; uv run mypy src/bian_quant/backtest/small_account.py\`

Expected: pass.

\`\`\`powershell
git add src/bian_quant/backtest/small_account.py tests/unit/backtest/test_small_account.py
git commit -m "feat(backtest): enforce 100u risk limits"
\`\`\`

### Task 5: Replay ranked Approved signals as a two-position portfolio

**Files:**
- Create: \`src/bian_quant/backtest/portfolio.py\`
- Create: \`tests/unit/backtest/test_portfolio.py\`
- Modify: \`src/bian_quant/backtest/events.py\`

- [ ] **Step 1: Write failing replay tests**

At a common decision time, assert rank one opens first, rank two is admitted only
at five-USDT risk, a third signal is rejected with \`MAX_POSITIONS_REACHED\`,
future-available signals are rejected, and total gross never exceeds 90 USDT.

- [ ] **Step 2: Confirm RED**

Run: \`uv run pytest tests/unit/backtest/test_portfolio.py -q\`

Expected: import failure.

- [ ] **Step 3: Implement deterministic replay**

Add defaulted \`asset: str = ""\` and \`rank: int = 0\` fields to
\`SignalEvent\` so existing callers remain compatible. Implement
\`replay_ranked_portfolio\`: group signals by timestamp, reject
\`available_time > timestamp\`, sort \`(rank, asset)\`, size at most two orders,
and route fills through existing next-bar, fee, slippage, Funding, and
\`STOP_FIRST\` semantics. Return fills, trades, equity, daily attribution,
rejections, maximum gross, and pause events.

- [ ] **Step 4: Verify and commit**

Run: \`uv run pytest tests/unit/backtest -q; uv run ruff check src/bian_quant/backtest tests/unit/backtest; uv run mypy src/bian_quant/backtest\`

Expected: all existing and new backtest tests pass.

\`\`\`powershell
git add src/bian_quant/backtest/events.py src/bian_quant/backtest/portfolio.py tests/unit/backtest/test_portfolio.py
git commit -m "feat(backtest): replay ranked small account portfolio"
\`\`\`

### Task 6: Gate the operator command on an Approved decision

**Files:**
- Modify: \`src/bian_quant/research/operations.py\`
- Modify: \`src/bian_quant/cli.py\`
- Create: \`tests/integration/backtest/test_small_account_command.py\`

- [ ] **Step 1: Write failing approval-boundary tests**

\`\`\`python
with pytest.raises(PermissionError, match="SMALL_ACCOUNT_APPROVAL_REQUIRED"):
    run_small_account_backtest(config, factor_id="momentum_24", factor_version="1.0.0", snapshot_id="snap", portfolio_config=PORTFOLIO)
\`\`\`

The passing fixture must have an \`APPROVED\` factor, its one-time holdout
artifact, a universe artifact, and immutable snapshots. Assert the output cites
all four inputs and every rejection reason.

- [ ] **Step 2: Confirm RED**

Run: \`uv run pytest tests/integration/backtest/test_small_account_command.py -q\`

Expected: missing function failure.

- [ ] **Step 3: Implement the operation and CLI**

Implement \`run_small_account_backtest(config, *, factor_id, factor_version,
snapshot_id, portfolio_config) -> Path\`. Require \`FactorState.APPROVED\`,
exactly one matching holdout artifact and universe artifact, then write an
exclusive \`artifact_root / "small-account"\` run containing input lineage,
orders, fills, trades, equity, costs, pause events, and rejections. Add the
\`backtest-small-account\` Typer command. It imports no network client and no
order client.

- [ ] **Step 4: Run full gates and commit**

Run: \`uv run pytest tests/unit/data/test_popular_universe.py tests/unit/backtest tests/unit/research/test_operations.py tests/integration/backtest/test_small_account_command.py -q; uv run pytest -q; uv run ruff check src tests; uv run ruff format --check src tests; uv run mypy src/bian_quant; git diff --check\`

Expected: all offline tests pass; only marked network tests are deselected.

\`\`\`powershell
git add src/bian_quant/research/operations.py src/bian_quant/cli.py tests/integration/backtest/test_small_account_command.py
git commit -m "feat(backtest): gate 100u replay on approval"
\`\`\`

Run the popular-universe acquisition and screening only after these gates pass.
If no Candidate or no Approved factor results, record its decision artifact; do
not run the backtest and do not begin the paper plan.
