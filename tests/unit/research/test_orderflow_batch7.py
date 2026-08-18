"""Synthetic tests for the production Development input adapter."""

from __future__ import annotations

import numpy as np
import pandas as pd

from bian_quant.research.orderflow_batch7 import build_orderflow_gate_inputs


def _frame() -> pd.DataFrame:
    times = pd.date_range("2024-07-01", periods=240, freq="1h", tz="UTC")
    rows: list[dict[str, object]] = []
    for asset_index, asset in enumerate(("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")):
        for i, timestamp in enumerate(times):
            open_price = 100.0 + asset_index * 5.0 + i * (0.02 + asset_index * 0.003)
            volume = 1000.0 + i + asset_index * 20.0
            rows.append(
                {
                    "asset": asset,
                    "event_time": timestamp,
                    "available_time": timestamp,
                    "open": open_price,
                    "close": open_price,
                    "high": open_price + 1.0,
                    "low": open_price - 1.0,
                    "volume": volume,
                    "quote_volume": volume * open_price,
                    "taker_buy_base": volume * (0.2 + asset_index * 0.15),
                }
            )
    return pd.DataFrame(rows)


def test_build_inputs_freezes_complete_grid_and_development_cutoff() -> None:
    result = build_orderflow_gate_inputs(
        _frame(),
        development_start=pd.Timestamp("2024-07-01", tz="UTC").to_pydatetime(),
        development_end_exclusive=pd.Timestamp("2024-07-10", tz="UTC").to_pydatetime(),
    )

    assert result.development_rows == 4 * 9 * 24
    assert result.fold_count > 0
    assert result.preregistered_units
    assert len(result.slices) == len(result.preregistered_units) * 9
    assert {s.horizon for s in result.slices} == {"1h", "2h", "4h"}
    assert {s.q for s in result.slices} == {0.1, 0.2, 0.3}
    assert all(s.factor_id == "taker_orderflow_imbalance" for s in result.slices)
    assert all(np.isfinite(s.direction_estimate) for s in result.slices if s.p_value is not None)
