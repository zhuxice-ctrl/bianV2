from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from bian_quant.signals.protocol import SignalRecord


def _record(**changes: object) -> SignalRecord:
    values: dict[str, object] = {
        "asset": "BTCUSDT",
        "decision_time": datetime(2026, 1, 1, 4, tzinfo=UTC),
        "available_time": datetime(2026, 1, 1, 4, tzinfo=UTC),
        "horizon": "4h",
        "value": 0.5,
        "confidence": None,
        "factor_id": "price.momentum",
        "factor_version": "1.0.0",
    }
    values.update(changes)
    return SignalRecord.model_validate(values)


def test_signal_rejects_future_availability() -> None:
    with pytest.raises(ValidationError, match="not available"):
        _record(available_time=datetime(2026, 1, 1, 5, tzinfo=UTC))


def test_signal_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        _record(decision_time=datetime(2026, 1, 1, 4))


def test_confidence_is_probability_when_present() -> None:
    with pytest.raises(ValidationError):
        _record(confidence=1.1)


def test_signal_is_frozen_and_direction_is_derived() -> None:
    record = _record(value=-0.2)
    assert record.direction == -1
    with pytest.raises(ValidationError):
        record.value = 1.0  # type: ignore[misc]
