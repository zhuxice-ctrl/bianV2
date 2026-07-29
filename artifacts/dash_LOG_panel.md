这是一套暗绿终端风格的**量化交易策略防过拟合验证系统界面**，整体为价格行为（PA）类策略的回测校验结果，各模块内容如下：

---

## 1. 协议测试状态 PROTOCOL STATUS
用户要求的四项防过拟合协议全部测试完成：
| 测试项 | 完成情况 | 测试规则 |
| ---- | ---- | ---- |
| 样本内基线 | 39 RUNS 全部完成 | 全量 4h + 1d 数据基线回测 |
| 随机分段 | 34/60 PASS 完成 | 4h 数据均分4段独立回测，检验时间段稳定性 |
| 单盲留出 | 3/15 OOS PASS 完成 | 前70%训练 / 后30% 留出验证，选型不见留出集 |
| 扰动注入 | 34/45 PASS 完成 | ±0.5% 噪声 / 截断前15% / 插入 5 根扰动 K 线 |

---

## 2. 策略排名 STRATEGY RANKING
共5款策略参评，综合评分权重：基线30% + 分段25% + 样本外（OOS）25% + 扰动20%，得分从高到低排序：
| 排名 | 策略名 | 说明 | Baseline均收益 | 分段通过率 | OOS通过率 | OOS均收益 | 扰动通过率 | 综合得分 |
| ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- |
| 1 | PA-Fast-Trend <font color=green>RECOMMENDED</font> | 快速趋势跟踪变体，缩短 EMA 至 100/18/30，更快响应趋势变化，适合高波动行情 | +8.86% | 75.0% | 33.3% | <font color=red>-5.64%</font> | 66.7% | 43.07 |
| 2 | PA-PinBar-Only | 仅 Pin Bar 形态逻辑，剥离 Engulfing 和 BOS 信号，专针杆形态质量，减少信号数量但提高单信号可靠性 | +5.16% | 50.0% | 33.3% | <font color=red>-5.19%</font> | 77.8% | 37.94 |
| 3 | PA-Confluence-Baseline | 原版价格行为学融合策略，EMA260 主趋势 + EMA20/50 次级确认 + Pin Bar/Engulfing/BOS 三形态 + 1.5xATR 止损 | +11.53% | 75.0% | 0.0% | <font color=red>-7.47%</font> | 77.8% | 37.76 |
| 4 | PA-WideStop-Conservative | 保守宽止损版，2.5xATR 止损给予更大呼吸空间，1:4 盈亏比追求更大趋势利润，1.5% 风险控制回撤 | +0.14% | 33.3% | 33.3% | <font color=red>-3.58%</font> | 77.8% | 32.26 |
| 5 | PA-RR2-Aggressive | 激进低盈亏比版，1:2 盈亏比 + 2.5% 风险，追求更高胜率和高频交易，适合震荡行情 | +8.54% | 50.0% | 0.0% | <font color=red>-12.03%</font> | 77.8% | 30.62 |

---

## 3. 分析日志与最终建议
数据源：BINANCE_VISION，成交笔数189，统计时间2026-07-27 03:32:06
> 👉 日志结论：
> - Baseline策略全量数据收益最高（均值+11.53%）但 OOS 通过率 0% —— 三币种留出集全部亏损，是过拟合的典型特征，防过拟合协议有效捕捉到了该风险。
> - PA-Fast-Trend 综合排名第一（43.07分）：分段一致性最好（BTC 4/4 段全盈利）、OOS 通过率最高（BTC 留出集+3.20%）、扰动稳健性可接受。
> - 1d 周期表现普遍优于 4h —— Baseline 在 1d 上 BTC +0.5% / ETH +15.4% / BNB +16.7%，而 4h 上 BNB 亏损 -7.4%，策略更适合日线级别。
> - BNB 在 4h 周期上所有策略全部亏损 —— 高波动特性不适合当前框架，建议 4h 周期排除 BNB 或单独设计参数。
> - 噪声注入对策略影响最大 —— 多个策略在 ±0.5% 噪声后翻负，实盘中需关注滑点控制。

