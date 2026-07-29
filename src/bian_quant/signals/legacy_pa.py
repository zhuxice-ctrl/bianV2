from datetime import datetime
from typing import Any

import pandas as pd

from bian_quant.signals.protocol import SignalRecord


def adapt_confluence_signals(
    frame: pd.DataFrame,
    *,
    asset: str,
    horizon: str = "4h",
    strategy_parameters: dict[str, Any] | None = None,
) -> list[SignalRecord]:
    from strategies.price_action import confluence_signals

    if not isinstance(frame.index, pd.DatetimeIndex):
        raise TypeError("legacy PA input must use a DatetimeIndex")
    if frame.index.tz is None:
        raise ValueError("legacy PA index must be timezone-aware")
    if not frame.index.is_monotonic_increasing or frame.index.has_duplicates:
        raise ValueError("legacy PA index must be sorted and unique")

    bar_duration = pd.Timedelta(horizon)
    result = confluence_signals(frame, **(strategy_parameters or {}))
    signals: list[SignalRecord] = []
    for timestamp, row in result.iterrows():
        value = float(row["signal"])
        if value == 0.0:
            continue
        if not isinstance(timestamp, pd.Timestamp):
            raise TypeError("legacy PA emitted a non-timestamp index")
        completed_at = (timestamp + bar_duration).to_pydatetime()
        if not isinstance(completed_at, datetime):
            raise TypeError("failed to convert completed bar timestamp")
        signals.append(
            SignalRecord(
                asset=asset,
                decision_time=completed_at,
                available_time=completed_at,
                horizon=horizon,
                value=value,
                confidence=None,
                factor_id="legacy.pa_confluence",
                factor_version="baseline-0",
            )
        )
    return signals


def signal_count(frame: pd.DataFrame, *, asset: str, horizon: str = "4h") -> int:
    return len(adapt_confluence_signals(frame, asset=asset, horizon=horizon))
