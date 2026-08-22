from __future__ import annotations

import builtins
import hashlib
import importlib.util
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
import yaml

from bian_quant.factors.preregistration import ProposalPreregistration

CONFIG = Path(__file__).resolve().parents[3] / "configs" / "factors" / "proposal_factory.yaml"
RUNNER_PATH = Path(__file__).resolve().parents[3] / "scripts" / "run_factor_factory.py"


def _load_runner_module() -> Any:
    spec = importlib.util.spec_from_file_location("task5_run_factor_factory", RUNNER_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@contextmanager
def _forbidden_import_guard() -> Iterator[None]:
    real_import = builtins.__import__
    blocked_prefixes = (
        "bian_quant.backtest",
        "bian_quant.data",
        "bian_quant.experiments.holdout",
        "bian_quant.experiments.registry",
        "bian_quant.factors.registry",
        "bian_quant.live",
        "bian_quant.paper",
    )
    blocked_tokens = {"account", "exchange", "holdout"}

    def guarded_import(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] | list[str] | None = (),
        level: int = 0,
    ) -> Any:
        names_to_check = {name}
        names_to_check.update(
            f"{name}.{item}" for item in (fromlist or ()) if isinstance(item, str) and item != "*"
        )
        for candidate in names_to_check:
            if any(
                candidate == prefix or candidate.startswith(f"{prefix}.")
                for prefix in blocked_prefixes
            ):
                raise AssertionError(f"forbidden import attempted: {candidate}")
            candidate_tokens = {token for token in candidate.lower().split(".") if token}
            if candidate_tokens & blocked_tokens:
                raise AssertionError(f"forbidden import attempted: {candidate}")
        return real_import(name, globals_, locals_, fromlist, level)

    builtins.__import__ = guarded_import
    try:
        yield
    finally:
        builtins.__import__ = real_import


def test_factory_run_is_proposal_only_and_has_no_registry_or_data_access(
    tmp_path: Path,
) -> None:
    with _forbidden_import_guard():
        module = _load_runner_module()
        result = module.run_factory(config_path=CONFIG, output_root=tmp_path, code_sha="abc")

    manifest_path = result.artifact_paths["run_manifest.json"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    expected_config_sha256 = hashlib.sha256(
        json.dumps(
            expected_config,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()

    assert result.status == "completed"
    assert result.mode == "proposal_only"
    assert result.holdout_accessed is False
    assert result.paper_trading is False
    assert result.live_trading is False
    assert result.data_read is False
    assert result.network_access is False
    assert result.config_sha256 == expected_config_sha256
    assert result.run_directory.exists()
    assert set(result.artifact_paths) == {
        "audit_report.md",
        "candidate_registry.json",
        "candidate_summary.md",
        "decision_queue.md",
        "deduplication_report.md",
        "run_manifest.json",
    }
    assert manifest["mode"] == "proposal_only"
    assert manifest["boundary_assertions"] == {
        "data_read": False,
        "holdout_accessed": False,
        "live_trading": False,
        "network_access": False,
        "paper_trading": False,
    }
    assert not list(tmp_path.glob("**/*.sqlite"))


def test_run_writes_only_passed_preregistrations_and_manifest_hashes(tmp_path: Path) -> None:
    with _forbidden_import_guard():
        module = _load_runner_module()
        result = module.run_factory(config_path=CONFIG, output_root=tmp_path, code_sha="abc")

    preregistration_dir = result.run_directory / "preregistration"
    preregistration_paths = sorted(preregistration_dir.glob("*.yaml"))
    manifest = json.loads(result.artifact_paths["run_manifest.json"].read_text(encoding="utf-8"))
    registry = json.loads(
        result.artifact_paths["candidate_registry.json"].read_text(encoding="utf-8")
    )
    selected_registry_identities = {
        proposal["identity_sha256"]
        for proposal in registry["proposals"]
        if proposal["selection_reason"] == "SELECTED"
    }
    loaded_preregistrations = {
        path.stem: ProposalPreregistration.model_validate(
            yaml.safe_load(path.read_text(encoding="utf-8"))
        ).validated()
        for path in preregistration_paths
    }

    assert preregistration_paths
    assert len(preregistration_paths) == manifest["selection"]["selected_count"]
    assert manifest["preregistrations"]
    assert {path.stem for path in preregistration_paths} == selected_registry_identities
    assert set(manifest["preregistrations"]) == selected_registry_identities
    assert all(item["sha256"] for item in manifest["preregistrations"].values())
    assert all(
        manifest["preregistrations"][path.stem]["path"].endswith(f"{path.stem}.yaml")
        for path in preregistration_paths
    )
    assert all(
        record.proposal_identity_sha256 != proposal_identity
        for proposal_identity, record in loaded_preregistrations.items()
    )


def test_factory_rejects_non_mapping_preregistration_config(tmp_path: Path) -> None:
    invalid_config = tmp_path / "invalid_proposal_factory.yaml"
    config_payload = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config_payload["preregistration"] = ["not", "a", "mapping"]
    invalid_config.write_text(yaml.safe_dump(config_payload, sort_keys=False), encoding="utf-8")

    with _forbidden_import_guard():
        module = _load_runner_module()
        with pytest.raises(ValueError, match="preregistration config must be a mapping"):
            module.run_factory(config_path=invalid_config, output_root=tmp_path, code_sha="abc")


def test_cli_repeated_runs_append_new_run_directories(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with _forbidden_import_guard():
        module = _load_runner_module()
        first_exit = module.main(
            [
                "--config",
                str(CONFIG),
                "--output-root",
                str(tmp_path),
                "--code-sha",
                "abc",
            ]
        )
        first_stdout = capsys.readouterr().out
        second_exit = module.main(
            [
                "--config",
                str(CONFIG),
                "--output-root",
                str(tmp_path),
                "--code-sha",
                "abc",
            ]
        )
        second_stdout = capsys.readouterr().out

    first_payload = json.loads(first_stdout)
    second_payload = json.loads(second_stdout)
    first_run_directory = Path(first_payload["run_directory"])
    second_run_directory = Path(second_payload["run_directory"])

    assert first_exit == 0
    assert second_exit == 0
    assert first_payload["status"] == "completed"
    assert second_payload["status"] == "completed"
    assert first_payload["config_sha256"] == second_payload["config_sha256"]
    assert first_payload["proposal_count"] >= second_payload["deduplicated_count"]
    assert first_payload["run_id"] != second_payload["run_id"]
    assert first_run_directory.exists()
    assert second_run_directory.exists()
    assert first_run_directory.parent == second_run_directory.parent == tmp_path
    assert first_run_directory != second_run_directory
    assert len(list(tmp_path.iterdir())) == 2
