"""Append-only artifact writer for dual-horizon research outputs."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RunDirectory:
    """Exclusive run directory for a single research run."""

    path: Path
    name: str


class ArtifactWriter:
    """Write artifacts into exclusive run directories.

    Run directories are created exclusively — duplicate names raise
    FileExistsError.  JSON writes are UTF-8, sorted, finite-value-only,
    and atomic through a temporary file followed by same-filesystem rename.
    Existing final files are never replaced.
    """

    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def create_run(self, name: str) -> RunDirectory:
        """Create an exclusive run directory.

        Raises FileExistsError if the run already exists.
        """
        run_path = self._root / name
        try:
            run_path.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            if run_path.is_dir():
                raise FileExistsError(f"Run directory already exists: {run_path}") from None
            raise
        return RunDirectory(path=run_path, name=name)

    def write_json(self, run: RunDirectory, filename: str, data: Any) -> Path:
        """Write JSON atomically.  Existing files are never replaced."""
        target = run.path / filename
        if target.exists():
            raise FileExistsError(f"Artifact already exists: {target}")

        # Verify finite values only
        text = json.dumps(data, sort_keys=True, ensure_ascii=False, default=str)
        # Parse back to check for NaN/Infinity
        parsed = json.loads(text)
        _check_finite(parsed)

        # Atomic write: temp file in same dir, then rename
        fd, tmp_path = tempfile.mkstemp(dir=run.path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tmp_path, target)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

        return target

    def write_text(self, run: RunDirectory, filename: str, text: str) -> Path:
        """Write text atomically.  Existing files are never replaced."""
        target = run.path / filename
        if target.exists():
            raise FileExistsError(f"Artifact already exists: {target}")

        fd, tmp_path = tempfile.mkstemp(dir=run.path, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.rename(tmp_path, target)
        except Exception:
            Path(tmp_path).unlink(missing_ok=True)
            raise

        return target


def _check_finite(value: Any) -> None:
    """Recursively verify that a value contains no NaN or Infinity."""
    if isinstance(value, float):
        if not (value == value and value != float("inf") and value != float("-inf")):
            raise ValueError(f"Non-finite float value: {value}")
    elif isinstance(value, dict):
        for v in value.values():
            _check_finite(v)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_finite(item)
