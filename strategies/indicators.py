"""
技术指标库：为价格行为学策略提供基础指标。
包含 ATR、EMA、swing 结构、支撑阻力位识别。
"""
import numpy as np
import pandas as pd


def ema(series, period):
    return series.ewm(span=period, adjust=False).mean()


def sma(series, period):
    return series.rolling(window=period).mean()


def atr(df, period=14):
    """Average True Range，衡量波动率，价格行为学核心指标。"""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        (high - low),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def swing_highs_lows(df, lookback=2):
    """
    识别 swing 高点/低点（分形结构）。
    lookback: 左右各 N 根比较。
    返回标记列：1=swing high, -1=swing low, 0=无。
    """
    high = df["high"].values
    low = df["low"].values
    n = len(df)
    marks = np.zeros(n, dtype=int)
    for i in range(lookback, n - lookback):
        if high[i] == max(high[i - lookback:i + lookback + 1]):
            marks[i] = 1
        if low[i] == min(low[i - lookback:i + lookback + 1]):
            marks[i] = -1
    return pd.Series(marks, index=df.index, name="swing")


def detect_trend(df, ema_fast=20, ema_slow=50):
    """
    趋势判定：EMA 多头排列 + 价格在 EMA20 之上 = 上升；
    EMA 空头排列 + 价格在 EMA20 之下 = 下降；否则震荡。
    返回 1/0/-1。
    """
    ef = ema(df["close"], ema_fast)
    es = ema(df["close"], ema_slow)
    trend = pd.Series(0, index=df.index)
    trend[(ef > es) & (df["close"] > ef)] = 1
    trend[(ef < es) & (df["close"] < ef)] = -1
    return trend


def find_support_resistance(df, lookback=50, tolerance=0.008):
    """
    基于近期 swing 极值聚类，找出关键支撑/阻力区。
    返回 (resistance_levels, support_levels) 列表。
    """
    swings = swing_highs_lows(df, lookback=3)
    recent = df.tail(lookback * 3)
    rs = recent.loc[swings.recent.index[swings.recent.values == 1], "high"] if False else None

    highs = df.loc[swings[swings == 1].index, "high"].tail(lookback)
    lows = df.loc[swings[swings == -1].index, "low"].tail(lookback)

    def cluster(levels):
        if len(levels) == 0:
            return []
        lv = sorted(levels.values)
        groups = [[lv[0]]]
        for v in lv[1:]:
            if abs(v - np.mean(groups[-1])) / np.mean(groups[-1]) < tolerance:
                groups[-1].append(v)
            else:
                groups.append([v])
        return [float(np.mean(g)) for g in groups]

    return cluster(highs), cluster(lows)
