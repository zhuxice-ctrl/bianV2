# Relative Funding Pressure Factor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在锁定的双周期研究快照中增加 `relative_funding_pressure@1.0.0`，以同一决策时点可用 Funding 的横截面中位数/MAD 计算压力值，并且只进入现有 development-only 筛选流程。

**Architecture:** `data/snapshots.py` 已将本地 Canonical Funding 因果写入带 snapshot ID 的 `micro-4h`/`micro-1h` 快照。本切片只补读 Funding 间隔；`factors/derivatives.py` 是唯一新计算位置，`factors/dual_horizon.py` 加性注册第 9 个因子，已有 research 筛选、artifact、registry 和只读展示路径消费其结果。

**Tech Stack:** Python 3.11、pandas、numpy、Pydantic v2、PyArrow、pytest、Ruff、mypy。

---

## 强制前置规则

每个 Task 开始时先阅读 `docs/AILY_EXECUTION_RULES.md`、`docs/superpowers/specs/2026-08-14-relative-funding-pressure-factor-design.md` 和本计划，然后运行：

```powershell
git status --short --branch
git log --oneline -5
git diff --stat
git diff --check
```

- `.superpowers/` 是用户文件：不删除、不暂存、不格式化。
- 不合并 `main`，不下载数据，不用 API Key、私有端点、账户、订单、WebSocket、paper 或实盘。
- 不调用 `evaluate_candidate_holdout`，不将 FactorState 改为 Candidate 或 Approved；development 的真实 `observed` 结果必须停止。
- 修改公共符号前，先 `rg -n "符号名" src tests dashboard`，再 `git show HEAD:<文件>`。

## 文件边界

| 文件 | 变更 | 职责 |
|---|---|---|
| `src/bian_quant/factors/derivatives.py` | 修改 | 纯横截面压力计算；不读取路径或写 artifact。 |
| `src/bian_quant/factors/dual_horizon.py` | 修改 | 注册第 9 个 FactorSpec 并接入固定因子帧。 |
| `src/bian_quant/research/operations.py` | 修改 | 从锁定 snapshot 读取 `funding_interval_hours`。 |
| `src/bian_quant/research/dual_horizon.py` | 修改 | 将新缺失原因写入 diagnostics，不改晋级门槛。 |
| `tests/unit/factors/test_derivatives_factors.py` | 修改 | 公式、缺失和前缀因果测试。 |
| `tests/integration/factors/test_dual_horizon_screening.py` | 修改 | 第 9 因子、筛选和前缀稳定性。 |
| `tests/unit/research/test_dual_horizon.py` | 修改 | diagnostics 原因码测试。 |
| `tests/unit/research/test_operations.py` | 修改 | snapshot 字段血缘与 artifact 测试。 |
| `docs/evidence/2026-08-14-relative-funding-pressure-factor-run.md` | 新建 | 真实 development 证据。 |
| `docs/implementation-notes.md` | 修改 | 已验证范围和停止边界。 |

不修改 `data/funding_alignment.py`、`regimes/market_cycle.py`、`backtest/*`、`reporting/research_protocol.py`、`dashboard/*` 或 UI 契约。新因子经已有 artifact 动态消费；如证明必须修改 wire contract，停止并先写新的契约设计。

## 固定因子契约

在 UTC-aware `available_time=t`，有效记录必须满足 `funding_available_time <= t`、Funding 值有限、`funding_interval_hours > 0`，且 `t - funding_available_time` 不大于该间隔。有效资产少于两个时给出 `NaN` / `INSUFFICIENT_PEER_COVERAGE`；缺失、未来或陈旧输入给出 `NaN` / `FUNDING_UNAVAILABLE_OR_GAPPED`；MAD 非正给出 `NaN` / `ZERO_CROSS_SECTIONAL_MAD`。不得填零。

```text
median_rate = median(valid funding_rate)
mad = median(abs(valid funding_rate - median_rate))
pressure = clip((funding_rate - median_rate) / (1.4826 * mad), -5.0, 5.0)
```

FactorSpec 固定为 ID `relative_funding_pressure`、version `1.0.0`、direction `two_sided`、`missing_policy="preserve"`。

### Task 1: 纯横截面函数与测试

**Files:**

