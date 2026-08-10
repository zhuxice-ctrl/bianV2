# 热门币研究终端页面设计

## 目标

在保留现有价格／回测首页的前提下，新增一个独立本地网页页面，用于浏览热门币研究管线的真实运行结果、数据质量和热门池状态。

页面只展示已经落盘的 artifact、catalog 和 snapshot 元数据；它不修改策略、不运行采集、不提交订单，也不接入 API Key、私有 endpoint 或真实资金。

## 页面与导航

- 新页面地址为 `/research`。
- 新增 `dashboard/research.html`，沿用现有 `dashboard/index.html` 的黑绿终端风格：数字雨、CRT 扫描线、命令栏、状态灯、KPI 卡片与紧凑数据表。
- 原首页保持原有价格／回测内容和地址 `/` 不变。
- 两个页面在顶部命令栏互相跳转，研究页提供返回交易终端首页的链接。

## 数据 API

新增只读 API：`GET /api/research/latest`。

它定位 `var/artifacts/dual-horizon-popular-v1/` 下最新一次包含 `data-acquisition.json` 与 `data-quality.json` 的运行目录，并返回一个面向页面的 JSON 视图。API 只使用最新运行目录，不扫描网页、不访问网络。

返回内容包括：

- 运行 ID、更新时间、总状态、计划对象数；
- availability manifest SHA-256、上市前排除对象数；
- 阻断对象及其稳定错误码、临时/永久属性；
- coverage 报告按资产和数据集汇总后的状态；
- 已发布 snapshot 的 ID、名称与时间边界；
- 每日热门池 artifact 的日期、成员数、成员、排除原因；
- artifact 目录的相对路径。

若没有 artifact，API 返回 HTTP 200 和明确的 `empty` 状态；若 artifact JSON 损坏，则返回 HTTP 500 与 `RESEARCH_ARTIFACT_INVALID`。页面不能把无数据或阻断状态渲染为成功。

## 研究终端布局

### 顶部状态区

- 状态灯：`PASSED` 为绿色、`BLOCKED` 为红色、外部临时阻断为黄色、无运行记录为灰色。
- 四张 KPI：最新运行 ID、计划对象数、上市前排除数、热门池最近成员数。
- 紧凑提示行：数据截止时间、manifest SHA 前缀和 artifact 路径。

### 热门池与覆盖区

- 最近一个有效交易日的热门币成员表：排名、币种、成交额/OI 分数（若 artifact 提供）、状态。
- 覆盖状态表：资产、OHLCV、Funding、OI 三列，按通过、排除、阻断标色。
- 排除／阻断表：时间段、资产、数据集、错误码与是否临时；默认只显示最近 20 条，可展开查看全部。

### 数据血缘区

- 四个 snapshot 卡片：名称、ID、时间范围、状态。
- 最近运行记录卡片：run ID、状态、生成时间、artifact 目录。
- 当热门池尚未发布时，显示“等待 Slice 1 数据门禁通过”，并保留阻断详情。

## 失败与空状态

- 当前 Slice 1 被阻断时，页面必须优先展示阻断原因，而不是空白图表。
- 没有 artifact 时，显示如何运行 `prepare-dual-horizon` 的只读提示；页面不提供执行按钮。
- API 请求失败时，显示可重试提示与错误码，不覆盖最后一次成功渲染的数据。

## 验收标准

1. `dashboard/server.py` 启动后，`/` 继续返回原首页，`/research` 返回新研究终端页面。
2. `/api/research/latest` 对现有 blocked artifact 返回真实状态、30 个阻断期、manifest SHA 与 207 个上市前排除记录。
3. 缺少 artifact 时 API 和页面显示 `empty`，不返回 404 或假阳性成功状态。
4. 页面不包含下单、杠杆、API Key、私有 endpoint 或运行采集的控制按钮。
5. API 解析与页面渲染具有自动化测试；现有 dashboard API 不回归。

## 非目标

- 不在本任务中解决 Slice 1 的数据覆盖阻断。
- 不实现因子研究、100U 回测、纸面交易或实盘入口。
- 不重构现有首页视觉系统；新页面只复用其风格和导航。
