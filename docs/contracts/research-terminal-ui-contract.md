# Popular Universe Research Terminal — UI Contract v1

交付对象：Aily 前端视觉 Mock。  
页面地址：`/research`。  
数据接口：`GET /api/research/latest`。  
限制：该页面是只读研究浏览器，不提供任何下单、运行采集、杠杆、API Key、私有接口或真实资金控制。

## 1. 视觉继承协议

必须以 `dashboard/index.html` 的现有视觉系统为基准，不使用白底 SaaS 后台风格。

- 背景：近黑绿 `#030704`；面板 `#071009`；内嵌区域 `#040b05`。
- 主色：荧光绿 `#00ff41`；信息青 `#29d8ff`；警告黄 `#ffb000`；阻断红 `#ff3b4e`。
- 字体：JetBrains Mono / Cascadia Code 等等宽字体。
- 保留数字雨、CRT 扫描线、顶部命令栏、固定底部状态栏、1px 绿色边框、终端式标签。
- 数据密集但不要拥挤：桌面四列 KPI；窄屏自动折为两列或一列；表格允许横向滚动。

## 2. 页面信息架构

```text
顶部命令栏
  [PRICE_ACTION://TERMINAL] [HOME] [RESEARCH active] [SYSTEM STATUS]

研究状态区
  状态灯 + 当前状态文字
  运行 ID / 计划对象数 / 上市前排除数 / 最近热门池成员数
  数据截止时间 / manifest SHA 前缀 / artifact 路径

热门池区
  最近有效日成员表
  历史成员数迷你趋势或日期列表

数据质量区
  资产覆盖状态矩阵：OHLCV / Funding / OI
  阻断与排除表：默认最近 20 条，可展开

数据血缘区
  四张 snapshot 卡片
  最近运行记录卡片

底部状态栏
  API 状态 / 数据更新时间 / “READ-ONLY · NO LIVE TRADING”
```

## 3. 唯一数据接口

### `GET /api/research/latest`

成功时始终返回 HTTP 200。页面根据 `state` 决定渲染，不依赖 HTTP 状态猜测成功或失败。

```ts
type ResearchTerminalResponse = {
  schema_version: "research-terminal-v1";
  state: "empty" | "blocked" | "passed";
  generated_at: string; // ISO-8601 UTC
  run: {
    id: string | null;
    status: "empty" | "blocked" | "passed";
    as_of: string | null; // ISO-8601 UTC
    planned_objects: number;
    availability_manifest_sha256: string | null;
    pre_listing_exclusion_count: number;
    popular_universe_start: string | null;
    popular_universe_warmup_start: string | null;
    popular_universe_warmup_end: string | null;
    artifact_path: string | null;
  };
  kpis: {
    popular_member_count: number | null;
    published_snapshot_count: number;
    blocked_period_count: number;
    temporary_blocker_count: number;
  };
  popular_universe: {
    latest_date: string | null; // YYYY-MM-DD
    latest_members: PopularMember[];
    daily_counts: Array<{ date: string; member_count: number }>;
  };
  coverage: CoverageRow[];
  blockers: Blocker[];
  pre_listing_exclusions: Exclusion[];
  partial_availability_exclusions: PartialAvailabilityExclusion[];
  partial_availability_impact: PartialAvailabilityImpact;
  market_cycle: MarketCycle;
  allocation: Allocation;
  backtest_comparison: BacktestComparison;
  snapshots: Snapshot[];
};

type PopularMember = {
  rank: number;
  asset: string;
  composite_score: number | null;
  quote_volume_rank: number | null;
  open_interest_rank: number | null;
};

type CoverageRow = {
  asset: string;
  ohlcv: "passed" | "excluded" | "blocked" | "unavailable";
  funding: "passed" | "excluded" | "blocked" | "unavailable";
  metrics_oi: "passed" | "excluded" | "blocked" | "unavailable";
};

type Blocker = {
  identity_key: string;
  asset: string | null;
  dataset: "ohlcv" | "funding" | "metrics_oi" | null;
  period: string | null;
  error_code: string;
  message: string;
  temporary: boolean;
};

type Exclusion = {
  identity_key: string;
  asset: string;
  dataset: "ohlcv" | "funding" | "metrics_oi";
  granularity: "monthly" | "daily";
  reason: "PRE_LISTING_EXCLUDED";
};

type PartialAvailabilityExclusion = {
  identity_key: string;
  asset: string;
  dataset: "ohlcv" | "funding" | "metrics_oi";
  granularity: "monthly" | "daily";
  period: string;
  reason: "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE";
  error_code: string;
  temporary: boolean;
};

type PartialAvailabilityImpact = {
  affected_assets: string[];
  affected_periods: number;
  affected_selection_days: number;
};

type MarketCycle = {
  label: "bull" | "neutral" | "risk_off" | "insufficient_evidence";
  confidence: number; // 0..1
  probabilities: { bull: number; neutral: number; risk_off: number };
  decision_time: string | null;
  sample_count: number;
  evidence_sha256: string | null;
  status: "ok" | "missing" | "error" | "insufficient_evidence";
};

type Allocation = {
  total_cap_usdt: number;
  per_asset_caps_usdt: { BTCUSDT: number; ETHUSDT: number; BNBUSDT: number };
  selected_assets: Array<"BTCUSDT" | "ETHUSDT" | "BNBUSDT">;
  reason: string;
};

type BacktestMetrics = {
  final_equity: number;
  total_return: number;
  annualized_volatility: number;
  max_drawdown: number;
  sharpe_like: number;
  trade_count: number;
};

type BacktestComparison = {
  status: "ok" | "missing" | "missing_returns" | "error";
  baseline: BacktestMetrics;
  confidence_weighted: BacktestMetrics;
  artifact_sha256: string | null;
};

type Snapshot = {
  name: "macro-1d" | "macro-4h" | "micro-1h" | "micro-4h";
  id: string;
  min_event_time: string;
  max_event_time: string;
  status: "published";
};
```