- Modify: `src/bian_quant/factors/derivatives.py`
- Test: `tests/unit/factors/test_derivatives_factors.py`

- [ ] **Step 1: 写失败测试**

导入尚不存在的 `relative_funding_pressure`，构造 BTC/ETH/BNB 同时点、可用时间相同、间隔 8 小时、Funding 为 `0.0003/0.0001/-0.0001` 的 fixture：

```python
def test_relative_funding_pressure_uses_median_and_mad() -> None:
    values, reasons = relative_funding_pressure(frame)
    scale = 1.4826 * 0.0002
    assert values.tolist() == pytest.approx([0.0002 / scale, 0.0, -0.0002 / scale])
    assert reasons.isna().all()
```

再分别测试：一项有效资产产生 `INSUFFICIENT_PEER_COVERAGE`；未来或超过 Funding 间隔的记录产生 `FUNDING_UNAVAILABLE_OR_GAPPED`；相同 Funding 产生 `ZERO_CROSS_SECTIONAL_MAD`；重复 `asset/available_time` 抛出 `ValueError("duplicate asset/available_time rows")`。新增未来 Funding 前缀测试，并在两边以同一 cutoff 过滤 value 与 reason。

- [ ] **Step 2: 确认失败**

```powershell
uv run pytest -p no:cov tests/unit/factors/test_derivatives_factors.py -q
```

预期：收集阶段因函数不存在而失败。

- [ ] **Step 3: 实现纯接口**

在 `leverage_crowding` 后实现下面签名：

```python
def relative_funding_pressure(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    required = {
        "asset", "available_time", "funding_available_time",
        "funding_interval_hours", "funding_rate",
    }
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"relative funding frame missing columns: {sorted(missing)}")
    if frame.duplicated(["asset", "available_time"]).any():
        raise ValueError("duplicate asset/available_time rows")
    # 以 UTC 转换时间与数值；无效值先标记 FUNDING_UNAVAILABLE_OR_GAPPED。
    # 按 available_time 分组；少于两资产、MAD 非正均返回 NaN 和规定原因码。
    # 对有效组计算公式并 clip 到 [-5.0, 5.0]，返回同输入索引的 values/reasons。
```

实际实现不得修改输入 DataFrame，不得读取文件、网络或 Canonical 根目录，也不得计算标签、写 JSON 或导入 `research`/`dashboard`。

- [ ] **Step 4: 验证与提交**

```powershell
uv run pytest -p no:cov tests/unit/factors/test_derivatives_factors.py -q
uv run ruff check src/bian_quant/factors/derivatives.py tests/unit/factors/test_derivatives_factors.py
uv run ruff format --check src/bian_quant/factors/derivatives.py tests/unit/factors/test_derivatives_factors.py
git add src/bian_quant/factors/derivatives.py tests/unit/factors/test_derivatives_factors.py
git diff --cached --check
git commit -m "feat(factors): add relative funding pressure"
```

### Task 2: 接入固定因子帧和锁定 snapshot

**Files:**

- Modify: `src/bian_quant/factors/dual_horizon.py`
- Modify: `src/bian_quant/research/operations.py`
- Test: `tests/integration/factors/test_dual_horizon_screening.py`
- Test: `tests/unit/research/test_operations.py`

- [ ] **Step 1: 写失败测试**

将 `test_eight_interpretable_factors_are_registered` 改为 `test_nine_interpretable_factors_are_registered`，预期集合包含 `relative_funding_pressure`。新增多资产 4H fixture，断言：

```python
assert {
    "relative_funding_pressure",
    "relative_funding_pressure_exclusion_reason",
} <= set(frame.columns)
assert frame.loc[frame["available_time"] == timestamp, "relative_funding_pressure"].notna().sum() == 3
```

在 `test_operations.py` 的 `_frame` 加入 `funding_interval_hours: 8`。新增 cataloged-analysis 测试，读取 `factor-screening.json`，断言 `gates`、`factor_diagnostics` 和 `planned_lifecycle_states` 都含新 ID，且没有 `holdout-access.sqlite`。

- [ ] **Step 2: 确认失败**

```powershell
uv run pytest -p no:cov tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_operations.py -q
```

预期：第 9 因子、帧列或 artifact key 缺失。

- [ ] **Step 3: 实现加性接线**

