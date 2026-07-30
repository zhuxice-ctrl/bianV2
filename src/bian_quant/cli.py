from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from bian_quant import __version__
from bian_quant.config import load_config
from bian_quant.data.legacy import import_legacy_ohlcv
from bian_quant.data.writer import write_canonical_ohlcv
from bian_quant.paths import ProjectPaths

app = typer.Typer(no_args_is_help=True)


def _parse_aware_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise typer.BadParameter("must be an ISO-8601 timestamp with timezone") from error
    if parsed.tzinfo is None:
        raise typer.BadParameter("must include a timezone offset")
    return parsed


@app.command()
def version() -> None:
    typer.echo(__version__)


@app.command()
def init(config: Path = Path("configs/base.yaml")) -> None:
    repo_root = Path.cwd()
    settings = load_config(config, repo_root=repo_root)
    paths = ProjectPaths.from_var_dir(settings.var_dir)
    paths.create()
    typer.echo(str(paths.var))


@app.command("import-legacy")
def import_legacy(
    source: Path,
    asset: str,
    interval: str,
    output: Path,
    ingested_at: Annotated[str, typer.Option("--ingested-at")],
) -> None:
    frame = import_legacy_ohlcv(
        source,
        asset=asset,
        interval=interval,
        ingested_at=_parse_aware_datetime(ingested_at),
    )
    write_canonical_ohlcv(frame, output, expected_frequency=interval)
    typer.echo(str(output))


@app.command("evaluate-factors")
def evaluate_factors(
    dataset: Annotated[str, typer.Option("--dataset")],
    config: Annotated[Path, typer.Option("--config")],
    code_sha: Annotated[str, typer.Option("--code-sha")],
    seed: Annotated[int, typer.Option("--seed")] = 42,
) -> None:
    """Run factor evaluation pipeline. Prints only run_id and artifact path."""
    import yaml

    from bian_quant.experiments.registry import ExperimentRegistry
    from bian_quant.factors.registry import FactorRegistry
    from bian_quant.factors.runner import FactorRunConfig, run_factor_pipeline
    from bian_quant.factors.screening import (
        BUILTIN_FACTOR_FUNCTIONS,
        builtin_factor_specs,
        load_legacy_screening_data,
    )

    with open(config, encoding="utf-8") as file:
        cfg = yaml.safe_load(file)
    if not isinstance(cfg, dict):
        raise typer.BadParameter("factor config must be a YAML mapping")

    interval = str(cfg.get("interval", "4h"))
    assets_value = cfg.get("assets", ["BTCUSDT", "ETHUSDT", "BNBUSDT"])
    if not isinstance(assets_value, list) or not all(
        isinstance(asset, str) for asset in assets_value
    ):
        raise typer.BadParameter("assets must be a list of symbols")
    assets = [str(asset) for asset in assets_value]
    data_dir = Path(str(cfg.get("data_dir", "data")))
    data, content_snapshot_id = load_legacy_screening_data(
        data_dir, assets=assets, interval=interval
    )

    selected_value = cfg.get("factors", list(BUILTIN_FACTOR_FUNCTIONS))
    if not isinstance(selected_value, list) or not all(
        isinstance(name, str) for name in selected_value
    ):
        raise typer.BadParameter("factors must be a list of built-in factor IDs")
    selected = {str(name) for name in selected_value}
    unknown = selected - set(BUILTIN_FACTOR_FUNCTIONS)
    if unknown:
        raise typer.BadParameter(f"unknown built-in factors: {sorted(unknown)}")
    specs = [spec for spec in builtin_factor_specs(horizon=interval) if spec.factor_id in selected]
    functions = {
        factor_id: function
        for factor_id, function in BUILTIN_FACTOR_FUNCTIONS.items()
        if factor_id in selected
    }

    run_config = FactorRunConfig(
        dataset_snapshot_id=f"{dataset}:{content_snapshot_id}",
        factor_specs=specs,
        split_config=cfg.get("split", {"n_folds": 3, "train_ratio": 0.6, "purge_bars": 6}),
        code_sha=code_sha,
        seed=seed,
        artifact_dir=Path(cfg.get("artifact_dir", "var/factor_runs")),
        experiment_registry_path=Path(cfg.get("experiment_registry", "var/experiments.sqlite")),
    )

    factor_registry_path = Path(cfg.get("factor_registry", "var/factors.sqlite"))
    factor_registry_path.parent.mkdir(parents=True, exist_ok=True)
    Path(run_config.experiment_registry_path).parent.mkdir(parents=True, exist_ok=True)
    with (
        FactorRegistry(factor_registry_path) as factor_registry,
        ExperimentRegistry(run_config.experiment_registry_path) as experiment_registry,
    ):
        result = run_factor_pipeline(
            run_config,
            data,
            registry=factor_registry,
            factor_functions=functions,
            experiment_registry=experiment_registry,
        )
    typer.echo(result.run_id)
    typer.echo(str(result.artifact_path))
    if result.status != "completed":
        raise typer.Exit(code=1)


