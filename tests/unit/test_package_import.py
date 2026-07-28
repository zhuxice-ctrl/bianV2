def test_package_version_is_exposed() -> None:
    import bian_quant

    assert bian_quant.__version__ == "0.1.0"
