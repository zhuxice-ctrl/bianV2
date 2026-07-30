# Funding Monthly-Tail Acquisition Design

**Status:** Approved conceptually in conversation on 2026-07-31; written-spec
review pending

**Phase:** Plan 03.5 amendment

**Parent design:**
`docs/superpowers/specs/2026-07-30-dual-horizon-derivatives-design.md`

## Purpose

The locked Plan 03.5 source plan requested daily Binance USD-M Funding archives
for the partial month containing the evidence cutoff. Binance does not publish
those objects: all 78 requested objects for BTCUSDT, ETHUSDT, and BNBUSDT from
2026-07-01 through 2026-07-26 returned HTTP 404. The authoritative blocked run
`0c71dfd0-e15f-43e5-ae50-ee44cee99736` otherwise verified 3,114 objects with no
parse failures, blocking quality reports, or excluded periods.

This amendment keeps the approved research window intact and changes only the
Funding acquisition unit for the cutoff month. The cutoff-month Funding data is
acquired from the official monthly archive after Binance publishes it, then
causally clipped to the original evidence cutoff.

## Locked decisions

- The evidence cutoff remains exactly `2026-07-26T19:59:59.999Z`.
- Macro and Micro starts, intervals, assets, factor protocol, alignment buffer,
  locked holdout, and promotion gates do not change.
- Binance USD-M public archives remain the sole source for the initial evidence.
- Funding uses monthly archives for every month, including the month containing
  `as_of`; nonexistent daily Funding objects are no longer planned.
- The cutoff-month monthly object may be acquired after `as_of` and after the
  source month closes. Acquisition time is provenance, not factor availability.
- The immutable raw monthly ZIP and its manifest are preserved in full.
- Canonical and research data include only rows with
  `event_time <= as_of` and `available_time <= as_of`.
- Rows after `as_of` are counted and recorded as an expected cutoff tail; they
  are not a source-period mismatch and never enter a snapshot.
- REST API Funding, synthetic values, zero fill, forward fill, and a changed
  cutoff are outside this amendment.

## Time semantics

Plan 03.5 now distinguishes three clocks:

1. `event_time` is the archived Funding calculation time.
2. `available_time` is the archived Funding publication/calculation time used by
   causal joins and remains the research-availability clock.
3. `ingested_at` is when the monthly ZIP was actually acquired. It may be later
   than `as_of` and is retained solely as provenance for this retrospective,
   immutable evidence build.

No model, threshold, factor, or holdout decision may use `ingested_at` to move a
row earlier. A row is eligible only when both event and availability timestamps
are at or before the locked cutoff.

## Source planning

The Funding source planner emits exactly one monthly object per asset and
calendar month from `macro_start` through the month containing `as_of`,
inclusive. For the locked initial run this includes:

```text
funding|BTCUSDT|native|monthly|2026-07-01T00:00:00+00:00
funding|ETHUSDT|native|monthly|2026-07-01T00:00:00+00:00
funding|BNBUSDT|native|monthly|2026-07-01T00:00:00+00:00
```

The plan contains no Funding daily objects. OHLCV daily tails and Metrics/OI
daily planning are unchanged. The locked source plan therefore changes from
3,192 objects to exactly 3,117: Funding decreases from 258 objects to 183,
while Metrics/OI remains 2,268 and OHLCV remains 666.

The configuration records the strategy explicitly:

```yaml
funding_tail_strategy: monthly_archive_after_period_close
```

The strategy is part of config and source-plan identity. An old run and a new
run therefore cannot silently share lineage even when their research cutoff is
the same.

## Acquisition and resumability

The downloader continues to fetch the archive plus upstream checksum, verify
the content hash, and write the ZIP and sidecar exclusively. A verified existing
monthly object is skipped on rerun.

If the cutoff-month archive is not yet published, the run stops with:

```text
FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE
```

The artifact records asset, source month, URL, HTTP status, attempt count, and
the unchanged config identity. This is a temporary, resumable source state, not
78 permanent missing daily objects. A later run retries the same three monthly
identities without deleting or rewriting other verified raw data.

An HTTP 404 for a historical month before the cutoff month remains a normal
required-source failure, not the temporary-tail code.

## Canonicalization and cutoff clipping

The parser validates the complete monthly archive before filtering it. Schema,
member-count, hash, timestamp, duplicate, and Funding-interval failures remain
blocking.

After validation, the canonical writer partitions the cutoff-month frame into:

- eligible rows: `event_time <= as_of` and `available_time <= as_of`;
- expected cutoff-tail rows: any valid source rows after `as_of`.

Only eligible rows are written to the cutoff-bound canonical partition and
registered in the catalog. The raw ZIP remains complete. The acquisition and
quality artifacts record `post_cutoff_rows_excluded`, the earliest excluded
timestamp, and the latest excluded timestamp. A nonzero expected tail is not a
warning or failure.