在 `research/operations.py` 的 `SNAPSHOT_COLUMNS` 紧邻 `funding_available_time` 增加 `funding_interval_hours`；只从 Catalog 锁定 snapshot 读列。

将 `FACTOR_COLUMNS` 更新为以下固定顺序：

```python
FACTOR_COLUMNS = (
    "momentum_24", "reversal_12", "realized_vol_24", "volume_surprise_24",
    "amihud_24", "funding_zscore", "relative_funding_pressure",
    "oi_change", "leverage_crowding",
)
```

在 `funding_zscore` Spec 后增加：

```python
build(
    factor_id="relative_funding_pressure",
    formula="clip((funding_rate - cross_sectional_median(funding_rate)) / (1.4826 * cross_sectional_mad(funding_rate)), -5, 5)",
    direction="two_sided",
    hypothesis="relative funding extremes may reveal asset-specific leveraged crowding and subsequent return asymmetry",
    required_columns=["funding_rate", "funding_available_time", "funding_interval_hours"],
),
```

在 `compute_dual_horizon_factor_columns` 的按资产循环之前，复制并按 `available_time, asset` 排序全帧；缺失的三个 Funding 输入列填 `NaN`；调用 Task 1 函数并写入 values/reasons。之后保留原按资产的价格、Funding z-score、OI 和 leverage 计算，不能在循环内重算相对压力，结果仍按 `asset, available_time` 排序。

- [ ] **Step 4: 加入前缀与旧因子兼容测试**

仅修改 cutoff 之后的同伴 Funding（例如乘以 `-100`），双方均按 `available_time <= cutoff` 过滤，精确比较 asset、时间、压力与 reason。另以缺少三个新元数据列的输入断言新因子全缺失，而原有 8 列与原 fixture 数值和索引一致。

- [ ] **Step 5: 验证与提交**

```powershell
uv run pytest -p no:cov tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_operations.py -q
uv run ruff check src/bian_quant/factors/dual_horizon.py src/bian_quant/research/operations.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_operations.py
uv run ruff format --check src/bian_quant/factors/dual_horizon.py src/bian_quant/research/operations.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_operations.py
uv run mypy src/bian_quant
git add src/bian_quant/factors/dual_horizon.py src/bian_quant/research/operations.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_operations.py
git diff --cached --check
git commit -m "feat(research): screen relative funding pressure"
```

### Task 3: 诊断证据与 lifecycle 停止门

**Files:**

- Modify: `src/bian_quant/research/dual_horizon.py`
- Test: `tests/unit/research/test_dual_horizon.py`
- Test: `tests/integration/factors/test_dual_horizon_screening.py`

- [ ] **Step 1: 写失败测试**

构造带有 `relative_funding_pressure_exclusion_reason` 的 primary frame，并断言：

```python
assert _factor_exclusion_counts(primary, "relative_funding_pressure") == {
    "relative_funding_pressure_exclusion_reason": {
        "INSUFFICIENT_PEER_COVERAGE": 2,
        "ZERO_CROSS_SECTIONAL_MAD": 1,
    }
}
```

以固定 `run_id` 和 registry 运行弱信号多资产 fixture；`.development.json` 必须有新因子 diagnostics 和 `holdout_accessed is False`，其 lifecycle 只能是 `observed` 或 `researching`。

- [ ] **Step 2: 确认失败并最小化实现**

```powershell
uv run pytest -p no:cov tests/unit/research/test_dual_horizon.py tests/integration/factors/test_dual_horizon_screening.py -q
```

在 `_factor_exclusion_counts` 中只加入：

```python
if name == "relative_funding_pressure":
    columns.append("relative_funding_pressure_exclusion_reason")
```

不得把新因子加入 OI 延迟集合 `{ "oi_change", "leverage_crowding" }`，不得更改 BH、成本、集中度、一小时敏感性、Candidate 规则或 registry 迁移。

- [ ] **Step 3: 验证与提交**

```powershell
uv run pytest -p no:cov tests/unit/research/test_dual_horizon.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_operations.py -q
uv run ruff check src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py tests/integration/factors/test_dual_horizon_screening.py
uv run ruff format --check src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py tests/integration/factors/test_dual_horizon_screening.py
uv run mypy src/bian_quant
git add src/bian_quant/research/dual_horizon.py tests/unit/research/test_dual_horizon.py tests/integration/factors/test_dual_horizon_screening.py
git diff --cached --check
git commit -m "feat(research): audit funding pressure exclusions"
```

