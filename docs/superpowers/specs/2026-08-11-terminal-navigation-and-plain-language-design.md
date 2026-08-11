# Terminal Navigation and Plain-Language Design

## Purpose

Make the existing strategy dashboard and the popular-universe research terminal easy to move between and understand without changing their data, research rules, or terminal visual style.

## Scope

- Add a `[6] RESEARCH` navigation item to `dashboard/index.html` that opens `/research`.
- Keep the existing `HOME` navigation item in `dashboard/research.html` so both pages are reachable from each other.
- Keep the BTC, ETH, BNB, system, log, charts, data values, and keyboard behavior of the existing dashboard unchanged.
- Use the same interaction model on both pages: plain-language conclusions first; compact explanations on demand; technical evidence only when expanded.

## Information Layering

### First layer: immediate conclusion

Research state text must answer whether the next research step can start.

- Blocked: `暂不能进入回测：发现 N 个数据问题`.
- Passed: `数据已就绪：可以进入因子分析和回测`.
- Empty: `尚未准备热门币研究数据`.

The existing colored status light remains, with red for blocked, green for passed, and muted green for empty. The original English state labels may appear only as small secondary labels.

### Second layer: concise explanations

Terms that are useful but not self-explanatory receive a quiet tooltip. On desktop it appears after hovering over the term; on touch devices it opens after tapping a small question-mark control beside the term. Tooltips must not block content and must be dismissible by moving away or tapping elsewhere.

The shared tooltip vocabulary includes:

| Term | Explanation |
| --- | --- |
| 胜率 | 已结束的交易中，盈利交易所占的比例。 |
| 盈亏比 | 平均每笔盈利与平均每笔亏损的比值。高于 1 表示平均盈利大于平均亏损。 |
| 最大回撤 | 账户从历史最高点回落的最大幅度，用来衡量可能承受的亏损。 |
| 样本外验证 | 用没有参与参数选择的数据检验策略，避免只适合过去的数据。 |
| 扰动测试 | 给历史数据加入小变化，检查策略是否过于脆弱。 |
| 计划对象 | 本次准备并检查的数据文件数量。 |
| 上市前排除 | 合约尚未上市时没有数据文件，属于正常排除，不是错误。 |
| 阻断周期 | 发现数据缺失或校验失败、因而不能继续研究的时间段。 |
| 临时阻断 | 上游数据暂未发布或暂时不可访问，稍后重试可能恢复。 |
| 数据覆盖 | 每个币的价格、资金费率和持仓量数据是否齐全。 |
| 已发布快照 | 已校验并固定下来、可供研究使用的数据版本。 |

### Third layer: technical detail

The research page hides manifest SHA, artifact path, and raw identity keys by default in a collapsed `技术详情` section. The section exposes the original values unchanged when expanded. Errors must still show asset, data type, period, and plain-language message in the normal blocker table.

## Page Changes

### Existing dashboard (`/`)

- Add a sixth top navigation item labeled `[6] RESEARCH` that navigates to `/research`.
- Add the matching keyboard shortcut entry to the help panel, but do not intercept existing `1` through `5`, `S`, or `L` behavior.
- Convert only existing metric labels to tooltip triggers. Values, charts, recommendations, and layout stay unchanged.

### Research terminal (`/research`)

- Keep the terminal visual system, read-only restriction, API endpoint, state ordering, and data tables.
- Replace technical primary state wording with the first-layer conclusions above.
- Add tooltips to KPI labels and section labels listed in the shared vocabulary.
- Place manifest SHA and artifact path in `技术详情`.
- Keep blocker reason and dataset names visible, adding a plain-language explanation where needed.

## Accessibility and Responsiveness

- Tooltip triggers are keyboard-focusable and use `aria-describedby` or equivalent accessible labeling.
- Tooltip text is available through focus as well as pointer hover.
- Touch interaction uses a button-sized question-mark control with an accessible label.
- On narrow screens, technical details and wide tables remain horizontally scrollable or collapsible without covering data.

## Acceptance Criteria

1. From `/`, a visible `[6] RESEARCH` action opens `/research`; `HOME` on `/research` opens `/`.
2. Existing dashboard navigation for BTC, ETH, BNB, system, log, and their shortcuts remains unchanged.
3. Both pages show the agreed explanation when hovering or focusing each listed term; touch devices can reveal the same text.
4. `/research` blocked state reads `暂不能进入回测：发现 N 个数据问题`, where `N` is the actual blocked-period count.
5. SHA, artifact path, and identity keys are absent from the default reading path and accessible through `技术详情`.
6. `GET /api/research/latest` and its response schema remain unchanged.
7. Browser checks show no console errors and confirm navigation plus tooltip behavior on desktop and mobile widths.

## Non-Goals

- Do not alter the data acquisition pipeline, availability policy, backtest results, or research state calculation.
- Do not add live trading, controls that run pipelines, account actions, API key handling, or new backend endpoints.
- Do not redesign either page away from the existing terminal visual system.
