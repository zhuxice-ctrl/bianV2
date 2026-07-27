# 多策略回测 + 防过拟合验证报告

生成时间：2026-07-27 03:08  

随机种子：20260727（可复现）

策略数量：5  |  币种：BTCUSDT, ETHUSDT, BNBUSDT  |  总回测次数：165


## 综合评分排名

| 排名 | 策略 | Baseline均收益 | 分段通过率 | OOS通过率 | OOS均收益 | 扰动通过率 | 综合得分 |
|------|------|---------------|-----------|----------|----------|-----------|---------|
| 1 | PA-Fast-Trend | +8.86% | 75.0% | 33.3% | -5.64% | 66.7% | **43.07** |
| 2 | PA-PinBar-Only | +5.16% | 50.0% | 33.3% | -5.19% | 77.8% | **37.94** |
| 3 | PA-Confluence-Baseline | +11.53% | 75.0% | 0.0% | -7.47% | 77.8% | **37.76** |
| 4 | PA-WideStop-Conservative | +0.14% | 33.3% | 33.3% | -3.58% | 77.8% | **32.26** |
| 5 | PA-RR2-Aggressive | +8.54% | 50.0% | 0.0% | -12.03% | 77.8% | **30.62** |

## 协议 1：In-Sample Baseline（全量数据）

| 策略 | 币种 | 周期 | 收益 | 胜率 | PF | 回撤 | 交易数 |
|------|------|------|------|------|-----|------|--------|
| PA-Confluence-Baseline | BTCUSDT | 4h | +27.85% | 33.3% | 1.247 | -17.64% | 63 |
| PA-Confluence-Baseline | BTCUSDT | 1d | +0.51% | 26.1% | 1.03 | -10.98% | 23 |
| PA-Confluence-Baseline | ETHUSDT | 4h | +16.04% | 29.5% | 1.128 | -28.37% | 61 |
| PA-Confluence-Baseline | ETHUSDT | 1d | +15.43% | 41.7% | 2.018 | -4.06% | 12 |
| PA-Confluence-Baseline | BNBUSDT | 4h | -7.39% | 26.1% | 0.938 | -23.61% | 65 |
| PA-Confluence-Baseline | BNBUSDT | 1d | +16.72% | 33.3% | 1.472 | -9.91% | 21 |
| PA-Fast-Trend | BTCUSDT | 4h | +19.58% | 31.4% | 1.186 | -16.54% | 70 |
| PA-Fast-Trend | BTCUSDT | 1d | +10.38% | 30.8% | 1.289 | -11.94% | 26 |
| PA-Fast-Trend | ETHUSDT | 4h | +4.80% | 27.4% | 1.016 | -31.46% | 73 |
| PA-Fast-Trend | ETHUSDT | 1d | +8.44% | 33.3% | 1.383 | -7.97% | 15 |
| PA-Fast-Trend | BNBUSDT | 4h | -7.70% | 26.5% | 0.928 | -26.70% | 68 |
| PA-Fast-Trend | BNBUSDT | 1d | +17.65% | 34.8% | 1.548 | -7.09% | 23 |
| PA-WideStop-Conservative | BTCUSDT | 4h | -12.47% | 13.6% | 0.572 | -16.01% | 22 |
| PA-WideStop-Conservative | BTCUSDT | 1d | +5.34% | 28.6% | 1.892 | -4.52% | 7 |
| PA-WideStop-Conservative | ETHUSDT | 4h | -0.35% | 17.6% | 0.845 | -10.89% | 17 |
| PA-WideStop-Conservative | ETHUSDT | 1d | +1.20% | 0.0% | inf | 0.00% | 1 |
| PA-WideStop-Conservative | BNBUSDT | 4h | -5.74% | 17.2% | 0.804 | -17.35% | 29 |
| PA-WideStop-Conservative | BNBUSDT | 1d | +12.85% | 33.3% | 2.093 | -4.52% | 12 |
| PA-PinBar-Only | BTCUSDT | 4h | +6.53% | 31.0% | 1.144 | -11.92% | 29 |
| PA-PinBar-Only | BTCUSDT | 1d | +5.89% | 30.8% | 1.362 | -10.01% | 13 |
| PA-PinBar-Only | ETHUSDT | 4h | +7.63% | 30.3% | 1.135 | -19.53% | 33 |
| PA-PinBar-Only | ETHUSDT | 1d | -6.45% | 14.3% | 0.454 | -9.85% | 7 |
| PA-PinBar-Only | BNBUSDT | 4h | +6.10% | 30.0% | 1.08 | -28.16% | 40 |
| PA-PinBar-Only | BNBUSDT | 1d | +11.24% | 33.3% | 1.551 | -6.09% | 12 |
| PA-RR2-Aggressive | BTCUSDT | 4h | +3.06% | 38.1% | 1.02 | -18.64% | 84 |
| PA-RR2-Aggressive | BTCUSDT | 1d | +0.45% | 34.6% | 1.025 | -14.50% | 26 |
| PA-RR2-Aggressive | ETHUSDT | 4h | +22.25% | 39.7% | 1.168 | -31.27% | 73 |
| PA-RR2-Aggressive | ETHUSDT | 1d | +11.28% | 46.1% | 1.591 | -5.42% | 13 |
| PA-RR2-Aggressive | BNBUSDT | 4h | -5.94% | 36.0% | 0.956 | -28.78% | 75 |
| PA-RR2-Aggressive | BNBUSDT | 1d | +20.13% | 44.0% | 1.523 | -7.97% | 25 |

