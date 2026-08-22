# Factor Preregistration Dry Run Evidence — 2026-08-22

This note records the Task 4 verification pass for the factor-factory preregistration
tooling path. It is tooling evidence only. It is not Development evidence, Alpha
evidence, IC evidence, return evidence, Holdout evidence, Paper evidence, or Live
trading evidence.

## Run identity

```text
command: uv run python scripts/run_factor_factory.py --config configs/factors/proposal_factory.yaml --output-root var/artifacts/factor-preregistration-dry-run --code-sha 2dd676bc51f1d38883abfdef8f18c79429249ccf
code SHA: 2dd676bc51f1d38883abfdef8f18c79429249ccf
config SHA-256: 7e9b38612f4718e6a76339918a8ec57ed70dc19c86bc747db511123f340aa374
run ID: proposal-factory-7e9b38612f47-2dd676bc51f1d388
artifact directory: F:/bianV2/var/artifacts/factor-preregistration-dry-run/proposal-factory-7e9b38612f47-2dd676bc51f1d388
mode: proposal_only
```

## Verification gates

### Expected failing package test

Command:

```text
uv run pytest -p no:cov tests/integration/factors/test_aily_skill_package.py -q
```

Observed failure before the schema/doc updates:

```text
FileNotFoundError: [Errno 2] No such file or directory: 'F:\\bianV2\\skills\\quant-factor-research-factory\\schemas\\preregistration.yaml'
```

### Focused package test after the fix

Command:

```text
uv run pytest -p no:cov tests/integration/factors/test_aily_skill_package.py -q
```

Result:

```text
2 passed in 0.57s
```

### Full Task 4 factor test suite

Command:

```text
uv run pytest -p no:cov tests/unit/factors/test_proposals.py tests/unit/factors/test_proposal_audit.py tests/unit/factors/test_generator.py tests/unit/factors/test_proposal_selection.py tests/unit/factors/test_preregistration.py tests/unit/factors/test_proposal_artifacts.py tests/integration/factors/test_factor_factory.py tests/integration/factors/test_aily_skill_package.py -q
```

Result:

```text
74 passed in 3.19s
```

### Ruff check

Command:

```text
uv run ruff check skills/quant-factor-research-factory tests/integration/factors/test_aily_skill_package.py
```

Result:

```text
All checks passed!
```

### Ruff format check

Command:

```text
uv run ruff format --check skills/quant-factor-research-factory tests/integration/factors/test_aily_skill_package.py
```

Result:

```text
5 files already formatted
```

### mypy

Command:

```text
uv run mypy src/bian_quant
```

Result:

```text
Success: no issues found in 107 source files
```

## Dry run summary

The local run produced one new preregistration dry-run directory:

```text
F:/bianV2/var/artifacts/factor-preregistration-dry-run/proposal-factory-7e9b38612f47-2dd676bc51f1d388
```

Artifact SHA-256 values:

```text
audit_report.md: 4d29c755e7d6729fa0154d59afbddb6f7dfadd9786b89fe3d7cfe5f776f42ee1
candidate_registry.json: a7148b1fa30c11804bbcebc8773a128b991b477e93e9cefc5d92ad7ce3b44870
candidate_summary.md: 6c50ade72ffcbf856a5f15f601b610905ecf3bfb00b4925b02a2228efaaf948d
decision_queue.md: 205ab43c821f9470ca886a71aa1b959a9c4fd4429687bc8513d8d4f72cdf0db6
deduplication_report.md: 4aae6ae5bcdc2f48aa7da952ed2f270570e592fb6ed20e6520fa5b477bd352eb
run_manifest.json: b500c637fb6b95853d0d5eb30dc8eb5ecd42627e25698c6b6118a55115ddff04
```

Selected and excluded counts:

```text
proposal_count: 8
deduplicated_count: 8
duplicate_identity_count: 0
selected_count: 5
excluded_count: 3
audit_verdict_counts: PASS=8
```

Boundary assertions recorded in `run_manifest.json`:

```text
data_read=false
network_access=false
holdout_accessed=false
paper_trading=false
live_trading=false
```

Registry and queue observations:

- `candidate_registry.json` contains 8 `proposal_only` entries and records 5
  preregistration paths for the selected queue items.
- `decision_queue.md` contains 5 queue rows, each marked `SELECTED` and linked to a
  preregistration YAML file.
- The run manifest records 5 preregistration YAML artifacts under the
  `preregistration/` directory and 3 excluded proposals with
  `selection_reason=DIVERSITY_MECHANISM_DUPLICATE`.

Preregistration artifact hashes from the manifest:

```text
preregistration/4976a0640320ccc0a411d1292b1d8cd218b53b7d0605412f3de7a14d16c14035.yaml: 893addaaef8405f0580b6c8d146eb6f21a43d61fd92844833f7821c174c3d13e
preregistration/adcde6a03b73947edc7d45ac58fc55e6970940e4e6a001dc7607b453909e1b73.yaml: a628d3e2c9ce7c028f907824cf86ad88b6c35608928c831c1da004e934904a25
preregistration/0e7fd7233b5aa1f38909aafb0c410e25b54b1055ceefc66cbe76dd892d535c7e.yaml: 336849e34dda5da1dd2b4022787e8e5b108ffc4047601aa72d0d7fa96ecec703
preregistration/971fcbb957935a9fbef574465c2ce5e0f0956a8c884a62fb3c6f1dfc36c4dd15.yaml: 190ca6083afad1a673816cd3a299ed303593a24fbc883276fb868fb134d87ebd
preregistration/0f81dd1fd3a9dee80b2c50dfdebb25c41956b61d427612b5c6a3f828d99bffef.yaml: 5518e3943975b97fdb00066cea1af81df7652e88ea87156678f2f3d433c21b4f
```

## Limitation

This packet validates the local preregistration tooling path only. It does not start
Development, does not approve or modify lifecycle state, does not read or download
data, and does not provide Alpha, IC, return, Holdout, Paper, or Live evidence.
