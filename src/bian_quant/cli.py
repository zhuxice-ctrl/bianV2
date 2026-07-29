from datetime import datetime
from pathlib import Path

import typer

from bian_quant import __version__
from bian_quant.config import load_config
from bian_quant.data.legacy import import_legacy_ohlcv
from bian_quant.data.writer import write_parquet
from bian_quant.paths import ProjectPaths

app = typer.Typer(no_args_is_help=True)


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
    ingested_at: datetime,
) -> None:
    frame = import_legacy_ohlcv(
        source, asset=asset, interval=interval, ingested_at=ingested_at
    )
    write_parquet(frame, output)
    typer.echo(str(output))
