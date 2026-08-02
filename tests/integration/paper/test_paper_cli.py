"""CLI integration tests for the paper-trading commands."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from bian_quant.cli import app

runner = CliRunner()


def test_run_paper_cycle_help_lists_required_options() -> None:
    result = runner.invoke(app, ["run-paper-cycle", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.stdout
    assert "--scheduled-time" in result.stdout


def test_paper_status_help_lists_required_options() -> None:
    result = runner.invoke(app, ["paper-status", "--help"])
    assert result.exit_code == 0
    assert "--config" in result.stdout


def test_run_paper_cycle_rejects_api_key_flag() -> None:
    result = runner.invoke(
        app,
        [
            "run-paper-cycle",
            "--config",
            "x.yaml",
            "--scheduled-time",
            "2026-08-03T08:00:00Z",
            "--api-key",
            "secret",
        ],
    )
    assert result.exit_code != 0


def test_paper_status_no_ledger_exits_nonzero(tmp_path: Path) -> None:
    config = tmp_path / "paper.yaml"
    config.write_text(
        """
run_id: paper-run-cli
base_url: https://fapi.binance.com
approved_factor_id: momentum-4h-popular-v1
approved_factor_version: "1.0.0"
holdout_artifact_path: var/holdout.json
small_account_artifact_path: var/backtest.json
universe_artifact_id: popular-universe-2026-07-26
snapshot_ids: ["micro-4h-popular-2026-07-26"]
decision_assets: ["BTCUSDT"]
decision_asset: BTCUSDT
artifact_root: {root}
""".format(root=str(tmp_path / "artifacts")),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["paper-status", "--config", str(config)])
    assert result.exit_code == 1


def test_commands_accept_no_order_arguments() -> None:
    """Neither command exposes a buy/sell/order parameter."""
    for command in ("run-paper-cycle", "paper-status"):
        result = runner.invoke(app, [command, "--help"])
        assert "--order" not in result.stdout
        assert "--side" not in result.stdout