### Task 4: 真实 development 证据、最终门禁与停止

**Files:**

- Create: `docs/evidence/2026-08-14-relative-funding-pressure-factor-run.md`
- Modify: `docs/implementation-notes.md`

- [ ] **Step 1: 运行真实离线分析**

只能用已有本地 snapshot；禁止 acquisition、Holdout、paper 和 backtest：

```powershell
@'
from pathlib import Path
from bian_quant.data.acquisition import DualHorizonAcquisition
from bian_quant.research.operations import analyze_cataloged_dual_horizon
root = Path.cwd()
config = DualHorizonAcquisition.from_yaml(
    root / "configs" / "experiments" / "popular_universe_100u.yaml"
)
result = analyze_cataloged_dual_horizon(config, code_sha="relative-funding-pressure-1.0.0")
print("run_id=", result.run_id)
print("status=", result.status)
print("candidates=", result.candidate_factor_ids)
print("artifact_dir=", result.artifact_dir)
'@ | uv run python -
```

若结果为 `blocked`，逐字记录 error code、快照/覆盖缺口和 `holdout_accessed=false`；不得下载或编造结果。若为 `passed`，从 `factor-screening.json` 记录 snapshot IDs、代码 SHA、窗口、排除计数、每折结果、BH、冗余、增量、lifecycle、gate reasons 和 candidate 列表。

- [ ] **Step 2: 写真实证据**

证据文档必须写入实际的分支/commit、UTC 时间、执行命令、snapshot IDs/内容哈希、development 区间、`holdout_accessed: false`、Funding 覆盖/排除、因子定义、lifecycle、candidate 列表、全部 reason codes、每项门禁输出，以及“research-only；无 Holdout、paper 或 live 授权”。

- [ ] **Step 3: 最终门禁**

```powershell
uv run pytest -p no:cov tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_dual_horizon.py tests/unit/research/test_operations.py tests/unit/data/test_snapshots.py tests/unit/reporting/test_research_terminal.py tests/integration/dashboard/test_research_page.py -q
uv run ruff check src/bian_quant/factors/derivatives.py src/bian_quant/factors/dual_horizon.py src/bian_quant/research/dual_horizon.py src/bian_quant/research/operations.py tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_dual_horizon.py tests/unit/research/test_operations.py
uv run ruff format --check src/bian_quant/factors/derivatives.py src/bian_quant/factors/dual_horizon.py src/bian_quant/research/dual_horizon.py src/bian_quant/research/operations.py tests/unit/factors/test_derivatives_factors.py tests/integration/factors/test_dual_horizon_screening.py tests/unit/research/test_dual_horizon.py tests/unit/research/test_operations.py
uv run mypy src/bian_quant
git diff --check
```

任一命令非零即记录原始输出；同一缺陷三次定向修复仍失败时停止修改，记录命令、影响和下一步。

- [ ] **Step 4: 提交、推送分支并停止**

```powershell
git add docs/evidence/2026-08-14-relative-funding-pressure-factor-run.md docs/implementation-notes.md
git diff --cached --check
git commit -m "docs(research): record funding pressure evidence"
git push -u origin codex/relative-funding-pressure-factor
```

推送后停止并汇报提交、原始门禁、真实 lifecycle、candidate 列表和证据路径。即使产生 Candidate，也必须由人工另行授权才可设计或调用 Holdout；本计划不授权 main 合并、paper 或实盘。

## 完成验收

- [ ] 公式、MAD、截断、低覆盖、陈旧/Future Funding、零 MAD 与前缀因果均有精确测试。
- [ ] 仅消费锁定 snapshot；`factors` 不读取路径，research 不绕过 Catalog。
- [ ] 原有 8 因子、Funding alignment regime、ETH/100U 回测和 `research-terminal-v1` 不变。
- [ ] 新 ID 在 FactorSpec、列、diagnostics、registry artifact 和证据中一致。
- [ ] `holdout_accessed` 始终为 false，没有 ledger、paper run、订单、密钥或下载。
- [ ] 不自动合并 `main`。

