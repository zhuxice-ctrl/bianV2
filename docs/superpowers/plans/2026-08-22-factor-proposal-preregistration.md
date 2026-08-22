# Factor Proposal Preregistration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add deterministic first-round diversity selection and one validated preregistration record for every selected `PASS` factor proposal, without leaving proposal-only mode.

**Architecture:** Keep proposal generation and static audit unchanged. Add a pure selection service that labels one representative per family/mechanism as selected and preserves excluded variants with a reason. Add a preregistration protocol and let the append-only artifact writer emit selected records under a `preregistration/` subdirectory, reference them from the decision queue, and hash them in the manifest.

**Tech Stack:** Python 3.12, Pydantic v2, PyYAML, canonical JSON/YAML, SHA-256, pytest, Ruff, mypy.

---

## File map

```text
src/bian_quant/factors/proposal_selection.py         # Pure diversity selection and reason codes
src/bian_quant/factors/preregistration.py            # Immutable preregistration protocol and YAML serialization
src/bian_quant/factors/proposal_artifacts.py          # Append-only integration and manifest/queue rendering
scripts/run_factor_factory.py                          # Passes selected audited records into artifacts
configs/factors/proposal_factory.yaml                 # Explicit preregistration defaults
skills/quant-factor-research-factory/schemas/preregistration.yaml
skills/quant-factor-research-factory/SKILL.md
skills/quant-factor-research-factory/prompts/family_worker.md
tests/unit/factors/test_proposal_selection.py
tests/unit/factors/test_preregistration.py
tests/unit/factors/test_proposal_artifacts.py
tests/integration/factors/test_factor_factory.py
tests/integration/factors/test_aily_skill_package.py
```

### Task 1: Define deterministic diversity selection

**Files:**

- Create: `src/bian_quant/factors/proposal_selection.py`
- Create: `tests/unit/factors/test_proposal_selection.py`

- [ ] **Step 1: Write failing selection tests**

```python
from bian_quant.factors.proposal_audit import ProposalAuditResult
from bian_quant.factors.proposal_selection import select_first_round


def test_repeated_window_variants_keep_only_first_mechanism() -> None:
    first, later = volume_mean_proposals(window_values=(6, 12))
    result = select_first_round(
        [(first, ProposalAuditResult(verdict="PASS")),
         (later, ProposalAuditResult(verdict="PASS"))],
        max_per_family=4,
    )
    assert [item.proposal.factor_id for item in result.selected] == [first.factor_id]
    assert result.exclusions[later.identity_sha256] == "DIVERSITY_MECHANISM_DUPLICATE"


def test_non_pass_proposals_are_not_selected() -> None:
    proposal = valid_proposal()
    result = select_first_round(
        [(proposal, ProposalAuditResult(verdict="BLOCKED"))], max_per_family=4
    )
    assert result.selected == ()
    assert result.exclusions[proposal.identity_sha256] == "AUDIT_NOT_PASS"
```

- [ ] **Step 2: Run the test and verify collection fails**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposal_selection.py -q`

Expected: collection fails because `proposal_selection` does not exist.

- [ ] **Step 3: Implement the selection protocol**

Create frozen models `SelectionRecord` and `DiversitySelection`. Implement:

```python
def mechanism_key(proposal: FactorProposal) -> str:
    operator = proposal.formula.split("(", maxsplit=1)[0].strip().lower()
    channels = ",".join(sorted(
        column for column in proposal.required_columns
        if column not in {"open_time", "available_time", "open"}
    ))
    return f"{operator}:{channels}"


def select_first_round(
    records: Sequence[tuple[FactorProposal, ProposalAuditResult | None]],
    *,
    max_per_family: int,
) -> DiversitySelection:
    ...
```

Process records in the existing stable proposal sort order. Give all non-PASS
records `AUDIT_NOT_PASS`; give later equal `(research_family, mechanism_key)`
records `DIVERSITY_MECHANISM_DUPLICATE`; and give candidates beyond a family
cap `DIVERSITY_FAMILY_CAP`. Never drop records from the returned accounting.
Reject non-positive caps.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposal_selection.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the selection service**

```powershell
git add src/bian_quant/factors/proposal_selection.py tests/unit/factors/test_proposal_selection.py
git commit -m "feat(factors): select diverse first-round proposals"
```

### Task 2: Add the preregistration protocol and writer

**Files:**

- Create: `src/bian_quant/factors/preregistration.py`
- Create: `tests/unit/factors/test_preregistration.py`

- [ ] **Step 1: Write failing preregistration tests**

```python
from pydantic import ValidationError
import pytest
from bian_quant.factors.preregistration import ProposalPreregistration


