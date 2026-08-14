# 资金费率对齐市场周期评分 — 运行证据

## 基本信息

| 项目 | 值 |
|---|---|
| 分支 | `codex/eth-cycle-weighted-strategy` |
| 基线 Commit | `063e457` |
| 运行日期 | 2026-08-13 |
| 沙箱环境 | 1 Core CPU / 4 GB 内存 / Python 3.11 |

## 实现范围

本切片在 `codex/eth-cycle-weighted-strategy` 分支上以加性契约方式扩展市场周期评分，引入资金费率对齐信号。所有变更为加性：旧消费者在 `funding_alignment=None` 时获得与基线字节一致的结果。

### 任务 2 — 资金费率对齐数据契约与本地 Parquet 适配器

- 新建 `src/bian_quant/data/funding_alignment.py`
- 冻结数据类 `FundingAlignmentRecord`：`decision_time`、`available_time`、`member_count`、`positive_rate_share`、`median_rate`、`coverage_ratio`、`source_sha256`
- `__post_init__` 验证：tz-aware、`available_time <= decision_time`、shares ∈ [0,1]、`member_count >= 0`、`source_sha256` 为 64 位小写 hex
- `build_daily_funding_alignment(canonical_root, *, assets, as_of)`：读取 `plan=*/funding/<ASSET>/native/*.parquet`，过滤 `available_time <= as_of`，按 UTC 日期聚合
- `latest_alignment_through(records, decision_time)`：返回决策时刻可用的最近对齐记录
- API 缓存 `_ALIGNMENT_CACHE` 避免重复扫描 Canonical lake

### 任务 3 — 纯市场周期评分扩展

- 修改 `src/bian_quant/backtest/market_cycle_comparison.py`
- `classify_market_cycle` 新增可选参数 `funding_alignment: tuple[FundingAlignmentRecord, ...] | None = None`
- 当 `funding_alignment` 非空且覆盖率 ≥ 0.5 时：`alignment_raw = 1.0 - 2.0 * positive_rate_share`，贡献 = clamp(alignment_raw × 0.10, -0.10, +0.10)
- 风险厌恶门控：当 `risk_score > bull_score` 时，正向贡献归零（逆向看涨不提升风险厌恶主导期）
- 当 `funding_alignment=None` 时：evidence 字典不含任何 funding 键 → `evidence_sha256` 与基线字节一致

### 任务 4 — 加性 API/UI 契约

- `research_protocol.py`：`MarketCycle` 新增 `funding_alignment: FundingAlignment` 字段（`Field(default_factory=_default_funding_alignment)`）
- `FundingAlignment` Pydantic 模型：`score`、`positive_rate_share`、`median_rate`、`coverage_ratio`、`source_sha256`（均 `| None`）+ `status: str`（`"ok" | "missing" | "error"`）
- `research_terminal.py`：`_build_funding_alignment_safe()` + `_build_funding_alignment_node()` 防御调用
- `server.py`：异常兜底 JSON 的 `market_cycle` 块新增 `funding_alignment` 子对象
- `research.html`：新增 `fundingLine()` JS 辅助 + 技术网格「资金费率对齐」行

### 任务 5 — 完整证据

- 本文档
- 契约文档更新
- 实现笔记更新

## 新建文件

| 文件 | 说明 |
|---|---|
| `src/bian_quant/data/funding_alignment.py` | Canonical 资金费率 Parquet → 不可变每日对齐记录适配器 |
| `tests/unit/data/test_funding_alignment.py` | 适配器单测（10 个测试） |

## 修改文件

