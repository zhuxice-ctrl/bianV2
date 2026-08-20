# Quant Factor Research Factory

This package defines an Aily / Feishu skill for proposal-only factor research. It is
strictly research-only: every emitted record must remain `proposal_only`, must never
read market data directly, must never touch Holdout, Candidate, Paper, or Live
systems, and must allow no external trading.

## Scope

- Research-only ideation and proposal normalization for factor hypotheses.
- Dispatch proposals through five family workers:
  - `price_dynamics`
  - `volume_liquidity`
  - `price_volume`
  - `derivatives_stack`
  - `cross_market_structure`
- Emit only structured proposal payloads that satisfy
  `schemas/factor_proposal.yaml`.
- Run the local Python proposal factory through:
  `uv run python scripts/run_factor_factory.py --config configs/factors/proposal_factory.yaml --output-root <artifact_root> --code-sha <git_sha>`

## Hard Boundaries

- Every proposal stays in `proposal_only`.
- No Holdout access.
- No Paper promotion or paper-trading orchestration.
- No Live promotion or live-trading orchestration.
- No candidate registration or approval actions.
- No external trading, exchange, account, credential, or raw data path access.

## Supervisor Contract

- Use `prompts/supervisor.md` to enforce structured-only responses.
- Reject any output that omits required protocol fields.
- Reject autonomous promotion, approval, registry writes, or execution requests.
- Stop on boundary violations and return the configured reason code.

## Worker Contract

- Use `prompts/family_worker.md` for each dispatched family worker.
- Emit exactly one economic hypothesis per proposal.
- Include every field required by `FactorProposal`.
- Keep field names and enum values aligned with the Python protocol schema.

## Reason Codes

- `STOP_HARD_CAP_REACHED`
- `STOP_UNSTRUCTURED_OUTPUT`
- `STOP_MISSING_REQUIRED_FIELD`
- `STOP_INVALID_ENUM`
- `STOP_DUPLICATE_FACTOR_ID`
- `STOP_AUTONOMOUS_PROMOTION_ATTEMPT`
- `STOP_BOUNDARY_VIOLATION`

## Stop Conditions

Read `configs/stop_conditions.yaml` before execution. The skill must stop
immediately when a hard cap, protocol mismatch, duplication issue, or boundary
breach is detected.
