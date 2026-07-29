# Factors and Regimes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a versioned factor factory, causal market-regime classifier, dependence-aware evaluation, redundancy control, and evidence-driven factor lifecycle.

**Architecture:** Factor implementations are pure functions over point-in-time frames and are registered with immutable specifications. Labels are created separately, evaluation occurs inside walk-forward folds, and lifecycle transitions consume saved evidence rather than ad hoc rankings.

**Tech Stack:** Pydantic, pandas/NumPy/SciPy, scikit-learn optional, SQLite, pytest/Hypothesis.

---

### Task 1: Define factor specifications and lifecycle transitions

**Files:**
- Create: `src/bian_quant/factors/__init__.py`
- Create: `src/bian_quant/factors/spec.py`
- Create: `src/bian_quant/factors/registry.py`
- Test: `tests/unit/factors/test_registry.py`

- [ ] **Step 1: Write failing registry tests**

Create `tests/unit/factors/test_registry.py`:

```python
from pathlib import Path

import pytest

from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorSpec, FactorState


def sample_spec() -> FactorSpec:
    return FactorSpec(
        factor_id="price.momentum",
        version="1.0.0",
        formula="close / close.shift(24) - 1",
        direction="positive",
        hypothesis="persistent price movement may continue over the next horizon",
        required_columns=["close"],
        horizon="4h",
        missing_policy="preserve",
        winsor_limits=[0.01, 0.99],
        valid_regimes=["all"],
        failure_conditions=["cost-adjusted OOS IC lower bound <= 0"],
        parent_factors=[],
    )


def test_retired_factor_needs_explicit_restart_evidence(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)
    registry.transition("price.momentum", "1.0.0", FactorState.RETIRED, evidence_run_id="run-1")

    with pytest.raises(ValueError, match="restart evidence"):
        registry.transition("price.momentum", "1.0.0", FactorState.RESEARCHING)
```

- [ ] **Step 2: Implement immutable factor spec**

Create empty `src/bian_quant/factors/__init__.py` and create `src/bian_quant/factors/spec.py`:

```python
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class FactorState(StrEnum):
    RESEARCHING = "researching"
    OBSERVED = "observed"
    CANDIDATE = "candidate"
    APPROVED = "approved"
    RETIRED = "retired"


class FactorSpec(BaseModel):
    model_config = ConfigDict(frozen=True)

    factor_id: str
    version: str
    formula: str
    direction: Literal["positive", "negative", "two_sided"]
    hypothesis: str = Field(min_length=20)
    required_columns: list[str]
    horizon: str
    missing_policy: Literal["preserve", "zero_if_structural"]
    winsor_limits: tuple[float, float]
    valid_regimes: list[str]
    failure_conditions: list[str]
    parent_factors: list[str]
```

- [ ] **Step 3: Implement SQLite registry**

Create `src/bian_quant/factors/registry.py` with `factor_specs` and append-only `factor_transitions` tables. Enforce:

```python
LEGAL = {
    FactorState.RESEARCHING: {FactorState.OBSERVED, FactorState.RETIRED},
    FactorState.OBSERVED: {FactorState.CANDIDATE, FactorState.RETIRED},
    FactorState.CANDIDATE: {FactorState.APPROVED, FactorState.OBSERVED, FactorState.RETIRED},
    FactorState.APPROVED: {FactorState.OBSERVED, FactorState.RETIRED},
    FactorState.RETIRED: {FactorState.RESEARCHING},
}
```

Every transition except initial registration requires `evidence_run_id`. `RETIRED → RESEARCHING` additionally requires non-empty `restart_reason` and `restart_evidence_run_id`.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/factors/test_registry.py -q
git add src/bian_quant/factors tests/unit/factors
git commit -m "feat(factors): add factor registry and lifecycle"
```

### Task 2: Add causal return labels

**Files:**
- Create: `src/bian_quant/factors/labels.py`
- Test: `tests/unit/factors/test_labels.py`

- [ ] **Step 1: Write exact horizon tests**

Create `tests/unit/factors/test_labels.py`:

```python
import pandas as pd

from bian_quant.factors.labels import forward_log_return


def test_forward_label_uses_future_close_only_as_label() -> None:
    close = pd.Series([100.0, 110.0, 121.0], index=pd.date_range("2026-01-01", periods=3, freq="h", tz="UTC"))

    label = forward_log_return(close, periods=1)

    assert round(label.iloc[0], 12) == round(label.iloc[1], 12)
    assert pd.isna(label.iloc[-1])
```

- [ ] **Step 2: Implement labels in an isolated module**

Create `src/bian_quant/factors/labels.py`:

```python
import numpy as np
import pandas as pd


def forward_log_return(close: pd.Series, *, periods: int) -> pd.Series:
    if periods <= 0:
        raise ValueError("periods must be positive")
    return np.log(close.shift(-periods) / close).rename(f"forward_log_return_{periods}")
