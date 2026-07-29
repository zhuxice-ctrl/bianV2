"""Adapter that converts legacy PA strategy signals to the unified ``SignalRecord`` protocol.

This module wraps ``strategies.price_action.confluence_signals`` without
copying or modifying the legacy strategy math.  The adapter:

1. Calls the legacy function on Canonical OHLCV data.
2. Converts each non-zero signal into a ``SignalRecord`` with
   ``factor_id="legacy.pa_confluence"`` and ``factor_version="baseline-0"``
   stored in the ``payload``.
3. Sets ``decision_time`` and ``available_time`` to the completed signal-bar
   close timestamp (the bar on which the signal was generated).
4. Never exposes the next bar's open inside the signal record.

The legacy strategy module remains frozen — this adapter only reads its
output and translates it into the common pipeline format.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pandas as pd

from .protocol import SignalRecord


def adapt_confluence_signals(
    df: pd.DataFrame,
    *,
    asset: str = "default",
    horizon: str = "4h",
) -> list[SignalRecord]:
    """Convert legacy PA confluence signals to ``SignalRecord`` rows.

    Parameters
    ----------
    df:
        OHLCV DataFrame with columns ``open``, ``high``, ``low``,
        ``close``, ``volume`` and a DatetimeIndex.
    asset:
        Asset identifier for the emitted signals.
    horizon:
        Signal horizon (default ``"4h"`` to match the legacy strategy).

    Returns
    -------
    list[SignalRecord]
        One ``SignalRecord`` for every non-zero legacy signal.

    Notes
    -----
    The legacy ``confluence_signals`` function returns a DataFrame with
    a ``signal`` column (values: -1, 0, 1).  This adapter converts each
    non-zero entry to a ``SignalRecord`` where:

    - ``decision_time`` = ``available_time`` = the bar's timestamp
      (the signal is available at bar close, the earliest decision point).
    - ``direction`` = the legacy signal value (-1 or 1).
    - ``confidence`` = 0.5 (neutral; the legacy strategy does not emit confidence).
    - ``payload`` includes ``factor_id``, ``factor_version``, ``horizon``,
      and ``value`` (float version of direction).
    """
    from strategies.price_action import confluence_signals

    result = confluence_signals(df)

    signals: list[SignalRecord] = []
    for ts, row in result.iterrows():
        sig = int(row["signal"])
        if sig == 0:
            continue

        # Ensure the timestamp is timezone-aware
        ts_aware: datetime
        if isinstance(ts, pd.Timestamp):
            if ts.tzinfo is None:
                ts_aware = ts.to_pydatetime().replace(tzinfo=UTC)
            else:
                ts_aware = ts.to_pydatetime()
        elif isinstance(ts, datetime):
            ts_aware = ts if ts.tzinfo is not None else ts.replace(tzinfo=UTC)
        else:
            ts_aware = datetime(2026, 1, 1, tzinfo=UTC)

        signals.append(
            SignalRecord(
                asset=asset,
                decision_time=ts_aware,
                available_time=ts_aware,
                direction=sig,
                confidence=0.5,
                payload={
                    "factor_id": "legacy.pa_confluence",
                    "factor_version": "baseline-0",
                    "horizon": horizon,
                    "value": float(sig),
                },
            )
        )

    return signals


def signal_count(df: pd.DataFrame, **kwargs: Any) -> int:
    """Return the number of non-zero signals emitted by the legacy strategy."""
    return len(adapt_confluence_signals(df, **kwargs))
