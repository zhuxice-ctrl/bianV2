"""Taker orderflow imbalance factor signal.

Computes a cross-sectional robust z-score of active buy volume share
(taker_buy_base / volume) using median/MAD normalization with clip [-5, 5].
"""

from __future__ import annotations

import numpy as np
import pandas as pd

MAD_SCALE = 1.4826
CLIP_LIMIT = 5.0


def taker_orderflow_imbalance(
    frame: pd.DataFrame,
) -> tuple[pd.Series, pd.Series]:
    """Compute cross-sectional taker buy-share robust z-score.

    Parameters
    ----------
    frame
        DataFrame with columns: asset, event_time, available_time,
        volume, taker_buy_base.

    Returns
    -------
    tuple of (values, reasons)
        *values*: clipped robust z-score or NaN.  Name: ``taker_orderflow_imbalance``.
        *reasons*: missing-value reason code or empty string.  Name: ``taker_orderflow_reason``.
    """
    required = {"asset", "event_time", "available_time", "volume", "taker_buy_base"}
    missing_cols = required - set(frame.columns)
    if missing_cols:
        raise ValueError(f"missing required columns: {sorted(missing_cols)}")

    work = frame[["asset", "event_time", "available_time", "volume", "taker_buy_base"]].copy()
    work["_values"] = np.nan
    work["_reasons"] = ""
    work["_buy_share"] = np.nan

    # --- identify invalid inputs ---
    vol_zero = ~np.isfinite(work["volume"].to_numpy(dtype=float)) | (work["volume"] <= 0)
    taker_missing = ~np.isfinite(work["taker_buy_base"].to_numpy(dtype=float))

    work.loc[vol_zero, "_reasons"] = "TAKER_VOLUME_ZERO"
    work.loc[taker_missing & ~vol_zero, "_reasons"] = "TAKER_FIELD_MISSING"

    # --- compute buy_share for valid rows ---
    valid_mask = work["_reasons"] == ""
    work.loc[valid_mask, "_buy_share"] = (
        work.loc[valid_mask, "taker_buy_base"] / work.loc[valid_mask, "volume"]
    )

    invalid_ratio = valid_mask & (
        ~np.isfinite(work["_buy_share"].to_numpy(dtype=float))
        | (work["_buy_share"] < 0)
        | (work["_buy_share"] > 1)
    )
    work.loc[invalid_ratio, "_reasons"] = "TAKER_RATIO_INVALID"
    valid_mask = work["_reasons"] == ""

    # --- cross-sectional median/MAD per available_time ---
    for _ts, group in work.loc[valid_mask].groupby("available_time", sort=True):
        peers = group["_buy_share"]
        if len(peers) < 2:
            work.loc[group.index, "_reasons"] = "INSUFFICIENT_PEER_COVERAGE"
            continue
        median = float(peers.median())
        mad = float((peers - median).abs().median())
        if mad <= 0:
            work.loc[group.index, "_reasons"] = "ZERO_CROSS_SECTIONAL_MAD_TAKER"
            continue
        z = (peers - median) / (mad * MAD_SCALE)
        work.loc[group.index, "_values"] = z.clip(-CLIP_LIMIT, CLIP_LIMIT)

    values = work["_values"].copy()
    values.name = "taker_orderflow_imbalance"
    reasons = work["_reasons"].copy()
    reasons.name = "taker_orderflow_reason"
    return values, reasons
