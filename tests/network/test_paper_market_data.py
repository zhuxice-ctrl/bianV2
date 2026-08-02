"""Network compatibility test for the public paper market-data client.

Marked ``network``; never requests the full universe.  Verifies that the three
permitted public endpoints respond without credentials and expose valid
timestamps.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bian_quant.paper.market_data import (
    PaperDataBlocked,
    PublicPaperMarketDataClient,
    urllib_byte_reader,
)

pytestmark = pytest.mark.network


def test_btcusdt_kline_capture() -> None:
    client = PublicPaperMarketDataClient(byte_reader=urllib_byte_reader)
    decision_time = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    try:
        capture = client.capture_klines("BTCUSDT", decision_time)
    except PaperDataBlocked as exc:
        pytest.skip(f"public endpoint unavailable in this environment: {exc.code}")
    assert capture.endpoint == "/fapi/v1/klines"
    assert len(capture.body_sha256) == 64
    assert capture.data_time is not None
    assert capture.data_time <= decision_time


def test_exchange_info_capture() -> None:
    client = PublicPaperMarketDataClient(byte_reader=urllib_byte_reader)
    try:
        capture = client.capture_exchange_info()
    except PaperDataBlocked as exc:
        pytest.skip(f"public endpoint unavailable in this environment: {exc.code}")
    assert capture.endpoint == "/fapi/v1/exchangeInfo"
    assert isinstance(capture.parsed, dict)
    assert "serverTime" in capture.parsed


def test_funding_history_capture() -> None:
    client = PublicPaperMarketDataClient(byte_reader=urllib_byte_reader)
    end = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    try:
        capture = client.capture_funding("BTCUSDT", start, end)
    except PaperDataBlocked as exc:
        pytest.skip(f"public endpoint unavailable in this environment: {exc.code}")
    assert capture.endpoint == "/fapi/v1/fundingRate"
    assert isinstance(capture.parsed, list)
