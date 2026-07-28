from pathlib import Path

import typer

from bian_quant import __version__
from bian_quant.config import load_config
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