> <font color=green>✅ 正式策略建议</font>：
> 正式策略建议采用 PA-Fast-Trend（EMA100 主趋势 + EMA10/30 次级 + 1.5xATR 止损 + 1:3 盈亏比 + 2% 风险）。分段一致性 75% 说明收益不是靠某段行情碰运气；OOS 通过率 33.3% 虽不高，但已是 5 个策略中最好的留出集表现。注意：当前 4h 数据仅 1 年（2190 根），样本量偏少，建议扩充至 2-3 年数据后重新验证，并优先在 1d 周期部署。

---

## 4. 运行历史 RUN HISTORY
共165条实验记录，支持按协议/策略/币种/判定筛选，当前展示前15条样本内基线测试记录：
| RUN编号 | 策略 | 币种 | 周期 | 协议 | 数据段 | 收益% | 胜率% | PF | 回撤% | 笔数 | 判定 | 备注 |
| ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- | ---- |
| RUN-001 | PA-Confluence-Baseline | BTC | 4h | in-sample baseline | full | +27.85 | 33.3 | 1.25 | -17.64 | 63 | BASELINE | 全量 4h 数据基线回测 |
| RUN-002 | PA-Confluence-Baseline | BTC | 1d | in-sample baseline | full | +0.51 | 26.1 | 1.03 | -10.98 | 23 | BASELINE | 全量 1d 数据基线回测 |
| RUN-003 | PA-Confluence-Baseline | ETH | 4h | in-sample baseline | full | +16.04 | 29.5 | 1.13 | -28.37 | 61 | BASELINE | 全量 4h 数据基线回测 |
| RUN-004 | PA-Confluence-Baseline | ETH | 1d | in-sample baseline | full | +15.43 | 41.7 | 2.02 | -4.06 | 12 | BASELINE | 全量 1d 数据基线回测 |
| RUN-005 | PA-Confluence-Baseline | BNB | 4h | in-sample baseline | full | <font color=red>-7.39</font> | 26.2 | 0.94 | -23.61 | 65 | BASELINE | 全量 4h 数据基线回测 |
| RUN-006 | PA-Confluence-Baseline | BNB | 1d | in-sample baseline | full | +16.72 | 33.3 | 1.47 | -9.91 | 21 | BASELINE | 全量 1d 数据基线回测 |
| RUN-007 | PA-Fast-Trend | BTC | 4h | in-sample baseline | full | +19.58 | 31.4 | 1.19 | -16.54 | 70 | BASELINE | 全量 4h 数据基线回测 |
| RUN-008 | PA-Fast-Trend | BTC | 1d | in-sample baseline | full | +10.38 | 30.8 | 1.29 | -11.94 | 26 | BASELINE | 全量 1d 数据基线回测 |
| RUN-009 | PA-Fast-Trend | ETH | 4h | in-sample baseline | full | +4.80 | 27.4 | 1.02 | -31.46 | 73 | BASELINE | 全量 4h 数据基线回测 |
| RUN-010 | PA-Fast-Trend | ETH | 1d | in-sample baseline | full | +8.44 | 33.3 | 1.38 | -7.97 | 15 | BASELINE | 全量 1d 数据基线回测 |
| RUN-011 | PA-Fast-Trend | BNB | 4h | in-sample baseline | full | <font color=red>-7.70</font> | 26.5 | 0.93 | -26.70 | 68 | BASELINE | 全量 4h 数据基线回测 |
| RUN-012 | PA-Fast-Trend | BNB | 1d | in-sample baseline | full | +17.65 | 34.8 | 1.55 | -7.09 | 23 | BASELINE | 全量 1d 数据基线回测 |
| RUN-013 | PA-WideStop-Conservative | BTC | 4h | in-sample baseline | full | <font color=red>-12.47</font> | 13.6 | 0.57 | -16.01 | 22 | BASELINE | 全量 4h 数据基线回测 |
| RUN-014 | PA-WideStop-Conservative | BTC | 1d | in-sample baseline | full | +5.34 | 28.6 | 1.89 | -4.52 | 7 | BASELINE | 全量 1d 数据基线回测 |
| RUN-015 | PA-WideStop-Conservative | ETH | 4h | in-sample baseline | full | <font color=red>-0.35</font> | 17.7 | 0.85 | -10.89 | 17 | BASELINE | 全量 4h 数据基线回测 |