## 4. 三种固定 Mock 状态

### A. `blocked`（优先制作）

这是当前真实状态。必须以红色主状态灯显示 `PIPELINE BLOCKED`，同时使用黄色标签标识临时外部问题。

```json
{
  "schema_version": "research-terminal-v1",
  "state": "blocked",
  "generated_at": "2026-08-11T00:00:00Z",
  "run": {
    "id": "eec9516c-9d3a-427b-a377-52e689ba1bef",
    "status": "blocked",
    "as_of": "2026-07-26T19:59:59.999Z",
    "planned_objects": 16417,
    "availability_manifest_sha256": "8298300bfdf0d2d67d438abcc4bf49b97951856cdbd88d011688e8249296250e",
    "pre_listing_exclusion_count": 207,
    "artifact_path": "var/artifacts/dual-horizon-popular-v1/eec9516c-9d3a-427b-a377-52e689ba1bef"
  },
  "kpis": {
    "popular_member_count": null,
    "published_snapshot_count": 0,
    "blocked_period_count": 30,
    "temporary_blocker_count": 1
  },
  "popular_universe": { "latest_date": null, "latest_members": [], "daily_counts": [] },
  "coverage": [],
  "blockers": [
    {
      "identity_key": "funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00",
      "asset": "TONUSDT",
      "dataset": "funding",
      "period": "2026-07",
      "error_code": "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE",
      "message": "Official monthly funding archive is not available yet.",
      "temporary": true
    }
  ],
  "pre_listing_exclusions": [],
  "snapshots": []
}
```

页面文案：`研究管线被数据质量门禁阻断；未启动因子研究、回测或纸面交易。`

### B. `passed`

- 绿色状态灯：`RESEARCH DATA READY`。
- `published_snapshot_count` 必须为 4。
- `latest_members` 显示 8–12 个资产，按 `rank` 升序。
- 四张 snapshot 卡片全部显示 `PUBLISHED`。
- 不显示阻断警报，但可保留上市前排除计数作为审计信息。

### B2. `passed`（含局部排除警告）

当 Funding 尾部两个月内有临时缺档、但热门池仍有足够资产时，管线以 `passed` 状态发布数据，同时在数据就绪结论下方追加琥珀色局部排除警告。

