import pandas as pd

from bian_quant.data.query import as_known_at


def test_future_available_row_is_excluded() -> None:
    frame = pd.DataFrame(
        {
            "event_time": pd.to_datetime(["2026-01-01T00:00:00Z", "2026-01-01T01:00:00Z"]),
            "available_time": pd.to_datetime(["2026-01-01T01:00:00Z", "2026-01-01T02:00:00Z"]),
            "close": [100.0, 999.0],
        }
    )

    known = as_known_at(frame, pd.Timestamp("2026-01-01T01:30:00Z"))

    assert known["close"].tolist() == [100.0]


def test_naive_decision_time_raises() -> None:
    frame = pd.DataFrame(
        {
            "event_time": pd.to_datetime(["2026-01-01T00:00:00Z"]),
            "available_time": pd.to_datetime(["2026-01-01T01:00:00Z"]),
            "close": [100.0],
        }
    )

    try:
        as_known_at(frame, pd.Timestamp("2026-01-01T01:30:00"))
    except ValueError:
        pass
    else:
        raise AssertionError("naive decision_time was accepted")
