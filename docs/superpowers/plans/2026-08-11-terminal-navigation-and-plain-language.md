# Terminal Navigation and Plain-Language Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the legacy dashboard and research terminal mutually navigable and easier to understand without changing research data or backend contracts.

**Architecture:** Keep the two existing standalone HTML pages and their shared terminal visual language. Add a normal link from the legacy page, introduce one small client-side tooltip primitive per page, and change only the research page's presentation strings and technical-detail grouping. Browser verification will exercise both routes at desktop and mobile widths.

**Tech Stack:** Static HTML/CSS/vanilla JavaScript, FastAPI static routes, Playwright-compatible browser checks.

---

### Task 1: Add Mutual Navigation

**Files:**
- Modify: `dashboard/index.html:251-258` navigation markup
- Modify: `dashboard/index.html:384-396` keyboard-help markup
- Inspect only: `dashboard/index.html:947-950` keyboard map; do not modify it

- [ ] **Step 1: Add the research link beside the existing view buttons**

Insert this anchor after the LOG button. It must use the existing `nav-btn` class but must not use `data-view`, because research is a separate route rather than an in-page view:

```html
<a class="nav-btn nav-link" href="/research"><b>[6]</b>RESEARCH</a>
```

Add a small CSS rule near the existing `.nav-btn` rules so the anchor has the same appearance and focus behavior as the buttons:

```css
.nav-link{text-decoration:none;display:inline-block}
```

- [ ] **Step 2: Document the route in the help overlay**

Add this row before the existing help footer:

```html
<div class="row"><span>研究终端</span><kbd>6</kbd></div>
```

Do not add `6` to the in-page `map` object. The link is intentionally a route navigation and existing keys `1` through `5`, `S`, and `L` must remain unchanged.

- [ ] **Step 3: Verify the old page still initializes normally**

Run the existing dashboard server and load `/`. Confirm BTC is still selected, the five existing view buttons still switch views, and the new `[6] RESEARCH` link has `href="/research"`.

Expected: no JavaScript console errors; clicking the link changes the URL to `/research`.

### Task 2: Add Shared Tooltip Presentation

**Files:**
- Modify: `dashboard/index.html` tooltip CSS and metric-label markup
- Modify: `dashboard/research.html` tooltip CSS, helper markup, and render functions

- [ ] **Step 1: Add an accessible tooltip style and helper markup to each page**

Use a focusable button trigger, not a non-semantic span. The minimum helper shape is:

```html
<button class="term-help" type="button" aria-label="解释：胜率" aria-describedby="tip-win-rate">胜率<span class="help-mark">?</span></button>
<span class="tooltip" role="tooltip" id="tip-win-rate">已结束的交易中，盈利交易所占的比例。</span>
```

Add CSS that keeps the default layout unchanged, shows the tooltip on `:hover` or `:focus-visible`, and lets the tooltip wrap on narrow screens. Use existing green/black variables rather than introducing a new visual theme. Add a document-level click handler only where needed to remove an `.is-open` class from touch triggers when the user taps elsewhere.

- [ ] **Step 2: Apply the tooltip vocabulary to legacy dashboard metrics**

Replace only the visible labels in the generated metric sections and static strategy/system cards with tooltip triggers for: `胜率`, `盈亏比`, `最大回撤`, `样本外验证`, and `扰动测试`. Keep each numeric value and its existing element id unchanged so current rendering and sorting continue to work.

- [ ] **Step 3: Apply the vocabulary to research labels**

Add tooltip triggers to the research KPI labels and section headings for: `计划对象`, `上市前排除`, `阻断周期`, `临时阻断`, `数据覆盖`, and `已发布快照`. Use stable ids generated from the term name so `aria-describedby` remains valid after `app.innerHTML` rerenders.

- [ ] **Step 4: Verify tooltip interaction without data changes**

In the browser, focus a legacy metric label with Tab, hover the same label with the pointer, and tap a research KPI help mark at a mobile viewport. Expected: the same explanation is visible in all supported interaction modes, and clicking outside closes a touch-open tooltip.

