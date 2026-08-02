"""GET-only public market-data capture for forward paper trading.

The client never accepts caller-supplied headers, never sends credentials, and
only ever builds URLs from the fixed base URL and the three-endpoint allowlist.
Responses are captured (body SHA-256, timestamps, status) before being parsed;
every failure mode maps to a stable :class:`PaperDataBlocked` code so the runner
can persist a no-trade decision.
"""

from __future__ import annotations

import hashlib
import json
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from bian_quant.paper.models import (
    ALLOWED_BASE_URL,
    ALLOWED_ENDPOINTS,
    MarketDataCapture,
)


class ByteReader(Protocol):
    """Callable that fetches raw bytes for *url* and returns a RawResponse."""

    def __call__(self, url: str) -> RawResponse: ...


@dataclass(frozen=True)
class RawResponse:
    """Raw HTTP response materialised before any parsing."""

    status: int
    body: bytes
    server_time: datetime | None = None


class PaperDataBlocked(Exception):
    """A public-data capture was blocked; ``code`` is a stable reason string."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


def _sha256(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def _parse_server_time(headers_body: bytes) -> datetime | None:
    """Best-effort extraction of a server timestamp from a raw response body.

    Binance embeds ``serverTime`` in most JSON payloads; we read it after the
    caller has confirmed the body is JSON.  Returns ``None`` when absent.
    """
    return None  # parsed lazily by the capture methods below


class PublicPaperMarketDataClient:
    """Capture-only adapter for the three permitted public endpoints.

    A dependency-injected ``byte_reader(url) -> RawResponse`` performs the actual
    HTTP GET; production code supplies a urllib-based reader, tests supply a
    fixture reader.  No headers are ever accepted from the caller.
    """

    def __init__(
        self,
        byte_reader: ByteReader,
        *,
        base_url: str = ALLOWED_BASE_URL,
        request_time: Callable[[], datetime] | None = None,
    ) -> None:
        if base_url != ALLOWED_BASE_URL:
            raise PaperDataBlocked("PAPER_DATA_ENDPOINT_NOT_ALLOWED", base_url)
        self._read = byte_reader
        self._base_url = base_url
        self._now = request_time or (lambda: datetime.now(UTC))

    # -- public capture methods --------------------------------------------

    def capture_klines(self, symbol: str, decision_time: datetime) -> MarketDataCapture:
        """Capture four-hour klines for *symbol* up to *decision_time*."""
        params = {
            "symbol": symbol,
            "interval": "4h",
            "limit": "200",
        }
        capture = self._capture("/fapi/v1/klines", params)
        self._validate_klines(capture, decision_time)
        return capture

    def capture_exchange_info(self) -> MarketDataCapture:
        """Capture exchange contract filters (no symbol required)."""
        return self._capture("/fapi/v1/exchangeInfo", {})

    def capture_funding(
        self, symbol: str, start_time: datetime, end_time: datetime
    ) -> MarketDataCapture:
        """Capture funding-rate history for *symbol* over [start_time, end_time]."""
        if end_time <= start_time:
            raise PaperDataBlocked("PAPER_DATA_MALFORMED", "end_time must follow start_time")
        params = {
            "symbol": symbol,
            "startTime": str(int(start_time.timestamp() * 1000)),
            "endTime": str(int(end_time.timestamp() * 1000)),
            "limit": "1000",
        }
        capture = self._capture("/fapi/v1/fundingRate", params)
        self._validate_funding(capture, end_time)
        return capture

    # -- internals ---------------------------------------------------------

    def _capture(self, endpoint: str, params: dict[str, str]) -> MarketDataCapture:
        if endpoint not in ALLOWED_ENDPOINTS:
            raise PaperDataBlocked("PAPER_DATA_ENDPOINT_NOT_ALLOWED", endpoint)
        url = self._build_url(endpoint, params)
        request_time = self._now()
        try:
            response = self._read(url)
        except PaperDataBlocked:
            raise
        except OSError as exc:
            raise PaperDataBlocked("PAPER_DATA_UNAVAILABLE", str(exc)) from exc

        if response.status == 429:
            raise PaperDataBlocked("PAPER_DATA_RATE_LIMITED", url)
        if response.status != 200:
            raise PaperDataBlocked("PAPER_DATA_UNAVAILABLE", f"HTTP {response.status}")

        body = response.body
        try:
            parsed = json.loads(body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as exc:
            raise PaperDataBlocked("PAPER_DATA_MALFORMED", "non-JSON body") from exc

        data_time = self._extract_data_time(endpoint, parsed)
        return MarketDataCapture(
            endpoint=endpoint,
            url=url,
            request_time=request_time,
            server_time=response.server_time,
            data_time=data_time,
            status=response.status,
            body_sha256=_sha256(body),
            body_size=len(body),
            parsed=parsed,
        )

    def _build_url(self, endpoint: str, params: dict[str, str]) -> str:
        query = urllib.parse.urlencode(params)
        return f"{self._base_url}{endpoint}?{query}" if query else f"{self._base_url}{endpoint}"

    @staticmethod
    def _extract_data_time(endpoint: str, parsed: object) -> datetime | None:
        """Derive the most recent data timestamp from a parsed payload."""
        if endpoint == "/fapi/v1/klines":
            if isinstance(parsed, list) and parsed:
                last = parsed[-1]
                if isinstance(last, list) and len(last) > 6:
                    # kline: [open_time, open, high, low, close, volume, close_time, ...]
                    return _from_ms(last[6])
            return None
        if endpoint == "/fapi/v1/fundingRate":
            if isinstance(parsed, list) and parsed:
                last = parsed[-1]
                if isinstance(last, dict) and "fundingTime" in last:
                    return _from_ms(last["fundingTime"])
            return None
        if endpoint == "/fapi/v1/exchangeInfo":
            if isinstance(parsed, dict) and "serverTime" in parsed:
                return _from_ms(parsed["serverTime"])
            return None
        return None

    @staticmethod
    def _validate_klines(capture: MarketDataCapture, decision_time: datetime) -> None:
        parsed = capture.parsed
        if not isinstance(parsed, list) or not parsed:
            raise PaperDataBlocked("PAPER_DATA_MALFORMED", "empty klines payload")
        last = parsed[-1]
        if not isinstance(last, list) or len(last) < 7:
            raise PaperDataBlocked("PAPER_DATA_MALFORMED", "incomplete four-hour bar")
        close_time = _from_ms(last[6])
        if close_time is None:
            raise PaperDataBlocked("PAPER_DATA_MALFORMED", "missing close time")
        # The most recent closed bar must not be a future bar relative to the
        # scheduled decision time.
        if close_time > decision_time:
            raise PaperDataBlocked("PAPER_DATA_FUTURE_TIMESTAMP", str(close_time))

    @staticmethod
    def _validate_funding(capture: MarketDataCapture, end_time: datetime) -> None:
        parsed = capture.parsed
        if not isinstance(parsed, list):
            raise PaperDataBlocked("PAPER_DATA_MALFORMED", "funding payload not a list")
        for row in parsed:
            if isinstance(row, dict) and "fundingTime" in row:
                funding_time = _from_ms(row["fundingTime"])
                if funding_time is not None and funding_time > end_time:
                    raise PaperDataBlocked("PAPER_DATA_FUTURE_TIMESTAMP", str(funding_time))


def _from_ms(value: object) -> datetime | None:
    """Convert a Binance millisecond epoch value to an aware datetime."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str, bytes, bytearray)):
        return None
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    except (TypeError, ValueError, OSError):
        return None


def urllib_byte_reader(url: str) -> RawResponse:
    """Production byte reader using stdlib urllib (GET only, no headers)."""
    import urllib.request

    with urllib.request.urlopen(url, timeout=15) as response:  # noqa: S310 - public endpoint
        body = response.read()
        status_value = response.status
        if isinstance(status_value, bool) or not isinstance(status_value, int):
            raise PaperDataBlocked("PAPER_DATA_UNAVAILABLE", "response status is invalid")
        status = status_value
        server_header = response.headers.get("Date")
        server_time = _parse_http_date(server_header)
        return RawResponse(status=status, body=body, server_time=server_time)


def _parse_http_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(value).astimezone(UTC)
    except (TypeError, ValueError):
        return None


# Kept for symmetry with the plan's naming; the freshness window is four hours.
FRESHNESS_WINDOW = timedelta(hours=4)