Rows outside the source calendar month, rows with availability before event
time, and unexpected timestamp grids remain blocking findings. Cutoff clipping
must occur before Macro/Micro concatenation, resampling, quality publication,
and content hashing for research snapshots.

## Coverage semantics

Funding coverage for the cutoff month is computed only over the explicit
interval from the UTC month start through `as_of`. The expected count uses each
row's archived `funding_interval_hours`; the denominator is never extended to
month end and never shrunk to the first or last observed row.

The gate remains 99 percent. Missing eligible Funding events block publication.
Post-cutoff rows neither improve nor reduce coverage. Missing Funding values
remain missing and are never imputed.

## Artifacts and reporting

`data-acquisition.json` records:

- the monthly-tail strategy and source-plan hash;
- the three cutoff-month raw identities and hashes;
- fetched time and byte count;
- retry or temporary-unavailable status;
- `post_cutoff_rows_excluded` counts after parsing.

`data-quality.json` records eligible expected/observed counts, coverage,
Funding interval evidence, cutoff-tail counts and ranges, and any exact blocking
findings.

The bounded Git evidence summary identifies Funding as `real` only after all
three cutoff-month archives pass. If they are not yet available, it identifies
Funding as `temporarily_blocked` and does not claim snapshot completeness.

## Error handling

- Cutoff-month 404 before publication:
  `FUNDING_TAIL_ARCHIVE_NOT_YET_AVAILABLE`; stop and retry later.
- Missing earlier monthly archive: `RAW_DOWNLOAD_FAILED`; required input blocks.
- Checksum mismatch: `RAW_HASH_MISMATCH`; no canonical output.
- Schema change: `DERIVATIVES_SCHEMA_CHANGED`; no canonical output.
- Eligible Funding coverage below 99 percent: `DATA_COVERAGE_BLOCKED`.
- Post-cutoff row entering canonical or research output:
  `EVIDENCE_CUTOFF_VIOLATION`; affected snapshot blocks.
- Existing verified monthly archive: `skipped`; hashes and snapshot identities
  must reproduce.

No error path may fall back to REST, fabricate a row, or change `as_of`.

## Test strategy

### Unit tests

- The source plan contains the cutoff month's three Funding monthly identities
  and zero Funding daily identities.
- Other source datasets retain their exact locked counts and date bounds.
- A cutoff-month 404 maps to the temporary stable code; an earlier-month 404
  remains `RAW_DOWNLOAD_FAILED`.
- A monthly Funding fixture containing rows before and after `as_of` writes only
  eligible rows and records the exact tail count/range.
- Coverage uses month start through `as_of` and the archived interval.
- Appending post-cutoff Funding rows cannot change canonical content hashes,
  coverage, Macro labels, factor results, or snapshot IDs.
- A row whose `available_time` is after `as_of` is excluded even when its
  `event_time` is before the cutoff.

### Offline integration tests

A miniature monthly Funding ZIP runs through raw verification, canonical
clipping, quality reporting, four snapshot publication, analysis, and the full
decision packet. The rerun skips the verified raw object and reproduces snapshot
IDs and metrics.

### Network and real-data verification

The fixed network smoke test keeps its bounded historical monthly Funding
object. Task 10 then retries only the three cutoff-month monthly objects. Once
published, the full run must produce four snapshots and all three OI delay
views. The second unchanged run must report all raw objects as skipped.

## Migration and execution order

This amendment changes the relevant parts of the existing implementation:

1. configuration and source-plan identity;
2. Funding cutoff-month source planning;
3. temporary-unavailable error classification;
4. canonical cutoff clipping and tail evidence;
5. Funding coverage calculation;
6. offline and real-archive regression tests;
7. Task 10 acquisition, resumability proof, analysis, and bounded evidence;
8. Task 11 cross-platform, distribution, storage, final review, and push.

Existing blocked runs and artifacts remain immutable. They are diagnostic
history and are not rewritten or deleted.

## Exit criteria

The amendment is complete when:

- the locked plan contains zero Funding daily objects;
- it contains exactly three cutoff-month Funding monthly objects;
- all eligible cutoff-month rows are real, checksum-verified archive data;
- no post-cutoff row exists in canonical or research snapshots;
- Funding coverage through `as_of` is at least 99 percent for all three assets;
- the acquisition rerun is idempotent and snapshot IDs reproduce;
- four Macro/Micro snapshots and three OI delay views are cataloged;
- analysis writes the complete decision packet, including a valid zero-candidate
  outcome;
- holdout remains unopened unless a factor reaches Candidate;
- Windows, WSL2, network, build, isolated-install, storage, Git-boundary, and
  independent review gates pass;
- the implementation branch is pushed and Plan 04 is not started.
