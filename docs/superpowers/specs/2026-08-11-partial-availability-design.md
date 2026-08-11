# Partial Availability for Popular Research

## Purpose

Allow a popular-universe run to use verified data that is available while isolating a known, temporary upstream archive gap to the affected asset and period. The run must remain fail-closed for unknown failures and must never synthesize missing market data.

## Scope

- Change acquisition quality handling for registered temporary archive-unavailable errors.
- Preserve all successful raw and canonical objects exactly as they are today.
- Exclude only the affected asset from the affected daily universe windows when a required dataset is unavailable.
- Continue only when every daily popular universe still has at least 8 eligible assets.
- Persist a separate partial-availability audit list in acquisition and quality artifacts.
- Expose the audit list to the research terminal without changing the meaning of `blocked_periods`.

## Failure Classes

### Hard blockers

The following remain run-blocking and are written to `blocked_periods`:

- Any parse or validation failure.
- Any failed download that is not an explicitly registered temporary archive error.
- Any plan identity that is post-availability-boundary but returns an unexpected 404.
- Any daily popular-universe result with fewer than 8 eligible assets.
- Any required dataset with no usable data for the run.

### Partial temporary exclusions

Only the Funding tail is eligible for the partial path in this slice. The tail window is the cutoff month plus the immediately preceding calendar month. This two-month window is explicit policy for the current `monthly_archive_after_period_close` strategy; older Funding periods are historical data and remain hard-blocked when incomplete.

The partial path covers both forms of tail incompleteness:

- A download failure classified as `FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE`.
- A verified tail archive whose Funding coverage report is below its threshold, such as the current 75% TON June archive.

A failed object is eligible only when its acquisition evidence marks it `temporary=true`, its dataset is Funding, its period is inside the tail window, and it is not pre-listing. A coverage report is eligible only when the same dataset, tail-window, and non-pre-listing conditions hold.

The source of `temporary=true` is the error-code registry in `src/bian_quant/data/acquisition_failures.py`, specifically `classify_acquisition_failure()` and its focused tests. The registry contains one partial-eligible code in this slice. Adding another partial-eligible code requires a new design review entry, an explicit reason it is temporary, and a hard-block regression test; the generic artifact shape is not permission to expand the bypass.

Each partial exclusion is recorded as:

```json
{
  "identity_key": "funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00",
  "asset": "TONUSDT",
  "dataset": "funding",
  "granularity": "monthly",
  "period": "2026-07",
  "reason": "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE",
  "error_code": "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE",
  "temporary": true
}
```

It is not converted to `PRE_LISTING_EXCLUDED`, and it is not silently dropped.

## Processing Rules

1. Download and verify every planned object as today.
2. Classify known temporary Funding-tail failures into `partial_availability_exclusions`; do not add them to `blocked_periods`.
3. Keep successful objects in the canonical frames. Do not impute, forward-fill, or substitute the missing asset's Funding rows.
4. Build the daily popular universe using the existing 30-day completeness checks. An asset with a missing required dataset is naturally excluded for that daily selection window.
5. If every daily artifact contains 8–12 members, publish snapshots and mark the run `passed` with a non-empty partial audit list.
6. If any daily artifact has fewer than 8 members, keep the run `blocked` and include the exact daily shortage in the hard-block evidence.
7. Preserve the original upstream failure or coverage finding in the per-object results and the partial audit list; a later rerun can reuse successful objects and retry only missing objects.
8. Partial exclusions are run-scoped. Each run recomputes them from its own acquisition and quality evidence; a recovered archive removes the exclusion on the next run and does not inherit the previous run's warning.

## Artifact Contract

Both `data-acquisition.json` and `data-quality.json` gain:

```json
"partial_availability_exclusions": [
  {
    "identity_key": "...",
    "asset": "TONUSDT",
    "dataset": "funding",
    "granularity": "monthly",
    "period": "2026-07",
    "reason": "TEMPORARY_UPSTREAM_ARCHIVE_UNAVAILABLE",
    "error_code": "FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE",
    "temporary": true
  }
]
```

Both artifacts also include a deterministic impact summary:

```json
"partial_availability_impact": {
  "affected_assets": ["TONUSDT"],
  "affected_periods": 2,
  "affected_selection_days": 31
}
```

`affected_selection_days` counts daily popular-universe artifacts in which at least one affected asset was excluded. This makes a partial-data pass visibly different from a complete-data pass and lets the terminal explain how much of the selection history was shortened.

The source-plan hash, availability manifest hash, successful object manifests, and `blocked_periods` remain unchanged in meaning. Snapshot configuration includes a canonical hash of the partial exclusion list so the result is reproducible and cannot be confused with a complete-data run.

The research terminal response gains a `partial_availability_exclusions` list and `partial_availability_impact` with the same fields. A passed run with entries displays a warning such as `已使用可用数据；部分资产暂时排除 N 天` and the affected rows. A blocked run continues to put hard blockers first and shows partial entries as warnings, never as successes.

## Acceptance Criteria

1. A known temporary Funding-tail 404 is absent from `blocked_periods` and present in `partial_availability_exclusions`.
2. Unknown 404s, parse failures, and quality failures still block the run.
3. No rows are synthesized for the excluded asset and period.
4. Successful assets still produce canonical partitions and are eligible for snapshots.
5. A daily universe with 8 or more valid assets publishes; a daily universe with 7 or fewer blocks with an explicit shortage.
6. The current `macro_start=2024-07` popular run records the TON June coverage gap and July tail gap as partial exclusions and either passes or reports a genuine `<8` shortage; it never reports a false complete-data pass. “2024-07 run” refers to this macro start boundary, not the missing archive period.
7. A later run with recovered archives has an empty partial list and does not inherit the previous run's exclusions.
8. Artifact hashes and partial-exclusion lineage are deterministic across a resumable rerun.
9. Existing strict acquisition and plan-cropping tests continue to pass, with focused tests added for partial, coverage-shortage, and hard-block paths.

## Non-Goals

- No REST Funding fallback or alternate data source.
- No imputation, forward-fill, synthetic rows, or manual data patching.
- No changes to the 16-asset seed universe, ranking formula, 30-day window, 8–12 member bounds, factor definitions, backtest, or paper-trading logic.
