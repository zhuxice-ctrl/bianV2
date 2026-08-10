# 热门币研究：切片 1（数据与热门池）设计

## 目标

交付一个可独立运行、可明确验收的真实数据闭环：热门币历史归档、canonical 数据、四个 research snapshot 与每日热门池 artifact。

本切片只解决数据层的可用性问题。不运行因子研究、holdout、100U 回测或纸面周期。

## 当前问题

`build_source_plan()` 以统一的 `macro_start` 为全部 16 个合约生成归档请求。APT、SUI、TON 等合约在部分早期月份尚未上市，Binance 公开归档正确返回 HTTP 404；采集器将这些请求记为阻断，导致真实数据运行的状态为 `blocked`。

这不是网络瞬断，也不是应通过降低覆盖率来掩盖的数据缺口。

## 已确认的产品边界

- 研究继续使用 16 个热门、高流动性 USDT 永续合约作为种子池。
- BTC、ETH、BNB 是未来纸面交易的优先范围；本切片不实现交易筛选或交易执行。
- 每日热门池仍要求：点时数据可见、30 日 K 线/Funding/OI 覆盖、上市至少 180 天、最多 12 币、少于 8 币稳定阻断。
- 不使用 API Key、私有 endpoint、订单、杠杆、真实资金或自动实盘逻辑。
- 保留现有 `var/` 原始归档；不得删除或覆盖已校验的对象。

## 设计

### 历史归档可用性清单

新增仓库受控的 YAML 文件 `configs/data/popular_universe_archive_availability.yaml`。清单以 `(asset, dataset, granularity)` 为键，而不是为每个资产设置单一起点。每条记录至少包含：

- `asset`、`dataset` 与 `granularity`；
- 第一个可请求的归档 period：月度对象使用 `first_available_month`，日度对象使用 `first_available_day`；
- 该对象的 `identity_key`、公开归档 URL、manifest 的内容 SHA-256；
- 该归档解析出的 `first_event_time`，仅作审计，不作为月度 URL 的边界。

因此，OHLCV、Funding、Metrics/OI 不假定从同一时刻可用。Metrics/OI 只有日度记录；OHLCV 和 Funding 的月度记录独立冻结。若后续发现某数据集的首个可用 period 与 OHLCV 不同，只更新该数据集的记录，不共用或猜测起点。

清单与主配置一起进入计划 hash；采集 artifact 保存清单内容 hash 和每个证据对象的哈希。

### 清单初始化（bootstrap）

初始化不依赖一份 `passed` 的旧运行，也不访问新网络资源。实现一个本地 bootstrap 命令或受测试的库函数，扫描当前 `var/lake/raw/binance-futures-um-popular-v1`：

1. 对每个已有 zip 与 manifest 调用现有 `reuse_verified_artifact()`，仅接受哈希和身份都匹配的对象。
2. 按 `(asset, dataset, granularity, source_period)` 排序，选择每类最早的已验证归档对象。
3. 使用现有 canonicalizer 只读解析该对象，记录 `first_event_time`，并以该对象的月或日 `source_period` 作为清单边界。
4. 任一资产/数据集/粒度缺少可验证证据时，bootstrap 显式失败；不得写入估计值或以 404 推断上市日期。

被阻断的旧运行可以包含大量独立校验通过的 raw 对象；其整体状态为 `blocked` 不影响这些对象用作 bootstrap 证据。生成的清单必须人工复核后才纳入配置并用于新的 source plan。

### 资产级计划裁剪

在生成 source plan 时，按对象粒度将全局起点与清单中的首个可请求 period 取较晚者。月度对象比较月度 period，日度对象比较自然日；不将月度归档内的首行事件时间转换为请求边界。

其中：

- OHLCV 的全局起点仍分别是 `macro_start` 或 `micro_start`。
- Funding 的全局起点仍是 `macro_start`。
- Metrics/OI 的全局起点仍是 `micro_start`。
- 月度对象从 `max(global_month, first_available_month)` 开始生成；这允许资产在月中上市时保留其首个实际存在的月度 archive，也避免请求首个实际 archive 之前不存在的月份。
- 日度对象从 `max(global_day, first_available_day)` 开始生成。

因此，上市前的 URL 不会再进入采集计划；BTC、ETH、BNB 及其他较早可用资产的历史不会被全局缩短。

### 审计与错误处理

采集 artifact 必须包括可用性清单的内容哈希，以及按资产、数据集、粒度列出的 `PRE_LISTING_EXCLUDED` 对象数或范围。该记录表示“没有生成请求”，不是下载成功。

对于计划内对象，以下情况仍为阻断：

- HTTP 404 或其他不可获取响应；
- 校验和不匹配；
- 不完整原始对象；
- canonical schema、时间可见性或覆盖率失败；
- 每日热门池少于 8 个符合条件的资产。

不把计划内的 404 自动豁免为上市前缺失。

`funding_tail_strategy` 与上市前裁剪是两套规则。尚未由上游发布的 cutoff 月 Funding archive 不能被写入 `PRE_LISTING_EXCLUDED`；它仍为阻断，并要求在官方 archive 发布后重新运行。切片 1 的真实验收以 cutoff 月 archive 已可获得为前提。

### 数据复用和运行方式

既有原始文件及其 manifest 会由现有校验复用逻辑跳过。裁剪后的计划仅包含仍需验证或下载的对象；不会清理 `var/`。

切片验收时运行同一入口：

```powershell
$sha = git rev-parse HEAD
uv run bian-quant prepare-dual-horizon --config configs/experiments/popular_universe_100u.yaml --code-sha $sha --download
```

## 验收标准

1. 真实运行的 acquisition 与 quality artifact 均为 `passed`。
2. artifact 记录数据集级、归档粒度级的可用性清单及 `PRE_LISTING_EXCLUDED` 审计信息。
3. 四个 snapshot：`macro-1d`、`macro-4h`、`micro-1h`、`micro-4h` 全部存在，且 lineage 一致。
4. 每日热门池 artifact 全部生成；每一天均有 8–12 个成员，否则以稳定、可解释的错误阻断。
5. 上市前月份或日期不在 source plan 中；上市后人为模拟的 404 仍使运行阻断。
6. 已存在且校验通过的 raw 对象可复用，不产生覆盖写入。
7. snapshot 可包含各资产不同的最早时间；下游构建与热门池只使用各自可见、满足覆盖率的数据，不要求各资产等长。

## 验证计划

- 单元测试：清单 bootstrap 只接受校验通过的 raw 对象，并为月度和日度对象记录正确的 period 边界。
- 单元测试：资产/数据集/粒度级裁剪、月度边界、日度边界、计划 hash 稳定性。
- 单元测试：清单缺失、证据无效或数据集起点不一致时阻断或按数据集独立处理。
- 集成测试：有效 raw artifact 重跑被跳过；计划内 404 仍 `blocked`。
- 集成测试：不同资产起点的 snapshot 可发布；未发布的 Funding cutoff archive 仍稳定阻断。
- 目标测试与静态检查通过后，执行一次真实的 `prepare-dual-horizon --download`，读取全部 artifact 后才宣布切片 1 完成。

## 非目标

- 不改变因子定义、Candidate/Approved 门禁或 holdout 协议。
- 不运行 100U 回测或纸面交易。
- 不将热门池缩减为 BTC、ETH、BNB；三者的交易优先级属于后续切片。
