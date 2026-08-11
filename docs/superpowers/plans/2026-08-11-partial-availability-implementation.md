# Partial Availability for Popular Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish popular-universe research from verified available data when only the registered two-month Funding tail is incomplete, while retaining hard failure behavior and a complete audit trail.

**Architecture:** Keep `blocked_periods` exclusively for hard failures. The pipeline will convert only temporary Funding defects in the cutoff month or preceding month into run-scoped `partial_availability_exclusions`; existing 30-day selection removes the affected asset. A daily pool below eight assets remains a hard blocker. Artifacts, snapshot lineage, API response, and terminal UI carry the partial-data impact.

**Tech Stack:** Python 3.11, Pydantic v2, pandas, pytest, FastAPI, static HTML/CSS/vanilla JavaScript.

---

## File map

- `src/bian_quant/data/acquisition_failures.py`: tail-window error classifier.
- `src/bian_quant/data/dual_horizon.py`: partial audit, hard/partial separation, daily shortage gate, artifact lineage.
- `tests/unit/data/test_acquisition_failures.py`: temporary-window regression tests.
- `tests/integration/data/test_dual_horizon_pipeline.py`: partial pass and hard-shortage tests.
- `src/bian_quant/reporting/research_protocol.py`: immutable API models.
- `src/bian_quant/reporting/research_terminal.py`: artifact-to-API aggregation.
- `tests/unit/reporting/test_research_terminal.py`: API aggregation test.
- `docs/contracts/research-terminal-ui-contract.md`, `dashboard/research.html`: warning contract and UI.

### Task 1: Register the explicit two-month Funding tail

**Files:**
- Modify: `src/bian_quant/data/acquisition_failures.py:28-60`
- Modify: `tests/unit/data/test_acquisition_failures.py:10-50`

- [ ] **Step 1: Write failing classifier tests**

Add a test proving 404s for Funding monthly 2026-06 and 2026-07 are temporary when the acquisition cutoff is July 2026. Add a test proving 2026-05, daily Funding, OHLCV, and local integrity failures remain non-temporary.

~~~python
def test_current_and_previous_funding_month_404_are_temporary() -> None:
    config = DualHorizonAcquisition.from_yaml(CONFIG)
    sources = {
        item.source_period: item
        for item in build_source_plan(config)
        if item.dataset == SourceDataset.FUNDING and item.asset == "BTCUSDT"
    }
    for period in ("2026-06", "2026-07"):
        result = classify_acquisition_failure(sources[period], config, _http_404(sources[period].url))
        assert result.error_code == "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE"
        assert result.temporary is True
        assert result.attempt_count == 1
~~~

- [ ] **Step 2: Run the failing test**

Run:

~~~powershell
uv run pytest tests/unit/data/test_acquisition_failures.py -q
~~~

Expected: the June assertion fails because the current classifier accepts only the cutoff month.

- [ ] **Step 3: Implement the tail boundary**

Replace `is_cutoff_month_funding` with `is_funding_tail_period`. It must return true only for monthly Funding sources where `period_start` is between the first day of the preceding month and the first day of the cutoff month, inclusive.

~~~python
def is_funding_tail_period(source: SourceObject, config: DualHorizonAcquisition) -> bool:
    if source.dataset != SourceDataset.FUNDING or source.granularity != SourceGranularity.MONTHLY:
        return False
    cutoff = config.as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    previous = cutoff.replace(year=cutoff.year - 1, month=12) if cutoff.month == 1 else cutoff.replace(month=cutoff.month - 1)
    return previous <= source.period_start <= cutoff
~~~

Use this helper only in the HTTP 404 branch of `classify_acquisition_failure`.

- [ ] **Step 4: Verify and commit**

~~~powershell
uv run pytest tests/unit/data/test_acquisition_failures.py -q
git add src/bian_quant/data/acquisition_failures.py tests/unit/data/test_acquisition_failures.py
git commit -m "feat(data): classify two-month funding tail gaps"
~~~

Expected: all classifier tests pass; historical gaps remain hard failures.

### Task 2: Separate partial Funding defects from hard pipeline defects

