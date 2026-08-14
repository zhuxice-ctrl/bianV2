# 相对 Funding 压力因子设计

## 目标

在不打开 Holdout、不改变现有 ETH/100U 回测仓位规则、也不触发 paper/live 流程的前提下，新增一个可解释、点时因果、可审计的候选研究因子：`relative_funding_pressure@1.0.0`。该因子衡量某资产的 Funding 是否相对同一决策时点可用的同伴 Funding 更拥挤或更逆拥挤，并仅进入既有双周期 walk-forward 筛选流程。

本切片的完成不意味着因子进入 Candidate、Approved、Holdout、paper 或实盘。筛选不通过时，唯一允许的结果是带有真实证据的 `observed` 状态。

## 已知事实与设计选择

当前的价格/成交量筛选已对 5 个因子给出 `observed`，没有 Candidate；历史衍生品因子研究曾因可用快照不足而停止。已经合并的 Funding-alignment 切片证明本地 Canonical Funding 数据可以因果读取，并且由 `data/funding_alignment.py` 提供的是每日市场整体证据，适用于 regime 打分。

本设计不把该整体证据复制成横截面因子。相对 Funding 压力必须基于每个资产自己的最新可用 Funding，并在每一个决策时点同可用的同伴进行比较。已有 `data/snapshots.py` 已将 Canonical Funding 因果并入具有内容标识的研究快照；本切片复用该契约，不新增旁路数据读取。它不改变 `FundingAlignmentRecord`、市场周期分数或当前仓位乘数。

## 因子定义

研究资产集合由已有实验配置决定，初始范围为 BTCUSDT、ETHUSDT、BNBUSDT，频率为 4H。

对任意资产 `i` 和决策时点 `t`：

1. 取该资产最新的 Canonical Funding 事件 `r_i(t)`，要求其 `available_time <= t`，且年龄未超过该事件声明的 Funding 间隔；超过间隔的记录视为缺失。
2. 令 `P(t)` 是同一时点满足上述条件的资产集合。仅当 `|P(t)| >= 2` 时计算；否则所有资产该时点的因子值均为缺失。
3. 计算 `m(t) = median(r_j(t), j ∈ P(t))` 与 `MAD(t) = median(|r_j(t) - m(t)|, j ∈ P(t))`。
4. 若 `MAD(t) <= 0`、任意输入非有限、或资产 `i` 不属于 `P(t)`，值为缺失。不得改为零。
5. 否则：

   ```text
   relative_funding_pressure_i(t) = clip(
       (r_i(t) - m(t)) / (1.4826 * MAD(t)),
       -5.0,
       5.0,
   )
   ```

该因子采用 `two_sided` 方向：极端正值代表相对正 Funding 拥挤，极端负值代表相对负 Funding；筛选器使用既有的双侧统计与多重检验规则决定其是否具有预测价值，设计阶段不预设可交易方向，也不调优窗口、截断值或阈值。

## 架构与解耦边界

```text
Canonical Funding Parquet
  → data/snapshots.py（既有点时 Funding 加入 research snapshot）
  → immutable micro-4h research snapshot
  → factors/derivatives.py（纯横截面变换）
  → factors/dual_horizon.py（FactorSpec 与既有筛选帧）
  → research/dual_horizon.py、screening/registry（既有 walk-forward 与生命周期）
  → reporting artifact / read-only API / Dashboard
```

### 已有数据契约

`src/bian_quant/data/snapshots.py` 已负责从本地 Canonical Funding 建立 point-in-time research snapshot，并写入 `funding_rate`、`funding_available_time` 与 `funding_interval_hours`。本切片只消费已锁定的 `micro-4h`/`micro-1h` snapshot；其 snapshot ID、内容哈希、UTC 时间和可用性语义是因子输入血缘的唯一来源。

因此不新增直接读取 Parquet 的数据模块，也不改变 `data/funding_alignment.py` 的每日市场证据职责。`factors` 不读取路径，`research` 不绕过 Catalog，`backtest`、`reporting` 和 `dashboard` 不读取 Funding 文件。

### 纯因子层

`src/bian_quant/factors/derivatives.py` 只接收已标准化的 DataFrame 或不可变快照，按 `available_time` 生成相对 Funding 压力列。它不读取路径、不计算交易、不访问市场周期，也不写 artifact。因子计算必须在每个决策时点只使用此前或当时可用的同伴记录。

