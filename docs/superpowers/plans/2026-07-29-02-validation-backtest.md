# Validation and Backtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give every factor and model one causal signal protocol, nested anchored walk-forward validation, cost-aware vector screening, and deterministic event-driven portfolio backtesting.

**Architecture:** Signal providers emit immutable `SignalRecord` rows. A split generator owns all time boundaries, an experiment registry owns run status and artifacts, a vector evaluator screens candidates, and an event engine verifies fills, costs, funding, and drawdown under scenario stress.

**Tech Stack:** Pydantic, pandas/NumPy/SciPy, SQLite, pytest/Hypothesis.

---

### Task 1: Define the unified signal protocol

**Files:**
- Create: `src/bian_quant/signals/__init__.py`
- Create: `src/bian_quant/signals/protocol.py`
- Test: `tests/unit/signals/test_protocol.py`

- [ ] **Step 1: Write failing causality tests**

Create `tests/unit/signals/test_protocol.py`:

```python
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bian_quant.signals.protocol import SignalRecord


def test_signal_cannot_be_available_after_decision() -> None:
    with pytest.raises(ValidationError):
        SignalRecord(
            asset="BTCUSDT",
            decision_time=datetime(2026, 1, 1, tzinfo=UTC),
            available_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
            horizon="4h",
            value=0.2,
            confidence=None,
            factor_id="price.momentum",
            factor_version="1.0.0",
        )


def test_confidence_is_probability_when_present() -> None:
    with pytest.raises(ValidationError):
        SignalRecord(
            asset="BTCUSDT",
            decision_time=datetime(2026, 1, 1, 1, tzinfo=UTC),
            available_time=datetime(2026, 1, 1, tzinfo=UTC),
            horizon="4h",
            value=0.2,
            confidence=1.1,
            factor_id="price.momentum",
            factor_version="1.0.0",
        )
```

- [ ] **Step 2: Implement the frozen protocol**

Create empty `src/bian_quant/signals/__init__.py` and create `src/bian_quant/signals/protocol.py`:

```python
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SignalRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    asset: str
    decision_time: datetime
    available_time: datetime
    horizon: str
    value: float
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    factor_id: str
    factor_version: str

    @model_validator(mode="after")
    def validate_causality(self) -> "SignalRecord":
        if self.decision_time.tzinfo is None or self.available_time.tzinfo is None:
            raise ValueError("signal timestamps must be timezone-aware")
        if self.available_time > self.decision_time:
            raise ValueError("signal was not available at decision_time")
        return self
```

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/signals/test_protocol.py -q
git add src/bian_quant/signals tests/unit/signals
git commit -m "feat(validation): define causal signal protocol"
```

### Task 2: Add experiment run identity and state transitions

**Files:**
- Create: `src/bian_quant/experiments/__init__.py`
- Create: `src/bian_quant/experiments/models.py`
- Create: `src/bian_quant/experiments/registry.py`
- Test: `tests/unit/experiments/test_registry.py`

- [ ] **Step 1: Write failing append-only run tests**

Create `tests/unit/experiments/test_registry.py`:

```python
from pathlib import Path

import pytest

from bian_quant.experiments.models import RunManifest, RunStatus
from bian_quant.experiments.registry import ExperimentRegistry


def test_completed_run_cannot_return_to_running(tmp_path: Path) -> None:
    registry = ExperimentRegistry(tmp_path / "registry.sqlite")
    manifest = RunManifest.create(
        code_sha="a" * 40,
        dataset_snapshot_ids=["legacy-v1"],
        config={"factor": "momentum"},
        seed=7,
    )
    registry.create(manifest)
    registry.transition(manifest.run_id, RunStatus.RUNNING)
    registry.transition(manifest.run_id, RunStatus.PASSED)

    with pytest.raises(ValueError, match="invalid run transition"):
        registry.transition(manifest.run_id, RunStatus.RUNNING)
```

- [ ] **Step 2: Implement manifest and deterministic identity payload**

Create empty `src/bian_quant/experiments/__init__.py` and create `src/bian_quant/experiments/models.py`:

```python
import hashlib
import json
import uuid
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"


