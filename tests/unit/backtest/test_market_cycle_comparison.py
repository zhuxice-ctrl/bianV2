from __future__ import annotations

import pandas as pd

from bian_quant.backtest.market_cycle_comparison import run_market_cycle_comparison


def _popular(days: int) -> pd.DataFrame:
    rows = []
    for index in range(days):
        rows.append(
            {
                "selection_time": pd.Timestamp("2026-01-01", tz="UTC")
                + pd.Timedelta(days=index),
                "member_count": 12,
                "median_quote_volume": 100.0 + index,
                "median_oi_value": 200.0 + index,
                "top3_share": 0.35,
            }
        )
    return pd.DataFrame(rows)


def test_market_cycle_comparison_is_deterministic() -> None:
    returns = pd.DataFrame(
        {
            "date": pd.date_range("2026-02-01", periods=5, tz="UTC"),
            "BTCUSDT": [0.01, -0.01, 0.02, 0.00, 0.01],
            "ETHUSDT": [0.00, 0.01, -0.01, 0.01, 0.00],
            "BNBUSDT": [0.005, 0.005, 0.005, -0.005, 0.005],
        }
    )

    first = run_market_cycle_comparison(returns, _popular(70))
    second = run_market_cycle_comparison(returns, _popular(70))

    assert first.artifact_sha256 == second.artifact_sha256
    assert first.baseline.final_equity > 0
    assert first.confidence_weighted.final_equity > 0


def test_empty_returns_preserve_initial_equity() -> None:
    result = run_market_cycle_comparison(pd.DataFrame(), _popular(70))

    assert result.baseline.final_equity == 100.0
    assert result.confidence_weighted.final_equity == 100.0
    assert result.baseline.trade_count == 0


def test_outputs_remain_bounded_on_small_returns() -> None:
    returns = pd.DataFrame(
        {
            "date": pd.date_range("2026-02-01", periods=4, tz="UTC"),
            "BTCUSDT": [0.01, 0.01, 0.01, 0.01],
            "ETHUSDT": [0.01, 0.01, 0.01, 0.01],
            "BNBUSDT": [0.01, 0.01, 0.01, 0.01],
        }
    )

    result = run_market_cycle_comparison(returns, _popular(70))

    assert result.baseline.final_equity > 100.0
    assert result.baseline.final_equity < 200.0
    assert result.confidence_weighted.final_equity < 200.0