```

No production factor module may import `factors.labels`; enforce this later with an import-boundary test.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/factors/test_labels.py -q
git add src/bian_quant/factors/labels.py tests/unit/factors/test_labels.py
git commit -m "feat(factors): isolate forward return labels"
```

### Task 3: Implement the first interpretable price and volume factors

**Files:**
- Create: `src/bian_quant/factors/base.py`
- Create: `src/bian_quant/factors/price.py`
- Create: `src/bian_quant/factors/volume.py`
- Test: `tests/unit/factors/test_price_factors.py`
- Test: `tests/unit/factors/test_volume_factors.py`

- [ ] **Step 1: Write causal-prefix invariance tests**

Create `tests/unit/factors/test_price_factors.py`:

```python
import pandas as pd
from pandas.testing import assert_series_equal

from bian_quant.factors.price import momentum, realized_volatility, reversal


def test_future_append_does_not_change_existing_factor_values() -> None:
    base = pd.Series(range(1, 101), dtype=float)
    extended = pd.concat([base, pd.Series([10_000.0])], ignore_index=True)

    assert_series_equal(momentum(base, periods=12), momentum(extended, periods=12).iloc[:-1])
    assert_series_equal(reversal(base, periods=6), reversal(extended, periods=6).iloc[:-1])
    assert_series_equal(
        realized_volatility(base, periods=12), realized_volatility(extended, periods=12).iloc[:-1]
    )
```

Create equivalent prefix tests for `volume_surprise(volume, periods=24)` and `amihud_illiquidity(close, volume, periods=24)`.

- [ ] **Step 2: Implement pure functions**

Create `src/bian_quant/factors/price.py`:

```python
import numpy as np
import pandas as pd


def momentum(close: pd.Series, *, periods: int) -> pd.Series:
    return (close / close.shift(periods) - 1.0).rename(f"momentum_{periods}")


def reversal(close: pd.Series, *, periods: int) -> pd.Series:
    return (-momentum(close, periods=periods)).rename(f"reversal_{periods}")


def realized_volatility(close: pd.Series, *, periods: int) -> pd.Series:
    returns = np.log(close / close.shift(1))
    return returns.rolling(periods, min_periods=periods).std(ddof=1).rename(f"realized_vol_{periods}")
```

Create `src/bian_quant/factors/volume.py`:

```python
import numpy as np
import pandas as pd


def volume_surprise(volume: pd.Series, *, periods: int) -> pd.Series:
    mean = volume.rolling(periods, min_periods=periods).mean()
    std = volume.rolling(periods, min_periods=periods).std(ddof=1)
    return ((volume - mean) / std.replace(0.0, np.nan)).rename(f"volume_surprise_{periods}")


def amihud_illiquidity(close: pd.Series, volume: pd.Series, *, periods: int) -> pd.Series:
    absolute_return = np.log(close / close.shift(1)).abs()
    dollar_volume = close * volume
    ratio = absolute_return / dollar_volume.replace(0.0, np.nan)
    return ratio.rolling(periods, min_periods=periods).mean().rename(f"amihud_{periods}")
```

Create `base.py` with a `FactorFunction` protocol accepting a point-in-time `DataFrame` and returning a named `Series` aligned to its index.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/factors/test_price_factors.py tests/unit/factors/test_volume_factors.py -q
git add src/bian_quant/factors tests/unit/factors
git commit -m "feat(factors): add causal price and volume library"
```

### Task 4: Add derivatives factors with availability checks

**Files:**
- Create: `src/bian_quant/factors/derivatives.py`
- Test: `tests/unit/factors/test_derivatives_factors.py`

- [ ] **Step 1: Write point-in-time tests**

Test `funding_zscore`, `oi_change`, and `leverage_crowding` with fixtures where one funding/OI record has `available_time` after the decision bar. Assert that the late record cannot influence the factor at that bar.

- [ ] **Step 2: Implement an as-of join helper**

Use `pandas.merge_asof` on sorted `available_time`, grouped by asset, with `direction="backward"` and `allow_exact_matches=True`. The joined row must expose its source `available_time` for audit.

- [ ] **Step 3: Implement factors**

```python
def funding_zscore(funding_rate: pd.Series, *, periods: int) -> pd.Series:
    mean = funding_rate.rolling(periods, min_periods=periods).mean()
    std = funding_rate.rolling(periods, min_periods=periods).std(ddof=1)
    return ((funding_rate - mean) / std.replace(0.0, np.nan)).rename(
        f"funding_zscore_{periods}"
    )


def oi_change(open_interest: pd.Series, *, periods: int) -> pd.Series:
    return open_interest.pct_change(periods=periods, fill_method=None).rename(
        f"oi_change_{periods}"
    )


