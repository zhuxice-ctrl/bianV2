# 本地研究 Snapshot 恢复设计

## 目标

在不下载任何数据、不修改旧 artifact、不放宽 snapshot resolver 身份规则的前提下，使用已有本地 Canonical 数据重建一组与当前实验配置和当前代码提交一致的内容寻址 research snapshots。恢复后仅重跑一次 development-only analysis，以验证 `relative_funding_pressure` 能进入真实研究筛选；任何结果都在 Holdout 之前停止。

## 已确认根因

`var/catalog-popular-v1.sqlite` 中存在 research-layer 的 `macro-1d` 条目，目标 Parquet 文件也存在。但 `resolve_dual_horizon_snapshots()` 要求每个主 snapshot 的 `config_json` 同时匹配：assets、`macro_start`、`micro_start`、`as_of` 和调用 analysis 时的 `code_sha`。旧 snapshot 的身份不匹配当前因子分支代码提交，因此 resolver 正确返回 `SNAPSHOT_MISSING:macro-1d`。

这不是通过改名、覆盖 Catalog、修改旧 manifest 或忽略 `code_sha` 可安全解决的问题。旧内容与当前代码身份混用会使研究输入无法复现。

## 设计决策

### 采用：从本地 Canonical 重建新的内容寻址快照

恢复切片先做只读 preflight，审计：

- 当前实验配置指定的 assets、时间区间和 `as_of`；
- Canonical OHLCV、Funding、OI 的本地路径、内容、可用时间和覆盖；
- 当前 Raw parent lineage；
- 现有 research Catalog 条目、其 manifest 与路径。

只有当所有输入可在本地验证时，才调用既有 snapshot 发布机制创建新的 research-layer 文件和 Catalog 条目。四个主 snapshot 为 `macro-1d`、`macro-4h`、`micro-1h`、`micro-4h`；其 parent snapshot IDs 必须完全相同。随后创建 5/10/15 分钟的 OI delay views，它们的 parent IDs 必须精确等于新四个主 snapshot 的 ID 集合。

新 snapshot 的 `config_json` 使用当前配置和当前 Git `code_sha`。既有 `publish_snapshot()` 的内容哈希、config 哈希、原子写入和 Catalog 注册语义是唯一允许的写入路径。旧 Parquet、旧 manifest、旧 Catalog 行和既有 evidence 不得修改或删除。

### 拒绝：放宽 resolver 身份匹配

不允许删除 `code_sha` 比较、不允许让 resolver 选择“最近”条目、不允许加入回退到旧配置的逻辑。这样会让新因子代码在旧代码身份所声明的输入上运行，破坏可审计性。

### 拒绝：手工修补 Catalog

不允许直接编辑 SQLite 行、复制 manifest JSON、重写路径或复用 snapshot ID。所有 Catalog 写入必须由 `DatasetCatalog.register()` 伴随新的不可变 `DatasetManifest` 完成。

## 架构与责任

```text
existing local Canonical data
  → read-only coverage / lineage preflight
  → existing data snapshot builder
  → new content-addressed research Parquet + Catalog rows
  → strict resolver validation
  → development-only analysis
  → immutable evidence document
```

| 层 | 允许工作 | 禁止工作 |
|---|---|---|
| `data/` | 读取本地 Canonical、构建/发布 snapshot、检查时间可用性和 lineage | 网络下载、修改旧 snapshot、因子评分 |
| `research/` | 严格解析 Catalog、运行 development 筛选、写决策 evidence | 绕过 Catalog、打开 Holdout |
| `factors/` | 消费锁定 snapshot 中的字段 | 读取路径、重建数据 |
| `reporting/dashboard` | 只消费已有 artifact | 重建、下载或运行研究 |

依赖继续保持 `data → research/factors → reporting → dashboard`。恢复切片不改变 `research-terminal-v1`、市场周期、ETH/100U 回测、paper 或交易代码。

## 状态与错误语义

| 情形 | 恢复结果 | 后续动作 |
|---|---|---|
| 本地 Canonical 覆盖、parent lineage 与四个主 snapshot 都可重建 | `recovered` | 严格 resolver 验证后重跑 development analysis |
| 任一所需本地输入缺失、损坏、覆盖不足或时间不一致 | `blocked` | 记录准确原因；不下载、不伪造 snapshot、不运行 development |
| 新 snapshot 与已存在同 ID 且内容相同 | `recovered` | 允许幂等注册，继续验证 |
| 同 ID 但内容或 manifest 冲突 | `blocked` | 保留现有文件，记录 `SNAPSHOT_CONTENT_CONFLICT` |
| resolver 找到多个满足当前身份的条目 | `blocked` | 保留所有条目，记录 `SNAPSHOT_AMBIGUOUS:<name>` |

恢复成功不代表因子表现通过。development analysis 的 `blocked`、`observed` 或零 Candidate 都是有效结果；只有明确的未来人工批准才能打开 Holdout。

## 安全与因果约束

- 所有输入均来自当前机器已有的本地 Raw/Canonical/research 文件；禁止 HTTP、交易所客户端、API Key、私有端点和下载器。
- snapshot 只包含 `available_time <= as_of` 的输入；Funding/OI 可用延迟沿用既有 data 层实现，不能在 factor 或页面修正。
- 重建前后必须比较现有旧 snapshot 的路径、manifest JSON 和字节哈希，证明旧 artifact 未变。
- 新 Catalog 条目必须带当前 `code_sha`、当前配置和同一 parent lineage；不允许使用 legacy identity 伪造通过。
- 不调用 `evaluate_candidate_holdout`、`run_small_account_backtest`、paper runner 或任何交易函数。

## 验收标准

1. preflight 产生只读审计，列出所有本地输入路径、覆盖、父 lineage 与阻塞原因；没有本地数据时停止。
2. 成功路径只新建内容寻址的 research snapshot 和 Catalog 注册；旧条目、旧文件、旧 hash 不变。
3. 四个主 snapshot 各有且仅有一个满足当前身份的 resolver 条目，且共享同一非空 parent IDs；三个 OI delay view 精确引用新主 snapshot 集合。
4. 恢复后 development analysis 实际运行并记录真实 run ID、状态、snapshot IDs、`holdout_accessed=false`、因子状态和所有原因码；不能编造指标。
5. 单元/集成测试、Ruff、format、mypy 和 `git diff --check` 全部通过；若真实 preflight blocked，证据只声明 blocked。

## 非目标

- 不修订旧 snapshot 的 `config_json`、Catalog 行或 Parquet 内容。
- 不放宽 resolver、降低覆盖门槛或改变当前实验 `as_of` 来获取通过。
- 不进行 Holdout、Candidate/Approved 人工晋级、paper、live、订单或账户操作。
