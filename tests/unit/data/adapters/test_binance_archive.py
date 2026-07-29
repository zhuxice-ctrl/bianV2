from pathlib import Path

import pytest

from bian_quant.data.adapters.binance_archive import archive_url, save_raw_bytes


def test_monthly_futures_kline_url() -> None:
    assert archive_url("BTCUSDT", "1h", 2025, 1).endswith(
        "/futures/um/monthly/klines/BTCUSDT/1h/BTCUSDT-1h-2025-01.zip"
    )


def test_raw_bytes_are_append_only(tmp_path: Path) -> None:
    target = tmp_path / "sample.zip"
    save_raw_bytes(target, b"first")
    try:
        save_raw_bytes(target, b"changed")
    except FileExistsError:
        pass
    else:
        raise AssertionError("raw evidence was overwritten")


@pytest.mark.network
def test_download_monthly_zip(tmp_path: Path) -> None:
    from bian_quant.data.adapters.binance_archive import download_month

    target = tmp_path / "BTCUSDT-1h-2025-01.zip"
    download_month(target, asset="BTCUSDT", interval="1h", year=2025, month=1)
    assert target.exists()
    with target.open("rb") as f:
        magic = f.read(2)
    assert magic == b"PK"
