"""
价格行为学 (Price Action) 形态识别。

价格行为学核心理念：抛弃滞后指标，直接阅读 K 线结构与多空力量，
在关键位置 (支撑/阻力/趋势) 结合形态确认进场。

实现形态：
1. Pin Bar (针杆/锤子线) —— 长影线拒绝
2. Engulfing (吞没) —— 多空力量反转
3. Inside Bar (内包线) —— 盘整蓄势
4. Break of Structure (结构突破) —— 趋势延续/反转确认
"""
import numpy as np
import pandas as pd
from .indicators import atr, ema, swing_highs_lows, detect_trend


def _body(candle):
    """实体大小。"""
    return abs(candle["close"] - candle["open"])


def _upper_wick(candle):
    return candle["high"] - max(candle["open"], candle["close"])


def _lower_wick(candle):
    return min(candle["open"], candle["close"]) - candle["low"]


def pin_bar(df, atr_series, min_ratio=0.6, body_max=0.35):
    """
    Pin Bar 识别：
    - 影线 >= ATR * min_ratio
    - 实体 <= 全高的 body_max 比例
    - 方向：下影线长 = 看多(1)，上影线长 = 看空(-1)
    返回信号 Series：1/-1/0
    """
    sig = pd.Series(0, index=df.index)
    rng = df["high"] - df["low"]
    rng = rng.replace(0, np.nan)
    body = (df["close"] - df["open"]).abs()
    uw = df["high"] - df[["open", "close"]].max(axis=1)
    lw = df[["open", "close"]].min(axis=1) - df["low"]

    wick_dom_lower = (lw >= atr_series * min_ratio) & (body <= rng * body_max) & (lw > uw)
    wick_dom_upper = (uw >= atr_series * min_ratio) & (body <= rng * body_max) & (uw > lw)
    sig[wick_dom_lower] = 1
    sig[wick_dom_upper] = -1
    return sig


def engulfing(df):
    """
    Engulfing 吞没识别：
    - 看多吞没：前阴后阳，阳实体完全包住阴实体
    - 看空吞没：前阳后阴，阴实体完全包住阳实体
    返回信号 Series：1/-1/0
    """
    sig = pd.Series(0, index=df.index)
    o, c = df["open"], df["close"]
    prev_bear = c.shift(1) < o.shift(1)
    prev_bull = c.shift(1) > o.shift(1)
    cur_bull = c > o
    cur_bear = c < o

    bull_eng = prev_bear & cur_bull & (c > o.shift(1)) & (o < c.shift(1))
    bear_eng = prev_bull & cur_bear & (c < o.shift(1)) & (o > c.shift(1))
    sig[bull_eng] = 1
    sig[bear_eng] = -1
    return sig


def inside_bar(df):
    """
    Inside Bar 内包线：当前 K 线高低完全在上一根范围内 —— 盘整蓄势。
    方向需结合趋势判定。返回标记 Series：True/False
    """
    return (df["high"] <= df["high"].shift(1)) & (df["low"] >= df["low"].shift(1))


def break_of_structure(df, lookback=3):
    """
    Break of Structure：价格突破近期 swing 高/低 —— 趋势确认。
    突破 swing high = 看多(1)，突破 swing low = 看空(-1)
    """
    swings = swing_highs_lows(df, lookback)
    sig = pd.Series(0, index=df.index)
    # 找最近的 swing high/low
    sh = df["high"].where(swings == 1).ffill()
    sl = df["low"].where(swings == -1).ffill()
    sig[df["close"] > sh.shift(1)] = 1
    sig[df["close"] < sl.shift(1)] = -1
    # 只在突破当根标记
    sig = sig.diff().fillna(0).clip(-1, 1)
    return sig


def confluence_signals(df, atr_period=14, ema_fast=20, ema_slow=50, ema_trend=200,
                        rr_ratio=3.0, atr_filter=True):
    """
    价格行为学综合交易系统 —— 多重确认融合。

    信号生成逻辑（顺势交易，逆势过滤）：
    1. 主趋势：EMA200 作为多空分水岭（高于看多环境，低于看空环境）
    2. 次级趋势：EMA20/EMA50 结构确认
    3. 计算 ATR 波动率 + 波动率过滤（避免在极端波动中交易）
    4. 识别 Pin Bar / Engulfing 形态 + 结构突破
    5. 融合：主趋势方向 + 次级趋势 + 形态确认 = 进场信号
    6. 风险管理：止损 1.5×ATR，止盈 rr_ratio 倍风险

    返回带信号列的 DataFrame。
    """
    out = df.copy()
    out["atr"] = atr(out, atr_period)
    out["ema_fast"] = ema(out["close"], ema_fast)
    out["ema_slow"] = ema(out["close"], ema_slow)
    out["ema_trend"] = ema(out["close"], ema_trend)
    out["trend"] = detect_trend(out, ema_fast, ema_slow)
    out["pin"] = pin_bar(out, out["atr"])
    out["eng"] = engulfing(out)
    out["bos"] = break_of_structure(out)

    # 主趋势过滤：收盘价在 EMA200 之上 = 多头环境，之下 = 空头环境
    master_bull = out["close"] > out["ema_trend"]
    master_bear = out["close"] < out["ema_trend"]

    # 波动率过滤：ATR/Close 比率在 0.5%~5% 之间才交易
    atr_pct = out["atr"] / out["close"]
    vol_ok = atr_pct.between(0.005, 0.05) if atr_filter else True

    # 综合信号：主趋势 + 次级趋势 + 形态 三重确认
    long_cond = master_bull & (out["trend"] == 1) & vol_ok & (
        (out["pin"] == 1) | (out["eng"] == 1) | (out["bos"] == 1)
    )
    short_cond = master_bear & (out["trend"] == -1) & vol_ok & (
        (out["pin"] == -1) | (out["eng"] == -1) | (out["bos"] == -1)
    )

    out["signal"] = 0
    out.loc[long_cond, "signal"] = 1
    out.loc[short_cond, "signal"] = -1

    # 进场价 = 下一根开盘（避免未来函数）
    out["entry"] = out["open"].shift(-1)
    # 止损 = 信号 K 线的 ATR 倍数
    out["stop"] = np.where(
        out["signal"] == 1, out["entry"] - out["atr"] * 1.5,
        np.where(out["signal"] == -1, out["entry"] + out["atr"] * 1.5, np.nan)
    )
    # 止盈 = rr_ratio 倍风险 (1:3 盈亏比)
    risk = (out["entry"] - out["stop"]).abs()
    out["target"] = np.where(
        out["signal"] == 1, out["entry"] + risk * rr_ratio,
        np.where(out["signal"] == -1, out["entry"] - risk * rr_ratio, np.nan)
    )
    return out
