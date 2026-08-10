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

### 资产历史可用起点

新增一份版本化、受证据约束的热门币历史可用起点表。每个资产至少记录：

- `asset`
- `first_available_time`
- 支撑该结论的公开归档对象及其 SHA-256

该表的值来自已成功校验的原始 OHLCV 归档中该资产的最早事件时间；它不是人工估计的上市日期。表随配置和采集 artifact 一起纳入 lineage。

### 资产级计划裁剪

在生成 source plan 时，对每个资产与数据集计算：

`effective_start = max(global_dataset_start, first_available_time)`

其中：

- OHLCV 的全局起点仍分别是 `macro_start` 或 `micro_start`。
- Funding 的全局起点仍是 `macro_start`。
- Metrics/OI 的全局起点仍是 `micro_start`。
- 月度对象只在其覆盖期间与 `effective_start` 相交时生成；日度对象只在其自然日不早于 `effective_start` 时生成。

因此，上市前的 URL 不会再进入采集计划；BTC、ETH、BNB 及其他较早可用资产的历史不会被全局缩短。

### 审计与错误处理

采集 artifact 必须包括资产起点表的内容哈希，以及按资产列出的 `PRE_LISTING_EXCLUDED` 对象数或范围。该记录表示“没有生成请求”，不是下载成功。

对于计划内对象，以下情况仍为阻断：

- HTTP 404 或其他不可获取响应；
- 校验和不匹配；
- 不完整原始对象；
- canonical schema、时间可见性或覆盖率失败；
- 每日热门池少于 8 个符合条件的资产。

不把计划内的 404 自动豁免为上市前缺失。

### 数据复用和运行方式

既有原始文件及其 manifest 会由现有校验复用逻辑跳过。裁剪后的计划仅包含仍需验证或下载的对象；不会清理 `var/`。

切片验收时运行同一入口：

```powershell
$sha = git rev-parse HEAD
uv run bian-quant prepare-dual-horizon \
  --config configs/experiments/popular_universe_100u.yaml \
  --code-sha $sha \
  --download
```

## 验收标准

1. 真实运行的 acquisition 与 quality artifact 均为 `passed`。
2. artifact 记录资产历史可用起点及 `PRE_LISTING_EXCLUDED` 审计信息。
3. 四个 snapshot：`macro-1d`、`macro-4h`、`micro-1h`、`micro-4h` 全部存在，且 lineage 一致。
4. 每日热门池 artifact 全部生成；每一天均有 8–12 个成员，否则以稳定、可解释的错误阻断。
5. 上市前月份不在 source plan 中；上市后人为模拟的 404 仍使运行阻断。
6. 已存在且校验通过的 raw 对象可复用，不产生覆盖写入。

## 验证计划

- 单元测试：资产级起点裁剪、月度边界、日度边界、计划 hash 稳定性。
- 单元测试：起点表缺失或证据无效时阻断。
- 集成测试：有效 raw artifact 重跑被跳过；计划内 404 仍 `blocked`。
- 目标测试与静态检查通过后，执行一次真实的 `prepare-dual-horizon --download`，读取全部 artifact 后才宣布切片 1 完成。

## 非目标

- 不改变因子定义、Candidate/Approved 门禁或 holdout 协议。
- 不运行 100U 回测或纸面交易。
- 不将热门池缩减为 BTC、ETH、BNB；三者的交易优先级属于后续切片。
