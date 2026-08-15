# Local Snapshot Recovery Contract

## Scope

The recovery adapter reads existing Canonical Parquet files and their Catalog
manifests. It does not acquire data, publish research snapshots, calculate
factors, or run research analysis. Its read-only entry point is:

```python
preflight_local_snapshot_recovery(
    config: DualHorizonAcquisition,
) -> LocalSnapshotRecoveryPreflight
```

## Input identity

For every source returned by
`canonical_input_sources(build_source_plan_audit(config), as_of=config.as_of)`,
exactly one Catalog entry must match all of the following. The full Raw
acquisition plan remains the source-plan identity, so excluding an unclosed 1d
bar or a recorded permanent source exclusion does not create a new Canonical
namespace:

- name `canonical-{dataset.value}-{interval}`;
- `manifest.layer == canonical`;
- `manifest.config_json.identity_key == source.identity_key`;
- `manifest.config_json.raw_sha256` equal to the local Raw manifest content SHA;
- a path equal to the current source-plan-namespaced Canonical path;
- an existing regular Parquet path; and
- a recomputed `dataframe_content_hash(frame, sort_by=["asset", "event_time"])`
  equal to `manifest.content_sha256`.

The frame must contain the dataset's required columns, use the source asset,
have UTC-coercible `event_time` and `available_time`, and satisfy
`available_time >= event_time`. Every row must already satisfy both
`event_time <= config.as_of` and `available_time <= config.as_of`; a future row
is a blocking cutoff violation rather than a row to silently drop.

## Result states

`READY` means all source objects have one verified input and a non-empty,
stable-sorted `parent_snapshot_ids` tuple. `BLOCKED` means at least one stable
reason exists; the caller must not publish or analyze. `RECOVERED` is reserved
for the later write-capable recovery operation and is not returned by the
preflight function.

Stable reasons include:

```text
CANONICAL_INPUT_MISSING:<identity_key>
CANONICAL_INPUT_AMBIGUOUS:<identity_key>
CANONICAL_LAYER_INVALID:<snapshot_id>
CANONICAL_FILE_MISSING:<snapshot_id>
CANONICAL_CONTENT_HASH_MISMATCH:<snapshot_id>
CANONICAL_SCHEMA_INVALID:<identity_key>
CANONICAL_TIME_INVALID:<identity_key>
CANONICAL_CAUSALITY_INVALID:<identity_key>
CANONICAL_CUTOFF_VIOLATION:<identity_key>
CANONICAL_ASSET_INVALID:<identity_key>
CANONICAL_SOURCE_PERIOD_MISMATCH:<identity_key>
CANONICAL_DUPLICATE:<identity_key>
CANONICAL_VALUE_INVALID:<identity_key>
CANONICAL_INTERVAL_INVALID:<identity_key>
CANONICAL_NEGATIVE_OI:<identity_key>
RAW_LINEAGE_MISSING:<identity_key>
```

Reasons are deduplicated and sorted. A blocked result has empty parent IDs and
no input-set hash. A ready result hashes the canonical JSON list of each
source identity, snapshot ID, and content SHA-256 with UTF-8, sorted keys and
compact separators. A ready result may also contain a non-empty
`excluded_source_ids` tuple for `PermanentSourceExclusion` identities. Those
identities are intentionally absent from the eligible source set and must
remain visible to callers; READY does not authorize Funding imputation,
fallback APIs, or a claim that the excluded source was observed.

## Side-effect and lineage boundary

Preflight must not call `DatasetCatalog.register`, `publish_snapshot`, a
downloader, or any network/API client. Catalog access uses a read-only SQLite
connection. Existing Canonical files, research files, manifests and Catalog
rows must remain byte-for-byte unchanged. The later recovery operation is the
only writer and must use existing content-addressed snapshot builders.

The four main research snapshots must share the exact non-empty Canonical
parent tuple. Each OI delay view must use the exact set of those four new main
snapshot IDs. No preflight result authorizes Holdout, Candidate promotion,
paper trading, live trading, or account operations.