@app.command("prepare-dual-horizon")
def prepare_dual_horizon(
    config: Annotated[Path, typer.Option("--config")],
    code_sha: Annotated[str, typer.Option("--code-sha")],
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    download: Annotated[bool, typer.Option("--download")] = False,
) -> None:
    """Prepare dual-horizon acquisition and snapshot build."""
    import json as _json

    from bian_quant.data.acquisition import DualHorizonAcquisition
    from bian_quant.data.dual_horizon import BinanceDownloader
    from bian_quant.data.dual_horizon import prepare_dual_horizon as _prepare

    cfg = DualHorizonAcquisition.from_yaml(config)

    if dry_run:
        dry_result = _prepare(cfg, code_sha=code_sha, dry_run=True)
        typer.echo(_json.dumps(dry_result, indent=2, default=str))
        return

    result = _prepare(
        cfg,
        code_sha=code_sha,
        downloader=BinanceDownloader() if download else None,
    )

    typer.echo(result.run_id)
    typer.echo(str(result.acquisition_artifact))
    typer.echo(str(result.quality_artifact))
    for snap in result.snapshots:
        typer.echo(snap.snapshot_id)
    if result.status != "passed":
        raise typer.Exit(code=1)


@app.command("analyze-dual-horizon")
def analyze_dual_horizon(
    config: Annotated[Path, typer.Option("--config")],
    code_sha: Annotated[str, typer.Option("--code-sha")],
) -> None:
    """Analyze cataloged dual-horizon snapshots and produce decision packet."""

    from bian_quant.data.acquisition import DualHorizonAcquisition
    from bian_quant.research.operations import analyze_cataloged_dual_horizon

    cfg = DualHorizonAcquisition.from_yaml(config)
    result = analyze_cataloged_dual_horizon(cfg, code_sha=code_sha)
    typer.echo(result.run_id)
    typer.echo(str(result.artifact_dir))
    if result.status != "passed":
        typer.echo(result.error_code or "ANALYSIS_BLOCKED", err=True)
        raise typer.Exit(code=1)


@app.command("evaluate-holdout")
def evaluate_holdout(
    run_id: Annotated[str, typer.Option("--run-id")],
    factor_id: Annotated[str, typer.Option("--factor-id")],
    factor_version: Annotated[str, typer.Option("--factor-version")],
    snapshot_id: Annotated[str, typer.Option("--snapshot-id")],
    config: Annotated[
        Path,
        typer.Option("--config"),
    ] = Path("configs/experiments/dual_horizon_derivatives.yaml"),
) -> None:
    """Evaluate a candidate factor on the locked holdout."""
    from bian_quant.data.acquisition import DualHorizonAcquisition
    from bian_quant.research.operations import evaluate_candidate_holdout

    try:
        result = evaluate_candidate_holdout(
            DualHorizonAcquisition.from_yaml(config),
            run_id=run_id,
            factor_id=factor_id,
            factor_version=factor_version,
            snapshot_id=snapshot_id,
        )
        typer.echo(result.status)
        typer.echo(str(result.artifact_path))
        typer.echo(result.factor_state.value)
        if result.status != "passed":
            raise typer.Exit(code=1)
    except (KeyError, PermissionError, ValueError, FileExistsError) as exc:
        typer.echo(f"Denied: {exc}", err=True)
        raise typer.Exit(code=1) from None
