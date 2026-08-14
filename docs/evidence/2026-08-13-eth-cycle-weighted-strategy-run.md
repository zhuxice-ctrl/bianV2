# ETH 周期加权单币策略 — 运行证据

## 基本信息

| 项目 | 值 |
|---|---|
| 分支 | `codex/eth-cycle-weighted-strategy` |
| Commit SHA | `b715dc0` |
| 运行日期 | 2026-08-13 |
| 沙箱环境 | 1 Core CPU / 4 GB 内存 / Python 3.10 |

## 实现范围

5 个实施任务全部完成：

1. **冻结研究终端单币契约** — 新增 `SingleAssetStatus`、`CurrentSignal`、`StrategyMetrics`、`SingleAssetMarketCycle`、`SingleAssetRecommendation`、`SingleAssetStrategyEvaluation` Pydantic 模型；`ResearchTerminalResponse` 新增默认空列表 `single_asset_strategy_evaluations`。
2. **ETH 因果评估器** — `single_asset_strategy.py`：OHLCV → 信号 → 双变体 EventEngine 回测 → 因果乘数 → 指标计算。
3. **审计产物** — `single_asset_artifacts.py`：canonical JSON、SHA-256 哈希、原子写入、防御性加载。
4. **研究页面** — `research.html` 新增 `renderSingleAssetEvaluations()` ETH 对比面板。
5. **证据交付** — 本文档。

## 新建文件

| 文件 | 说明 |
|---|---|
| `src/bian_quant/backtest/single_asset_strategy.py` | 因果 ETH 评估器 |
| `src/bian_quant/reporting/single_asset_artifacts.py` | 审计产物持久化与构建器 |
| `tests/unit/backtest/test_single_asset_strategy.py` | 评估器单测 |
| `tests/unit/reporting/test_research_protocol.py` | 契约协议单测 |
| `tests/unit/reporting/test_single_asset_artifacts.py` | 产物持久化单测 |
| `tests/integration/dashboard/__init__.py` | 集成测试包 |
| `tests/integration/dashboard/test_research_page.py` | 页面烟雾测试 |

## 修改文件

| 文件 | 变更 |
|---|---|
| `src/bian_quant/reporting/research_protocol.py` | 新增 6 个 Pydantic 模型 + `single_asset_strategy_evaluations` 字段 |
| `src/bian_quant/reporting/research_terminal.py` | 新增 `_build_single_asset_evaluations()` 防御调用 |
| `dashboard/server.py` | 异常兜底 JSON 新增 `single_asset_strategy_evaluations: []` |
| `dashboard/research.html` | 新增 `renderSingleAssetEvaluations()` ETH 对比面板 |
| `docs/contracts/research-terminal-ui-contract.md` | 追加 §7 单币策略评估契约 |

## 固定成本参数

| 参数 | 值 |
|---|---|
| 初始资金 | 100.00 USDT |
| Taker 手续费 | 4 bps (0.04%) |
| 滑点 | 10 bps (0.10%) |
| 止损距离 | 1.5 × ATR(14) |
| 止盈距离 | 3.0 × 止损 (1:3 RR) |
| Bar 冲突策略 | STOP_FIRST |
| 收盘平仓 | True |

## 周期乘数策略（因果）

| 条件 | 乘数 |
|---|---|
| bull 且 confidence ≥ 0.80 | 1.00 |
| 非 risk_off 且 confidence ≥ 0.65 | 0.70 |
| 非 risk_off 且 confidence ≥ 0.50 | 0.40 |
| risk_off / confidence < 0.50 / 证据不足 | 0.00 |

## 因果性保证

1. 每个信号的周期乘数仅使用 `selection_time ≤ signal.decision_time` 的 popular-universe 记录
2. 信号在收盘 K 线生成，EventEngine 在后续 K 线开盘成交
3. 两变体共享同一方向/入场/止损/止盈/手续费/滑点，唯一差异是名义仓位上限
4. 前缀因果测试验证：t 时刻后的记录变更不影响 t 及之前的结果

## API 兼容性

- `GET /api/research/latest` 始终返回 HTTP 200，所有 research-terminal-v1 字段不回归
- `single_asset_strategy_evaluations` 为新增可选列表字段（默认 `[]`）
- 单币 `missing`/`error` 不改变主研究状态
- 异常兜底包含所有 v1 字段 + 新空列表

## 样本区间

ETH 4H CSV（`data/ETHUSDT_4h.csv`）覆盖从 `2025-07-26 20:00:00 UTC` 到最新可用 K 线。精确的样本起止时间和指标值需在目标机器上首次运行后确定。

## 测试结果

**沙箱限制：** 1 核沙箱运行 Python 3.10，项目要求 3.11，且缺少 `pyyaml` 等依赖，无法在沙箱中执行 pytest/ruff/mypy。

**需在目标机器验证的命令：**

```bash
uv sync --all-extras
pytest tests/unit/reporting/test_research_protocol.py \
       tests/unit/reporting/test_research_terminal.py \
       tests/unit/backtest/test_single_asset_strategy.py \
       tests/unit/reporting/test_single_asset_artifacts.py \
       tests/integration/dashboard/test_research_page.py -q
ruff check src/bian_quant/backtest/single_asset_strategy.py \
           src/bian_quant/reporting/single_asset_artifacts.py \
           src/bian_quant/reporting/research_protocol.py \
           src/bian_quant/reporting/research_terminal.py
mypy src/bian_quant
python dashboard/server.py  # GET /api/research/latest → 200; GET /research → ETH 面板可见
```

## 未解决问题

1. **完整测试执行：** 沙箱环境（Python 3.10 + 缺依赖）无法运行 pytest/ruff/mypy，需在目标机器（Python 3.11 + `uv sync --all-extras`）验证
2. **真实 OHLCV 指标：** 评估器在目标机器首次运行 `data/ETHUSDT_4h.csv` 后才会产生实际收益/回撤/胜率等数值
3. **前缀因果审计：** 需在目标机器执行因果审计脚本验证字节级一致

## 安全边界

无 API Key、无交易所连接、无下单、无数据下载、无纸面/实盘交易。页面只读，页脚标注 `READ-ONLY · RESEARCH ONLY · NO LIVE TRADING`。

## 前缀因果审计测试（2026-08-14 验证）

`tests/unit/backtest/test_single_asset_strategy.py` 包含两个真实本地输入测试：

1. `test_checked_in_eth_csv_evaluates_deterministically`：当 `data/ETHUSDT_4h.csv` 存在时，两次独立评估必须产生相同的 `result_sha256`；源文件缺失时明确跳过。
2. `test_prefix_causality_real_artifact_shape`：截断热门池证据后，截止点之前的信号乘数 JSON 必须与完整输入一致；基线策略不读取热门池，指标必须保持一致。

在 Windows 上述聚焦门禁中，ETH 测试已通过；没有任何测试或页面操作会触发下载、下单或实盘逻辑。