def test_preregistration_has_fixed_research_defaults() -> None:
    record = ProposalPreregistration.from_proposal(valid_proposal())
    assert record.status == "preregistration_only"
    assert record.q_nominal == 0.2
    assert record.holding_bars == 4
    assert record.entry_price == "next_continuous_bar_open"


def test_blank_falsification_criterion_is_rejected() -> None:
    with pytest.raises(ValidationError):
        ProposalPreregistration.from_proposal(valid_proposal()).model_copy(
            update={"falsification_criteria": ""}
        ).validated()
```

- [ ] **Step 2: Run the test and verify collection fails**

Run: `uv run pytest -p no:cov tests/unit/factors/test_preregistration.py -q`

Expected: collection fails because `ProposalPreregistration` does not exist.

- [ ] **Step 3: Implement immutable preregistration records**

Implement frozen `ProposalPreregistration(BaseModel)` with `extra="forbid"`.
It copies proposal identity and human-readable protocol fields, requires
non-blank `cost_assumption`, `development_sample_definition`,
`evaluation_horizon`, and `falsification_criteria`, and restricts
`status: Literal["preregistration_only"]`.

Provide:

```python
@classmethod
def from_proposal(
    cls,
    proposal: FactorProposal,
    *,
    q_nominal: float = 0.2,
    holding_bars: int = 4,
    cost_assumption: str = "declare_before_development",
    development_sample_definition: str = "declare_before_development",
    evaluation_horizon: str = "4_bars",
    falsification_criteria: str = "declare_before_development",
) -> "ProposalPreregistration":
    ...

def canonical_yaml_bytes(record: ProposalPreregistration) -> bytes:
    ...
```

Validate `0 < q_nominal <= 1`, positive `holding_bars`, closed-bar timing,
next-continuous-bar entry, and the existing missing-data policy. YAML must be
UTF-8, sorted, and use no aliases.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest -p no:cov tests/unit/factors/test_preregistration.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the preregistration protocol**

```powershell
git add src/bian_quant/factors/preregistration.py tests/unit/factors/test_preregistration.py
git commit -m "feat(factors): add proposal preregistration protocol"
```

### Task 3: Integrate selections and preregistrations into run artifacts

**Files:**

- Modify: `src/bian_quant/factors/proposal_artifacts.py`
- Modify: `scripts/run_factor_factory.py`
- Modify: `configs/factors/proposal_factory.yaml`
- Modify: `tests/unit/factors/test_proposal_artifacts.py`
- Modify: `tests/integration/factors/test_factor_factory.py`

- [ ] **Step 1: Add failing integration tests**

```python
def test_run_writes_only_passed_preregistrations_and_manifest_hashes(tmp_path: Path) -> None:
    result = run_factory(CONFIG, tmp_path, code_sha="abc")
    preregistration_dir = result.run_directory / "preregistration"
    preregistration_paths = sorted(preregistration_dir.glob("*.yaml"))
    manifest = json.loads(result.artifact_paths["run_manifest.json"].read_text())
    assert preregistration_paths
    assert len(preregistration_paths) == manifest["selection"]["selected_count"]
    assert manifest["preregistrations"]
    assert all(item["sha256"] for item in manifest["preregistrations"].values())
```

Also add an artifact-unit test with two same-mechanism `PASS` records and one
`BLOCKED` record. Assert one YAML is written; registry selection data includes
all three identities; and the decision queue has the preregistration relative
path only for the selected `PASS` record.

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest -p no:cov tests/unit/factors/test_proposal_artifacts.py tests/integration/factors/test_factor_factory.py -q`

Expected: new assertions fail because no preregistration directory or manifest
selection data exists.

- [ ] **Step 3: Extend artifact writing without changing boundary flags**

Add `max_proposals_per_family` and preregistration-default parameters to
`write_proposal_run`. After audit normalization and stable ordering, call
`select_first_round`. For each selected record call
`ProposalPreregistration.from_proposal`, then atomically write:

```text
<run_directory>/preregistration/<proposal_identity_sha256>.yaml
```

Add `selection_reason` and `preregistration_path` to each candidate-registry
entry. Change `decision_queue.md` columns to include `Selection` and
`Preregistration`, showing only selected PASS entries. Keep non-selected
records in the registry/audit report.

Add manifest keys:

```json
{
  "selection": {"selected_count": 0, "excluded_count": 0},
  "preregistrations": {
    "<identity>": {"path": "preregistration/<identity>.yaml", "bytes": 0, "sha256": "..."}
  }
}
```

The six existing top-level artifacts remain unchanged in name. The
preregistration directory is an additional append-only artifact group.

- [ ] **Step 4: Wire runner configuration**

Add this configuration block:

```yaml
preregistration:
  q_nominal: 0.2
  holding_bars: 4
  cost_assumption: declare_before_development
  development_sample_definition: declare_before_development
  evaluation_horizon: 4_bars
  falsification_criteria: declare_before_development
```

