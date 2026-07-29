from pathlib import Path
from urllib.request import urlopen

BASE = "https://data.binance.vision/data/futures/um/monthly/klines"


def archive_url(asset: str, interval: str, year: int, month: int) -> str:
    filename = f"{asset}-{interval}-{year:04d}-{month:02d}.zip"
    return f"{BASE}/{asset}/{interval}/{filename}"


def save_raw_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(payload)


def download_month(path: Path, *, asset: str, interval: str, year: int, month: int) -> None:
    with urlopen(archive_url(asset, interval, year, month), timeout=60) as response:
        save_raw_bytes(path, response.read())
