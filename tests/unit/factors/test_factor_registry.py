from pathlib import Path

import pytest

from bian_quant.factors.registry import FactorRegistry
from bian_quant.factors.spec import FactorSpec, FactorState


def sample_spec() -> FactorSpec:
    return FactorSpec(
        factor_id="price.momentum",
        version="1.0.0",
        formula="close / close.shift(24) - 1",
        direction="positive",
        hypothesis="persistent price movement may continue over the next horizon",
        required_columns=["close"],
        horizon="4h",
        missing_policy="preserve",
        winsor_limits=(0.01, 0.99),
        valid_regimes=["all"],
        failure_conditions=["cost-adjusted OOS IC lower bound <= 0"],
        parent_factors=[],
    )


def test_register_and_retrieve_spec(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)

    spec = registry.get("price.momentum", "1.0.0")
    assert spec.factor_id == "price.momentum"
    assert spec.version == "1.0.0"


def test_initial_state_is_researching(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)

    assert registry.state("price.momentum", "1.0.0") == FactorState.RESEARCHING


def test_legal_transition(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)
    registry.transition("price.momentum", "1.0.0", FactorState.OBSERVED, evidence_run_id="run-1")
    assert registry.state("price.momentum", "1.0.0") == FactorState.OBSERVED


def test_illegal_transition_raises(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)

    with pytest.raises(ValueError, match="illegal"):
        registry.transition(
            "price.momentum", "1.0.0", FactorState.APPROVED, evidence_run_id="run-1"
        )


def test_transition_requires_evidence_run_id(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)

    with pytest.raises(ValueError, match="evidence_run_id"):
        registry.transition("price.momentum", "1.0.0", FactorState.OBSERVED)


def test_retired_factor_needs_explicit_restart_evidence(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)
    registry.transition("price.momentum", "1.0.0", FactorState.RETIRED, evidence_run_id="run-1")

    with pytest.raises(ValueError, match="restart evidence"):
        registry.transition("price.momentum", "1.0.0", FactorState.RESEARCHING)


def test_retired_factor_can_restart_with_evidence(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)
    registry.transition("price.momentum", "1.0.0", FactorState.RETIRED, evidence_run_id="run-1")
    registry.transition(
        "price.momentum",
        "1.0.0",
        FactorState.RESEARCHING,
        evidence_run_id="run-2",
        restart_reason="new data available",
        restart_evidence_run_id="run-2",
    )
    assert registry.state("price.momentum", "1.0.0") == FactorState.RESEARCHING


def test_spec_is_immutable(tmp_path: Path) -> None:
    spec = sample_spec()
    with pytest.raises((TypeError, ValueError, AttributeError)):
        spec.factor_id = "other"  # type: ignore[misc]


def test_duplicate_registration_raises(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)

    with pytest.raises(ValueError, match="already registered"):
        registry.register(sample_spec(), code_sha="b" * 40)


def test_transition_history_is_append_only(tmp_path: Path) -> None:
    registry = FactorRegistry(tmp_path / "registry.sqlite")
    registry.register(sample_spec(), code_sha="a" * 40)
    registry.transition("price.momentum", "1.0.0", FactorState.OBSERVED, evidence_run_id="run-1")
    registry.transition("price.momentum", "1.0.0", FactorState.CANDIDATE, evidence_run_id="run-2")

    history = registry.history("price.momentum", "1.0.0")
    assert len(history) == 3  # initial registration + 2 transitions
    assert history[0]["to_state"] == "researching"
    assert history[1]["to_state"] == "observed"
    assert history[2]["to_state"] == "candidate"


def test_invalid_winsor_limits_are_rejected() -> None:
    payload = sample_spec().model_dump()
    payload["winsor_limits"] = (0.9, 0.1)
    with pytest.raises(ValueError, match="winsor_limits"):
        FactorSpec.model_validate(payload)


def test_spec_defaults_family_and_universe_to_none() -> None:
    spec = sample_spec()
    assert spec.research_family is None
    assert spec.universe_id is None


def test_spec_keeps_family_and_universe_metadata() -> None:
    spec = sample_spec().model_copy(
        update={"research_family": "microstructure_orderflow", "universe_id": "popular-usdm-v1"}
    )
    assert spec.research_family == "microstructure_orderflow"
    assert spec.universe_id == "popular-usdm-v1"


def test_spec_family_and_universe_are_immutable() -> None:
    spec = sample_spec().model_copy(update={"research_family": "microstructure_orderflow"})
    with pytest.raises((TypeError, ValueError, AttributeError)):
        spec.research_family = "other"  # type: ignore[misc]
