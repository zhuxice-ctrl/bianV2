# Factor Factory Dry Run Evidence — 2026-08-19

This note records the Task 7 verification pass for the factor-factory proposal pipeline. It is a tooling evidence packet only. It is not Alpha evidence, IC evidence, return evidence, Development evidence, or a trading record.

## Run identity

```text
command: uv run python scripts/run_factor_factory.py --config configs/factors/proposal_factory.yaml --output-root var/artifacts/factor-factory-dry-run --code-sha bfb2b0b
code SHA: c7ff71b
config SHA-256: f617ef440f4a8a09862c47d2c4184f396bfd6fede07fed6939014c7001bacd42
run ID: proposal-factory-f617ef440f4a-c7ff71b
artifact directory: F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-f617ef440f4a-c7ff71b
mode: proposal_only
```

## Verification gates

### Focused tests

Command:

```text
uv run pytest -p no:cov tests/unit/factors/test_proposals.py tests/unit/factors/test_proposal_audit.py tests/unit/factors/test_generator.py tests/unit/factors/test_proposal_artifacts.py tests/integration/factors/test_factor_factory.py tests/integration/factors/test_aily_skill_package.py -q
```

Result:

```text
56 passed in 2.11s
```

No Development test was invoked.

### Ruff check

Command:

```text
uv run ruff check src/bian_quant/factors scripts tests/unit/factors tests/integration/factors
```

Result:

```text
All checks passed!
```

Exit code: 0. Ruff check passed after commit `39ee2b0`; the earlier formatting failure in `tests/unit/factors/test_proposals.py` is no longer current.

### Ruff format check

Command:

```text
uv run ruff format --check src/bian_quant/factors scripts tests/unit/factors tests/integration/factors
```

Result:

```text
41 files already formatted
```

Exit code: 0.

### mypy

Command:

```text
uv run mypy src/bian_quant
```

Result:

```text
Success: no issues found in 105 source files
```

Exit code: 0.

### git diff --check

Command:

```text
git diff --check
```

Result: no output.

Exit code: 0.

## Dry run summary

The local dry run produced a new run directory and exactly six proposal-run artifacts:

```text
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-f617ef440f4a-c7ff71b/audit_report.md
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-f617ef440f4a-c7ff71b/candidate_registry.json
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-f617ef440f4a-c7ff71b/candidate_summary.md
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-f617ef440f4a-c7ff71b/decision_queue.md
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-f617ef440f4a-c7ff71b/deduplication_report.md
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-f617ef440f4a-c7ff71b/run_manifest.json
```

Artifact SHA-256 values:

```text
audit_report.md: 4d29c755e7d6729fa0154d59afbddb6f7dfadd9786b89fe3d7cfe5f776f42ee1
candidate_registry.json: 45559de52b0b7c87a6b52e5ff87d9fb0342c9def99b8c5476b3a7ff1fe8e91af
candidate_summary.md: c865624626b82829fd301c36604814390baffa31c0309395fee1ff41dd3081b3
decision_queue.md: 4b65a9e2a68c980b61167d4e72555c2e5ae9b282258a8ee6d078cd7ec2a35104
deduplication_report.md: 4aae6ae5bcdc2f48aa7da952ed2f270570e592fb6ed20e6520fa5b477bd352eb
run_manifest.json: bfc7d672d7e7abf3cf642ac0806c36b94eef8d8829b161151dbf73981b785a55
```

Counts:

```text
proposal_count: 8
deduplicated_count: 8
duplicate_identity_count: 0
audit_verdict_counts: PASS=8, BLOCKED=0, DEFERRED=0, REJECTED=0
reason_code_counts: none observed; every audited proposal had an empty reason-code list
```

Boundary flags recorded by the run manifest:

```text
data_read=false
network_access=false
holdout_accessed=false
paper_trading=false
live_trading=false
```

The dry run stayed in `proposal_only` mode. It exposed zero empirical metrics in the run manifest and, as observed from the artifact set and manifest, zero registry writes.

## Manifest notes

The run manifest also recorded the following summary fields:

```text
code_sha=c7ff71b
config_sha256=f617ef440f4a8a09862c47d2c4184f396bfd6fede07fed6939014c7001bacd42
proposal_count=8
deduplicated_count=8
duplicate_identity_count=0
```

## Limitation

This packet validates the tooling path only. It does not establish Alpha, IC, return, Development, or live-trading evidence.