**Files:**
- Modify: `src/bian_quant/data/dual_horizon.py:391-447, 585-890`
- Modify: `tests/integration/data/test_dual_horizon_pipeline.py:240-380`

- [ ] **Step 1: Add failing partial-path integration tests**

Create a `TailGapDownloader` which delegates to `FixtureDownloader(FIXTURES)` and raises `HTTPError(..., 404, ...)` only for monthly Funding sources inside the two-month tail. Use the miniature popular config with a 1-day trailing window and `min_selected=8`.

Assert:

~~~python
assert result.status == DualHorizonStatus.PASSED
assert result.blocked_periods == ()
assert result.snapshots
assert {row["reason"] for row in acquisition["partial_availability_exclusions"]} == {
    "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE"
}
assert acquisition["partial_availability_exclusions"] == quality["partial_availability_exclusions"]
assert acquisition["partial_availability_impact"]["affected_periods"] > 0
~~~

Add a second test with `min_selected=16`. It must be blocked with at least one `popular-universe|YYYY-MM-DD` key and no snapshots.

- [ ] **Step 2: Run the test and confirm strict behavior fails it**

~~~powershell
uv run pytest tests/integration/data/test_dual_horizon_pipeline.py -q
~~~

Expected: the partial test is currently blocked with empty snapshots and no partial fields.

- [ ] **Step 3: Add a single partial-audit representation**

Near the helpers in `dual_horizon.py`, add helpers that generate this exact JSON-safe object. Do not reuse `PRE_LISTING_EXCLUDED`.

~~~python
def _partial_exclusion(source: SourceObject, *, error_code: str) -> dict[str, object]:
    return {
        "identity_key": source.identity_key,
        "asset": source.asset,
        "dataset": source.dataset.value,
        "granularity": source.granularity.value,
        "period": source.source_period,
        "reason": "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE",
        "error_code": error_code,
        "temporary": True,
    }
~~~

Add `partial_exclusions: list[dict[str, object]] = []` next to `blocked_periods`.

- [ ] **Step 4: Change only registered tail acquisition failures**

In the acquisition outcome loop, retain every failed row in `acquisition_results`. If `failure.temporary` is true and `is_funding_tail_period(source, config)` is true, append `_partial_exclusion(source, error_code=failure.error_code)` and do not append that identity to `blocked_periods`. All other failures keep the existing hard-block behavior.

- [ ] **Step 5: Change only registered tail coverage defects**

After `report = _quality_report(...)`, a blocking report may be partial only when the source is monthly Funding in the same two-month tail. Append:

~~~python
_partial_exclusion(source, error_code="FUNDING_TAIL_COVERAGE_INCOMPLETE")
~~~

Retain the verified incomplete rows in `funding_frames`, preserve the coverage report, and do not append that identity to `blocked_periods`. Every other `report.blocking`, parsing failure, and evidence-cutoff exception remains hard-blocked.

Deduplicate exclusions by `identity_key`, sort them, and compute:

~~~python
partial_exclusion_sha256 = hashlib.sha256(
    json.dumps(partial_exclusions, sort_keys=True, separators=(",", ":")).encode()
).hexdigest()
~~~

Include this SHA in `snapshot_config_dict` as `partial_availability_exclusion_sha256`.

- [ ] **Step 6: Make the daily 8-asset floor a real hard gate**

Replace the silent `except RuntimeError: continue` in `_build_popular_universe_artifacts` with a return object:

~~~python
@dataclass(frozen=True)
class PopularUniverseBuildResult:
    artifacts: list[dict[str, object]]
    shortages: list[dict[str, str]]
~~~

For a `POPULAR_UNIVERSE_INSUFFICIENT:` exception, append:

~~~python
{"identity_key": f"popular-universe|{selection_time:%Y-%m-%d}", "message": str(exc)}
~~~

Continue collecting later dates. In `prepare_dual_horizon`, append all shortage identity keys to `blocked_periods`; do not build snapshots when any such hard blocker exists. Re-raise any unrelated RuntimeError instead of silently skipping it.

Include each daily artifact's existing exclusions in its internal result so the next step can count impact.

