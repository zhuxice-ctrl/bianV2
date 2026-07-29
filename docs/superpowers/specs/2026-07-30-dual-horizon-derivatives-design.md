# Dual-Horizon Derivatives Evidence Design

**Status:** Approved in conversation on 2026-07-30

**Phase:** Plan 03.5, inserted between Factors and Regimes (Plan 03) and
Observability and Dashboard (Plan 04)

## Purpose

Plan 03 proved that the research platform can reject weak factors, but the
committed evidence covers only about one year of OHLCV and has no real
Funding/OI snapshot. Plan 03.5 adds enough history to describe crypto-native
market cycles and enough recent derivatives detail to evaluate causal factors.

The phase does not have to discover a promotable factor. Engineering completion
and research success are separate decisions. A reproducible result with zero
candidates is a valid successful run.

## Locked decisions

- Assets: `BTCUSDT`, `ETHUSDT`, and `BNBUSDT` only.
- Venue: Binance USD-M futures archives, matching the existing adapters.
- Initial fixed evidence cutoff: `2026-07-26T19:59:59.999Z`.
- Macro start: `2021-07-01T00:00:00Z`.
- Micro start: `2024-07-01T00:00:00Z`.
- Macro research frequencies: `1d` and `4h`.
- Micro research frequencies: `1h` and `4h`.
- The primary factor horizon remains `4h`; `1h` is a robustness check, not a
  second search space.
- Crypto-internal cycle evidence is in scope. Traditional macroeconomic series
  such as rates, dollar indices, and VIX are outside this phase.
- Raw compressed archives remain local under `var/raw/`; Git stores only small
  manifests, hashes, configurations, tests, and evidence summaries.
- Disk budget: reserve 10 GB, target no more than 2.5 GB persistent phase data,
  and no more than 5 GB peak working space.
- No live trading, exchange credentials, model weights, dashboard redesign, or
  scheduled automation is included.

## Data scope

The design uses a dual-horizon matrix rather than retaining five years at every
available frequency.

| Dataset | Source granularity | Coverage | Persistent research views | Purpose |
|---|---|---|---|---|
| USD-M OHLCV | monthly ZIP plus daily current-month tail | 2021-07-01 through cutoff | 1d, 4h | macro cycle |
| USD-M OHLCV | monthly ZIP plus daily current-month tail | 2024-07-01 through cutoff | 1h, 4h | micro factor study |
| Funding | monthly ZIP, native interval | 2021-07-01 through cutoff | native events, 1d summaries | leverage-cycle context |
| Metrics/OI | daily ZIP, native records | 2024-07-01 through cutoff | 1h, 4h, 1d | detailed derivatives factors |

Five-year OI is intentionally excluded because Binance exposes metrics as daily
archives. Downloading and retaining roughly five years of daily high-frequency
metrics would add thousands of network objects without improving the locked
five-year price/volume/funding regime objective. OI enriches the most recent two
years, where detailed factor validation occurs.

The fixed cutoff is part of snapshot identity. Later updates create new configs,
raw manifests, dataset IDs, run IDs, and evidence; they never mutate this initial
snapshot.

## Architecture

```text
Explicit acquisition config
        |
        v
Binance monthly/daily ZIP + CHECKSUM
        |
        v
Immutable raw artifacts and manifests
        |
        v
Schema-specific parsers
        |
        v
Canonical point-in-time event records
        |
        v
Causal aggregation and quality gates
        |
        +--> Macro 1d/4h snapshot
        |
        +--> Micro 1h/4h snapshot
        |
        v
Regime analysis + factor validation
        |
        v
Append-only run artifacts and decision summary
```

### Acquisition configuration

Every acquisition run receives a versioned configuration containing:

- exact asset list;
- exact start and end timestamps;
- required source datasets and intervals;
- raw, canonical, and research output roots;
- retry count of three;
- minimum free-space warning threshold of 10 GB;
- minimum free-space blocking threshold of 5 GB;
- OI publication-delay scenarios of 5, 10, and 15 minutes;
- expected coverage thresholds;
- code SHA and parent snapshot IDs.

The code must not infer an end date from the system clock or select a directory's
latest file.

### Raw layer

Raw downloads are immutable. Each raw ZIP has a sidecar manifest with source
URL, fetched time, byte count, local SHA-256, upstream checksum, asset, dataset,
and source period. An existing artifact or sidecar at the target path causes a
fail-closed error unless both identify the same previously verified object, in
which case the resumable controller records a skip.

OHLCV and Funding work is grouped by calendar month. Metrics/OI is downloaded
from daily source objects but scheduled and reported in monthly batches. The
controller records each daily object independently so a failed day can resume
without repeating the month.

Compressed ZIP files persist. Expanded CSV content exists only in a temporary
directory during parsing and is removed on success or failure.

### Canonical layer

Canonical records reuse the Plan 01 point-in-time contracts. Every record has at
least:

- `asset`;
- `event_time`;
- `available_time`;
- `ingested_at`;
- `source`;
- source-specific values;
- an availability assumption identifier when publication time is inferred.