`src/bian_quant/factors/dual_horizon.py` 在不改变已有八个因子含义的前提下，以加性方式注册 `relative_funding_pressure@1.0.0`；它保留现有 Funding z-score、OI change 和 leverage crowding 的行为与输出字节稳定性。新因子的 `missing_policy` 为 `preserve`。

### 研究、报告与页面层

现有 walk-forward、BH 校正、冗余与增量验证是唯一的研究判定来源。研究产物记录数据集/输入哈希、样本区间、覆盖率、缺失原因、每折指标、因子状态与拒绝原因。

若现有 read-only 因子 API 已可从 artifact 枚举新因子，则页面不新增专用计算逻辑；只渲染 API 给出的名称、状态、覆盖与证据。若 wire contract 需要新增字段，必须同时更新 Pydantic 模型、空响应、异常 fallback、契约文档、契约测试和页面渲染。Dashboard 不读取 Parquet、不运行研究、不下载数据，也不显示批准、下单或运行控件。

## 契约和错误语义

| 情形 | 因子值 | 研究状态 | 证据要求 |
|---|---|---|---|
| 少于 2 个可用资产 | 缺失 | 可完成但覆盖不足时为 `observed` | `INSUFFICIENT_PEER_COVERAGE` |
| Funding 陈旧或资产无数据 | 对应资产缺失 | 可完成 | `FUNDING_UNAVAILABLE_OR_GAPPED` 或 `FUNDING_ASSET_MISSING` |
| MAD 为零 | 缺失 | 可完成 | `ZERO_CROSS_SECTIONAL_MAD` |
| 研究快照缺少 Funding 字段或不可读 | 不生成该因子帧 | 父研究按既有防御语义降级 | 明确 `missing`/`error`，不得伪造通过 |
| 合格的真实研究数据 | 按公式输出有限值 | 由既有门槛判定 | canonical JSON 与 SHA-256 |

因子 ID、版本、公式、方向、必需列、失败条件和父因子集合通过不可变 `FactorSpec` 注册。新字段一律加性；`research-terminal-v1` 现有字段和 HTTP 200 响应行为不可删除、重命名或变为可空。

## 因果性、可复现性与安全边界

- 任一输入必须满足 `available_time <= decision_time`，且全部时间戳为 UTC-aware。
- 改写截止点之后的 Funding 行、增加未来行，或改变未来同伴的 Funding，不得改变截止点及之前的快照、因子、筛选帧、统计结果或 artifact 哈希前缀。
- 相同 Canonical 输入、配置和代码版本必须产生相同排序、因子帧、canonical JSON 与 SHA-256。
- 不下载数据，不使用 API Key、私有端点、账户、订单、WebSocket、杠杆、paper 订单或实盘资金。
- 不执行 `evaluate-holdout`，不转移 FactorState 至 Candidate/Approved；任何这种决定只在后续独立的人工批准切片中考虑。

## 验收标准

1. 新因子在合成样本上精确符合中位数/MAD/截断定义，缺失和零 MAD 不产生伪零值。
2. 已有 snapshot 的 Funding 可用性契约与纯因子函数各有独立测试；依赖方向保持 `data → factors → research/reporting → dashboard`。
3. 无新输入时，已有因子帧和研究产物维持既有行为；现有 Funding-alignment 市场周期和 ETH/100U 回测不受影响。
4. 前缀因果测试覆盖未来 Funding、未来同伴值和未来可用时间三种变更。
5. 研究测试、Ruff、Ruff format、mypy、`git diff --check` 和真实离线聚合全部通过，并在证据文档中记录实际命令、哈希、覆盖率、指标和状态。
6. 若真实数据不足或未通过既有 Candidate 门槛，产物明确记录 `observed`/缺失原因并停止；不以语法检查、合成数据或局部测试替代真实证据。

## 非目标

- 不调节市场周期置信度、Funding alignment 分数、ETH 单币倍率或 BTC/ETH/BNB 100U 回测参数。
- 不修改原有八个因子的公式、窗口、门槛或历史证据。
- 不进行参数搜索、模型训练、Kronos 接入、组合优化、Holdout 开放、paper 交易或实盘交易。
