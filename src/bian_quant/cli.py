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
