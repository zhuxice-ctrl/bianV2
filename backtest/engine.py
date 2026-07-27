"""
回测引擎：事件驱动模拟价格行为学策略交易。

特性：
- 每次只持有一个仓位（趋势跟随策略典型设置）
- 进场后用 stop/target 管理出场，或趋势反转平仓
- 包含手续费（0.04% taker）与滑点
- 输出交易明细、权益曲线、绩效指标
"""
import numpy as np
import pandas as pd

TAKER_FEE = 0.0004  # 0.04% taker 手续费
SLIPPAGE = 0.0005   # 0.05% 滑点


def run_backtest(df_signals, initial_capital=10000.0, risk_pct=0.02):
    """
    执行回测。

    参数：
    - df_signals: confluence_signals 输出的带信号 DataFrame
    - initial_capital: 初始资金 (USDT)
    - risk_pct: 单笔风险占资金比例

    返回 dict:
        trades: 交易明细 DataFrame
        equity: 每根 K 线的权益曲线 Series
        metrics: 绩效指标 dict
    """
    # 保留 datetime 索引用于位置查找（不要 reset_index）
    rows = df_signals.dropna(subset=["entry", "stop", "target"]).copy()
    rows = rows[rows["signal"] != 0]

    trades = []
    equity_curve = []
    capital = initial_capital
    peak = capital
    max_dd = 0.0
    # 用于权益曲线：从原始 df 构造
    df = df_signals.copy()
    pos_equity = np.full(len(df), np.nan)

    idx_map = {d: k for k, d in enumerate(df.index)}
    last_exit_idx = -1  # 上一笔平仓位置，避免重叠
    for _, r in rows.iterrows():
        if capital <= 0:
            break
        side = int(r["signal"])
        entry = float(r["entry"])
        stop = float(r["stop"])
        target = float(r["target"])
        risk = abs(entry - stop)
        if risk <= 0 or np.isnan(risk):
            continue

        # 仓位：风险金额 / 单位风险
        risk_amount = capital * risk_pct
        qty = risk_amount / risk
        fee = qty * entry * (TAKER_FEE + SLIPPAGE)

        # 找到进场后的 K 线，逐根检查是否触及 stop/target
        start = idx_map.get(r.name)
        if start is None:
            continue
        if start <= last_exit_idx:
            continue  # 跳过与上一笔重叠的信号
        outcome = None
        exit_price = None
        exit_idx = None
        for j in range(start + 1, len(df)):
            hi = df.iloc[j]["high"]
            lo = df.iloc[j]["low"]
            if side == 1:
                if lo <= stop:
                    outcome = "loss"
                    exit_price = stop
                    exit_idx = j
                    break
                if hi >= target:
                    outcome = "win"
                    exit_price = target
                    exit_idx = j
                    break
            else:
                if hi >= stop:
                    outcome = "loss"
                    exit_price = stop
                    exit_idx = j
                    break
                if lo <= target:
                    outcome = "win"
                    exit_price = target
                    exit_idx = j
                    break
        if outcome is None:
            # 数据结束未触发，按最后收盘价平仓
            outcome = "open"
            exit_price = float(df.iloc[-1]["close"])
            exit_idx = len(df) - 1

        exit_fee = qty * exit_price * (TAKER_FEE + SLIPPAGE)
        pnl = (exit_price - entry) * qty * side - fee - exit_fee
        capital += pnl
        peak = max(peak, capital)
        dd = (capital - peak) / peak if peak > 0 else 0
        max_dd = min(max_dd, dd)

        trades.append({
            "entry_time": df.iloc[start]["datetime"] if "datetime" in df.columns else r.name,
            "exit_time": df.iloc[exit_idx]["datetime"] if "datetime" in df.columns else df.index[exit_idx],
            "side": "LONG" if side == 1 else "SHORT",
            "entry": round(entry, 4),
            "stop": round(stop, 4),
            "target": round(target, 4),
            "exit": round(exit_price, 4),
            "outcome": outcome,
            "pnl": round(pnl, 2),
            "equity": round(capital, 2),
            "bars_held": exit_idx - start,
            "return_pct": round(pnl / (qty * entry) * 100, 2),
        })
        last_exit_idx = exit_idx
        # 标记持仓期间的权益
        if exit_idx is not None:
            for jj in range(start, exit_idx + 1):
                if side == 1:
                    unreal = (df.iloc[jj]["close"] - entry) * qty - fee
                else:
                    unreal = (entry - df.iloc[jj]["close"]) * qty - fee
                pos_equity[jj] = capital - pnl + unreal if outcome != "open" else capital

    # 构造权益曲线
    for k in range(len(df)):
        if not np.isnan(pos_equity[k]):
            equity_curve.append(pos_equity[k])
        else:
            equity_curve.append(np.nan if not trades else (trades[-1]["equity"] if k > 0 else initial_capital))

    # 填充无持仓段为上次资金
    eq = pd.Series(equity_curve, index=df.index)
    eq = eq.ffill().fillna(initial_capital)

    metrics = compute_metrics(trades, eq, initial_capital, max_dd)
    return {
        "trades": pd.DataFrame(trades),
        "equity": eq,
        "metrics": metrics,
    }


def compute_metrics(trades, equity, initial_capital, max_dd):
    """计算绩效指标。"""
    if len(trades) == 0:
        return {"total_trades": 0, "final_equity": float(initial_capital), "total_return_pct": 0.0}
    tdf = trades if isinstance(trades, pd.DataFrame) else pd.DataFrame(trades)
    wins = tdf[tdf["outcome"] == "win"]
    losses = tdf[tdf["outcome"] == "loss"]
    final_eq = float(equity.iloc[-1])
    total_ret = (final_eq - initial_capital) / initial_capital * 100
    win_rate = len(wins) / len(tdf) * 100 if len(tdf) > 0 else 0
    avg_win = wins["pnl"].mean() if len(wins) > 0 else 0
    avg_loss = losses["pnl"].mean() if len(losses) > 0 else 0
    pf = (wins["pnl"].sum() / abs(losses["pnl"].sum())) if len(losses) > 0 and losses["pnl"].sum() != 0 else float("inf")
    # 年化（按 K 线数量粗估）
    return {
        "total_trades": len(tdf),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(win_rate, 2),
        "avg_win": round(float(avg_win), 2),
        "avg_loss": round(float(avg_loss), 2),
        "profit_factor": round(float(pf), 3) if pf != float("inf") else "inf",
        "total_pnl": round(float(tdf["pnl"].sum()), 2),
        "final_equity": round(final_eq, 2),
        "total_return_pct": round(total_ret, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "avg_bars_held": round(float(tdf["bars_held"].mean()), 1) if len(tdf) > 0 else 0,
        "best_trade": round(float(tdf["pnl"].max()), 2),
        "worst_trade": round(float(tdf["pnl"].min()), 2),
    }
