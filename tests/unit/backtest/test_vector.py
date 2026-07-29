import pandas as pd

from bian_quant.backtest.vector import vector_backtest


def test_signal_earns_only_next_bar_return() -> None:
    frame = pd.DataFrame(
        {"signal": [1.0, 0.0, 0.0], "forward_return": [0.10, -0.20, 0.30]}
    )
    result = vector_backtest(frame, cost_bps=0.0)
    assert result.net_returns.tolist() == [0.0, -0.20, 0.0]


def test_turnover_pays_cost() -> None:
    frame = pd.DataFrame(
        {"signal": [1.0, -1.0, 0.0], "forward_return": [0.0, 0.0, 0.0]}
    )
    result = vector_backtest(frame, cost_bps=10.0)
    assert result.costs.sum() == 0.003
    assert result.net_returns.sum() == -0.003