- [ ] **Step 7: Persist deterministic impact and empty defaults**

Compute:

~~~python
partial_assets = sorted({str(row["asset"]) for row in partial_exclusions})
affected_selection_days = sum(
    1 for artifact in popular_universe_artifacts
    if any(
        row["asset"] in partial_assets and row["reason"] == "FUNDING_DAYS_INSUFFICIENT"
        for row in artifact["exclusions"]
    )
)
partial_impact = {
    "affected_assets": partial_assets,
    "affected_periods": len(partial_exclusions),
    "affected_selection_days": affected_selection_days,
}
~~~

Write `partial_availability_exclusions`, `partial_availability_impact`, and `partial_availability_exclusion_sha256` to both acquisition and quality artifacts. The disk-block early-return artifacts must include `[]`, `{"affected_assets": [], "affected_periods": 0, "affected_selection_days": 0}`, and `null` for the same keys.

- [ ] **Step 8: Verify and commit**

~~~powershell
uv run pytest tests/integration/data/test_dual_horizon_pipeline.py tests/unit/data/test_acquisition_failures.py -q
git add src/bian_quant/data/dual_horizon.py tests/integration/data/test_dual_horizon_pipeline.py
git commit -m "feat(data): publish with partial funding tail availability"
~~~

Expected: partial gaps pass with enough assets, <8 shortages block, and all legacy hard-failure tests remain blocked.

### Task 3: Expose partial audit data through the read-only API

**Files:**
- Modify: `src/bian_quant/reporting/research_protocol.py:57-180`
- Modify: `src/bian_quant/reporting/research_terminal.py:60-205, 331-390`
- Create: `tests/unit/reporting/test_research_terminal.py`

- [ ] **Step 1: Write failing aggregation tests**

Create a temporary passed derivatives run plus acquisition and quality artifacts containing one partial exclusion and this impact:

~~~python
{
    "affected_assets": ["TONUSDT"],
    "affected_periods": 2,
    "affected_selection_days": 31,
}
~~~

Assert the response is passed, has no hard blockers, maps the exclusion, and exposes all three impact values. Add a no-partial artifact case and assert an empty list plus zero impact.

- [ ] **Step 2: Add immutable protocol fields**

In `research_protocol.py`, add `PartialExclusionReason`, `PartialAvailabilityExclusion`, and `PartialAvailabilityImpact`:

~~~python
class PartialExclusionReason(StrEnum):
    TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE = "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE"

class PartialAvailabilityImpact(BaseModel):
    model_config = ConfigDict(frozen=True)
    affected_assets: list[str]
    affected_periods: int
    affected_selection_days: int
~~~

`PartialAvailabilityExclusion` must contain `identity_key, asset, dataset, granularity, period, reason, error_code, temporary`. Append both partial fields to `ResearchTerminalResponse`.

- [ ] **Step 3: Map artifacts without creating blockers**

In `research_terminal.py`, add `_build_partial_exclusions(raw)` beside `_build_exclusions(raw)`; skip malformed input with the same `KeyError, ValueError, ValidationError` handling. Read partial fields from acquisition, create zero impact defaults when missing, and add them to normal and `_empty_response()` responses. Do not send these entries through `_build_blockers()`.

- [ ] **Step 4: Verify and commit**

~~~powershell
uv run pytest tests/unit/reporting/test_research_terminal.py -q
uv run mypy src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py
git add src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py tests/unit/reporting/test_research_terminal.py
git commit -m "feat(reporting): expose partial availability warnings"
~~~

### Task 4: Display the impact on the research page

**Files:**
- Modify: `docs/contracts/research-terminal-ui-contract.md`
- Modify: `dashboard/research.html:289-710`

- [ ] **Step 1: Extend the contract**

Document `partial_availability_exclusions` and `partial_availability_impact`. Define passed-with-warning: green data-ready conclusion stays visible, followed by an amber warning containing affected assets, archive periods, and affected selection days. It remains read-only research and is not complete-data certification.

- [ ] **Step 2: Implement a warning section**

Add `renderPartialAvailability(data)`. It returns empty HTML with no partial entries; otherwise it renders in amber:

