# Quant Factor Research Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the bounded factor generator into a deterministic proposal-only research factory and package the Aily orchestration protocol for direct skill-library installation.

**Architecture:** Keep pure expression generation in `bian_quant.factors`, add an immutable `FactorProposal` protocol plus static audit and artifact services, and expose one local runner that Aily can invoke. Package Aily prompts and schemas separately under `skills/quant-factor-research-factory`; neither layer may write formal FactorRegistry state or perform empirical evaluation.

**Tech Stack:** Python 3.12, Pydantic v2, pandas/NumPy expression primitives, PyYAML, canonical JSON, SHA-256, pytest, Ruff, mypy, Markdown/YAML skill assets.

---

## File map

Create or modify only the following task-owned files:

```text
src/bian_quant/factors/proposals.py
src/bian_quant/factors/proposal_audit.py
src/bian_quant/factors/proposal_artifacts.py
src/bian_quant/factors/generator.py
configs/factors/proposal_factory.yaml
configs/factors/forbidden_factors.yaml
scripts/run_factor_factory.py
tests/unit/factors/test_proposals.py
tests/unit/factors/test_proposal_audit.py
tests/unit/factors/test_proposal_artifacts.py
tests/integration/factors/test_factor_factory.py
skills/quant-factor-research-factory/SKILL.md
skills/quant-factor-research-factory/README.md
skills/quant-factor-research-factory/prompts/supervisor.md
skills/quant-factor-research-factory/prompts/family_worker.md
skills/quant-factor-research-factory/schemas/factor_proposal.yaml
skills/quant-factor-research-factory/configs/audit_rules.yaml
skills/quant-factor-research-factory/configs/stop_conditions.yaml
```

Existing user-owned untracked files remain untouched.

### Task 1: Add the proposal-only protocol

**Files:**

- Create: `src/bian_quant/factors/proposals.py`
- Create: `tests/unit/factors/test_proposals.py`

- [ ] **Step 1: Write failing protocol tests**

```python
from pydantic import ValidationError
import pytest
from bian_quant.factors.proposals import FactorProposal


def proposal_payload() -> dict[str, object]:
    return {
        "factor_id": "volume_surge_breakout",
        "factor_version": "1.0.0",
        "research_family": "volume_liquidity",
        "economic_hypothesis": "Abnormal volume confirms a price breakout and increases continuation probability.",
        "formula": "zscore(volume, 24)",
        "direction": "positive",
        "required_columns": ["open_time", "close", "volume", "available_time"],
        "signal_time": "close_time",
        "decision_time": "close_time",
        "entry_price": "next_continuous_bar_open",
        "holding_rule": "hold_for_4_bars",
        "exit_rule": "time_exit_or_invalid_execution_bar",
        "missing_policy": "preserve_missing_and_exclude",
        "parent_factors": [],
        "source_type": "registered_template",
        "proposal_status": "proposal_only",
    }


def test_valid_proposal_is_immutable() -> None:
    proposal = FactorProposal.model_validate(proposal_payload())
    assert proposal.proposal_status == "proposal_only"
    with pytest.raises(ValidationError):
        proposal.factor_id = "changed"  # type: ignore[misc]


def test_promotion_state_is_rejected() -> None:
    payload = proposal_payload()
    payload["proposal_status"] = "candidate"
    with pytest.raises(ValidationError):
        FactorProposal.model_validate(payload)


def test_required_columns_and_execution_fields_are_non_empty() -> None:
    payload = proposal_payload()
    payload["required_columns"] = []
    with pytest.raises(ValidationError):
        FactorProposal.model_validate(payload)


def test_canonical_identity_is_stable() -> None:
    first = FactorProposal.model_validate(proposal_payload())
    second = FactorProposal.model_validate(dict(reversed(list(proposal_payload().items()))))
    assert first.identity_sha256 == second.identity_sha256
```

- [ ] **Step 2: Run the focused test file and verify it fails**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposals.py -q`

Expected: collection fails because `FactorProposal` is not defined.

- [ ] **Step 3: Implement the immutable model**

Implement `FactorProposal(BaseModel)` with `ConfigDict(frozen=True, extra="forbid")`, literal `proposal_status="proposal_only"`, non-empty string/list validators, direction literal `positive|negative|two_sided`, and a read-only `identity_sha256` property hashing `model_dump(mode="json")` with sorted keys and compact separators. Reject lifecycle values other than `proposal_only` before any artifact writer is called.

- [ ] **Step 4: Run the focused tests**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposals.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the protocol**

```powershell
git add src/bian_quant/factors/proposals.py tests/unit/factors/test_proposals.py
git commit -m "feat(factors): add proposal-only factor protocol"
```

### Task 2: Add static causal and completeness audits

**Files:**

- Create: `src/bian_quant/factors/proposal_audit.py`
- Create: `configs/factors/forbidden_factors.yaml`
- Create: `tests/unit/factors/test_proposal_audit.py`

- [ ] **Step 1: Write failing audit tests**

```python
from bian_quant.factors.proposal_audit import audit_proposal
from tests.unit.factors.test_proposals import proposal_payload


