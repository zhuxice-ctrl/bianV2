from pathlib import Path

from bian_quant.config import AppConfig, load_config


def test_load_base_config_resolves_repo_relative_paths(tmp_path: Path) -> None:
    config_file = tmp_path / "base.yaml"
    config_file.write_text("var_dir: var\ntimezone: UTC\n", encoding="utf-8")
    config = load_config(config_file, repo_root=tmp_path)
    assert config == AppConfig(var_dir=tmp_path / "var", timezone="UTC")
