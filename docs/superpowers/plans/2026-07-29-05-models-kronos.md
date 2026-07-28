# Models and Kronos Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add transparent naive and machine-learning baselines, then evaluate Kronos as an isolated candidate-factor generator under identical data, fold, cost, and promotion rules.

**Architecture:** Every model implements one forecast interface and returns prediction distributions, not orders. Preprocessing is fit on train folds only. Kronos runs from a commit-pinned external checkout with verified weight hashes; its derived signals enter the ordinary factor registry and cannot bypass baseline comparisons.

**Tech Stack:** scikit-learn, LightGBM, optional PyTorch, Hugging Face Hub, Kronos pinned at upstream commit `67b630e67f6a18c9e9be918d9b4337c960db1e9a`.

---

### Task 1: Define model and forecast contracts

**Files:**
- Create: `src/bian_quant/models/__init__.py`
- Create: `src/bian_quant/models/protocol.py`
- Test: `tests/unit/models/test_protocol.py`

- [ ] **Step 1: Write failing protocol tests**

Create `tests/unit/models/test_protocol.py`:

```python
import pandas as pd
import pytest

from bian_quant.models.protocol import ForecastFrame


def test_forecast_rejects_noncausal_origin() -> None:
    with pytest.raises(ValueError, match="available after forecast origin"):
        ForecastFrame.from_frame(
            pd.DataFrame(
                {
                    "asset": ["BTCUSDT"],
                    "origin_time": pd.to_datetime(["2026-01-01T00:00:00Z"]),
                    "input_available_time": pd.to_datetime(["2026-01-01T01:00:00Z"]),
                    "target_time": pd.to_datetime(["2026-01-01T04:00:00Z"]),
                    "sample_id": [0],
                    "predicted_close": [101.0],
                }
            )
        )
```

- [ ] **Step 2: Implement contracts**

Create empty `src/bian_quant/models/__init__.py` and create `src/bian_quant/models/protocol.py` with:

```python
class ForecastFrame:
    REQUIRED = {
        "asset",
        "origin_time",
        "input_available_time",
        "target_time",
        "sample_id",
        "predicted_close",
    }

    @classmethod
    def from_frame(cls, frame: pd.DataFrame) -> "ForecastFrame":
        missing = cls.REQUIRED - set(frame.columns)
        if missing:
            raise ValueError(f"missing forecast columns: {sorted(missing)}")
        if (frame["input_available_time"] > frame["origin_time"]).any():
            raise ValueError("model input was available after forecast origin")
        if (frame["target_time"] <= frame["origin_time"]).any():
            raise ValueError("forecast target must follow origin")
        return cls(frame.sort_values(["asset", "origin_time", "target_time", "sample_id"]))
```

Add a `ForecastModel` protocol with `fit(train: ModelDataset)`, `predict(context: ModelDataset) -> ForecastFrame`, and `metadata() -> dict[str, object]`.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/models/test_protocol.py -q
git add src/bian_quant/models tests/unit/models
git commit -m "feat(models): define causal forecast protocol"
```

### Task 2: Add mandatory naive baselines

**Files:**
- Create: `src/bian_quant/models/baselines.py`
- Test: `tests/unit/models/test_baselines.py`

- [ ] **Step 1: Write exact baseline tests**

Create four tests with a literal close series `[100.0, 110.0, 121.0]`:

1. Persistence at origin index 2 predicts `121.0` for every requested future step.
2. Momentum with `k=2` uses the two observed log returns and predicts the next log price by adding their mean; changing a later held-out close must not change the prediction.
3. Mean reversion with `k=3` and `alpha=0.5` predicts the midpoint between `121.0` and the trailing mean `110.33333333333333`.
4. Calling `fit()` on a baseline records only train start/end and never reads a supplied test frame; use a sentinel test object that raises on access.

- [ ] **Step 2: Implement three baselines**

Implement:

```python
class PersistenceModel:  # y_hat[t+h] = close[t]
class MomentumModel:     # log y_hat = log close[t] + h * mean(last k log returns)
class MeanReversionModel:  # y_hat moves fraction alpha toward trailing k mean
```

All window and horizon values live in model metadata. Each prediction has `sample_id=0` and records the last input `available_time`.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/models/test_baselines.py -q
git add src/bian_quant/models/baselines.py tests/unit/models/test_baselines.py
git commit -m "feat(models): add mandatory naive baselines"
```

### Task 3: Build train-only model datasets and preprocessing

**Files:**
- Create: `src/bian_quant/models/dataset.py`
- Create: `src/bian_quant/models/preprocess.py`
- Test: `tests/unit/models/test_preprocess.py`

