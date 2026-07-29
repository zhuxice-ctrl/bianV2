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
    from datetime import datetime, UTC

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
    rows = [{"calc_time": "1738368000000", "funding_rate": "0.0001", "symbol": "BTCUSDT"}]
    payload = _make_zip(rows, cols)

    result = parse_funding(payload)

    assert len(result) == 1
    assert result[0]["funding_rate"] == 0.0001
    assert result[0]["available_time"] == result[0]["event_time"]


def test_parse_metrics_produces_oi_fields() -> None:
    cols = list(EXPECTED_METRICS_COLUMNS)
    rows = [{
        "sum_open_interest": "100.5",
        "sum_open_interest_value": "5000000",
        "count": "100",
        "sum_open_interest_cost": "50",
        "sum_open_interest_cost_value": "2500000",
        "long_short_ratio": "1.2",
        "long_account": "55",
        "short_account": "45",
        "long_position": "60",
        "short_position": "40",
        "timestamp": "1738368000000",
    }]
    payload = _make_zip(rows, cols)

    result = parse_metrics(payload)

    assert len(result) == 1
    assert result[0]["sum_open_interest"] == 100.5
    assert result[0]["sum_open_interest_value"] == 5000000.0
    assert result[0]["long_short_ratio"] == 1.2


def test_parse_metrics_rejects_unexpected_columns() -> None:
    cols = list(EXPECTED_METRICS_COLUMNS) + ["unexpected_new_col"]
    rows = [{
        "sum_open_interest": "100",
        "sum_open_interest_value": "5000",
        "count": "10",
        "sum_open_interest_cost": "5",
        "sum_open_interest_cost_value": "250",
        "long_short_ratio": "1.0",
        "long_account": "50",
        "short_account": "50",
        "long_position": "50",
        "short_position": "50",
        "timestamp": "1738368000000",
        "unexpected_new_col": "surprise",
    }]
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
        magic = f.read(2)
    assert magic == b"PK"