### Task 3: Make Research State and Technical Details Plain-Language First

**Files:**
- Modify: `dashboard/research.html:294-303` state text and messages
- Modify: `dashboard/research.html:331-360` KPI and run-information rendering
- Modify: `dashboard/research.html:362-385`, `440-498`, and `501-515` table headings/labels

- [ ] **Step 1: Replace primary state copy with actionable conclusions**

Set the static state message map to:

```js
const STATE_MSG={
  passed:'数据已就绪：可以进入因子分析和回测。',
  empty:'尚未准备热门币研究数据。'
};
```

Keep the English state labels as small secondary labels only. Because the blocked count is data-dependent, render the blocked sentence directly inside `renderStateBar(data)`:

```js
const message=s==='blocked'
  ? `暂不能进入回测：发现 ${fmtNumRaw(data.kpis.blocked_period_count)} 个数据问题。`
  : STATE_MSG[s]||'';
```

- [ ] **Step 2: Add explanations to KPI and section labels**

Keep the current values and API mapping, but render labels using the tooltip helper. Add visible short context below the state bar: `红色表示数据门禁尚未通过；黄色表示上游数据可能稍后恢复。` only for blocked state.

- [ ] **Step 3: Collapse technical evidence by default**

In `renderRunInfo(data)`, keep the human-readable rows `状态`, `数据截止`, `计划对象`, `上市前排除`, and `生成时间` visible. Put `RUN ID`, `MANIFEST SHA`, and `ARTIFACT` inside a native `<details class="technical-details">` block with summary `技术详情`. Preserve full values and current hover titles inside the expanded block.

In blocker and exclusion tables, keep asset, dataset, period, type, and message visible. Move `IDENTITY KEY` columns into the same details treatment or label them `技术标识` and hide them at the default mobile presentation; do not change the API payload.

- [ ] **Step 4: Translate section labels without removing technical identifiers**

Use plain-language primary headings with compact secondary tags:

```text
热门池 · POPULAR UNIVERSE
数据覆盖 · COVERAGE MATRIX
上市前排除 · PRE-LISTING EXCLUSIONS
数据快照 · SNAPSHOTS
阻断问题 · BLOCKERS
```

Update table headers to `数据类型`, `错误说明`, and `技术标识` where the current all-caps English labels are not needed for scanning. Keep dataset values in the payload-derived rows unchanged.

- [ ] **Step 5: Verify blocked, passed, and empty rendering paths**

Use the existing API response for blocked, plus fixture-style JSON overrides in the browser console for passed and empty. Expected: each state has an understandable primary sentence; the blocked count is the actual count; technical fields are hidden until `技术详情` is expanded.

### Task 4: Browser Acceptance and Regression Check

**Files:**
- Modify: no production files unless a failing acceptance check identifies a scoped issue
- Test evidence: browser console and route checks against `dashboard/server.py`

- [ ] **Step 1: Start the configured dashboard server**

Use the existing server on port `8787`; if it is already running, reuse it. Open both routes:

```text
http://localhost:8787/
http://localhost:8787/research
```

- [ ] **Step 2: Check route symmetry**

From `/`, click `[6] RESEARCH` and assert the pathname becomes `/research`. From `/research`, click `HOME` and assert the pathname becomes `/`.

- [ ] **Step 3: Check responsive tooltip behavior**

At a desktop viewport, hover and keyboard-focus at least one legacy metric and one research KPI. At a mobile viewport, tap each page's help trigger. Assert tooltip text is visible and no table or state text overlaps its neighboring content.

- [ ] **Step 4: Check console and API regressions**

Assert zero browser console errors, `GET /api/research/latest` remains HTTP 200, and the response still has `schema_version: "research-terminal-v1"`. Confirm refresh only requests the API and does not start a pipeline.

- [ ] **Step 5: Commit the implementation as one focused change**

```bash
git add dashboard/index.html dashboard/research.html
git commit -m "feat(ui): connect dashboards and explain research metrics"
```