- [ ] **Step 1: Write leakage tests**

Create a train frame centered at zero and a test frame centered at 100. Assert `TrainOnlyStandardizer.fit(train).transform(test)` uses train mean/std. Append an extreme future row and assert previously transformed values do not change.

- [ ] **Step 2: Implement model dataset**

`ModelDataset` contains X, optional y, asset, decision_time, available_time, target_time, fold, and feature versions. Validate all features were available by decision time and index rows are unique.

- [ ] **Step 3: Implement train-only transformers**

Use scikit-learn `Pipeline` with median imputation and standard scaling. `fit_transform_train` returns the fitted pipeline plus train matrix; `transform_test` accepts the fitted object. No convenience function may call `fit_transform` on concatenated train/test data.

- [ ] **Step 4: Add import-boundary test**

Scan `src/bian_quant/models` and fail if production model modules import `bian_quant.factors.labels`. Labels are passed through `ModelDataset`; models do not create them.

- [ ] **Step 5: Run and commit**

```bash
uv sync --extra ml --extra dev
uv run pytest tests/unit/models/test_preprocess.py -q
git add src/bian_quant/models tests/unit/models pyproject.toml uv.lock
git commit -m "feat(models): add train-only model datasets"
```

### Task 4: Add linear and LightGBM baselines

**Files:**
- Create: `src/bian_quant/models/sklearn_models.py`
- Create: `src/bian_quant/models/lightgbm_model.py`
- Test: `tests/unit/models/test_ml_models.py`

- [ ] **Step 1: Write deterministic fit tests**

Use a synthetic monotonic dataset. Assert seeded Ridge predicts finite values, LightGBM produces identical predictions for the same seed, feature columns are stored in metadata, and an unexpected feature order raises an error.

- [ ] **Step 2: Implement Ridge baseline**

Use `Ridge(alpha=config.alpha)` inside the train-only preprocessing pipeline. Metadata records alpha, feature list, training start/end, row count, seed, package versions, and fitted-data content hash.

- [ ] **Step 3: Implement constrained LightGBM**

Initial parameters are fixed, not optimized on OOS:

```python
LGBMRegressor(
    n_estimators=300,
    learning_rate=0.03,
    num_leaves=15,
    max_depth=5,
    min_child_samples=100,
    subsample=0.8,
    colsample_bytree=0.8,
    reg_alpha=1.0,
    reg_lambda=1.0,
    random_state=seed,
    deterministic=True,
    force_col_wise=True,
)
```

If later tuning is added, it occurs only inside inner folds and logs the full search space and trial count.

- [ ] **Step 4: Run and commit**

```bash
uv run pytest tests/unit/models/test_ml_models.py -q
git add src/bian_quant/models tests/unit/models
git commit -m "feat(models): add linear and tree baselines"
```

### Task 5: Add a pinned external Kronos checkout script

**Files:**
- Create: `scripts/fetch_kronos.sh`
- Create: `scripts/fetch_kronos.ps1`
- Create: `src/bian_quant/models/kronos_checkout.py`
- Test: `tests/unit/models/test_kronos_checkout.py`

- [ ] **Step 1: Write checkout validation tests**

Mock git commands and assert validation rejects a dirty checkout, wrong remote URL, or any SHA other than `67b630e67f6a18c9e9be918d9b4337c960db1e9a`.

- [ ] **Step 2: Implement Linux fetch script**

```bash
#!/usr/bin/env bash
set -euo pipefail
target="var/vendor/kronos"
sha="67b630e67f6a18c9e9be918d9b4337c960db1e9a"
test ! -e "$target" || { echo "target exists: $target" >&2; exit 1; }
git clone https://github.com/shiyu-coder/Kronos.git "$target"
git -C "$target" checkout --detach "$sha"
test -z "$(git -C "$target" status --porcelain)"
```

Create an equivalent PowerShell script using `Test-Path`, `git clone`, `git checkout --detach`, and a clean-status assertion. Do not delete or replace an existing checkout.

- [ ] **Step 3: Implement validator**

`validate_kronos_checkout(path)` returns upstream SHA and remote URL after verifying exact values and clean status. It raises stable reason codes `KRONOS_SHA_MISMATCH`, `KRONOS_REMOTE_MISMATCH`, or `KRONOS_DIRTY`.

- [ ] **Step 4: Run offline tests and commit**

```bash
uv run pytest tests/unit/models/test_kronos_checkout.py -q
git add scripts/fetch_kronos.* src/bian_quant/models/kronos_checkout.py tests/unit/models/test_kronos_checkout.py
git commit -m "feat(models): pin isolated Kronos source"
```

