"""Causal forward return labels.

This module is intentionally isolated from production factor modules.
No ``bian_quant.factors.*`` module other than this one may import it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

_EXECUTION_FIELDS = ("open", "volume", "quote_volume")
_EXPECTED_INTERVAL = np.timedelta64(1, "h")


def forward_log_return(close: pd.Series, *, periods: int) -> pd.Series:
    """Compute the forward log return as a prediction label.

    Parameters
    ----------
    close
        Close price series aligned to the bar index.
    periods
        Number of bars to look forward.  Must be positive.

    Returns
    -------
    Series of ``log(close[t+periods] / close[t])`` with NaN for the
    last ``periods`` bars.
    """
    if periods <= 0:
        raise ValueError("periods must be positive")
    ratio = (close.shift(-periods) / close).to_numpy(dtype=float)
    return pd.Series(
        np.log(ratio),
        index=close.index,
        name=f"forward_log_return_{periods}",
        dtype=float,
    )


def forward_open_to_open_log_return(
    frame: pd.DataFrame,
    *,
    holding_bars: int,
) -> tuple[pd.Series, pd.Series]:
    """Compute forward open-to-open log return labels with strict continuity.

    Entry is ``open[t+1]`` and exit is ``open[t+1 + holding_bars]``.
    Every bar on the entry-to-exit path (inclusive) must be present with
    a strictly-continuous ``event_time`` (exactly one hour apart) and have
    positive, finite ``open``, ``volume``, and ``quote_volume``.

    Parameters
    ----------
    frame
        DataFrame with columns: asset, event_time, open, volume, quote_volume.
    holding_bars
        Number of bars to hold.  Must be positive (1 = primary 1h label).

    Returns
    -------
    tuple of (values, reasons)
        *values*: log return or NaN.
        *reasons*: missing-value reason code or empty string.
    """
    if holding_bars <= 0:
        raise ValueError("holding_bars must be positive")

    required = {"asset", "event_time", "open", "volume", "quote_volume"}
    missing_cols = required - set(frame.columns)
    if missing_cols:
        raise ValueError(f"missing required columns: {sorted(missing_cols)}")

    values = pd.Series(np.nan, index=frame.index, dtype=float)
    reasons = pd.Series("", index=frame.index, dtype=object)
    values.name = f"forward_open_to_open_log_return_{holding_bars}"
    reasons.name = "forward_open_to_open_reason"

    for _asset, asset_frame in frame.groupby("asset", sort=True):
        idx = asset_frame.index
        et = asset_frame["event_time"].to_numpy()
        opens = asset_frame["open"].to_numpy(dtype=float)
        vols = asset_frame["volume"].to_numpy(dtype=float)
        qvs = asset_frame["quote_volume"].to_numpy(dtype=float)
        m = len(asset_frame)

        for i in range(m):
            entry = i + 1
            exit_bar = i + 1 + holding_bars
            if exit_bar >= m:
                reasons.loc[idx[i]] = "MISSING_NEXT_BAR"
                continue

            bad = False
            for j in range(i + 1, exit_bar + 1):
                if j >= m:
                    reasons.loc[idx[i]] = "MISSING_NEXT_BAR"
                    bad = True
                    break
                expected = et[j - 1] + _EXPECTED_INTERVAL
                if et[j] != expected:
                    reasons.loc[idx[i]] = "MISSING_NEXT_BAR"
                    bad = True
                    break

            if bad:
                continue

            trigger: list[str] = []
            for j in range(i + 1, exit_bar + 1):
                for field_name, arr in zip(
                    _EXECUTION_FIELDS, (opens, vols, qvs), strict=True
                ):
                    val = arr[j]
                    if (not np.isfinite(val) or val <= 0) and field_name not in trigger:
                        trigger.append(field_name)

            if trigger:
                reasons.loc[idx[i]] = "EXECUTION_BAR_INVALID"
                continue

            entry_open = opens[entry]
            exit_open = opens[exit_bar]
            if not np.isfinite(entry_open) or entry_open <= 0:
                reasons.loc[idx[i]] = "EXECUTION_BAR_INVALID"
                continue
            if not np.isfinite(exit_open) or exit_open <= 0:
                reasons.loc[idx[i]] = "EXECUTION_BAR_INVALID"
                continue

            values.loc[idx[i]] = float(np.log(exit_open / entry_open))

    return values, reasons
