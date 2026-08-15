# TONUSDT 2026-07 Funding — Permanent Source Exclusion Run

## Scope

This run implements the approved data-layer path A: a permanent source
exclusion is carried as audit metadata, does not enter `source_plan_hash`, and
is consumed only by Canonical-input repair and strict preflight. No network
request was made in this run; the exclusion record references Aily's verified
404 report for the Binance Vision archive.

```text
identity_key=funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00
reason_code=SOURCE_ARCHIVE_404
status=permanently_unavailable
source_plan_hash=f306aa6e0344847bd70defcb66410b9f6099572b1aa8aeeae7864982dc738cf4
exclusion_config=configs/data/canonical_input_exclusions.json
```

## Actual repair output

```text
status=repaired
repaired_snapshot_ids=()
blocked_reasons=()
excluded_source_ids=('funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00',)
cutoff_evidence_count=0
```

The repair verified all eligible local sources and wrote no Canonical or
Catalog artifact. The excluded source was not imputed, downloaded, or parsed.

## Actual strict preflight output

```text
status=ready
inputs=14879
parents=14879
input_set_sha256=fb6c5d3599dee1bf8018143df7c09a5d2f3cdb6047c091913ce9d7f24bb6f094
blocked_reasons=()
excluded_source_ids=('funding|TONUSDT|native|monthly|2026-07-01T00:00:00+00:00',)
```

The full acquisition plan remains 14,896 objects and its hash is unchanged;
the eligible Canonical input set is 14,879 objects. This `READY` state carries
the exclusion explicitly and does not claim that TONUSDT July Funding was
observed.

## Safety flags

```text
network_downloads=false
research_snapshot_publisher_called=false
development_analysis_called=false
holdout_accessed=false
paper_trading=false
live_trading=false
```

No research snapshot recovery is authorized by this slice. Downstream Funding
factors must preserve missing/gapped semantics for the excluded identity.
