# ETH 周期加权单币策略：Aily 执行计划

> **For agentic workers:** 按任务顺序执行；每个任务先写测试，再实现，再运行门禁。禁止下载数据、实盘交易、API Key、下单或 paper 订单执行。

**Goal:** 在统一信号、事件回测和只读研究终端契约下，完成 ETHUSDT 4H Price Action 基线与市场周期加权策略的可复现比较。

**Architecture:** 新增单币评估器和审计产物适配器；只消费已有本地数据、信号协议、事件引擎和市场周期证据。研究终端只读取评估 JSON，不参与计算；ETH 评估失败只降级该节点，不改变父运行状态。

**Tech Stack:** Python 3.11、Pandas、Pydantic v2、现有 EventEngine、FastAPI、原生 HTML/JavaScript、pytest、Ruff、mypy。

---

## 0. 工作区和分支

旧分支 `codex/research-platform-implementation` 已删除（本地和远端），当前分支为 `codex/eth-cycle-weighted-strategy`。执行前确认：

```powershell
git branch --show-current
git status --short --branch
```

`.superpowers/` 是未跟踪目录，保留，不纳入提交。

## Task 1：冻结研究终端单币契约

**Files:** 创建 `tests/unit/reporting/test_research_protocol.py`；修改 `src/bian_quant/reporting/research_protocol.py`、`src/bian_quant/reporting/research_terminal.py`、`dashboard/server.py`、`docs/contracts/research-terminal-ui-contract.md`。

先写测试：空响应序列化后包含 `single_asset_strategy_evaluations: []`；ETH 项包含状态、信号、周期、推荐、审计哈希和两组指标；服务异常 fallback 仍包含全部 v1 字段。

新增冻结 Pydantic 模型：`SingleAssetStatus(ok|missing|error)`、`CurrentSignal(long|short|flat|unavailable)`、`StrategyMetrics`、`SingleAssetStrategyEvaluation`。向 `ResearchTerminalResponse` 添加默认空列表，保持 `schema_version = research-terminal-v1` 和所有旧字段不变。

```powershell
uv run pytest tests/unit/reporting/test_research_protocol.py tests/unit/reporting/test_research_terminal.py -q
git add src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py dashboard/server.py docs/contracts/research-terminal-ui-contract.md tests/unit/reporting/test_research_protocol.py tests/unit/reporting/test_research_terminal.py
git commit -m "feat(research): add single-asset evaluation contract"
```

## Task 2：实现无未来泄漏的 ETH 评估器

**Files:** 创建 `src/bian_quant/backtest/single_asset_strategy.py` 和 `tests/unit/backtest/test_single_asset_strategy.py`。

测试必须覆盖：空输入返回 `missing`；两条策略从 100U 开始；加权名义金额不超过基线；信号只在下一根 4H K 线成交；修改未来热门池记录不影响此前 multiplier、交易和权益；重复运行指标和哈希完全一致。

实现约束：输入必须排序、唯一、UTC；使用 `adapt_confluence_signals` 和现有事件引擎；止损为 `1.5 * ATR`，止盈为止损距离的 3 倍；基线每个信号 `Decimal("100")`；加权策略只改变名义金额，方向、价格、止损、止盈、费用、滑点和成交时序完全相同；每个决策时间调用 `classify_market_cycle(records_through_t)`；置信度映射固定为 `>=.80: 1.0`、`>=.65: .70`、`>=.50: .40`、`<.50: 0`；`risk_off` 和证据不足不增加仓位。

```powershell
uv run pytest tests/unit/backtest/test_single_asset_strategy.py -q
git add src/bian_quant/backtest/single_asset_strategy.py tests/unit/backtest/test_single_asset_strategy.py
git commit -m "feat(research): add causal ETH strategy evaluator"
```

## Task 3：生成和发现可审计 ETH 产物

**Files:** 创建 `src/bian_quant/reporting/single_asset_artifacts.py`、`tests/unit/reporting/test_single_asset_artifacts.py`；修改 `src/bian_quant/reporting/research_terminal.py`。

实现 `canonical_json_bytes`、`canonical_sha256`、`write_single_asset_artifact`、`load_single_asset_artifact`、`build_eth_single_asset_evaluation`。产物必须包含契约版本、资产/策略标识、成本参数、样本边界、输入 OHLCV 哈希、周期证据哈希、运行耗时、推荐、两组指标和结果哈希；写入必须原子化、键排序、紧凑 JSON、UTF-8。

发现顺序：优先 `data/ETHUSDT_4h.csv`，其次已有本地 canonical/raw 4H ETH 数据；禁止下载。缺失输入映射为 `missing`，损坏或评估异常映射为 `error`，不得改变父运行状态。

```powershell
uv run pytest tests/unit/reporting/test_single_asset_artifacts.py tests/unit/reporting/test_research_terminal.py -q
git add src/bian_quant/reporting/single_asset_artifacts.py src/bian_quant/reporting/research_terminal.py tests/unit/reporting/test_single_asset_artifacts.py tests/unit/reporting/test_research_terminal.py
git commit -m "feat(research): persist auditable ETH evaluation"
```

## Task 4：接入只读研究页面

**Files:** 修改 `dashboard/research.html`；创建或修改 `tests/integration/dashboard/test_research_page.py`。

新增 ETH 单币比较区，先显示“当前是否建议参与”，再显示当前信号、市场周期、置信度、乘数、原始策略指标、加权策略指标、样本区间和审计信息。`missing`/`error` 只显示原因，不显示建议金额。所有 API 文本经过 `escapeHtml`。页面只能 GET 刷新，不新增运行、下载、下单、密钥或交易控件；保留 `READ-ONLY · RESEARCH ONLY · NO LIVE TRADING`。

```powershell
uv run pytest tests/integration/dashboard/test_research_page.py tests/unit/reporting/test_research_terminal.py -q
node scripts/verify_log_view.js
git add dashboard/research.html tests/integration/dashboard/test_research_page.py
git commit -m "feat(research): show ETH strategy comparison"
```

## Task 5：全链路验证和证据交付

```powershell
uv run pytest tests/unit/backtest/test_single_asset_strategy.py tests/unit/reporting/test_single_asset_artifacts.py tests/unit/reporting/test_research_terminal.py tests/integration/dashboard/test_research_page.py -q
uv run ruff check src/bian_quant/backtest/single_asset_strategy.py src/bian_quant/reporting/single_asset_artifacts.py src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py
uv run mypy src/bian_quant
git diff --check
```

做前缀因果审计：只修改决策时间之后的热门池记录，比较此前全部 multiplier、成交记录和权益，必须字节级一致；首笔成交时间必须严格晚于信号决策时间。

创建 `docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md`，记录 commit SHA、运行时间、样本边界、输入/结果/产物哈希、费用参数、两组指标、当前推荐、API 状态、命令结果和未解决问题。

```powershell
git add docs/evidence/2026-08-13-eth-cycle-weighted-strategy-run.md docs/contracts/research-terminal-ui-contract.md
git commit -m "docs(research): record ETH evaluation evidence"
```

## 最终门槛

- 聚焦测试、Ruff、mypy、diff 检查全部通过；
- API 仍返回 HTTP 200，旧 v1 字段全部保留；
- ETH 缺失/错误只影响单币节点；
- 无下载、API Key、私有端点、下单或实盘逻辑；
- 因果审计通过后才进入下一研究切片，否则停止并记录原因。