def leverage_crowding(funding_z: pd.Series, oi_delta: pd.Series) -> pd.Series:
    return (funding_z * oi_delta.clip(lower=0.0)).rename("leverage_crowding")
```

Use only backward-looking rolling statistics. Preserve missing values when a source did not exist; do not replace unavailable OI with zero.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/factors/test_derivatives_factors.py -q
git add src/bian_quant/factors/derivatives.py tests/unit/factors/test_derivatives_factors.py
git commit -m "feat(factors): add point-in-time derivatives factors"
```

### Task 5: Implement a causal regime classifier

**Files:**
- Create: `src/bian_quant/regimes/__init__.py`
- Create: `src/bian_quant/regimes/classifier.py`
- Test: `tests/unit/regimes/test_classifier.py`

- [ ] **Step 1: Write prefix invariance and threshold-fit tests**

Create `tests/unit/regimes/test_classifier.py` using a 200-row deterministic close/volume fixture. The first test fits thresholds on rows `0:120`, changes rows `120:` by a factor of ten, and asserts the fitted dataclass is unchanged. The second classifies rows `0:150`, appends a crash row, reclassifies, and uses `assert_series_equal` on the original 150 labels. The third constructs five trailing windows whose normalized trend, volatility, and illiquidity cross one threshold at a time and asserts the exact labels `trend_low_vol`, `trend_high_vol`, `range_low_vol`, `range_high_vol`, and `liquidity_stress`.

- [ ] **Step 2: Implement two-stage classifier**

Create `RegimeThresholds` containing train-only quantiles for rolling volatility, trend strength, and illiquidity. `fit_regime_thresholds(train_frame)` computes them. `classify_regime(frame, thresholds)` emits one of:

```python
"trend_low_vol"
"trend_high_vol"
"range_low_vol"
"range_high_vol"
"liquidity_stress"
```

Trend strength is `abs(close / close.shift(48) - 1) / rolling_vol_48`; liquidity stress overrides other classes when illiquidity exceeds its train-only 95th percentile. No full-sample quantiles are allowed.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/regimes/test_classifier.py -q
git add src/bian_quant/regimes tests/unit/regimes
git commit -m "feat(factors): classify causal market regimes"
```

### Task 6: Add IC, stability, and multiple-testing evaluation

**Files:**
- Create: `src/bian_quant/factors/evaluate.py`
- Create: `src/bian_quant/factors/multiple_testing.py`
- Test: `tests/unit/factors/test_evaluate.py`

- [ ] **Step 1: Write evaluation tests**

Create four tests with literal fixtures:

1. Factor `[1, 2, 3, 4]` and label `[10, 20, 30, 40]` must produce RankIC `1.0`.
2. Metadata containing two assets, two folds, and two regimes must produce all eight group keys, with no pooled group silently replacing them.
3. P-values `{"a": 0.001, "b": 0.02, "c": 0.20}` at alpha `0.05` must accept `a` and `b` and reject `c` under Benjamini-Hochberg.
4. Factor `[1.0, NaN, 3.0, NaN]` must report coverage `0.5` and sample count `2`; the evaluator must not turn missing values into zeros.

- [ ] **Step 2: Implement fold evaluator**

`evaluate_factor(factor, label, metadata, fold)` returns a `FactorEvaluation` with Pearson IC, Spearman RankIC, coverage, turnover, fold, asset, regime, sample count, and stationary-block confidence interval. Compute winsor thresholds on train data and apply them unchanged to test data.

- [ ] **Step 3: Implement Benjamini-Hochberg**

Implement `benjamini_hochberg(p_values: dict[str, float], alpha: float) -> dict[str, bool]` from the sorted rank threshold `p_(i) <= i/m * alpha`. Validate p-values are within `[0, 1]`.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/factors/test_evaluate.py -q
git add src/bian_quant/factors tests/unit/factors
git commit -m "feat(factors): evaluate stability and multiple tests"
```

### Task 7: Control factor redundancy and incremental contribution

**Files:**
- Create: `src/bian_quant/factors/redundancy.py`
- Test: `tests/unit/factors/test_redundancy.py`

- [ ] **Step 1: Write redundant-factor tests**

Create fixtures with one factor, an exact scaled copy, and an independent factor. Assert the scaled copy shares a cluster and cannot both become the cluster representative.

- [ ] **Step 2: Implement clustering**

Compute train-only Spearman correlation, convert to distance `1 - abs(correlation)`, use SciPy hierarchical clustering at a configured threshold, and select one representative per cluster using inner-validation score only. Return cluster membership and rejection reason codes.

- [ ] **Step 3: Add incremental test**