## 协议 2：Random-Segment（随机分段一致性）

将 4h 数据按时间均分为 4 段，每段单独回测。检验策略在不同时间段的稳定性。

### PA-Confluence-Baseline

| 币种 | 段1 | 段2 | 段3 | 段4 | 一致性 |
|------|------|------|------|------|--------|
| BTCUSDT | +0.7% | +19.5% | +11.2% | +0.1% | 4/4 |
| ETHUSDT | +0.5% | +14.7% | -4.9% | +9.6% | 3/4 |
| BNBUSDT | +4.9% | +6.9% | -6.0% | -14.2% | 2/4 |

### PA-Fast-Trend

| 币种 | 段1 | 段2 | 段3 | 段4 | 一致性 |
|------|------|------|------|------|--------|
| BTCUSDT | +0.8% | +10.8% | +6.4% | +6.7% | 4/4 |
| ETHUSDT | +0.6% | +5.3% | -8.9% | +10.2% | 3/4 |
| BNBUSDT | +6.0% | +2.3% | -8.0% | -14.1% | 2/4 |

### PA-WideStop-Conservative

| 币种 | 段1 | 段2 | 段3 | 段4 | 一致性 |
|------|------|------|------|------|--------|
| BTCUSDT | -8.8% | +7.6% | -0.1% | -5.5% | 1/4 |
| ETHUSDT | -6.5% | -0.9% | -5.4% | +1.8% | 1/4 |
| BNBUSDT | +3.7% | +7.1% | -3.9% | -6.9% | 2/4 |

### PA-PinBar-Only

| 币种 | 段1 | 段2 | 段3 | 段4 | 一致性 |
|------|------|------|------|------|--------|
| BTCUSDT | +3.2% | -2.1% | +7.6% | -3.4% | 2/4 |
| ETHUSDT | +15.2% | -3.4% | -8.9% | +1.4% | 2/4 |
| BNBUSDT | +33.2% | +14.7% | -13.0% | -17.6% | 2/4 |

### PA-RR2-Aggressive

| 币种 | 段1 | 段2 | 段3 | 段4 | 一致性 |
|------|------|------|------|------|--------|
| BTCUSDT | +1.2% | -2.2% | +1.8% | -4.1% | 2/4 |
| ETHUSDT | +5.5% | +18.0% | -10.6% | +6.7% | 3/4 |
| BNBUSDT | -6.1% | +34.1% | -12.1% | -13.6% | 1/4 |

## 协议 3：Blind-Holdout（单盲留出验证）

前 70% 数据做 in-sample（策略选择），后 30% 做 out-of-sample（留出验证）。

