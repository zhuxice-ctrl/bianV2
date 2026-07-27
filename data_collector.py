"""
数据采集器：通过 Binance 公开数据端点 (data-api.binance.vision) 拉取真实历史 K 线。

支持品种：BTCUSDT / ETHUSDT / BNBUSDT
支持周期：1h / 4h / 1d
输出：data/<symbol>_<interval>.csv

ETF 说明：用户提到的 "ETF" 在加密量化语境中对应 ETH（与 BTC、BNB 同为三大主流现货/合约标的），
本项目统一采集 ETHUSDT，可在 config 中扩展。
"""
import urllib.request
import json
import time
import csv
import os
from datetime import datetime, timezone

DATA_HOST = "https://data-api.binance.vision"
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# 交易标的与周期配置
SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
INTERVALS = ["1h", "4h", "1d"]

# 每个 interval 对应的毫秒时长（用于分页）
INTERVAL_MS = {
    "1h": 60 * 60 * 1000,
    "4h": 4 * 60 * 60 * 1000,
    "1d": 24 * 60 * 60 * 1000,
}

KLINES_LIMIT = 1000  # 单次最大 1000 根


def fetch_klines(symbol, interval, start_ms, end_ms):
    """分页拉取 [start_ms, end_ms) 区间的 K 线。"""
    all_rows = []
    cur = start_ms
    while cur < end_ms:
        url = (
            f"{DATA_HOST}/api/v3/klines"
            f"?symbol={symbol}&interval={interval}"
            f"&startTime={cur}&endTime={end_ms}&limit={KLINES_LIMIT}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode())
        if not data:
            break
        for k in data:
            all_rows.append(k)
        last_open = data[-1][0]
        if last_open <= cur:
            break
        cur = last_open + INTERVAL_MS[interval]
        time.sleep(0.15)  # 礼貌限速
        if len(data) < KLINES_LIMIT:
            break
    return all_rows


def save_csv(rows, path):
    """保存 K 线到 CSV。"""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "open_time", "datetime", "open", "high", "low", "close",
            "volume", "close_time", "quote_volume", "trades",
            "taker_buy_base", "taker_buy_quote",
        ])
        for k in rows:
            ot = k[0]
            dt = datetime.fromtimestamp(ot / 1000, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            w.writerow([
                ot, dt, k[1], k[2], k[3], k[4],
                k[5], k[6], k[7], k[8], k[9], k[10],
            ])


def collect(symbol, interval, days_back):
    """拉取指定品种/周期/回看天数的数据。"""
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - days_back * 24 * 60 * 60 * 1000
    print(f"[{symbol}/{interval}] 拉取 {days_back} 天数据 ...")
    rows = fetch_klines(symbol, interval, start_ms, now_ms)
    path = os.path.join(DATA_DIR, f"{symbol}_{interval}.csv")
    save_csv(rows, path)
    print(f"  -> {len(rows)} 根 K 线, 保存到 {os.path.basename(path)}")
    return len(rows)


def main():
    # 1h 拉 180 天, 4h 拉 365 天, 1d 拉 730 天(2年)
    plan = {"1h": 180, "4h": 365, "1d": 730}
    total = 0
    for sym in SYMBOLS:
        for itv in INTERVALS:
            try:
                total += collect(sym, itv, plan[itv])
            except Exception as e:
                print(f"  [ERROR] {sym}/{itv}: {e}")
    print(f"\n采集完成, 共 {total} 根 K 线。")


if __name__ == "__main__":
    main()