- 绿色状态灯：`RESEARCH DATA READY`（不变）。
- 琥珀色警告区域紧跟运行信息之后、热门池之前。
- 警告标题：`已使用可用数据；部分资产暂时排除`。
- 影响摘要：`影响：TONUSDT · 2 个归档周期 · 31 个选币日`。
- 表格列：币种 / 数据类型 / 周期 / 原因 / 错误码。
- 折叠的技术详情列出原始 identity_key。
- `partial_availability_exclusions` 非空，`partial_availability_impact.affected_periods > 0`。
- `blockers` 为空，`blocked_period_count` 为 0。

### C. `empty`

- 灰色状态灯：`NO RESEARCH RUN`。
- 所有数字使用 `—`，不是 `0`。
- 主提示：`尚无热门币研究产物。请在本地完成 Slice 1 数据准备。`
- 没有“开始运行”按钮；仅提供只读命令提示文本。

## 5. 状态和交互规则

- 页面初次加载请求一次 API；提供小型“刷新”图标，仅重新请求 API，不触发任何管线。
- `blocked` 时，阻断表在热门池区之前，不能用空图表遮掩问题。
- `temporary: true` 使用黄色；其他 blocker 使用红色。
- `PRE_LISTING_EXCLUDED` 是正常审计项，使用青色或暗绿色，绝不使用红色“错误”样式。
- 表格默认最多显示 20 行，点击 `SHOW ALL` 展开；不需要分页。
- `partial_availability_exclusions` 非空时，在 `passed` 状态下以琥珀色警告区域渲染，紧跟运行信息之后、热门池之前；在 `blocked` 状态下，阻断表在前、局部排除警告在后。
- 局部排除是临时上游缺档，使用琥珀色（`--amber`），与红色硬阻断严格区分。
- 不需要登录、设置页、交易开关、策略参数编辑或任何写操作。

## 6. Aily 交付检查

- 提供桌面 1440px 与移动 390px 两个 mock。
- 使用本契约中的 `blocked` JSON 完成主视觉；同时展示 `passed` 和 `empty` 的状态差异。
- 复用原页面的视觉 token，而非重新选择配色、圆角或字体。
- 所有数字使用等宽数字；长 run ID 和 SHA 截断显示，悬停或复制时可获得完整值。
- 页面必须清楚写明：`READ-ONLY · RESEARCH ONLY · NO LIVE TRADING`。

## 7. 单币策略评估扩展（§7）

`ResearchTerminalResponse` 新增可选列表字段 `single_asset_strategy_evaluations`，默认空列表。旧消费者可安全忽略此字段。

```ts
type ResearchTerminalResponse = {
  // ... 所有 v1 字段不变 ...
  single_asset_strategy_evaluations: SingleAssetStrategyEvaluation[];
};

type SingleAssetStrategyEvaluation = {
  asset: string;                    // 首期固定 "ETHUSDT"
  strategy_id: string;              // "legacy.pa_confluence"
  strategy_version: string;         // "baseline-0"
  status: "ok" | "missing" | "error";
  sample_start: string | null;
  sample_end: string | null;
  generated_at: string | null;
  runtime_ms: number | null;
  input_artifact_sha256: string | null;
  result_artifact_sha256: string | null;
  artifact_path: string | null;
  current_signal: "long" | "short" | "flat" | "unavailable";
  current_signal_time: string | null;
  market_cycle: {
    label: string;
    confidence: number;
    multiplier: number;
    evidence_sha256: string | null;
  } | null;
  recommendation: {
    participate: boolean;
    max_invest_usdt: number;
    reason: string;
  } | null;
  baseline: StrategyMetrics | null;
  confidence_weighted: StrategyMetrics | null;
  error_summary: string | null;
};

type StrategyMetrics = {
  final_equity: number;
  total_return: number;
  max_drawdown: number;
  win_rate: number | null;          // null when no trades
  trade_count: number;
  fee_paid_net_profit: number;
  fees_paid: number;
};
```

### 渲染规则

- 页面在快照区域之后新增「ETH 单币策略对比」面板。
- 首行显示「当前是否建议参与」及原因；参与时显示建议最大投入。
- 并列展示原始策略与置信度加权策略的指标对比表。
- `missing`/`error` 只显示原因，不显示建议金额或指标。
- 所有 API 文本经过 `escapeHtml`。
- 不新增运行、下载、下单或参数编辑控件。

