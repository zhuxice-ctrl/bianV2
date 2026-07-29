"""Tests for the causal SignalRecord protocol."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from bian_quant.signals.protocol import SignalRecord


def _ts(minute: int) -> datetime:
    """Fixed timezone-aware timestamp."""
    return datetime(2026, 1, 1, 12, minute, tzinfo=timezone.utc)


class TestSignalRecordCreation:
    def test_valid_record(self):
        rec = SignalRecord(
            asset="BTCUSDT",
            available_time=_ts(0),
            decision_time=_ts(5),
            direction=1,
            confidence=0.8,
        )
        assert rec.asset == "BTCUSDT"
        assert rec.direction == 1
        assert rec.confidence == 0.8

    def test_default_payload_is_empty(self):
        rec = SignalRecord(
            asset="ETHUSDT",
            available_time=_ts(0),
            decision_time=_ts(1),
            direction=-1,
            confidence=0.3,
        )
        assert rec.payload == {}

    def test_payload_preserved(self):
        rec = SignalRecord(
            asset="BTCUSDT",
            available_time=_ts(0),
            decision_time=_ts(1),
            direction=1,
            confidence=1.0,
            payload={"stop": 90.0, "target": 110.0},
        )
        assert rec.payload["stop"] == 90.0


class TestCausality:
    def test_available_equals_decision_is_ok(self):
        """Signal available and acted upon at the same instant is valid."""
        rec = SignalRecord(
            asset="BTCUSDT",
            available_time=_ts(5),
            decision_time=_ts(5),
            direction=1,
            confidence=0.5,
        )
        assert rec.direction == 1

    def test_available_after_decision_rejected(self):
        with pytest.raises(ValidationError, match="available_time must not precede"):
            SignalRecord(
                asset="BTCUSDT",
                available_time=_ts(10),
                decision_time=_ts(5),
                direction=1,
                confidence=0.5,
            )

    def test_naive_available_time_rejected(self):
        with pytest.raises(ValidationError, match="available_time must be timezone-aware"):
            SignalRecord(
                asset="BTCUSDT",
                available_time=datetime(2026, 1, 1, 12, 0),
                decision_time=_ts(5),
                direction=1,
                confidence=0.5,
            )

    def test_naive_decision_time_rejected(self):
        with pytest.raises(ValidationError, match="decision_time must be timezone-aware"):
            SignalRecord(
                asset="BTCUSDT",
                available_time=_ts(0),
                decision_time=datetime(2026, 1, 1, 12, 5),
                direction=1,
                confidence=0.5,
            )


class TestImmutability:
    def test_frozen(self):
        rec = SignalRecord(
            asset="BTCUSDT",
            available_time=_ts(0),
            decision_time=_ts(1),
            direction=1,
            confidence=0.5,
        )
        with pytest.raises(ValidationError):
            rec.direction = -1  # type: ignore[misc]


class TestBounds:
    @pytest.mark.parametrize("bad_direction", [-2, 2, 5])
    def test_direction_out_of_range(self, bad_direction: int):
        with pytest.raises(ValidationError):
            SignalRecord(
                asset="BTCUSDT",
                available_time=_ts(0),
                decision_time=_ts(1),
                direction=bad_direction,
                confidence=0.5,
            )

    @pytest.mark.parametrize("bad_conf", [-0.01, 1.01, 2.0])
    def test_confidence_out_of_range(self, bad_conf: float):
        with pytest.raises(ValidationError):
            SignalRecord(
                asset="BTCUSDT",
                available_time=_ts(0),
                decision_time=_ts(1),
                direction=1,
                confidence=bad_conf,
            )

    def test_confidence_boundary_zero(self):
        rec = SignalRecord(
            asset="BTCUSDT",
            available_time=_ts(0),
            decision_time=_ts(1),
            direction=0,
            confidence=0.0,
        )
        assert rec.confidence == 0.0

    def test_confidence_boundary_one(self):
        rec = SignalRecord(
            asset="BTCUSDT",
            available_time=_ts(0),
            decision_time=_ts(1),
            direction=1,
            confidence=1.0,
        )
        assert rec.confidence == 1.0
