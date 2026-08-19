# Quant Factor Research Factory Design

## Goal

Build a bounded, reproducible candidate-discovery workflow that combines an Aily skill package with a local Python validation engine. The workflow may create only `proposal_only` records. It must not evaluate returns, run Development, update the formal factor registry, or access Holdout, Paper, Live, exchange, or account interfaces.

## Scope and boundaries

The factory is a discovery and static-audit system, not a backtest or promotion system.

Inputs are controlled research-family templates, a versioned search-space configuration, a forbidden-factor archive, and structured candidate proposals from Aily workers. Outputs are append-only proposal artifacts and a human-review queue.

The factory is separate from the formal research lifecycle:

```text
factory output: proposal_only
human/research decision
formal FactorSpec and frozen preregistration
Development
```

A factory proposal never creates, modifies, or transitions a `FactorSpec` or `FactorRegistry` record.

## Architecture

```text
Aily skill package
  Supervisor: assign a bounded family task and enforce stop conditions
  Family worker: submit structured economic proposals only
  Audit worker: explain rejection and deduplication results only
                    |
                    v
Local Python proposal engine
  Candidate generation and normalization
  Structural, causal, and overlap validation
  Deterministic deduplication and risk classification
  Canonical artifact writer
                    |
                    v
Proposal artifacts
  candidate_registry.json
  candidate_summary.md
  audit_report.md
  deduplication_report.md
  decision_queue.md
  run_manifest.json
```

The Aily package orchestrates work but does not determine whether a structured candidate passes a machine-checkable rule. The Python engine owns deterministic validation, hashes, ordering, and output writing.

## Proposal protocol

Introduce a `FactorProposal` data model distinct from `FactorSpec`. It contains enough information for static review but is not a frozen research contract.

Required fields:

```yaml
factor_id:
factor_version:
research_family:
economic_hypothesis:
formula:
direction:
required_columns:
signal_time:
decision_time:
entry_price:
holding_rule:
exit_rule:
missing_policy:
parent_factors:
source_type:
proposal_status: proposal_only
```

Optional fields carry supported data constraints and warnings, including `available_time_definition`, expected turnover class, liquidity assumptions, known overlap candidates, and explanatory notes.

`proposal_status` is always `proposal_only`. The Python model rejects candidate, holdout, approved, paper, and live labels.

## Python engine responsibilities

The existing bounded expression generator remains the source of deterministic template and grammar candidates. It will be extended by focused proposal modules rather than embedding Aily orchestration in `generator.py`.

The engine will:

1. Load a versioned search-space configuration with a fixed global candidate cap.
2. Normalize generated or Aily-submitted candidates to `FactorProposal`.
3. Validate expression trees without `eval`, label references, future references, unknown columns, invalid windows, or invalid tree depth.
4. Require an economic hypothesis, fixed direction, research family, required columns, signal/decision time, next-bar execution rule, holding rule, exit rule, and missing-data policy.
5. Validate causal declarations: `available_time <= decision_time`; closed-bar signal generation; next continuous bar open execution. Static validation may mark a candidate `BLOCKED` when source delays cannot yet be proven.
6. Deduplicate identical normalized expression trees and flag semantic duplicates, inverse-direction wrappers, period-only wrappers, and forbidden-factor overlap.
7. Preserve rejected and deferred proposals with explicit reason codes. It never silently removes an audited candidate.
8. Write canonical UTF-8 artifacts with sorted keys, stable candidate ordering, SHA-256 identity, exclusive run directories, and no overwrite.

The engine does not load market data, calculate returns, calculate IC, optimize parameters, rank candidates by performance, or write strategy code.

## Deduplication and forbidden-factor policy

Three levels of checks are required:

| Level | Check | Outcome |
|---|---|---|
| Structural | normalized expression hash | duplicate rejected |
| Protocol | same input, direction inversion, or period-only wrapper | deferred or rejected with explicit reason |
| Historical | overlap with a forbidden factor's formula, input channel, or economic mechanism | deferred until independent mechanism is documented; reject when overlap is confirmed |

The forbidden archive includes `relative_funding_pressure@1.0.0` and `taker_orderflow_imbalance@1.0.0`. A proposal may not avoid this check by renaming itself, changing a bucket, changing a horizon, changing a sign, or filtering inconvenient observations.

## Aily skill package

The deliverable is a portable skill folder intended for later installation into the Feishu Aily skill library. It contains:

```text
SKILL.md
prompts/supervisor.md
prompts/family_worker.md
schemas/factor_proposal.yaml
configs/audit_rules.yaml
configs/stop_conditions.yaml
README.md
```

`SKILL.md` defines the strict research-only scope and forbids lifecycle promotion, data downloads, external trading access, automatic main-branch merge, and unstructured candidate acceptance.

The supervisor dispatches at most five family tasks per round. Workers return only schema-compliant proposals. The supervisor invokes the local engine, records its verdicts, and ends the round when the configured cap, duplicate threshold, no-new-independent-hypothesis threshold, or configured round limit is reached.

## Artifacts and status semantics

Every factory run writes a new run directory and the following artifacts:

- `candidate_registry.json`: all raw, kept, deferred, and rejected proposals with stable IDs and reason codes.
- `candidate_summary.md`: readable family and status summary.
- `audit_report.md`: structural, causal, economic, data, and security/static-boundary results.
- `deduplication_report.md`: duplicate pairs, comparison basis, and disposition.
- `decision_queue.md`: the limited human/research review queue; it contains no performance claim.
- `run_manifest.json`: input configuration hash, code hash, run identity, output hashes, cap, mode, and boundary assertions.

Allowed disposition values are `KEPT`, `DEFERRED`, and `REJECTED`; all retained proposals remain `proposal_only`. `BLOCKED` is a validation finding recorded in audit fields, not a lifecycle transition.

## Stop conditions

The factory must stop rather than endlessly generate candidates when any configured condition is met:

- maximum raw proposal count;
- maximum KEPT proposal count;
- maximum review-queue size;
- configured round count;
- a full round produces no new independent hypothesis;
- data prerequisites make an entire family blocked.

The decision queue is capped at five candidates. It is an ordering aid, not a recommendation or approval.

## Testing and verification

Tests will cover:

- deterministic output, ordering, and hashes for fixed inputs;
- global hard caps regardless of configuration values;
- proposal-schema required fields and illegal lifecycle labels;
- rejection of labels, future references, unknown columns, invalid windows, and missing execution rules;
- static causality outcomes for closed-bar/next-open timing and unavailable auxiliary data;
- structural duplicate, inversion wrapper, period wrapper, and forbidden-factor overlap handling;
- append-only artifact paths and stable canonical JSON;
- Aily schema fixtures accepted by the local engine and malformed worker output rejected;
- no FactorRegistry writes, no data reads, no network calls, and no lifecycle transitions.

The implementation will run focused pytest, Ruff, formatting check, mypy, and `git diff --check`. It will not run Development as part of the factory task.

## Acceptance criteria

The work is complete when a Feishu Aily operator can install the portable skill package, submit a controlled round of structured proposals, invoke the local engine, and obtain deterministic, append-only `proposal_only` artifacts with clear rejection, deduplication, and stop-condition evidence.
