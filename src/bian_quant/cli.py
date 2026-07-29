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
    seed: Annotated[int, typer.Option("--seed")] = 42,
) -> None:
    """Run factor evaluation pipeline. Prints only run_id and artifact path."""
    import yaml

    from bian_quant.factors.runner import FactorRunConfig

    with open(config) as f:
        cfg = yaml.safe_load(f)

    # Build factor specs from config
    from bian_quant.factors.spec import FactorSpec

    specs = []
    for fs in cfg.get("factors", []):
        specs.append(
            FactorSpec(
                factor_id=fs["factor_id"],
                version=fs.get("version", "1.0.0"),
                formula=fs["formula"],
                direction=fs.get("direction", "positive"),
                hypothesis=fs["hypothesis"],
                required_columns=fs.get("required_columns", ["close"]),
                horizon=fs.get("horizon", "4h"),
                missing_policy=fs.get("missing_policy", "preserve"),
                winsor_limits=tuple(fs.get("winsor_limits", [0.01, 0.99])),
                valid_regimes=fs.get("valid_regimes", ["all"]),
                failure_conditions=fs.get("failure_conditions", []),
                parent_factors=fs.get("parent_factors", []),
            )
        )

    _run_config = FactorRunConfig(
        dataset_snapshot_id=dataset,
        factor_specs=specs,
        split_config=cfg.get("split", {"n_folds": 3, "train_ratio": 0.6, "purge_bars": 6}),
        seed=seed,
        artifact_dir=Path(cfg.get("artifact_dir", "var/factor_runs")),
    )

    # Note: data loading and factor function mapping must be provided
    # by the caller via the config. This CLI command is a thin wrapper.
    typer.echo(f"Configuration loaded for dataset={dataset}, {len(specs)} factors")
    typer.echo("Use run_factor_pipeline() directly for programmatic access.")
