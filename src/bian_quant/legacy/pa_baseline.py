from pathlib import Path
from typing import Any

import pandas as pd


def replay_all(repo_root: Path) -> dict[str, Any]:
    from backtest.engine import run_backtest
    from strategies.price_action import confluence_signals

    results: dict[str, dict[str, Any]] = {}
    for symbol in ("BTCUSDT", "ETHUSDT", "BNBUSDT"):
        path = repo_root / "data" / f"{symbol}_4h.csv"
        frame = pd.read_csv(path, parse_dates=["datetime"]).set_index("datetime").sort_index()
        signals = confluence_signals(frame)
        metrics = run_backtest(signals, initial_capital=10_000.0, risk_pct=0.02)["metrics"]
        results[symbol] = {
            "total_return_pct": metrics["total_return_pct"],
            "win_rate_pct": metrics["win_rate_pct"],
            "profit_factor": metrics["profit_factor"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "total_trades": metrics["total_trades"],
            "final_equity": metrics["final_equity"],
        }
    return {
        "strategy": "价格行为学融合策略 (Price Action Confluence)",
        "symbols": ["BTCUSDT", "ETHUSDT", "BNBUSDT"],
        "interval": "4h",
        "initial_capital": 10_000.0,
        "risk_per_trade": 0.02,
        "fee": 0.0004,
        "results": results,
    }
