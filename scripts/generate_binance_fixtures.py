"""Generate deterministic miniature Binance ZIP fixtures for offline tests."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "binance"
ZIP_TIMESTAMP = (2026, 7, 30, 0, 0, 0)

FIXTURES = {
    "ohlcv-mini.zip": (
        "BTCUSDT-1h-2026-07-29.csv",
        (
            "open_time,open,high,low,close,volume,close_time,quote_volume,trades,"
            "taker_buy_base,taker_buy_quote,ignore\n"
            "1785283200000,50000.0,50100.0,49900.0,50050.0,100.5,1785286799999,"
            "5025000.0,120,55.0,2750000.0,0\n"
            "1785286800000,50050.0,50200.0,50000.0,50150.0,110.0,1785290399999,"
            "5516500.0,130,60.0,3000000.0,0\n"
            "1785290400000,50150.0,50300.0,50100.0,50250.0,120.0,1785293999999,"
            "6030000.0,140,65.0,3250000.0,0\n"
        ),
    ),
    "funding-mini.zip": (
        "BTCUSDT-fundingRate-2026-07.csv",
        (
            "calc_time,funding_interval_hours,last_funding_rate\n"
            "1785283200000,8,0.00010000\n"
            "1785312000000,8,0.00012000\n"
            "1785340800000,8,0.00009000\n"
        ),
    ),
    "metrics-mini.zip": (
        "BTCUSDT-metrics-2026-07-29.csv",
        (
            "create_time,symbol,sum_open_interest,sum_open_interest_value,"
            "count_toptrader_long_short_ratio,sum_toptrader_long_short_ratio,"
            "count_long_short_ratio,sum_taker_long_short_vol_ratio\n"
            "2026-07-29 00:00:00,BTCUSDT,100000.0,5000000000.0,1.10,1.20,1.05,1.15\n"
            "2026-07-29 01:00:00,BTCUSDT,101000.0,5050000000.0,1.11,1.21,1.06,1.16\n"
            "2026-07-29 02:00:00,BTCUSDT,102000.0,5100000000.0,1.12,1.22,1.07,1.17\n"
        ),
    ),
}


def write_fixture(path: Path, member_name: str, csv_text: str) -> None:
    """Write one reproducible ZIP member with fixed metadata and compression."""
    info = ZipInfo(member_name, date_time=ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = 0o100644 << 16
    with ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        archive.writestr(
            info, csv_text.encode("utf-8"), compress_type=ZIP_DEFLATED, compresslevel=9
        )


def main() -> None:
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    for filename, (member_name, csv_text) in FIXTURES.items():
        write_fixture(FIXTURE_DIR / filename, member_name, csv_text)


if __name__ == "__main__":
    main()