class RunManifest(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    identity_sha256: str
    code_sha: str
    dataset_snapshot_ids: list[str]
    config: dict[str, Any]
    seed: int
    status: RunStatus = RunStatus.QUEUED

    @classmethod
    def create(
        cls,
        *,
        code_sha: str,
        dataset_snapshot_ids: list[str],
        config: dict[str, Any],
        seed: int,
    ) -> "RunManifest":
        payload = json.dumps(
            {
                "code_sha": code_sha,
                "datasets": sorted(dataset_snapshot_ids),
                "config": config,
                "seed": seed,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        identity = hashlib.sha256(payload.encode()).hexdigest()
        return cls(
            run_id=str(uuid.uuid4()),
            identity_sha256=identity,
            code_sha=code_sha,
            dataset_snapshot_ids=dataset_snapshot_ids,
            config=config,
            seed=seed,
        )
```

- [ ] **Step 3: Implement legal state transitions in SQLite**

Create `src/bian_quant/experiments/registry.py` with a `runs` table and this transition map:

```python
LEGAL_TRANSITIONS = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.BLOCKED},
    RunStatus.RUNNING: {RunStatus.PASSED, RunStatus.FAILED, RunStatus.BLOCKED},
    RunStatus.PASSED: set(),
    RunStatus.FAILED: set(),
    RunStatus.BLOCKED: set(),
}
```

`create()` must insert a new `run_id`; `transition()` must read current status in one transaction and raise `ValueError("invalid run transition")` when the edge is absent. Never reuse a previous run ID even when `identity_sha256` matches.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/experiments/test_registry.py -q
git add src/bian_quant/experiments tests/unit/experiments
git commit -m "feat(validation): add append-only experiment registry"
```

### Task 3: Implement purged anchored walk-forward splits

**Files:**
- Create: `src/bian_quant/validation/__init__.py`
- Create: `src/bian_quant/validation/splits.py`
- Test: `tests/unit/validation/test_splits.py`

- [ ] **Step 1: Write split invariants with Hypothesis**

Create `tests/unit/validation/test_splits.py`:

```python
import pandas as pd
from hypothesis import given, strategies as st

from bian_quant.validation.splits import anchored_walk_forward


@given(embargo=st.integers(min_value=1, max_value=8))
def test_train_labels_never_overlap_test(embargo: int) -> None:
    index = pd.date_range("2020-01-01", periods=240, freq="D", tz="UTC")
    folds = anchored_walk_forward(
        index,
        initial_train=120,
        test_size=24,
        step=24,
        label_horizon=embargo,
        embargo=embargo,
    )

    assert folds
    for fold in folds:
        assert fold.train.max() + pd.Timedelta(days=embargo) < fold.test.min()
        assert fold.train.min() == index.min()
```

- [ ] **Step 2: Implement the split object and generator**

Create empty `src/bian_quant/validation/__init__.py` and create `src/bian_quant/validation/splits.py`:

```python
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class TimeFold:
    number: int
    train: pd.DatetimeIndex
    test: pd.DatetimeIndex


def anchored_walk_forward(
    index: pd.DatetimeIndex,
    *,
    initial_train: int,
    test_size: int,
    step: int,
    label_horizon: int,
    embargo: int,
) -> list[TimeFold]:
    if not index.is_monotonic_increasing or index.has_duplicates:
        raise ValueError("index must be sorted and unique")
    folds: list[TimeFold] = []
    test_start = initial_train
    number = 0
    while test_start + test_size <= len(index):
        train_end = test_start - label_horizon - embargo
        if train_end <= 0:
            raise ValueError("purge and embargo remove the training set")
        folds.append(
            TimeFold(
                number=number,
                train=index[:train_end],
                test=index[test_start : test_start + test_size],
            )
        )
        number += 1
        test_start += step
    return folds
```

- [ ] **Step 3: Add locked-holdout partition test**

Add `partition_locked_holdout(index, holdout_size)` that returns `(research_index, locked_index)`, refuses `holdout_size <= 0`, and guarantees disjoint indexes. Persist the locked range in the experiment config; no function may accept tuning results from the locked range.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/validation/test_splits.py -q
git add src/bian_quant/validation tests/unit/validation
git commit -m "feat(validation): add purged anchored walk-forward splits"
```

### Task 4: Add block-bootstrap metrics and effective sample reporting

**Files:**
- Create: `src/bian_quant/validation/metrics.py`
- Create: `src/bian_quant/validation/bootstrap.py`
- Test: `tests/unit/validation/test_metrics.py`

- [ ] **Step 1: Write deterministic metric tests**

Create `tests/unit/validation/test_metrics.py`:

```python
import numpy as np

from bian_quant.validation.bootstrap import stationary_block_ci
from bian_quant.validation.metrics import max_drawdown, sharpe_ratio


def test_max_drawdown_uses_equity_path() -> None:
    assert max_drawdown(np.array([100.0, 120.0, 90.0, 110.0])) == -0.25


def test_block_ci_is_seeded() -> None:
    values = np.linspace(-0.01, 0.02, 200)
    first = stationary_block_ci(values, statistic=np.mean, block_size=12, samples=500, seed=7)
    second = stationary_block_ci(values, statistic=np.mean, block_size=12, samples=500, seed=7)
    assert first == second


def test_zero_variance_sharpe_is_zero() -> None:
    assert sharpe_ratio(np.zeros(100), periods_per_year=365 * 6) == 0.0
```

- [ ] **Step 2: Implement metric functions**

Create `src/bian_quant/validation/metrics.py`:

```python
import numpy as np
from numpy.typing import NDArray


def max_drawdown(equity: NDArray[np.float64]) -> float:
    peak = np.maximum.accumulate(equity)
    return float(np.min(equity / peak - 1.0))


def sharpe_ratio(returns: NDArray[np.float64], *, periods_per_year: int) -> float:
    std = float(np.std(returns, ddof=1))
    if std == 0.0 or not np.isfinite(std):
        return 0.0
    return float(np.mean(returns) / std * np.sqrt(periods_per_year))
```

- [ ] **Step 3: Implement stationary block CI**

Create `src/bian_quant/validation/bootstrap.py` with a seeded NumPy generator. Each bootstrap path must sample contiguous circular blocks of `block_size` until it reaches the original length, evaluate `statistic`, and return `(2.5th percentile, 97.5th percentile)` as floats. Reject `block_size < 2`, `samples < 100`, and empty arrays.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/validation/test_metrics.py -q
git add src/bian_quant/validation tests/unit/validation
git commit -m "feat(validation): add dependence-aware metrics"
```

### Task 5: Implement the fast vector screening engine

**Files:**
- Create: `src/bian_quant/backtest/__init__.py`
- Create: `src/bian_quant/backtest/vector.py`
- Test: `tests/unit/backtest/test_vector.py`

- [ ] **Step 1: Write no-lookahead and cost tests**

Create `tests/unit/backtest/test_vector.py`:

```python
import pandas as pd

from bian_quant.backtest.vector import vector_backtest


def test_signal_earns_only_next_bar_return() -> None:
    frame = pd.DataFrame(
        {
            "signal": [1.0, 0.0, 0.0],
            "forward_return": [0.10, -0.20, 0.30],
        }
    )
    result = vector_backtest(frame, cost_bps=0.0)
    assert result.net_returns.tolist() == [0.0, -0.20, 0.0]


def test_turnover_pays_cost() -> None:
    frame = pd.DataFrame({"signal": [1.0, -1.0, 0.0], "forward_return": [0.0, 0.0, 0.0]})
    result = vector_backtest(frame, cost_bps=10.0)
    assert result.net_returns.sum() == -0.003
```

- [ ] **Step 2: Implement vector engine**

Create empty `src/bian_quant/backtest/__init__.py` and create `src/bian_quant/backtest/vector.py`:

```python
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class VectorResult:
    positions: pd.Series
    gross_returns: pd.Series
    costs: pd.Series
    net_returns: pd.Series


def vector_backtest(frame: pd.DataFrame, *, cost_bps: float) -> VectorResult:
    positions = frame["signal"].shift(1).fillna(0.0).clip(-1.0, 1.0)
    gross = positions * frame["forward_return"]
    turnover = positions.diff().abs().fillna(positions.abs())
    costs = turnover * cost_bps / 10_000.0
    return VectorResult(positions, gross, costs, gross - costs)
```

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/backtest/test_vector.py -q
git add src/bian_quant/backtest tests/unit/backtest
git commit -m "feat(backtest): add causal vector screening"
```

### Task 6: Implement deterministic cost and funding models

**Files:**
- Create: `src/bian_quant/backtest/costs.py`
- Test: `tests/unit/backtest/test_costs.py`

- [ ] **Step 1: Write exact cost tests**

Create `tests/unit/backtest/test_costs.py`:

```python
from bian_quant.backtest.costs import CostModel


def test_round_trip_cost_contains_fee_and_slippage_twice() -> None:
    model = CostModel(taker_fee_bps=4.0, slippage_bps=5.0)
    assert model.round_trip_fraction() == 0.0018


def test_long_position_pays_positive_funding() -> None:
    model = CostModel(taker_fee_bps=4.0, slippage_bps=5.0)
    assert model.funding_cashflow(notional=10_000, position_sign=1, funding_rate=0.0001) == -1.0
```

- [ ] **Step 2: Implement immutable model**

Create `src/bian_quant/backtest/costs.py`:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class CostModel:
    taker_fee_bps: float
    slippage_bps: float

    def one_way_fraction(self) -> float:
        return (self.taker_fee_bps + self.slippage_bps) / 10_000.0

    def round_trip_fraction(self) -> float:
        return 2.0 * self.one_way_fraction()

    def funding_cashflow(self, *, notional: float, position_sign: int, funding_rate: float) -> float:
        return -notional * position_sign * funding_rate
```

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/backtest/test_costs.py -q
git add src/bian_quant/backtest/costs.py tests/unit/backtest/test_costs.py
git commit -m "feat(backtest): model fees slippage and funding"
```

### Task 7: Add the event-driven engine with explicit bar-conflict policy

**Files:**
- Create: `src/bian_quant/backtest/events.py`
- Create: `src/bian_quant/backtest/engine.py`
- Test: `tests/unit/backtest/test_event_engine.py`

- [ ] **Step 1: Write golden fill tests**

Create `tests/unit/backtest/test_event_engine.py` with a five-bar UTC fixture. Use opens `[100, 101, 102, 103, 104]`, highs `[102, 112, 106, 107, 108]`, lows `[99, 89, 100, 101, 102]`, closes `[101, 105, 104, 106, 107]`, fee `4 bps`, slippage `10 bps`, and initial equity `10_000`.

Implement these exact assertions:

1. A long signal decided on bar 0 fills on bar 1 with reference price `101` and execution price `101.101`.
2. With stop `90` and target `110`, bar 1 touches both; `STOP_FIRST` records exit reason `stop` and reference price `90`, never target.
3. A funding event at bar 2 changes cash exactly once; an identical rate attached to a non-funding timestamp changes cash zero times.
4. A requested notional of `20_000` under gross limit `1.0` and equity `10_000` fills no more than `10_000` notional before costs.
5. With no stop/target hit and `close_at_end=True`, the final exit uses bar 4 close reference price `107`; with `close_at_end=False`, the trade remains open and equity is marked at `107`.

Assert exact fill reference price, execution direction, fee, funding, PnL, and final equity. Use `Decimal` or integer quote units inside the engine so cent-level golden fixtures do not depend on binary floating-point rounding.

- [ ] **Step 2: Implement event types**

Create `src/bian_quant/backtest/events.py` with frozen dataclasses `Bar`, `SignalEvent`, `Fill`, `FundingEvent`, `Trade`, and enum `BarConflictPolicy.STOP_FIRST`. All timestamps must be timezone-aware.

- [ ] **Step 3: Implement engine rules**

Create `src/bian_quant/backtest/engine.py` implementing:

1. Consume a signal only when `available_time <= decision_time`.
2. Place market entry at the next bar open with adverse slippage.
3. Cap target notional by `gross_limit * current_equity`.
4. If stop and target occur in one bar under `STOP_FIRST`, exit at stop.
5. Apply funding only at matching funding timestamps using position notional before the cashflow.
6. Deduct fee on every fill.
7. Close or mark the final position according to an explicit `close_at_end` flag.

The engine returns `BacktestResult(trades, fills, equity, returns, diagnostics)`; diagnostics include rejected signals and their reason codes.

- [ ] **Step 4: Run golden and property tests**

```bash
uv run pytest tests/unit/backtest/test_event_engine.py -q
```

Add Hypothesis properties: equity is finite, rejected future signals never create fills, gross exposure never exceeds the limit, and zero signal creates zero trades.

- [ ] **Step 5: Commit**

```bash
git add src/bian_quant/backtest tests/unit/backtest
git commit -m "feat(backtest): add deterministic event engine"
```

### Task 8: Add scenarios and promotion policy

**Files:**
- Create: `src/bian_quant/validation/scenarios.py`
- Create: `src/bian_quant/validation/promotion.py`
- Create: `configs/experiments/baseline_pa.yaml`
- Test: `tests/unit/validation/test_promotion.py`

- [ ] **Step 1: Write a policy rejection test**

Create `tests/unit/validation/test_promotion.py`:

```python
from bian_quant.validation.promotion import FoldMetrics, PromotionPolicy


def test_policy_rejects_strategy_driven_by_one_fold() -> None:
    folds = [
        FoldMetrics(net_return=0.50, sharpe=3.0, max_drawdown=-0.10),
        FoldMetrics(net_return=-0.02, sharpe=-0.2, max_drawdown=-0.12),
        FoldMetrics(net_return=-0.01, sharpe=-0.1, max_drawdown=-0.08),
        FoldMetrics(net_return=-0.03, sharpe=-0.3, max_drawdown=-0.09),
    ]

    decision = PromotionPolicy().evaluate(folds, sharpe_ci_lower=-0.1, stress_drawdown=-0.20)

    assert not decision.passed
    assert "POSITIVE_FOLD_RATIO" in decision.reasons
```

- [ ] **Step 2: Implement scenarios**

`scenarios.py` must produce named immutable configs for `ideal`, `normal`, `double_cost`, `one_bar_delay`, `parameter_down`, `parameter_up`, `data_gap`, and `price_spike`. It must not mutate the base experiment config.

- [ ] **Step 3: Implement exact promotion gates**

`PromotionPolicy.evaluate()` must require all of:

```python
positive_fold_ratio >= 0.70
median_sharpe >= 0.80
sharpe_ci_lower > 0.0
normal_max_drawdown >= -0.15
stress_drawdown >= -0.25
```

It must also accept boolean diagnostics for baseline increment, concentration, parameter stability, leakage, reproducibility, and data quality. Any false diagnostic adds a stable reason code and fails the decision.

- [ ] **Step 4: Create baseline experiment manifest**

Create `configs/experiments/baseline_pa.yaml` with explicit assets, interval, initial train size, test size, step, horizon, embargo, locked holdout size, seed, normal costs, stress costs, and promotion thresholds. Use the design thresholds above; do not tune them using PA results.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/unit/validation/test_promotion.py -q
git add src/bian_quant/validation configs/experiments tests/unit/validation
git commit -m "feat(validation): enforce scenario promotion gates"
```

### Task 9: Adapt legacy PA signals to the common pipeline

**Files:**
- Create: `src/bian_quant/signals/legacy_pa.py`
- Test: `tests/integration/signals/test_legacy_pa_adapter.py`
- Create: `docs/evidence/pa-engine-comparison.md`

- [ ] **Step 1: Write signal-count and timing tests**

Run the existing `confluence_signals` function on a fixed 4h fixture. Assert the adapter emits one `SignalRecord` for every nonzero legacy signal, sets `decision_time` and `available_time` to the completed signal-bar close, sets horizon `4h`, and never exposes the next bar open inside the signal record.

- [ ] **Step 2: Implement adapter without copying legacy strategy math**

Import `strategies.price_action.confluence_signals`, call it on Canonical OHLCV, and convert outputs to `factor_id="legacy.pa_confluence"`, `factor_version="baseline-0"`, values `-1.0` or `1.0`, and `confidence=None`. Keep the legacy strategy module frozen.

- [ ] **Step 3: Run identical data through both engines**

Execute the legacy engine and new event engine on the tracked BTC/ETH/BNB 4h snapshot. Produce `docs/evidence/pa-engine-comparison.md` with differences in entry timing, same-bar conflict policy, fees/slippage, trade count, return, drawdown, and open-position handling. Differences caused by more conservative explicit semantics are expected evidence, not reasons to alter the new engine to match old headline returns.

- [ ] **Step 4: Run PA through the new promotion gate**

Use `configs/experiments/baseline_pa.yaml`. Persist its result regardless of pass/fail. The adapter receives no exemption from positive-fold, Sharpe, drawdown, stress, concentration, or locked-holdout rules.

- [ ] **Step 5: Test and commit**

```bash
uv run pytest tests/integration/signals/test_legacy_pa_adapter.py -q
git add src/bian_quant/signals/legacy_pa.py tests/integration/signals docs/evidence/pa-engine-comparison.md
git commit -m "feat(validation): adapt PA baseline to common engine"
```

## Plan 02 exit gate

- [ ] Signal protocol rejects future availability.
- [ ] Run records are append-only and terminal statuses cannot reopen.
- [ ] Anchored folds satisfy purge/embargo properties.
- [ ] Block bootstrap is deterministic for a fixed seed.
- [ ] Vector engine shifts signals before returns.
- [ ] Event engine passes exact fill, conflict, funding, and exposure tests.
- [ ] All required stress scenarios exist.
- [ ] Promotion policy rejects concentrated or statistically weak results.
- [ ] Locked holdout boundaries are stored in the run manifest.
- [ ] Legacy PA enters through `SignalRecord` and receives no promotion exemption.