| 文件 | 变更 |
|---|---|
| `src/bian_quant/regimes/market_cycle.py` | `classify_market_cycle` 新增可选 `funding_alignment` 参数 + 评分逻辑 |
| `src/bian_quant/reporting/research_protocol.py` | 新增 `FundingAlignment` 模型 + `MarketCycle.funding_alignment` 字段 |
| `src/bian_quant/reporting/research_terminal.py` | 资金费率对齐安全构建 + 节点组装 |
| `dashboard/server.py` | 异常兜底 JSON 新增 `funding_alignment` 子对象 |
| `dashboard/research.html` | 新增 `fundingLine()` + 资金费率对齐渲染行 |
| `tests/unit/regimes/test_market_cycle.py` | 新增 7 个资金费率对齐测试 |
| `tests/unit/reporting/test_research_protocol.py` | 新增 4 个 `FundingAlignment` 序列化测试 |
| `tests/integration/dashboard/test_research_page.py` | 新增资金费率对齐标记验证 |
| `docs/contracts/research-terminal-ui-contract.md` | `MarketCycle` 类型新增 `funding_alignment` 字段 |
| `docs/implementation-notes.md` | 追加 2026-08-13 条目 |

## 评分参数

| 参数 | 值 | 说明 |
|---|---|---|
| `_MIN_FUNDING_COVERAGE_RATIO` | 0.5 | 低于此值不应用资金费率评分（不阻塞） |
| `_MAX_FUNDING_CONTRIBUTION` | 0.10 | 资金费率对 bull_score 的最大绝对贡献 |
| 广泛正向资金费率 | `positive_rate_share → 1.0` | alignment_raw → -1.0 → 贡献 → -0.10（看跌） |
| 广泛负向资金费率 | `positive_rate_share → 0.0` | alignment_raw → +1.0 → 贡献 → +0.10（看涨） |
| 风险厌恶门控 | `risk_score > bull_score` | 正向贡献归零 |

## 因果性保证

1. `build_daily_funding_alignment` 仅返回 `available_time <= as_of` 的记录
2. `latest_alignment_through(records, decision_time)` 过滤 `available_time <= decision_time`
3. 前缀因果测试 `test_future_funding_no_prefix_change`：截断后的资金费率记录不改变截止点之前的市场周期评分

## 向后兼容性

- `classify_market_cycle(funding_alignment=None)` → evidence 字典不含 funding 键 → `evidence_sha256` 与基线一致
- `MarketCycle.funding_alignment` 默认 `status="missing"`，旧消费者可安全忽略
- `research-terminal-v1` 契约仅加字段，不破坏旧字段

## 安全边界

无 API Key、无交易所连接、无下单、无数据下载、无纸面/实盘交易。资金费率数据来自本地 Canonical Parquet lake，不涉及任何网络请求。

## 测试结果

**Windows 验证结果（2026-08-14）：**

- `uv run pytest -p no:cov`（Funding、市场周期、三币比较、ETH、终端和页面聚焦集）：**44 passed, 5 skipped**。
- `uv run ruff check`（Funding、regime、比较、终端与契约文件）：通过。
- `uv run mypy src/bian_quant`：通过，检查 **93** 个源文件。
- 聚合器实测生成 `research-terminal-v1` 的 `passed` 响应，`market_cycle.funding_alignment.status == "ok"`。

使用的命令：

```bash
uv sync --all-extras
uv run pytest -p no:cov tests/unit/data/test_funding_alignment.py \
       tests/unit/regimes/test_market_cycle.py \
       tests/unit/backtest/test_market_cycle_comparison.py \
       tests/unit/backtest/test_single_asset_strategy.py \
       tests/unit/reporting/test_research_protocol.py \
       tests/unit/reporting/test_research_terminal.py \
       tests/integration/dashboard/test_research_page.py -q
uv run ruff check src/bian_quant/data/funding_alignment.py \
           src/bian_quant/regimes/market_cycle.py \
           src/bian_quant/reporting/research_protocol.py \
           src/bian_quant/reporting/research_terminal.py
uv run mypy src/bian_quant
```

## 未解决问题

1. **完整测试执行：** 默认全量 pytest 在此 Windows 输出环境仍可能超时；本证据只声明上述聚焦集已通过。
2. **合并建议：** 仍需人工确认完整质量门和审计证据后再合并 main；不自动合并。