def test_next_open_execution_passes_closed_bar_timing() -> None:
    result = audit_proposal(proposal_payload(), available_time_definition="close_time")
    assert result.verdict == "PASS"
    assert result.reason_codes == ()


def test_missing_auxiliary_delay_is_blocked() -> None:
    payload = proposal_payload()
    payload["required_columns"] = ["open_time", "funding_rate", "funding_time", "available_time"]
    result = audit_proposal(payload, available_time_definition=None)
    assert result.verdict == "BLOCKED"
    assert "MISSING_AVAILABLE_TIME_DEFINITION" in result.reason_codes


def test_missing_exit_rule_is_rejected() -> None:
    payload = proposal_payload()
    payload["exit_rule"] = ""
    result = audit_proposal(payload, available_time_definition="close_time")
    assert result.verdict == "REJECTED"
    assert "MISSING_EXIT_RULE" in result.reason_codes


def test_forbidden_factor_overlap_is_deferred() -> None:
    payload = proposal_payload()
    payload["factor_id"] = "funding_zscore"
    payload["research_family"] = "funding_dynamics"
    payload["formula"] = "rolling_zscore(funding_rate, 24)"
    result = audit_proposal(payload, available_time_definition="funding_available_time")
    assert result.verdict == "DEFERRED"
    assert "FORBIDDEN_FACTOR_OVERLAP" in result.reason_codes
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposal_audit.py -q`

Expected: collection fails because `audit_proposal` and the audit result type are absent.

- [ ] **Step 3: Define reason codes and audit result**

Implement frozen `ProposalAuditResult(verdict, reason_codes, checks, warnings)` where verdict is `PASS|BLOCKED|DEFERRED|REJECTED`. Implement checks for required execution fields, `available_time <= decision_time`, next-continuous-bar-open wording, auxiliary delay declarations, known forbidden-factor entries, and absence of empirical metrics in proposal payloads. Load `forbidden_factors.yaml` using a path argument; do not read market data.

- [ ] **Step 4: Add the forbidden-factor configuration**

Write entries for `relative_funding_pressure@1.0.0` and `taker_orderflow_imbalance@1.0.0`, including formula summary, required input channels, family, and prohibited wrapper patterns. Keep raw data, credentials, and private URIs out of the file.

- [ ] **Step 5: Run the focused tests**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposal_audit.py -q`

Expected: PASS.

- [ ] **Step 6: Commit static auditing**

```powershell
git add src/bian_quant/factors/proposal_audit.py configs/factors/forbidden_factors.yaml tests/unit/factors/test_proposal_audit.py
git commit -m "feat(factors): add proposal causal and overlap audits"
```

### Task 3: Integrate proposal normalization into bounded generation

**Files:**

- Modify: `src/bian_quant/factors/generator.py`
- Create: `configs/factors/proposal_factory.yaml`
- Modify: `tests/unit/factors/test_generator.py`

- [ ] **Step 1: Add failing generator integration tests**

```python
from bian_quant.factors.generator import generate_proposals


def test_generation_returns_proposal_only_records() -> None:
    proposals = generate_proposals("configs/factors/proposal_factory.yaml", code_sha="abc")
    assert proposals
    assert all(item.proposal_status == "proposal_only" for item in proposals)
    assert len(proposals) <= 20


def test_generator_does_not_call_formal_registry(monkeypatch) -> None:
    monkeypatch.setattr("bian_quant.factors.registry.FactorRegistry", lambda *_: (_ for _ in ()).throw(AssertionError()))
    generate_proposals("configs/factors/proposal_factory.yaml", code_sha="abc")
```

- [ ] **Step 2: Run the focused generator tests and verify the new tests fail**

Run: `uv run pytest -p no:cov tests/unit/factors/test_generator.py -q`

Expected: the new import or integration assertions fail while existing expression tests remain the baseline.

- [ ] **Step 3: Add the versioned factory configuration**

Configure `seed: 7`, `max_candidates: 20`, `max_review_queue: 5`, `max_rounds: 4`, windows `[6, 12, 24, 48, 168]`, allowed columns `close/open/high/low/volume/funding_rate/open_interest`, and only registered unary/binary operations already supported by `primitives.py`. Include `mode: proposal_only` and the forbidden archive path.