~~~text
已使用可用数据；部分资产暂时排除
影响：TONUSDT · 2 个归档周期 · 31 个选币日
~~~

Render columns `币种`, `数据类型`, `周期`, `原因`, and `错误码`. Reuse `DATASET_LABEL()`; place raw identity keys in a collapsed `技术详情`.

In `renderAll(data)`, order a passed partial run as state, KPIs, run information, partial warning, popular universe, coverage, exclusions, snapshots. For a blocked run with both types, render hard blockers first, then the partial warning.

- [ ] **Step 3: Browser acceptance**

Use a fixture-style response with a passed state, one TON partial exclusion, and the 2-period/31-day impact. Check desktop and 390px widths. Then check the real API response.

~~~powershell
cd F:\bianV2\dashboard
python server.py
~~~

Expected: passed partial is green plus amber warning; blocked shows red hard blockers before amber partials; neither state creates a run, download, order, or console error.

- [ ] **Step 4: Commit the API documentation and UI**

~~~powershell
git add docs/contracts/research-terminal-ui-contract.md dashboard/research.html
git commit -m "feat(ui): show partial data availability impact"
~~~

### Task 5: Full gate and real Slice 1 acceptance

**Files:**
- Modify: no production files unless a focused gate fails
- Evidence: `var/artifacts/dual-horizon-popular-v1/<new-run-id>/`

- [ ] **Step 1: Run focused gates**

~~~powershell
uv run pytest tests/unit/data/test_acquisition_failures.py tests/integration/data/test_dual_horizon_pipeline.py tests/unit/reporting/test_research_terminal.py -q
uv run ruff check src/bian_quant/data/acquisition_failures.py src/bian_quant/data/dual_horizon.py src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py tests/unit/data/test_acquisition_failures.py tests/integration/data/test_dual_horizon_pipeline.py tests/unit/reporting/test_research_terminal.py
uv run mypy src/bian_quant/data/acquisition_failures.py src/bian_quant/data/dual_horizon.py src/bian_quant/reporting/research_protocol.py src/bian_quant/reporting/research_terminal.py
~~~

Expected: every command succeeds.

- [ ] **Step 2: Run real Slice 1**

~~~powershell
$sha = git rev-parse HEAD
uv run bian-quant prepare-dual-horizon --config configs/experiments/popular_universe_100u.yaml --code-sha $sha --download
~~~

Expected: verified raw objects are reused. TON June and July become partial exclusions while their archive is incomplete. The run passes only if every daily popular pool has 8–12 assets; otherwise it blocks with exact `popular-universe|YYYY-MM-DD` keys and zero snapshots.

- [ ] **Step 3: Inspect artifacts and push after review**

~~~powershell
$root = 'var/artifacts/dual-horizon-popular-v1'
$run = Get-ChildItem $root -Directory | Sort-Object LastWriteTimeUtc -Descending | Select-Object -First 1
$acq = Get-Content (Join-Path $run.FullName 'data-acquisition.json') -Raw | ConvertFrom-Json
$quality = Get-Content (Join-Path $run.FullName 'data-quality.json') -Raw | ConvertFrom-Json
$acq.status
$quality.status
$acq.blocked_periods
$acq.partial_availability_exclusions
$acq.partial_availability_impact
$acq.snapshot_ids
git push origin codex/research-platform-implementation
~~~

Expected: a passed partial run has empty `blocked_periods`, non-empty partial audit, impact, and four snapshots. A blocked run has explicit hard keys and zero snapshots. Report the run id, status, affected assets/periods/days, hard blockers, and snapshot ids. Do not begin factor research, 100U backtest, paper trading, or live trading.

## Plan self-review

- Tasks 1–2 cover the strict two-month boundary, partial coverage and 404 evidence, run-scoped audit, no synthetic rows, and the daily eight-asset hard gate.
- Task 3 keeps the read-only API schema aligned with artifact keys; Task 4 keeps the terminal understandable; Task 5 verifies real artifacts and stops before later research slices.
- The names `partial_availability_exclusions`, `partial_availability_impact`, and `partial_availability_exclusion_sha256` are used consistently in every task.

