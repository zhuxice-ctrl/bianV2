from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class VectorResult:
    positions: pd.Series
    gross_returns: pd.Series
    costs: pd.Series
    net_returns: pd.Series


def vector_backtest(frame: pd.DataFrame, *, cost_bps: float) -> VectorResult:
    required = {"signal", "forward_return"}
    if not required <= set(frame.columns):
        raise ValueError(f"vector input is missing columns: {sorted(required - set(frame.columns))}")
    if cost_bps < 0:
        raise ValueError("cost_bps must be non-negative")
    if frame[["signal", "forward_return"]].isna().any().any():
        raise ValueError("vector input must not contain missing values")

    positions = frame["signal"].shift(1).fillna(0.0).clip(-1.0, 1.0)
    gross_returns = positions * frame["forward_return"]
    turnover = positions.diff().abs().fillna(positions.abs())
    costs = turnover * cost_bps / 10_000.0
    return VectorResult(
        positions=positions,
        gross_returns=gross_returns,
        costs=costs,
        net_returns=gross_returns - costs,
    )