- [ ] **Step 4: Implement `generate_proposals` without changing `generate_candidates` behavior**

Keep the current expression-level API and tests unchanged. Add a wrapper that converts each deterministic `CandidateFactor` to a complete `FactorProposal`, supplies template metadata, runs structural validation, assigns stable generation rank, and never calls `FactorRegistry` or any data adapter. Return proposals in deterministic order under the hard cap.

- [ ] **Step 5: Run existing and new generator tests**

Run: `uv run pytest -p no:cov tests/unit/factors/test_generator.py -q`

Expected: PASS with the existing expression tests and the new proposal-only tests.

- [ ] **Step 6: Commit generator integration**

```powershell
git add src/bian_quant/factors/generator.py configs/factors/proposal_factory.yaml tests/unit/factors/test_generator.py
git commit -m "feat(factors): normalize bounded candidates into proposals"
```

### Task 4: Add append-only canonical proposal artifacts

**Files:**

- Create: `src/bian_quant/factors/proposal_artifacts.py`
- Create: `tests/unit/factors/test_proposal_artifacts.py`

- [ ] **Step 1: Write failing artifact tests**

```python
def test_write_run_creates_all_required_artifacts(tmp_path: Path) -> None:
    result = write_proposal_run(tmp_path, proposals=[valid_proposal()], run_id="run-1", code_sha="abc")
    assert set(result.paths) == {
        "candidate_registry.json", "candidate_summary.md", "audit_report.md",
        "deduplication_report.md", "decision_queue.md", "run_manifest.json",
    }


def test_existing_run_directory_is_never_overwritten(tmp_path: Path) -> None:
    write_proposal_run(tmp_path, proposals=[valid_proposal()], run_id="run-1", code_sha="abc")
    with pytest.raises(FileExistsError):
        write_proposal_run(tmp_path, proposals=[valid_proposal()], run_id="run-1", code_sha="abc")
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposal_artifacts.py -q`

Expected: collection fails because the artifact writer is absent.

- [ ] **Step 3: Implement canonical artifact writing**

Implement `write_proposal_run(root, proposals, run_id, code_sha, config_sha256, audits)` using an exclusive run directory, UTF-8 JSON with sorted keys and compact separators, stable list ordering by `(research_family, factor_id, factor_version, identity_sha256)`, SHA-256 for every artifact, and atomic temporary-file replacement within the new directory. Include boundary assertions in `run_manifest.json`: `mode=proposal_only`, `holdout_accessed=false`, `paper_trading=false`, `live_trading=false`, `data_read=false`, and `network_access=false`.

