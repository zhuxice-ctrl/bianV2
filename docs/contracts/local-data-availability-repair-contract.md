# Local Data Availability Repair Contract

## Scope

`repair_verified_local_canonical_inputs(config)` is a data-layer operation for
current source-plan Canonical partitions only. It may read local Raw ZIPs and
write new Canonical Parquet files below `canonical_root/plan=<current-plan-hash>/`
plus new Canonical Catalog rows in `catalog_path`. It may not write Raw files,
historical Canonical paths, research snapshots or `research_root`; it may not
run analysis, access Holdout, use paper/live code or make network requests.

The public result is immutable:

```python
class LocalAvailabilityRepairStatus(StrEnum):
    REPAIRED = "repaired"
    BLOCKED = "blocked"

@dataclass(frozen=True)
class LocalAvailabilityRepairResult:
    status: LocalAvailabilityRepairStatus
    repaired_snapshot_ids: tuple[str, ...]
    blocked_reasons: tuple[str, ...]
    cutoff_evidence: tuple[CutoffEvidence, ...]
    excluded_source_ids: tuple[str, ...]
```

All result collections use deterministic identity/snapshot ordering.

## Selection and verification

The Raw acquisition plan remains the identity source for the current plan hash.
The adapter derives its repair candidates with
`canonical_input_sources(build_source_plan_audit(config), as_of=config.as_of)`.
This excludes a recorded `PermanentSourceExclusion` identity and a partial-day
1d OHLCV archive until its 23:59:59.999 UTC close is available, while retaining
intraday archives that contain earlier closed bars. For every remaining source,
the adapter computes the current
source-plan hash and current `canonical_plan_path`. Historical `plan=`
directories are never selected as inputs.

Permanent exclusions are loaded from the configured
`canonical_input_exclusions_path`. They must contain a stable identity, the
literal status `permanently_unavailable`, reason `SOURCE_ARCHIVE_404`, source
URL, evidence reference and observation date. The exclusion metadata is carried
by `SourcePlanAudit` but is deliberately excluded from `source_plan_hash`; it
therefore does not rename or rewrite existing Canonical/Catalog artifacts.

Before checking an existing entry or parsing a candidate, the adapter calls:

```python
reuse_verified_artifact(raw_root / source.relative_path, expected=source.raw_identity)
```

The Raw ZIP bytes, sidecar manifest hash, identity, byte count and source period
must all pass. A missing ZIP/sidecar, hash mismatch or identity mismatch is a
stable blocker; the adapter never reconstructs a sidecar or guesses a hash.

The only emitted blocker codes are:

- `RAW_ARTIFACT_INCOMPLETE:<identity_key>` for a missing or malformed Raw
  artifact/sidecar;
- `RAW_HASH_MISMATCH:<identity_key>` for content or byte-count mismatch;
- `RAW_IDENTITY_MISMATCH:<identity_key>` for a verified file with the wrong
  source identity;
- `EVIDENCE_CUTOFF_VIOLATION:<identity_key>` when no canonicalized row is
  eligible at the configured cutoff; and
- `CANONICAL_PARTITION_CONFLICT:<identity_key>` when an existing current-plan
  file or Catalog snapshot cannot be paired with the immutable manifest.

An identity listed in `PermanentSourceExclusion` is not emitted as
`RAW_ARTIFACT_INCOMPLETE`; it is returned in the repair result's
`excluded_source_ids` and remains absent from the eligible Canonical input set.
The exclusion record is not permission to impute Funding or to use another
network/API source.

## Published manifest

The verified Raw is canonicalized with the existing dataset parser, clipped by
`event_time <= config.as_of` and `available_time <= config.as_of`, and rejected
if the eligible frame is empty. The only write path is
`write_canonical_partition(eligible_frame, current_plan_path)` followed by
`DatasetCatalog.register(DatasetManifest(...))`.

The manifest must contain:

```python
layer = DatasetLayer.CANONICAL
name = f"canonical-{source.dataset.value}-{source.interval}"
parent_snapshot_ids = [f"raw-{verified.manifest.content_sha256}"]
config_json = json.dumps(
    {"identity_key": source.identity_key,
     "raw_sha256": verified.manifest.content_sha256},
    sort_keys=True,
    separators=(",", ":"),
)
```

The snapshot ID is the existing `canonical_snapshot_id(source,
content_sha=..., plan_hash=...)`. Existing files and rows are immutable: a
different content hash, path, lineage, metadata or canonical config causes
`CANONICAL_PARTITION_CONFLICT` and is never overwritten. A valid existing
entry must have the matching path, content hash, layer, name, row/time bounds,
currently verified Raw parent and canonical `config_json`; otherwise it is not
treated as a prior repair.

## Result and authorization boundary

`LocalAvailabilityRepairResult.status` is `repaired` when no blockers remain
and `blocked` otherwise. Repaired IDs, excluded IDs and blocker reasons are
sorted and deduplicated. A permanently excluded source is a documented gap,
not a successful data point; downstream Funding factors must preserve missing
or gapped semantics.
