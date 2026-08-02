# Popular-Universe 100U Paper-Trading Design

**Status:** Approved in conversation on 2026-08-02

## Goal

Create a new, separately versioned research cycle that can discover a robust
Candidate in a point-in-time universe of popular Binance USD-M perpetuals, then
validate an Approved factor in a 100 USDT forward paper portfolio. The system
must never open the locked holdout before Candidate promotion or send a live
order.

## Context and decision

The completed three-asset run (BTCUSDT, ETHUSDT, BNBUSDT) has sound data and
engineering evidence, but its 28 observed factors produced zero Candidates.
The primary gate failures were insufficient independent cross-asset evidence
and excessive asset/regime concentration. Repeating that exact run would not
create new evidence. Its source plan, snapshots, artifacts, registry entries,
and holdout state remain immutable.

The next cycle therefore separates a broad **research qualification universe**
from a concentrated **paper portfolio**. The qualification universe supports
statistical testing; it is never an instruction to divide 100 USDT evenly among
its members.

## Non-goals

- No live trading, API credential storage, exchange order placement, leverage,
  grid/martingale behaviour, averaging down, or automatic transition to live
  trading.
- No mutation, deletion, or reuse as-if-current of the completed Plan 03.5
  evidence.
- No REST Funding substitution, missing-value imputation, or relaxed
  event-time/availability-time cutoff.
- No holdout evaluation for an observed or researching factor.

## A. Popular-universe data contract

### Eligibility snapshot

At each UTC day boundary, construct an immutable eligibility snapshot from the
archive-backed USD-M perpetual universe. A symbol is eligible only when all of
the following are true at the decision time:

1. It is a USDT-settled perpetual contract and has been listed for at least
   180 calendar days.
2. It has complete, cutoff-valid daily OHLCV, Funding, and OI coverage across
   the previous 30 calendar days.
3. Its 30-day quote-volume and open-interest measurements are available no
   later than the decision time.
4. It is not a stablecoin, leveraged token, wrapped asset, or other excluded
   synthetic symbol defined by the committed universe policy.

Eligible symbols are ranked by a deterministic composite of their trailing
30-day median quote volume and median open-interest value. The top 12 are the
qualification universe for the next UTC day; fewer than 8 eligible symbols
blocks the research run with a stable `POPULAR_UNIVERSE_INSUFFICIENT` reason.
Ties break lexicographically by symbol. The exact ranked inputs, cutoff time,
source hashes, selected symbols, exclusions, and selector version are persisted
in an append-only universe artifact.

This membership must be computed only from rows with both `event_time` and
`available_time` no later than the snapshot decision time. A current popularity
ranking may never be backfilled into an earlier date. Every downstream data
plan, canonical path, research snapshot, experiment, and decision packet cites
the universe artifact ID and selector configuration hash.

### Research data lifecycle

The new experiment has a new configuration identity and a new source-plan hash.
It preserves the existing monthly-Funding tail strategy and dual-clock cutoff
rules. Data acquisition remains archive-backed, bounded, resumable, and limited
to four workers. Each selected symbol receives independent coverage, quality,
cutoff, raw, canonical, and snapshot evidence. Any unavailable or quality-blocked
symbol is excluded before signal construction; it does not become a zero-filled
input or a synthetic position.

Existing three-asset evidence remains read-only. The new cycle writes separate
raw/canonical/research/artifact namespaces and never replaces old run IDs.

## B. Candidate discovery and holdout rules

The existing factor protocol remains the promotion authority: all development
fold, BH, directional-agreement, redundancy, cost, delay, and concentration
gates apply unchanged. The broader point-in-time universe is intended to supply
valid cross-asset support, not to weaken those gates.

Candidate generation, model fitting, threshold fitting, rank selection, and
portfolio parameter selection may read development data only. An observed factor
becomes a Candidate only through the existing lifecycle transition. It then gets
one `evaluate-holdout` invocation for its exact factor ID, version, universe
artifact ID, and snapshot lineage. A failed holdout preserves its prior state;
a second evaluation is denied unless a genuinely new source plan, universe
artifact, snapshots, and experiment lineage exist.

Only an Approved factor can be passed into the small-account event backtest and
forward paper runner. Zero Candidates or zero Approved factors is a successful,
auditable research outcome and prevents paper trading from starting.