OHLCV close and volume become available at the bar's source `close_time`.
Funding becomes available at its archived calculation time. Metrics/OI uses the
existing five-minute publication assumption for the primary snapshot and stores
the assumption in every record.

Canonical outputs are partitioned by dataset, asset, year, and month. Dataset
catalog entries are immutable and contain content hashes, row counts, event-time
ranges, available-time ranges, parent raw hashes, and config JSON.

### Research snapshots

Aggregation is backward-looking and closes a bucket only when all contributing
records are available. The aggregated row's `available_time` is the maximum
source availability time in that bucket. No aggregation may forward-fill a
missing Funding or OI observation.

Macro and Micro snapshots receive different IDs and parent lineages. An OI
delay scenario creates a separate research snapshot or query view; it cannot
rewrite the five-minute primary snapshot.

## Storage and disk policy

The existing three-asset one-year OHLCV CSV set is about 3.65 MB. Expected
persistent usage for this phase is:

| Category | Expected persistent size |
|---|---:|
| Five-year 1d/4h OHLCV | 10-30 MB |
| Two-year 1h OHLCV | 5-20 MB |
| Funding raw and Parquet | 20-100 MB |
| Two-year OI raw daily ZIPs | 300 MB-1.2 GB |
| OI 1h/4h/1d Parquet | 100-400 MB |
| Catalogs, reports, and experiment evidence | 100-500 MB |
| Total target | 0.8-2.5 GB |

Peak space during download and extraction is expected to remain between 2 and
5 GB. The downloader warns below 10 GB free and refuses new downloads below 5
GB. Raw verified ZIPs and referenced snapshots are never automatically deleted.
Only unreferenced temporary extraction content is cleaned automatically.

## Data quality gates

### Common blocking gates

- malformed or timezone-naive timestamps;
- `available_time` preceding `event_time`;
- duplicate primary keys;
- out-of-order records after canonical sorting;
- source checksum mismatch;
- unexpected archive member count;
- source schema changes;
- snapshot ID reuse with different content or lineage.

### OHLCV

- close, open, high, and low must be positive;
- volume must be non-negative;
- high/low envelope relationships must hold;
- expected-frequency completeness must be at least 99.9%;
- any gap longer than two expected bars requires an explicit finding and blocks
  an unexplained snapshot publication.

### Funding

- event cadence is evaluated using each row's archived
  `funding_interval_hours`;
- coverage must be at least 99%;
- duplicates or impossible intervals block publication;
- missing Funding remains missing and is never forward-filled or zero-filled.

### Metrics/OI

- daily source archives are checked independently;
- monthly coverage must be at least 98%;
- months below 98% remain in raw storage but are excluded from factor research;
- missing OI remains missing;
- sum OI and sum OI value must be non-negative;
- the 5, 10, and 15 minute availability scenarios must never affect a decision
  timestamp earlier than their scenario-specific `available_time`.

### Monthly and daily-tail merge

The current partial month is assembled from daily archives after the last full
monthly archive. The merge rejects overlap with monthly data, duplicate source
periods, gaps not represented by findings, and rows later than the fixed cutoff.

## Error handling and resumability

Work units are dataset, asset, and source period. OHLCV/Funding periods are
months; Metrics/OI periods are days grouped in monthly progress reports.

- Network operations retry at most three times with bounded backoff.
- A persistent failure records `RAW_DOWNLOAD_FAILED` and blocks the required
  snapshot; no synthetic replacement is created.
- Hash failures record `RAW_HASH_MISMATCH` and preserve the invalid payload only
  in a quarantined temporary path for diagnosis.
- Schema changes record `DERIVATIVES_SCHEMA_CHANGED` and stop parsing that
  source period.
- Coverage failures record `DATA_COVERAGE_BLOCKED` and list excluded periods.
- Causality failures record `AVAILABLE_TIME_VIOLATION` and block the entire
  affected snapshot.
- Verified existing raw objects are skipped idempotently.
- Successful work units survive failures in other work units.
- A rerun starts from failed or missing work units, not from the beginning.
- Temporary extraction paths are removed in a `finally` path.

## Macro cycle analysis

The five-year Macro snapshot describes crypto-internal market state from OHLCV
and Funding. It does not use traditional macroeconomic inputs.

The existing five-state classifier remains the initial model:

- trend, low volatility;
- trend, high volatility;
- range, low volatility;
- range, high volatility;
- liquidity stress.

Thresholds are fit inside expanding training windows. Historical labels cannot
use full-sample quantiles. The report includes the current label, state duration,
threshold inputs, transition history, and prior comparable episodes. A state
with fewer than 30 observations is reported as insufficient evidence rather than
assigned an inferential statistic.

OI overlays are available only for the most recent two years and must be labeled
as Micro evidence when shown beside the five-year Macro regime.

## Micro factor protocol

The two-year Micro snapshot uses 4h as its primary evaluation horizon. The 1h
view is a predefined sensitivity check and cannot create a second parameter
search.

The initial interpretable factor set is:

- `momentum_24`;
- `reversal_12`;
- `realized_vol_24`;
- `volume_surprise_24`;
- `amihud_24`;
- `funding_zscore`;
- `oi_change`;
- `leverage_crowding`.

The first 18 months form anchored walk-forward development folds with purge and
embargo. The final six months form a locked holdout. Holdout rows cannot be
queried by factor generation, parameter selection, regime threshold fitting,
redundancy selection, or incremental models.

The bounded candidate generator may emit at most 20 candidates only after the
eight interpretable factors finish. Generated expressions inherit the same
folds, labels, costs, multiple-testing family, and holdout boundary. There is no
parameter sweep outside the committed search manifest.

## Lifecycle and promotion policy

Engineering completion does not depend on promotion.

### Observed

A registered factor may move from `researching` to `observed` after a completed,
persisted development run. The transition cites that run ID.

### Candidate

An observed factor can become a candidate only when all development gates pass:

- at least two independent asset/fold/regime slices survive BH at alpha 0.05;
- at least 60% of eligible slices agree on the factor direction;
- directional evidence exists in at least two assets;
- the factor is the selected representative of its redundancy cluster;
- final-fold incremental cost-adjusted return is positive at 5 bps;
- the 10 bps stress result is not materially negative;
- no single asset or regime supplies more than 50% of supporting evidence;
- OI-dependent factors remain directionally stable across 5, 10, and 15 minute
  publication-delay scenarios.

### Approved

A candidate receives one locked-holdout evaluation. It becomes approved only if
the holdout, cost stress, delay stress, and concentration gates all pass. Holdout
access is recorded. A second access attempt without an explicit new snapshot and
new experiment lineage fails with `HOLDOUT_ACCESS_DENIED`.

Rejected promotions record `FACTOR_PROMOTION_REJECTED` and preserve the factor's
prior state. Zero candidates or zero approvals is a valid research outcome.

## Artifacts and human decision report

Every run has an append-only run ID and produces:

- `data-acquisition.json`: requested and completed source periods, hashes,
  retries, skips, and failures;
- `data-quality.json`: coverage, gaps, exclusions, and blocking findings;
- `macro-regime.json` and `macro-regime.md`: current regime and historical
  context;
- `factor-screening.json` and `factor-screening.md`: per-fold, per-asset,
  per-regime evidence, BH, redundancy, incremental contribution, cost stress,
  and delay stress;
- `decision-summary.md`: a short human-readable decision packet.

The decision summary always answers:

1. What data changed?
2. What data was unavailable or excluded?
3. What is the current crypto market regime and why?
4. Which factors passed, failed, or remain observed?
5. What decision, if any, is requested from the user?

The report separately states engineering status, data status, factor status, and
human-decision status. A successful run with zero candidates still writes all
artifacts. Plan 04 will read these persisted artifacts rather than recompute the
research.

## Test strategy

### Unit tests

Unit tests cover URL construction, explicit date grids, free-space policy,
checksum handling, immutable paths, schemas, timestamp parsing, availability
scenarios, causal aggregation, gap detection, coverage thresholds, regime
prefix invariance, holdout denial, lifecycle gates, and stable error codes.

### Offline integration tests

Frozen miniature ZIP/CSV fixtures run the complete path from raw artifact to
canonical partitions, Macro/Micro snapshots, experiment registration, and all
five report artifacts. Default tests remain network-free.

### Network tests

Tests marked `network` download a small fixed set of real Binance source periods
and verify checksums plus parser compatibility. They never download the full
five-year/two-year matrix during a test run.

### Determinism and platform tests

Identical config, source hashes, and code SHA must create identical snapshot IDs,
quality findings, regimes, and factor metrics. Run IDs and acquisition timestamps
may differ. Windows and WSL2 run the same default suite. Wheel and sdist isolated
installation must import the new modules and execute the CLI help path.

## Exit gates

Plan 03.5 engineering is complete when:

- [ ] Macro and Micro configs use the locked explicit ranges and cutoff.
- [ ] Raw manifests exist for every required BTC/ETH/BNB source period, or the
      run ends blocked with exact missing periods.
- [ ] Verified raw objects are immutable and resumable.
- [ ] Macro 1d/4h and Micro 1h/4h snapshots are cataloged and immutable.
- [ ] OHLCV, Funding, and OI coverage gates run and persist findings.
- [ ] OI 5/10/15 minute availability scenarios pass causality tests.
- [ ] A current Macro regime report reproduces from the fixed snapshot.
- [ ] All eight interpretable factors complete real-data development screening.
- [ ] The locked holdout cannot be read before development promotion.
- [ ] A zero-candidate outcome produces complete reports and exits successfully.
- [ ] Persistent storage is at most 2.5 GB and processing peak remains below 5
      GB for the initial locked dataset.
- [ ] Ruff, format, strict mypy, default pytest, network pytest, Windows, WSL2,
      wheel build, sdist build, and isolated installation all pass.
- [ ] The implementation branch is clean, `main` is untouched, and no raw data,
      databases, credentials, or `var/` content is committed.

Research success is reported separately as the count of candidates and approved
factors. It is not an engineering exit gate.