- [ ] **Step 4: Run focused artifact tests**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposal_artifacts.py -q`

Expected: PASS.

- [ ] **Step 5: Commit artifact writing**

```powershell
git add src/bian_quant/factors/proposal_artifacts.py tests/unit/factors/test_proposal_artifacts.py
git commit -m "feat(factors): write append-only proposal artifacts"
```

### Task 5: Add the local factory runner and integration boundary tests

**Files:**

- Create: `scripts/run_factor_factory.py`
- Create: `tests/integration/factors/test_factor_factory.py`

- [ ] **Step 1: Write the integration boundary test**

```python
def test_factory_run_is_proposal_only_and_has_no_registry_or_data_access(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("bian_quant.factors.proposal_artifacts.Path.mkdir", Path.mkdir)
    result = run_factory(config_path=CONFIG, output_root=tmp_path, code_sha="abc")
    assert result.status == "completed"
    assert result.mode == "proposal_only"
    assert result.holdout_accessed is False
    assert not list(tmp_path.glob("**/factor_registry.sqlite"))
```

- [ ] **Step 2: Run the integration test and verify it fails**

Run: `uv run pytest -p no:cov tests/integration/factors/test_factor_factory.py -q`

Expected: collection fails because the runner is absent.

- [ ] **Step 3: Implement the runner entry point**

Expose `run_factory(config_path, output_root, code_sha)` and a CLI accepting `--config`, `--output-root`, and `--code-sha`. The runner loads configuration, calls `generate_proposals`, calls `audit_proposal` for every record, applies deterministic structural deduplication, writes the six artifacts, and exits nonzero only for invalid factory configuration or artifact failure. It must not import data adapters, backtest, paper, Holdout, exchange, or account modules.

- [ ] **Step 4: Run the integration test**

Run: `uv run pytest -p no:cov tests/integration/factors/test_factor_factory.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the runner**

```powershell
git add scripts/run_factor_factory.py tests/integration/factors/test_factor_factory.py
git commit -m "feat(factors): add proposal factory runner"
```

### Task 6: Package the Feishu Aily skill

**Files:**

- Create: `skills/quant-factor-research-factory/SKILL.md`
- Create: `skills/quant-factor-research-factory/README.md`
- Create: `skills/quant-factor-research-factory/prompts/supervisor.md`
- Create: `skills/quant-factor-research-factory/prompts/family_worker.md`
- Create: `skills/quant-factor-research-factory/schemas/factor_proposal.yaml`
- Create: `skills/quant-factor-research-factory/configs/audit_rules.yaml`
- Create: `skills/quant-factor-research-factory/configs/stop_conditions.yaml`

- [ ] **Step 1: Write a fixture validation test**

Add `tests/integration/factors/test_aily_skill_package.py` that loads the YAML schema and configuration files, asserts all referenced prompt files exist, checks that `SKILL.md` contains `proposal_only`, `Holdout`, `Paper`, `Live`, and `no external trading`, and validates a known-good worker payload against the same required field names used by `FactorProposal`.

- [ ] **Step 2: Run the fixture test and verify it fails**

Run: `uv run pytest -p no:cov tests/integration/factors/test_aily_skill_package.py -q`

Expected: collection or file assertions fail because the skill package has not been created.

- [ ] **Step 3: Write the skill files**

`SKILL.md` must define research-only scope, five-family dispatch, structured output, the Python runner invocation, hard caps, explicit reason codes, and the stop conditions. `supervisor.md` must forbid unstructured proposals and autonomous promotion. `family_worker.md` must require one hypothesis per proposal and all protocol fields. YAML files must use the same field names and limits as the Python engine; no credentials or raw data paths may appear.

- [ ] **Step 4: Run the fixture test**

Run: `uv run pytest -p no:cov tests/integration/factors/test_aily_skill_package.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the skill package**

```powershell
git add skills/quant-factor-research-factory tests/integration/factors/test_aily_skill_package.py
git commit -m "feat(aily): package factor research factory skill"
```

### Task 7: Run all task gates and produce a dry-run evidence packet

**Files:**

- Modify: `docs/AILY_EXECUTION_RULES.md` only if a new rule is required by the implementation and the change is additive.
- Create: `docs/evidence/2026-08-19-factor-factory-dry-run.md`

- [ ] **Step 1: Run focused tests**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposals.py tests/unit/factors/test_proposal_audit.py tests/unit/factors/test_generator.py tests/unit/factors/test_proposal_artifacts.py tests/integration/factors/test_factor_factory.py tests/integration/factors/test_aily_skill_package.py -q`

Expected: all selected tests pass; no Development test is invoked.

- [ ] **Step 2: Run static gates**

Run: `uv run ruff check src/bian_quant/factors scripts tests/unit/factors tests/integration/factors`

Expected: exit code 0.

Run: `uv run ruff format --check src/bian_quant/factors scripts tests/unit/factors tests/integration/factors`

Expected: exit code 0.

Run: `uv run mypy src/bian_quant`

Expected: exit code 0, or record the exact pre-existing unrelated failures without claiming a green gate.

Run: `git diff --check`

Expected: no output.

- [ ] **Step 3: Execute a local dry run**

Run: `uv run python scripts/run_factor_factory.py --config configs/factors/proposal_factory.yaml --output-root var/artifacts/factor-factory-dry-run --code-sha bfb2b0b`

Expected: a new run directory containing the six proposal artifacts, `mode=proposal_only`, zero empirical metrics, zero registry writes, and boundary flags showing no data/network/Holdout/Paper/Live access.

- [ ] **Step 4: Write the evidence note**

Record the exact command, code SHA, artifact directory, candidate counts, reason-code counts, artifact SHA-256 values, and any real test failures. Explicitly state that the dry run is a tooling validation and not Alpha, IC, return, or Development evidence.

- [ ] **Step 5: Commit the evidence note**

```powershell
git add docs/evidence/2026-08-19-factor-factory-dry-run.md
git commit -m "docs(research): record factor factory dry run"
```

## Plan self-review

- The design requirements map to Tasks 1–7: protocol, static audit, bounded generation, artifacts, runner, Aily package, and verification.
- No task writes a formal FactorRegistry record, accesses data, calculates performance, or promotes a lifecycle state.
- All new function names are defined before use: `FactorProposal`, `audit_proposal`, `generate_proposals`, `write_proposal_run`, and `run_factory`.
- The plan contains no TODO/TBD placeholders and preserves existing untracked user files.
- The only possible external-facing deliverable is the portable skill package under `skills/quant-factor-research-factory`; it contains no credentials or private data.