## C. 100U portfolio and backtest contract

The backtest and paper runner model an initial 100 USDT equity balance with no
leverage. At each four-hour decision point, they consider only eligible symbols
with an Approved factor signal calculated from data already available at that
time. Signals rank by the Approved factor's committed score; an insufficient or
stale signal results in no position.

The capital and risk limits are:

- Gross notional is at most 90 USDT.
- One position may risk at most 10 USDT at its committed stop.
- When two positions are open, their combined stop risk is at most 10 USDT and
  each position may risk at most 5 USDT.
- Position notional is the lesser of the risk-budget-derived quantity,
  exchange-rule-adjusted quantity, per-position notional cap, and remaining
  gross-notional capacity. Risk is a maximum loss, not a target: an order may
  be smaller when the stop distance, tick size, step size, or minimum notional
  requires it.
- An order that cannot meet the exchange's minimum notional or quantity
  increment without exceeding a limit is rejected and recorded; it is never
  rounded up beyond a risk limit.
- A completed stop loss near 10 USDT prevents new entries for the rest of that
  UTC day. A drawdown of 20 USDT from the paper-equity high-water mark pauses
  the runner pending explicit human review.

The approved factor's versioned configuration must provide the direction,
holding/rebalance behaviour, and initial stop definition before the holdout is
opened. The event-driven backtest applies exchange-rule snapshots, fees,
slippage, funding payments, liquidation-free no-leverage accounting, and
next-available-bar execution. It emits an immutable run manifest, equity curve,
orders, fills, trades, costs, risk rejections, and daily attribution.

## D. Forward paper-trading contract

Paper trading begins only after the same configuration has an Approved holdout
decision and a passing small-account event backtest. It runs every four hours
after the required inputs become available and uses read-only market-data
adapters. It never imports or reads exchange API secrets and has no live-order
adapter.

The runner must operate for at least 30 consecutive calendar days. It writes
append-only artifacts for every scheduled decision, including no-trade decisions,
stale-data blocks, rejected orders, fills, equity, gross/net exposure, fees,
slippage, funding, realized/unrealized P&L, and high-water-mark drawdown. A
paper period is eligible for human review only if it has no timing violation,
no limit breach, and no unexplained missing-decision interval. Profit alone is
not an approval criterion.

## E. Implementation boundaries

This scope deliberately splits into two dependent implementation plans.

1. **Popular-universe research and 100U backtest.** Add the point-in-time
   universe selector and artifact, new experiment configuration, archive data
   planning, lineage propagation, eligibility-aware factor screening, and an
   event-backtest adapter that enforces the 100U/10U contract. Its terminal
   result is an auditable Approved decision or a no-promotion decision.
2. **Forward paper runner and observability.** Consume only an Approved decision
   from plan 1. Add the four-hour scheduler/clock abstraction, read-only data
   ingestion, paper execution ledger, risk pause state, decision artifacts, and
   Plan 04 observability views. Its terminal result is a 30-day paper record
   for human review, never a live-trading action.

The second plan cannot start without a recorded Approved decision from the first.

## F. Acceptance and test strategy

The plans must include deterministic unit, integration, and contract tests for:

- point-in-time eligibility, listing-age, data-coverage, deterministic ranking,
  lexicographic tie-breaking, and rejection when fewer than eight symbols are
  eligible;
- source-plan and snapshot lineage containing the universe artifact ID and no
  post-cutoff event or availability timestamp;
- no Candidate-to-holdout bypass, one-time holdout access, and no paper-runner
  creation before Approved status;
- one-position 10 USDT risk, two-position aggregate 10 USDT risk, 90 USDT
  gross-notional cap, daily-loss pause, and 20 USDT drawdown pause;
- tick size, step size, minimum-notional handling, fees, slippage, Funding, and
  deterministic next-available-bar execution;
- paper artifacts for entries, exits, no-trade outcomes, stale-data blocks,
  rejected orders, and exact four-hour schedule continuity;
- absence of live-order clients and API-secret reads in the paper execution
  path.

All normal tests remain offline. Small fixed archive periods may be used for
network compatibility tests only; the full popular-universe matrix is never
downloaded by a test suite.
