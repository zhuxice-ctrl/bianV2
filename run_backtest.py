"""
主运行脚本：加载数据 -> 生成价格行为学信号 -> 回测 -> 输出结果 JSON。

对 BTC/ETH/BNB 的 4h 周期执行回测，结果写入 results/ 供 Web 看板读取。
"""
import os
import json
import sys
import numpy as np
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE)

from strategies.price_action import confluence_signals
from backtest.engine import run_backtest

DATA_DIR = os.path.join(BASE, "data")
RESULT_DIR = os.path.join(BASE, "results")
os.makedirs(RESULT_DIR, exist_ok=True)

# 回测配置
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
INTERVAL = "4h"          # 主交易周期
INIT_CAPITAL = 10000.0   # 初始资金 USDT
RISK_PCT = 0.02          # 单笔风险 2%


def load_csv(symbol, interval):
    path = os.path.join(DATA_DIR, f"{symbol}_{interval}.csv")
    df = pd.read_csv(path, parse_dates=["datetime"])
    df = df.set_index("datetime").sort_index()
    # 数值化
    for c in ["open", "high", "low", "close", "volume"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"])
    return df


def numpy_safe(obj):
    """递归把 numpy / pandas 类型转成原生 Python 类型，便于 JSON 序列化。"""
    if isinstance(obj, dict):
        return {k: numpy_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [numpy_safe(v) for v in obj]
    if isinstance(obj, pd.Timestamp):
        return str(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        f = float(obj)
        return None if (np.isnan(f) or np.isinf(f)) else f
    if isinstance(obj, float):
        return None if (np.isnan(obj) or np.isinf(obj)) else obj
    return obj


def run_one(symbol):
    print(f"\n===== {symbol} / {INTERVAL} =====")
    df = load_csv(symbol, INTERVAL)
    print(f"  数据: {len(df)} 根, {df.index[0]} ~ {df.index[-1]}")

    sig = confluence_signals(df)
    long_n = (sig["signal"] == 1).sum()
    short_n = (sig["signal"] == -1).sum()
    print(f"  信号: 做多 {long_n}, 做空 {short_n}")

    result = run_backtest(sig, initial_capital=INIT_CAPITAL, risk_pct=RISK_PCT)
    m = result["metrics"]
    print(f"  交易: {m['total_trades']} | 胜率: {m['win_rate_pct']}% | "
          f"盈亏比PF: {m['profit_factor']} | 总收益: {m['total_return_pct']}% "
          f"| 最大回撤: {m['max_drawdown_pct']}%")

    # 价格曲线（抽样以减小体积）
    price = df["close"].iloc[::6].tolist()
    price_idx = [str(t) for t in df.index[::6].tolist()]
    # 权益曲线（抽样）
    eq = result["equity"].iloc[::6].tolist()
    eq_idx = [str(t) for t in result["equity"].index[::6].tolist()]
    # 交易明细（取最近 50 笔展示）
    trades_df = result["trades"]
    trades_list = trades_df.tail(50).to_dict(orient="records") if len(trades_df) > 0 else []
    # 形态统计
    pin_n = (sig["pin"] != 0).sum()
    eng_n = (sig["eng"] != 0).sum()
    bos_n = (sig["bos"] != 0).sum()

    out = {
        "symbol": symbol,
        "interval": INTERVAL,
        "data_range": {"start": str(df.index[0]), "end": str(df.index[-1]), "bars": len(df)},
        "metrics": m,
        "signal_stats": {"pin_bar": int(pin_n), "engulfing": int(eng_n), "bos": int(bos_n),
                          "long_signals": int(long_n), "short_signals": int(short_n)},
        "price_curve": {"x": price_idx, "y": [round(p, 2) for p in price]},
        "equity_curve": {"x": eq_idx, "y": [round(v, 2) for v in eq]},
        "trades": trades_list,
    }
    out = numpy_safe(out)
    path = os.path.join(RESULT_DIR, f"backtest_{symbol}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"  -> 结果写入 {os.path.basename(path)}")
    return out


def main():
    all_results = []
    for sym in SYMBOLS:
        try:
            all_results.append(run_one(sym))
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"  [ERROR] {sym}: {e}")

    # 汇总
    summary = {
        "strategy": "价格行为学融合策略 (Price Action Confluence)",
        "symbols": SYMBOLS,
        "interval": INTERVAL,
        "initial_capital": INIT_CAPITAL,
        "risk_per_trade": RISK_PCT,
        "fee": 0.0004,
        "results": {
            r["symbol"]: {
                "total_return_pct": r["metrics"]["total_return_pct"],
                "win_rate_pct": r["metrics"]["win_rate_pct"],
                "profit_factor": r["metrics"]["profit_factor"],
                "max_drawdown_pct": r["metrics"]["max_drawdown_pct"],
                "total_trades": r["metrics"]["total_trades"],
                "final_equity": r["metrics"]["final_equity"],
            }
            for r in all_results
        },
    }
    with open(os.path.join(RESULT_DIR, "summary.json"), "w", encoding="utf-8") as f:
        json.dump(numpy_safe(summary), f, ensure_ascii=False, indent=2)
    print("\n===== 汇总 =====")
    print(json.dumps(numpy_safe(summary["results"]), ensure_ascii=False, indent=2))
    print(f"\n全部结果保存在 {RESULT_DIR}")


if __name__ == "__main__":
    main()