### Task 6: Download pinned weights and verify provenance before loading

**Files:**
- Create: `src/bian_quant/models/weights.py`
- Create: `scripts/fetch_kronos_weights.py`
- Create: `configs/models/kronos_zero_shot.yaml`
- Test: `tests/unit/models/test_weights.py`

- [ ] **Step 1: Write hash-manifest tests**

Assert a model directory with the expected files and SHA-256 passes; one changed byte fails before any Torch import. Assert missing provenance field `pretrained_after_leakage_fix` is represented as `unknown`, not guessed true.

- [ ] **Step 2: Implement pinned download script**

Create `scripts/fetch_kronos_weights.py` using `huggingface_hub.snapshot_download`. Download only `config.json`, `model.safetensors`, and `README.md` into separate ignored directories under `var/models/`. Use these immutable revisions:

```python
MODEL = ("NeoQuasar/Kronos-mini", "f4e68697d9d5aed55cef5c96aabc3376bcad9f81")
TOKENIZER = (
    "NeoQuasar/Kronos-Tokenizer-2k",
    "26966d0035065a0cae0ebad7af8ece35bc1fb51c",
)
```

After download, calculate SHA-256 for every regular file in streaming 1 MiB chunks and write `weight_manifest.json` with repository IDs, revisions, relative file paths, hashes, UTC download time, MIT license, `pretrained_after_leakage_fix: "unknown"`, and evidence URL `https://github.com/shiyu-coder/Kronos/issues/307`. Refuse to run when the destination already exists; never update weights in place.

- [ ] **Step 3: Implement weight manifest verification**

The local manifest contains model ID, tokenizer ID, Hugging Face revision, file hashes, download timestamp, license, `pretrained_after_leakage_fix`, and evidence URL. `verify_weight_manifest` validates every file in streaming chunks.

- [ ] **Step 4: Create zero-shot config**

Create `configs/models/kronos_zero_shot.yaml`:

```yaml
upstream_repo: https://github.com/shiyu-coder/Kronos.git
upstream_commit: 67b630e67f6a18c9e9be918d9b4337c960db1e9a
model_id: NeoQuasar/Kronos-mini
tokenizer_id: NeoQuasar/Kronos-Tokenizer-2k
model_revision: f4e68697d9d5aed55cef5c96aabc3376bcad9f81
tokenizer_revision: 26966d0035065a0cae0ebad7af8ece35bc1fb51c
lookback: 360
horizons: [1, 4, 24]
temperature: 0.8
top_p: 0.9
top_k: 0
sample_count: 5
seed: 7
device: cuda:0
pretrained_after_leakage_fix: unknown
```

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/unit/models/test_weights.py -q
git add scripts/fetch_kronos_weights.py src/bian_quant/models/weights.py configs/models/kronos_zero_shot.yaml tests/unit/models/test_weights.py
git commit -m "feat(models): verify Kronos weight provenance"
```

### Task 7: Implement Kronos inference behind an adapter

**Files:**
- Create: `src/bian_quant/models/kronos_adapter.py`
- Test: `tests/unit/models/test_kronos_adapter.py`
- Test: `tests/integration/models/test_kronos_smoke.py`

- [ ] **Step 1: Write mocked adapter tests**

Mock the upstream `KronosPredictor`. Assert the adapter supplies OHLCV columns in exact order, uses only rows available by origin, seeds NumPy/Torch, emits one row per sample/path/target, and records all sampling parameters.

- [ ] **Step 2: Implement lazy upstream import**

The module must not import Torch or upstream Kronos at module import time. `KronosAdapter.load()` first validates checkout and weights, inserts the validated checkout into an isolated import context, loads tokenizer/model, moves them to configured device, and sets eval mode.

- [ ] **Step 3: Add VRAM-safe batching**

Start `batch_size=1`, call `torch.inference_mode()`, use float32 for correctness baseline, and record peak allocated VRAM. On CUDA OOM, mark the run `failed` with `KRONOS_CUDA_OOM`; do not silently fall back to CPU because that changes resource and timing evidence.

- [ ] **Step 4: Add explicit integration smoke test**

Mark with both `models` and `network`. Use 400 BTC 1h rows, predict one step with `sample_count=1`, and assert finite OHLC output and causal timestamps:

```bash
uv sync --extra models --extra dev
bash scripts/fetch_kronos.sh
uv run python scripts/fetch_kronos_weights.py
uv run pytest tests/integration/models/test_kronos_smoke.py -q -m "models and network"
```

This smoke test downloads weights only after user/operator confirms disk usage. Record model file hashes in `var/`, not Git.

- [ ] **Step 5: Commit code without weights**

```bash
git add src/bian_quant/models/kronos_adapter.py tests/unit/models tests/integration/models
git commit -m "feat(models): add isolated Kronos inference adapter"
```

### Task 8: Derive registered factors from forecast distributions

**Files:**
- Create: `src/bian_quant/models/forecast_factors.py`
- Test: `tests/unit/models/test_forecast_factors.py`

- [ ] **Step 1: Write literal-path tests**

Given three forecast paths, assert exact values for median horizon return, positive-return probability, return dispersion, predicted realized volatility, predicted high/low range, and worst path drawdown.

- [ ] **Step 2: Implement derivations**

Implement pure functions over `ForecastFrame`. Each result emits a normal `SignalRecord` with factor IDs:

```text
model.kronos.median_return
model.kronos.positive_probability
model.kronos.return_dispersion
model.kronos.predicted_volatility
model.kronos.predicted_range
model.kronos.path_drawdown
```

Factor version includes upstream SHA, weight revision, and derivation version. Confidence for directional signals is empirical sample probability; dispersion remains a separate value, not inverted into undocumented confidence.

- [ ] **Step 3: Run and commit**

```bash
uv run pytest tests/unit/models/test_forecast_factors.py -q
git add src/bian_quant/models/forecast_factors.py tests/unit/models/test_forecast_factors.py
git commit -m "feat(models): derive factors from forecast paths"
```

### Task 9: Run identical-fold model comparison and enforce baseline gate

**Files:**
- Create: `src/bian_quant/models/compare.py`
- Modify: `src/bian_quant/cli.py`
- Test: `tests/integration/models/test_model_comparison.py`

- [ ] **Step 1: Write fairness test**

Create fake models whose predictions encode received fold IDs. Assert all models receive identical train/test indexes, labels, costs, assets, and horizons. Assert a Kronos-like model with lower MAPE but worse cost-adjusted return cannot be called the trading winner.

- [ ] **Step 2: Implement comparison**

For every outer fold, run persistence, momentum, mean reversion, Ridge, LightGBM, and enabled Kronos factors. Report forecast MAE/MAPE, direction accuracy, IC/RankIC, calibration where applicable, turnover, cost-adjusted return, drawdown, runtime, and peak RAM/VRAM.

- [ ] **Step 3: Enforce model gate**

Kronos-derived factors remain `observed` unless they provide statistically supported incremental performance over the best pre-registered baseline, pass normal/stress costs, pass concentration/stability gates, and disclose weight leakage provenance as known-clean. If provenance remains `unknown`, maximum state is `observed` regardless of performance.

- [ ] **Step 4: Add CLI**

```bash
bian-quant compare-models --dataset <snapshot-id> --config configs/models/kronos_zero_shot.yaml --seed 7
```

- [ ] **Step 5: Run and commit**

```bash
uv run pytest tests/integration/models/test_model_comparison.py -q
git add src/bian_quant/models/compare.py src/bian_quant/cli.py tests/integration/models
git commit -m "feat(models): compare models on identical folds"
```

### Task 10: Document the fine-tuning decision gate

**Files:**
- Create: `docs/models/kronos-finetuning-gate.md`

- [ ] **Step 1: Write the gate document**

The document must state that fine-tuning is blocked until all are true:

- Zero-shot adapter and baselines are reproducible.
- Public-weight provenance is resolved or locally clean weights will be trained.
- Task-aligned objective is selected using inner folds only.
- Dataset normalization passes the future-leakage sentinel.
- 32GB RAM and either 12GB+ local VRAM or approved cloud budget are available.
- Expected disk, GPU hours, experiment count, and stop conditions are approved.
- A no-fine-tune baseline and ablation plan are registered.

- [ ] **Step 2: Commit**

```bash
git add docs/models/kronos-finetuning-gate.md
git commit -m "docs: define Kronos fine-tuning gate"
```

## Plan 05 exit gate

- [ ] Persistence, momentum, and mean-reversion baselines are mandatory.
- [ ] Ridge/LightGBM preprocessing fits train folds only.
- [ ] Kronos source and weights are verified before Torch import.
- [ ] Default test suite requires no weights or network.
- [ ] One explicit GPU smoke test records hashes and peak VRAM.
- [ ] Kronos outputs ordinary registered signals, not orders.
- [ ] All models use identical folds and costs.
- [ ] Unknown clean-weight provenance prevents Kronos promotion beyond `observed`.
- [ ] Fine-tuning remains blocked behind the written approval gate.
