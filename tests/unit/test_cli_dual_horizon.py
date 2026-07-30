"""Tests for the dual-horizon CLI commands."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from bian_quant.cli import app

runner = CliRunner()


def test_prepare_dual_horizon_dry_run_is_network_free(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("network access detected during dry-run")

    monkeypatch.setattr("urllib.request.urlopen", fail_if_called)
    result = runner.invoke(
        app,
        [
            "prepare-dual-horizon",
            "--config",
            "configs/experiments/dual_horizon_derivatives.yaml",
            "--code-sha",
            "a" * 40,
            "--dry-run",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["as_of"] == "2026-07-26T19:59:59.999000+00:00"
    assert payload["network_access"] is False
