# Quant Factor Research Factory Aily Skill

This directory packages the Feishu Aily skill assets for the proposal-only factor
research factory.

Contents:

- `SKILL.md`: high-level operating contract and boundaries.
- `prompts/supervisor.md`: structured-output supervisor instructions.
- `prompts/family_worker.md`: per-family worker instructions.
- `schemas/factor_proposal.yaml`: YAML schema aligned to `FactorProposal`.
- `configs/audit_rules.yaml`: family dispatch, prompt references, and validation rules.
- `configs/stop_conditions.yaml`: hard caps and stop reason definitions.

The package is intentionally research-only and does not contain credentials,
runtime secrets, or raw data paths.
