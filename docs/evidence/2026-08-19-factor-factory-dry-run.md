# Factor Factory Dry Run Evidence — 2026-08-19

This note records the Task 7 verification pass for the factor-factory proposal pipeline. It is a tooling evidence packet only. It is not Alpha evidence, IC evidence, return evidence, Development evidence, or a trading record.

## Run identity

```text
command: uv run python scripts/run_factor_factory.py --config configs/factors/proposal_factory.yaml --output-root var/artifacts/factor-factory-dry-run --code-sha bfb2b0b
code SHA: bfb2b0b
config SHA-256: e94468b53f7fddfe1438f8742f202206ad06ea5f951b07d1a434f7ee77bb574f
run ID: proposal-factory-e94468b53f7f-bfb2b0b-02
artifact directory: F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-e94468b53f7f-bfb2b0b-02
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
54 passed in 5.89s
```

No Development test was invoked.

### Ruff check

Command:

```text
uv run ruff check src/bian_quant/factors scripts tests/unit/factors tests/integration/factors
```

Result:

```text
I001 [*] Import block is un-sorted or un-formatted
 --> tests\unit\factors\test_proposals.py:1:1

E501 Line too long (115 > 100)
 --> tests\unit\factors\test_proposals.py:12:101
```

Exit code: 1.

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
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-e94468b53f7f-bfb2b0b-02/audit_report.md
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-e94468b53f7f-bfb2b0b-02/candidate_registry.json
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-e94468b53f7f-bfb2b0b-02/candidate_summary.md
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-e94468b53f7f-bfb2b0b-02/decision_queue.md
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-e94468b53f7f-bfb2b0b-02/deduplication_report.md
F:/bianV2/var/artifacts/factor-factory-dry-run/proposal-factory-e94468b53f7f-bfb2b0b-02/run_manifest.json
```

Artifact SHA-256 values:

```text
audit_report.md: 05a50b355594584912a0adb9b0076b60540e9a3c0a60b8e79bd33353406c150f
candidate_registry.json: df19670a616ab0849d1dddd84662fa12e38bdfb4adff1232cb96000a6df612da
candidate_summary.md: fd672d94082dbf889efbafad1bb3a65593735cb3e4b6e8bb36b378e0b6beeed1
decision_queue.md: 7407355aaab77b720c8e7787d7e44b9c7d6dab4479a92c6119b1ee395063f7b4
deduplication_report.md: 6e55b1d6228bc2e1a3abf3d7b23997c97311b4389d0bf124fee1b7272867848c
run_manifest.json: 65ade38f904a29ac1daf4a70d0ce77dd33338098097d0c162d9ad32682fe6901
```

Counts:

```text
proposal_count: 20
deduplicated_count: 20
duplicate_identity_count: 0
audit_verdict_counts: PASS=20, BLOCKED=0, DEFERRED=0, REJECTED=0
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
code_sha=bfb2b0b
config_sha256=e94468b53f7fddfe1438f8742f202206ad06ea5f951b07d1a434f7ee77bb574f
proposal_count=20
deduplicated_count=20
duplicate_identity_count=0
```

## Limitation

This packet validates the tooling path only. It does not establish Alpha, IC, return, Development, or live-trading evidence.