Fit a regularized linear baseline on train data, add one candidate, and evaluate delta IC and delta cost-adjusted return on validation. Store both absolute and incremental metrics; a factor with no incremental value remains `observed` even if standalone IC is strong.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/factors/test_redundancy.py -q
git add src/bian_quant/factors/redundancy.py tests/unit/factors/test_redundancy.py
git commit -m "feat(factors): remove redundant candidates"
```

### Task 8: Add factor batch runner and lifecycle evidence

**Files:**
- Create: `src/bian_quant/factors/runner.py`
- Modify: `src/bian_quant/cli.py`
- Test: `tests/integration/factors/test_factor_pipeline.py`

- [ ] **Step 1: Write end-to-end factor test**

Using a small deterministic fixture, register momentum, compute it, build labels, create walk-forward folds, evaluate by fold/regime, apply multiple-testing and redundancy rules, persist metrics, and transition only when evidence passes. Assert the run ID appears in the transition row.

- [ ] **Step 2: Implement runner**

The runner must accept `dataset_snapshot_id`, factor specs, split config, seed, and artifact directory. It must never infer these values from the current clock or latest files. On failure, transition the run to `failed` and persist a structured error; on blocking data quality, transition to `blocked`.

- [ ] **Step 3: Add CLI command**

```bash
bian-quant evaluate-factors --dataset legacy-v1 --config configs/experiments/factor_screen.yaml --seed 7
```

The command prints only `run_id` and artifact path; detailed results belong in artifacts.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/integration/factors/test_factor_pipeline.py -q
git add src/bian_quant/factors src/bian_quant/cli.py tests/integration/factors
git commit -m "feat(factors): run evidence-driven factor pipeline"
```

### Task 9: Add bounded, auditable candidate generation

**Files:**
- Create: `src/bian_quant/factors/primitives.py`
- Create: `src/bian_quant/factors/generator.py`
- Create: `configs/factors/search_space.yaml`
- Test: `tests/unit/factors/test_generator.py`

- [ ] **Step 1: Write grammar and leakage-boundary tests**

Assert:

1. The grammar can build `zscore(momentum(close, 24), 168)` and produces the same expression hash for identical trees.
2. Expressions containing label names, negative lags, centered windows, forward fill from future rows, unrestricted Python calls, or unknown columns are rejected.
3. Algebraically duplicated candidates with identical normalized expression trees are emitted once.
4. A fixed seed and search manifest produce the same ordered candidate list.
5. `max_candidates=20` cannot emit 21 candidates even when the grid is larger.

- [ ] **Step 2: Implement safe primitives without `eval`**

Implement typed expression nodes for:

```text
column
lag(periods > 0)
delta(periods > 0)
percent_change(periods > 0)
rolling_mean(window >= 2)
rolling_std(window >= 2)
zscore(window >= 2)
rolling_rank(window >= 2)
add
subtract
multiply
safe_ratio
clip
```

Each node declares required lookback, output unit, parent IDs, and a pure pandas computation. `safe_ratio` returns missing when denominator magnitude is below the configured epsilon. The evaluator walks the node tree; it never evaluates source strings.

- [ ] **Step 3: Create the initial bounded search space**

Create `configs/factors/search_space.yaml`:

```yaml
seed: 7
max_candidates: 20
max_tree_depth: 3
base_factors:
  - price.momentum
  - price.reversal
  - price.realized_volatility
  - volume.surprise
  - volume.amihud
  - derivatives.funding_zscore
  - derivatives.oi_change
windows: [6, 12, 24, 48, 168]
allowed_unary: [lag, delta, zscore, rolling_rank]
allowed_binary: [add, subtract, multiply, safe_ratio]
```

Generation order is deterministic: registered economic templates first, then seeded grammar samples. Every output includes expression tree, expression hash, full search-manifest hash, generation rank, parent factors, required lookback, and code SHA.

- [ ] **Step 4: Enforce research-only initial state**

Generated candidates register as `researching`. They cannot transition during generation. Evaluation, multiple-testing correction, redundancy checks, and lifecycle evidence from earlier tasks remain mandatory.

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/unit/factors/test_generator.py -q
git add src/bian_quant/factors configs/factors/search_space.yaml tests/unit/factors/test_generator.py
git commit -m "feat(factors): generate bounded auditable candidates"
```

## Plan 03 exit gate

- [ ] Factor specs are immutable and versioned.
- [ ] Retired factors cannot silently restart.
- [ ] Label code is isolated from production factor modules.
- [ ] Price, volume, funding, and OI factors pass future-append invariance.
- [ ] Regime thresholds are fit on train folds only.
- [ ] Evaluation reports fold/asset/regime coverage and block confidence intervals.
- [ ] Multiple-testing and redundancy controls reject synthetic false discoveries.
- [ ] A factor lifecycle transition always cites evidence `run_id`.
- [ ] Candidate generation is bounded, deterministic, label-isolated, and fully recorded.
