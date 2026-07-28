from pathlib import Path

from bian_quant.paths import ProjectPaths


def test_project_paths_have_separate_evidence_directories(tmp_path: Path) -> None:
    paths = ProjectPaths.from_var_dir(tmp_path / "var")
    assert paths.raw == tmp_path / "var" / "lake" / "raw"
    assert paths.canonical == tmp_path / "var" / "lake" / "canonical"
    assert paths.research == tmp_path / "var" / "lake" / "research"
    assert paths.artifacts == tmp_path / "var" / "artifacts"
