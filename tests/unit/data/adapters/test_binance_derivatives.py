import csv
import io
import zipfile

import pytest

from bian_quant.data.adapters.binance_derivatives import (
    EXPECTED_FUNDING_COLUMNS,
    EXPECTED_METRICS_COLUMNS,
    funding_url,
    metrics_url,
    parse_funding,
    parse_metrics,
)


def test_funding_url() -> None:
    assert (
        funding_url("BTCUSDT", 2025, 1)
        == "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2025-01.zip"
    )


def test_metrics_url() -> None:
    from datetime import UTC, datetime

    url = metrics_url("BTCUSDT", datetime(2025, 1, 2, tzinfo=UTC))
    assert url == (
        "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2025-01-02.zip"
    )


def _make_zip(rows: list[dict], fieldnames: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        inner = io.StringIO()
        writer = csv.DictWriter(inner, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        zf.writestr("data.csv", inner.getvalue())
    return buf.getvalue()


def test_parse_funding_produces_event_time() -> None:
    cols = list(EXPECTED_FUNDING_COLUMNS)
    rows = [
        {
            "calc_time": "1735689600015",
            "funding_interval_hours": "8",
            "last_funding_rate": "0.00010000",
        }
    ]
    payload = _make_zip(rows, cols)

    result = parse_funding(payload, asset="BTCUSDT")

    assert len(result) == 1
    assert result[0]["funding_rate"] == 0.0001
    assert result[0]["asset"] == "BTCUSDT"
    assert result[0]["available_time"] == result[0]["event_time"]


def test_parse_metrics_produces_oi_fields() -> None:
    cols = list(EXPECTED_METRICS_COLUMNS)
    rows = [
        {
            "create_time": "2025-01-02 00:00:00",
            "symbol": "BTCUSDT",
            "sum_open_interest": "100.5",
            "sum_open_interest_value": "5000000",
            "count_toptrader_long_short_ratio": "1.2",
            "sum_toptrader_long_short_ratio": "1.3",
            "count_long_short_ratio": "1.1",
            "sum_taker_long_short_vol_ratio": "0.9",
        }
    ]
    payload = _make_zip(rows, cols)

    result = parse_metrics(payload)

    assert len(result) == 1
    assert result[0]["sum_open_interest"] == 100.5
    assert result[0]["sum_open_interest_value"] == 5000000.0
    assert result[0]["top_trader_account_long_short_ratio"] == 1.2
    assert result[0]["source_timestamp"] == "2025-01-02 00:00:00"


def test_parse_metrics_rejects_unexpected_columns() -> None:
    cols = list(EXPECTED_METRICS_COLUMNS) + ["unexpected_new_col"]
    rows = [
        {
            "create_time": "2025-01-02 00:00:00",
            "symbol": "BTCUSDT",
            "sum_open_interest": "100",
            "sum_open_interest_value": "5000",
            "count_toptrader_long_short_ratio": "1.0",
            "sum_toptrader_long_short_ratio": "1.0",
            "count_long_short_ratio": "1.0",
            "sum_taker_long_short_vol_ratio": "1.0",
            "unexpected_new_col": "surprise",
        }
    ]
    payload = _make_zip(rows, cols)

    try:
        parse_metrics(payload)
    except ValueError as e:
        assert "DERIVATIVES_SCHEMA_CHANGED" in str(e)
    else:
        raise AssertionError("unexpected columns were silently accepted")


@pytest.mark.network
def test_download_funding_zip(tmp_path) -> None:
    from bian_quant.data.adapters.binance_derivatives import download_funding

    target = tmp_path / "BTCUSDT-fundingRate-2025-01.zip"
    download_funding(target, asset="BTCUSDT", year=2025, month=1)
    assert target.exists()
    with target.open("rb") as f:
        payload = f.read()
    magic = payload[:2]
    assert magic == b"PK"
    assert parse_funding(payload, asset="BTCUSDT")
    assert target.with_suffix(".zip.manifest.json").exists()


@pytest.mark.network
def test_download_metrics_zip_matches_parser(tmp_path) -> None:
    from datetime import UTC, datetime

    from bian_quant.data.adapters.binance_derivatives import download_metrics

    target = tmp_path / "BTCUSDT-metrics-2025-01-02.zip"
    download_metrics(
        target,
        asset="BTCUSDT",
        date=datetime(2025, 1, 2, tzinfo=UTC),
    )

    rows = parse_metrics(target.read_bytes())
    assert rows
    assert rows[0]["asset"] == "BTCUSDT"
    assert target.with_suffix(".zip.manifest.json").exists()
