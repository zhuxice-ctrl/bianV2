"""Offline failure-mode tests for the public paper market-data client."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from bian_quant.paper.market_data import (
    PaperDataBlocked,
    PublicPaperMarketDataClient,
    RawResponse,
)

DECISION_TIME = datetime(2026, 8, 3, 12, 0, tzinfo=UTC)


def _klines_body(close_time_ms: int, bars: int = 3) -> bytes:
    rows = []
    base_open = close_time_ms - bars * 4 * 3600 * 1000
    for i in range(bars):
        open_t = base_open + i * 4 * 3600 * 1000
        close_t = open_t + 4 * 3600 * 1000
        rows.append(
            [open_t, "100.0", "101.0", "99.0", "100.5", "10.0", close_t, "1000.0", 10, "0.5", "0"]
        )
    return json.dumps(rows).encode("utf-8")


def _make_client(responder):
    """Build a client whose byte_reader delegates to *responder(url) -> RawResponse*."""
    return PublicPaperMarketDataClient(byte_reader=responder)


def test_accepted_klines_capture_has_sha256() -> None:
    payload = _klines_body(int(DECISION_TIME.timestamp() * 1000))

    def reader(url: str) -> RawResponse:
        return RawResponse(status=200, body=payload)

    client = _make_client(reader)
    capture = client.capture_klines("BTCUSDT", DECISION_TIME)
    assert capture.endpoint == "/fapi/v1/klines"
    assert capture.body_sha256 == hashlib.sha256(payload).hexdigest()
    assert capture.status == 200
    assert capture.data_time is not None
    assert capture.data_time <= DECISION_TIME


def test_rate_limit_maps_to_blocked() -> None:
    def reader(url: str) -> RawResponse:
        return RawResponse(status=429, body=b"{}")

    client = _make_client(reader)
    with pytest.raises(PaperDataBlocked, match="PAPER_DATA_RATE_LIMITED"):
        client.capture_exchange_info()


def test_http_failure_maps_to_unavailable() -> None:
    def reader(url: str) -> RawResponse:
        return RawResponse(status=503, body=b"oops")

    client = _make_client(reader)
    with pytest.raises(PaperDataBlocked, match="PAPER_DATA_UNAVAILABLE"):
        client.capture_exchange_info()


def test_transport_failure_maps_to_unavailable() -> None:
    def reader(url: str) -> RawResponse:
        raise OSError("TLS connection reset")

    client = _make_client(reader)
    with pytest.raises(PaperDataBlocked, match="PAPER_DATA_UNAVAILABLE"):
        client.capture_exchange_info()


def test_non_json_maps_to_malformed() -> None:
    def reader(url: str) -> RawResponse:
        return RawResponse(status=200, body=b"<html>nope</html>")

    client = _make_client(reader)
    with pytest.raises(PaperDataBlocked, match="PAPER_DATA_MALFORMED"):
        client.capture_exchange_info()


def test_future_kline_close_time_blocked() -> None:
    future_close = int((DECISION_TIME + timedelta(hours=2)).timestamp() * 1000)
    payload = _klines_body(future_close)

    def reader(url: str) -> RawResponse:
        return RawResponse(status=200, body=payload)

    client = _make_client(reader)
    with pytest.raises(PaperDataBlocked, match="PAPER_DATA_FUTURE_TIMESTAMP"):
        client.capture_klines("BTCUSDT", DECISION_TIME)


def test_incomplete_bar_blocked() -> None:
    payload = json.dumps([[1, "100", "101", "99", "100"]]).encode("utf-8")

    def reader(url: str) -> RawResponse:
        return RawResponse(status=200, body=payload)

    client = _make_client(reader)
    with pytest.raises(PaperDataBlocked, match="PAPER_DATA_MALFORMED"):
        client.capture_klines("BTCUSDT", DECISION_TIME)


def test_funding_capture_and_future_blocked() -> None:
    future_funding = int((DECISION_TIME + timedelta(hours=1)).timestamp() * 1000)
    payload = json.dumps(
        [{"fundingTime": future_funding, "fundingRate": "0.0001", "symbol": "BTCUSDT"}]
    ).encode("utf-8")

    def reader(url: str) -> RawResponse:
        return RawResponse(status=200, body=payload)

    client = _make_client(reader)
    start = DECISION_TIME - timedelta(days=1)
    with pytest.raises(PaperDataBlocked, match="PAPER_DATA_FUTURE_TIMESTAMP"):
        client.capture_funding("BTCUSDT", start, DECISION_TIME)


def test_funding_valid_range_captures() -> None:
    past_funding = int((DECISION_TIME - timedelta(hours=8)).timestamp() * 1000)
    payload = json.dumps(
        [{"fundingTime": past_funding, "fundingRate": "0.0001", "symbol": "BTCUSDT"}]
    ).encode("utf-8")

    def reader(url: str) -> RawResponse:
        return RawResponse(status=200, body=payload)

    client = _make_client(reader)
    start = DECISION_TIME - timedelta(days=1)
    capture = client.capture_funding("BTCUSDT", start, DECISION_TIME)
    assert capture.endpoint == "/fapi/v1/fundingRate"
    assert capture.body_sha256 == hashlib.sha256(payload).hexdigest()


def test_no_caller_supplied_headers() -> None:
    """The client exposes no parameter for custom headers / API keys."""
    import inspect

    sig = inspect.signature(PublicPaperMarketDataClient.__init__)
    assert "headers" not in sig.parameters
    assert "api_key" not in sig.parameters
    for name in ("capture_klines", "capture_exchange_info", "capture_funding"):
        method_sig = inspect.signature(getattr(PublicPaperMarketDataClient, name))
        assert "headers" not in method_sig.parameters
