from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel


class AppConfig(BaseModel):
    var_dir: Path
    timezone: str = "UTC"


def load_config(path: Path, *, repo_root: Path) -> AppConfig:
    raw: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    var_dir = Path(raw["var_dir"])
    if not var_dir.is_absolute():
        var_dir = repo_root / var_dir
    return AppConfig(var_dir=var_dir, timezone=raw.get("timezone", "UTC"))
