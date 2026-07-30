"""Unit tests for append-only artifact writer."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bian_quant.reporting.artifacts import ArtifactWriter


class TestArtifactWriter:
    def test_run_directory_is_append_only(self, tmp_path: Path) -> None:
        writer = ArtifactWriter(tmp_path)
        run = writer.create_run("run-1")
        assert run.name == "run-1"
        assert run.path.is_dir()
        with pytest.raises(FileExistsError):
            writer.create_run("run-1")

    def test_write_json_creates_file(self, tmp_path: Path) -> None:
        writer = ArtifactWriter(tmp_path)
        run = writer.create_run("run-1")
        path = writer.write_json(run, "test.json", {"key": "value"})
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data == {"key": "value"}

    def test_write_json_is_sorted(self, tmp_path: Path) -> None:
        writer = ArtifactWriter(tmp_path)
        run = writer.create_run("run-1")
        writer.write_json(run, "test.json", {"b": 1, "a": 2})
        text = (run.path / "test.json").read_text(encoding="utf-8")
        assert text.index('"a"') < text.index('"b"')

    def test_write_json_rejects_nan(self, tmp_path: Path) -> None:
        writer = ArtifactWriter(tmp_path)
        run = writer.create_run("run-1")
        with pytest.raises(ValueError, match="Non-finite"):
            writer.write_json(run, "test.json", {"value": float("nan")})

    def test_write_json_rejects_infinity(self, tmp_path: Path) -> None:
        writer = ArtifactWriter(tmp_path)
        run = writer.create_run("run-1")
        with pytest.raises(ValueError, match="Non-finite"):
            writer.write_json(run, "test.json", {"value": float("inf")})

    def test_existing_file_not_replaced(self, tmp_path: Path) -> None:
        writer = ArtifactWriter(tmp_path)
        run = writer.create_run("run-1")
        writer.write_json(run, "test.json", {"v": 1})
        with pytest.raises(FileExistsError):
            writer.write_json(run, "test.json", {"v": 2})

    def test_write_text_creates_file(self, tmp_path: Path) -> None:
        writer = ArtifactWriter(tmp_path)
        run = writer.create_run("run-1")
        path = writer.write_text(run, "test.md", "# Hello")
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "# Hello"

    def test_write_text_existing_not_replaced(self, tmp_path: Path) -> None:
        writer = ArtifactWriter(tmp_path)
        run = writer.create_run("run-1")
        writer.write_text(run, "test.md", "v1")
        with pytest.raises(FileExistsError):
            writer.write_text(run, "test.md", "v2")