In `run_factory`, parse the mapping as a string-keyed mapping and pass its
values plus `max_proposals_per_family` to the writer. Reject non-mapping
configuration with `ValueError`. Do not import any data, registry, trading,
or lifecycle module.

- [ ] **Step 5: Run focused gates**

Run:

```powershell
uv run pytest -p no:cov tests/unit/factors/test_proposal_selection.py tests/unit/factors/test_preregistration.py tests/unit/factors/test_proposal_artifacts.py tests/integration/factors/test_factor_factory.py -q
uv run ruff check src/bian_quant/factors/proposal_selection.py src/bian_quant/factors/preregistration.py src/bian_quant/factors/proposal_artifacts.py scripts/run_factor_factory.py tests/unit/factors tests/integration/factors
uv run ruff format --check src/bian_quant/factors/proposal_selection.py src/bian_quant/factors/preregistration.py src/bian_quant/factors/proposal_artifacts.py scripts/run_factor_factory.py tests/unit/factors tests/integration/factors
uv run mypy src/bian_quant/factors scripts/run_factor_factory.py
git diff --check
```

Expected: all commands exit 0.

- [ ] **Step 6: Commit artifact integration**

```powershell
git add src/bian_quant/factors/proposal_artifacts.py scripts/run_factor_factory.py configs/factors/proposal_factory.yaml tests/unit/factors/test_proposal_artifacts.py tests/integration/factors/test_factor_factory.py
git commit -m "feat(factors): write diverse proposal preregistrations"
```

### Task 4: Align the Aily package and verify a local dry run

**Files:**

- Create: `skills/quant-factor-research-factory/schemas/preregistration.yaml`
- Modify: `skills/quant-factor-research-factory/SKILL.md`
- Modify: `skills/quant-factor-research-factory/prompts/family_worker.md`
- Modify: `tests/integration/factors/test_aily_skill_package.py`
- Create: `docs/evidence/2026-08-22-factor-preregistration-dry-run.md`

- [ ] **Step 1: Add failing skill-package assertions**

```python
def test_skill_package_includes_preregistration_contract() -> None:
    preregistration = yaml.safe_load(PREREGISTRATION_SCHEMA.read_text(encoding="utf-8"))
    assert preregistration["required"] == [
        "proposal_identity_sha256", "q_nominal", "holding_bars",
        "cost_assumption", "development_sample_definition",
        "evaluation_horizon", "falsification_criteria", "status",
    ]
    assert "preregistration_only" in SKILL_PATH.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `uv run pytest -p no:cov tests/integration/factors/test_aily_skill_package.py -q`

Expected: missing schema or wording assertion failure.

- [ ] **Step 3: Add Aily contract language**

Define the same required preregistration fields and fixed values in the new
schema. State in `SKILL.md` and `family_worker.md` that an Aily worker may
propose text declarations but may not approve a preregistration, alter its
fixed fields, start Development, or access data/Holdout/Paper/Live/trading.

- [ ] **Step 4: Run all factory tests and local dry run**

Run:

```powershell
uv run pytest -p no:cov tests/unit/factors/test_proposals.py tests/unit/factors/test_proposal_audit.py tests/unit/factors/test_generator.py tests/unit/factors/test_proposal_selection.py tests/unit/factors/test_preregistration.py tests/unit/factors/test_proposal_artifacts.py tests/integration/factors/test_factor_factory.py tests/integration/factors/test_aily_skill_package.py -q
uv run python scripts/run_factor_factory.py --config configs/factors/proposal_factory.yaml --output-root var/artifacts/factor-preregistration-dry-run --code-sha <current_git_sha>
```

Read `run_manifest.json`, the registry, queue, and preregistration directory.
Write the exact run directory, selected/excluded counts, artifact hashes, and
boundary assertions to the evidence note. State explicitly that this validates
tooling only and is not Development, Alpha, IC, return, Holdout, Paper, or
Live evidence.

- [ ] **Step 5: Commit skill and evidence updates**

```powershell
git add skills/quant-factor-research-factory tests/integration/factors/test_aily_skill_package.py docs/evidence/2026-08-22-factor-preregistration-dry-run.md
git commit -m "feat(aily): document proposal preregistration contract"
```

## Plan self-review

- Task 1 covers deterministic mechanism and family diversity while retaining every generated candidate in accounting.
- Task 2 defines a strict, immutable preregistration record with all fixed and required declarations.
- Task 3 writes selected preregistrations, selection metadata, queue links, and manifest hashes without changing proposal-only boundaries.
- Task 4 aligns Aily documentation and verifies the full local, no-data tooling path.
- The plan has no lifecycle promotion, data acquisition, empirical evaluation, or unbounded external action.
