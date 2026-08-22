# Factor Proposal Preregistration and Diversity Design

## Goal

Extend the proposal-only factor factory so each audited `PASS` proposal has a
machine-validatable preregistration record before any later Development-only
research may begin. Improve first-round candidate diversity by preventing one
economic mechanism from consuming a family quota through simple window scans.

## Scope and boundary

This change remains entirely inside proposal-only tooling. It does not read
market data, calculate Alpha, IC, returns, or costs, write a FactorRegistry
record, create a FactorSpec, or access Development, Holdout, Paper, Live,
exchange, or account systems.

The output is a proposed research contract, not an approval or lifecycle
transition. A human must still decide whether a preregistered proposal may
enter a separate Development workflow.

## Architecture

```text
bounded proposal generation
  -> static audit
  -> diversity selection
  -> one preregistration YAML per PASS proposal
  -> decision queue with preregistration references
  -> human decision
  -> separate Development workflow
```

Each factory run creates an append-only `preregistration/` directory beneath
its exclusive run directory. A filename is derived from the proposal identity
hash; no preregistration artifact is overwritten.

## Preregistration contract

Every record must contain the immutable proposal identity and all of these
research declarations:

```yaml
proposal_identity_sha256:
factor_id:
factor_version:
research_family:
economic_hypothesis:
formula:
direction:
signal_time:
decision_time:
entry_price: next_continuous_bar_open
holding_bars: 4
missing_policy: preserve_missing_and_exclude
q_nominal: 0.2
cost_assumption:
development_sample_definition:
evaluation_horizon:
falsification_criteria:
status: preregistration_only
```

`cost_assumption`, `development_sample_definition`, `evaluation_horizon`, and
`falsification_criteria` must be explicit non-empty declarations. Their values
are research plans, not empirical measurements. The writer must reject absent
or lifecycle-bearing values and must not generate a preregistration for a
non-PASS proposal.

## Diversity policy

The selection layer keeps the existing total cap and per-family cap, then adds
two deterministic constraints:

1. A mechanism key is derived from the expression operator and required input
   channel set. Only one proposal per `(research_family, mechanism_key)` may
   enter the first-round decision queue.
2. For a repeated mechanism at several windows, the first deterministic window
   is retained and later windows remain visible in the candidate registry but
   receive a documented diversity exclusion rather than silently disappearing.

This policy applies to decision selection and preregistration generation, not
to raw candidate generation. It preserves the audit trail while ensuring the
first review set represents distinct hypotheses.

## Artifacts and auditability

The run manifest records preregistration artifact hashes and selection counts.
The decision queue includes each selected proposal's preregistration path and
any diversity exclusion reason. The candidate registry preserves all generated
proposals and static-audit findings.

All additions retain canonical UTF-8 serialization, stable ordering, SHA-256
hashing, atomic writes, and exclusive run-directory semantics.

## Validation

Tests must prove that:

- only `PASS` proposals receive preregistration files;
- every file includes the required declarations and immutable proposal identity;
- lifecycle, data, performance, and trading fields are rejected;
- repeated window variants do not fill a first-round queue;
- excluded variants remain in the registry with a reason;
- generated artifact paths and hashes are deterministic and append-only;
- the runner preserves all existing no-data, no-network, no-Holdout/Paper/Live
  boundary assertions.

## Non-goals

This work does not choose research winners, define empirical thresholds, run
Development evaluation, or promote any factor. Such decisions stay in the
separate research workflow after human approval.