| 策略 | 币种 | IS收益 | OOS收益 | IS交易 | OOS交易 | OOS判定 |
|------|------|--------|---------|--------|---------|---------|
| PA-Confluence-Baseline | BTCUSDT | +25.54% | -1.05% | 47 | 18 | fail |
| PA-Confluence-Baseline | ETHUSDT | +13.96% | -3.54% | 39 | 22 | fail |
| PA-Confluence-Baseline | BNBUSDT | +10.15% | -17.83% | 46 | 20 | fail |
| PA-Fast-Trend | BTCUSDT | +10.07% | +3.20% | 53 | 20 | pass |
| PA-Fast-Trend | ETHUSDT | -1.95% | -7.21% | 46 | 31 | fail |
| PA-Fast-Trend | BNBUSDT | +6.84% | -12.92% | 44 | 24 | fail |
| PA-WideStop-Conservative | BTCUSDT | -3.63% | -10.65% | 16 | 7 | fail |
| PA-WideStop-Conservative | ETHUSDT | -2.66% | -1.22% | 17 | 13 | fail |
| PA-WideStop-Conservative | BNBUSDT | +6.54% | +1.12% | 21 | 6 | pass |
| PA-PinBar-Only | BTCUSDT | -3.75% | +8.18% | 23 | 7 | pass |
| PA-PinBar-Only | ETHUSDT | +14.48% | -2.69% | 23 | 12 | fail |
| PA-PinBar-Only | BNBUSDT | +31.34% | -21.06% | 27 | 14 | fail |
| PA-RR2-Aggressive | BTCUSDT | +12.46% | -9.12% | 63 | 22 | fail |
| PA-RR2-Aggressive | ETHUSDT | +31.17% | -9.07% | 49 | 26 | fail |
| PA-RR2-Aggressive | BNBUSDT | +11.34% | -17.91% | 53 | 23 | fail |

## 协议 4：Perturbation（扰动稳健性）

对价格数据注入噪声、截断、插入扰动，检验策略在数据扰动后的稳健性。

### PA-Confluence-Baseline

| 币种 | 噪声 | 截断 | 插入 | 通过率 |
|------|------|------|------|--------|
| BTCUSDT | -22.7% | +32.4% | +27.9% | 2/3 |
| ETHUSDT | -4.9% | +30.9% | +16.0% | 3/3 |
| BNBUSDT | -3.5% | -2.0% | -7.4% | 2/3 |

### PA-Fast-Trend

| 币种 | 噪声 | 截断 | 插入 | 通过率 |
|------|------|------|------|--------|
| BTCUSDT | -36.9% | +26.8% | +19.6% | 2/3 |
| ETHUSDT | -7.5% | +6.2% | +2.5% | 2/3 |
| BNBUSDT | +10.8% | +0.7% | -7.7% | 2/3 |

### PA-WideStop-Conservative

| 币种 | 噪声 | 截断 | 插入 | 通过率 |
|------|------|------|------|--------|
| BTCUSDT | -0.9% | -1.0% | -12.5% | 2/3 |
| ETHUSDT | +6.9% | +1.8% | -0.3% | 3/3 |
| BNBUSDT | +1.4% | +1.4% | -5.7% | 2/3 |

### PA-PinBar-Only

| 币种 | 噪声 | 截断 | 插入 | 通过率 |
|------|------|------|------|--------|
| BTCUSDT | -20.4% | +5.4% | +4.2% | 2/3 |
| ETHUSDT | +9.8% | -12.5% | +5.3% | 2/3 |
| BNBUSDT | +8.8% | +0.3% | +3.8% | 3/3 |

### PA-RR2-Aggressive

| 币种 | 噪声 | 截断 | 插入 | 通过率 |
|------|------|------|------|--------|
| BTCUSDT | -4.8% | +0.3% | +0.2% | 3/3 |
| ETHUSDT | +5.5% | +3.2% | +22.2% | 3/3 |
| BNBUSDT | +7.8% | -11.1% | -5.9% | 1/3 |

## 正式策略建议

基于四维综合评分，**PA-Fast-Trend** 以 43.07 分排名第一。

- Baseline 平均收益：+8.86%
- 分段通过率：75.0%
- OOS 通过率：33.3%（均收益 -5.64%）
- 扰动通过率：66.7%

**策略参数**：

```json
{
  "ema_trend": 100,
  "ema_fast": 10,
  "ema_slow": 30,
  "atr_period": 14,
  "atr_stop_mult": 1.5,
  "rr_ratio": 3.0,
  "risk_pct": 0.02,
  "vol_min": 0.005,
  "vol_max": 0.05,
  "patterns": [
    "pin",
    "eng",
    "bos"
  ],
  "vol_filter": true
}
```

### 防过拟合评估

- **分段一致性**：75.0% 的分段实现正收益，策略在各时间段表现稳定。
- **单盲留出**：OOS 通过率 33.3%，留出集表现不稳定，需警惕过拟合。
- **扰动稳健性**：66.7% 的扰动测试通过，策略对数据扰动具有鲁棒性。