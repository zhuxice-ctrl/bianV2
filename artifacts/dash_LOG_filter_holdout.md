这是一套**深色极客风格的量化交易策略防过拟合回测实验控制台**，顶部标题为 `05 // EXPERIMENT LOG 回测实验留痕 · 多策略 × 防过拟合协议`，数据源为币安行情，当前共记录189笔交易，时间戳为2026-07-27 03:32:00。

---

## 一、协议状态 PROTOCOL STATUS
用户要求的四项防过拟合协议全部验证完成：
| 验证项       | 规则说明                                                     | 运行结果       | 状态   |
|--------------|--------------------------------------------------------------|----------------|--------|
| 样本内基线   | 全量 4h + 1d 数据基线回测                                    | 30 RUNS        | OK DONE |
| 随机分段     | 4h 数据均分4段独立回测，检验时间区段稳定性                    | 34/60 PASS     | OK DONE |
| 单盲留出     | 前70%训练 / 后30% OOS留出验证，选型过程不见留出集            | 3/15 OOS PASS  | OK DONE |
| 扰动注入     | ±0.5% 噪声 / 截断前15% / 插入5根扰动K线                      | 34/45 PASS     | OK DONE |

---

## 二、策略排名 STRATEGY RANKING
共5个策略参与排名，评分权重：`基线30% + 分段25% + OOS25% + 扰动20%`

| 排名 | 策略名 | 说明 | Baseline均收益 | 分段通过率 | OOS通过率 | OOS均收益 | 扰动通过率 | 综合得分 |
|-----|--------|------|----------------|------------|-----------|-----------|------------|----------|
| 1 | **PA-Fast-Trend** <br><sup>PA-002</sup> <span style="background:#0f0;color:#000;padding:0 4px;border-radius:2px">RECOMMENDED</span> | 快速趋势跟踪变体，缩短 EMA 至 100/10/30，更快响应趋势变化，适合高波动行情 | +8.86% | 75.0% | 33.3% | <span style="color:red">-5.64%</span> | 66.7% | 43.07 |
| 2 | PA-PinBar-Only <br><sup>PA-004</sup> | 仅 Pin Bar 形态版，剥离 Engulfing 和 BOS 信号，专注针形形态质量，减少信号数量但提高信号可靠性 | +5.16% | 50.0% | 33.3% | <span style="color:red">-5.19%</span> | 77.8% | 37.94 |
| 3 | PA-Confluence-Baseline <br><sup>PA-001</sup> | 原版价格行为学融合策略，EMA200 主趋势 + EMA20/50 次级确认 + Pin Bar/Engulfing/BOS 三形态 + 1.5×ATR 止损 | +11.53% | 75.0% | 0.0% | <span style="color:red">-7.47%</span> | 77.8% | 37.76 |
| 4 | PA-WideStop-Conservative <br><sup>PA-003</sup> | 保守止损版，2.5×ATR 止损给予更大呼吸空间，1:4 盈亏比追求更大趋势利润，1.5% 风险控制回撤 | +0.14% | 33.3% | 33.3% | <span style="color:red">-3.58%</span> | 77.8% | 32.26 |
| 5 | PA-RR2-Aggressive <br><sup>PA-005</sup> | 激进低盈亏比版，1:2 盈亏比 + 2.5% 风险，追求更高胜率和高频交易，适合震荡行情 | +8.54% | 50.0% | 0.0% | <span style="color:red">-12.03%</span> | 77.8% | 30.62 |

---

## 三、终端分析日志
### 普通分析结论
- Baseline 策略全量数据收益最高（均值+11.53%）但 OOS 通过率 0% —— 三币种留出集全部亏损，是过拟合的典型特征，防过拟合协议有效捕捉到了该风险。
- PA-Fast-Trend 综合排名第一（43.07分）：分段一致性最好（BTC 4/4 段全盈利）、OOS 通过率最高（BTC 留出集 +3.20%）、扰动稳健性可接受。
- 1d 周期表现普遍优于 4h —— Baseline 在 1d 上 BTC +9.5% / ETH +15.4% / BNB +16.7%，而 4h 上 BNB 亏损 -7.4%，策略更适合日线级别。
- BNB 在 4h 周期上所有策略全部亏损 —— 高波动性不适合当前框架，建议 4h 周期排除 BNB 或单独设计参数。
- 噪声注入对策略影响最大 —— 多个策略在 ±0.5% 噪声后翻负，实盘中需关注滑点控制。

### 正式策略建议（绿标高亮）
> 正式策略建议采用 PA-Fast-Trend（EMA100 主趋势 + EMA10/30 次级 + 1.5×ATR 止损 + 1:3 盈亏比 + 2% 风险）。分段一致性 75% 说明收益不是靠某段行情碰运气；OOS 通过率 33.3% 虽不高，但已是 5 个策略中最好的留出集表现。注意：当前 4h 数据仅 1 年（2190 根），样本量偏少，建议扩充至 2-3 年数据后重新验证，并优先在 1d 周期部署。

---

## 四、运行历史 RUN HISTORY
共165条实验记录，支持按协议/策略/币种/判定筛选，当前筛选后共展示30/165次运行，部分记录如下：

| RUN 编号 | 策略 | 币种 | 周期 | 协议 | 数据段 | 收益% | 胜率% | PF | 回撤% | 笔数 | 判定 | 备注 |
|----------|------|------|------|------|--------|-------|-------|----|-------|------|------|------|
| RUN-300 | PA-Confluence-Baseline | BTC | 4h | blind-holdout | in-sample(70%) | +25.54 | 34.0 | 1.34 | -18.07 | 47 | <span style="background:#d4a000;color:#000;padding:0 4px;border-radius:2px">CANDIDATE</span> | 训练集（前70%），用于策略选择 |
| RUN-301 | PA-Confluence-Baseline | BTC | 4h | blind-holdout | out-of-sample(30%) | -1.05 | 27.8 | 0.97 | -12.56 | 18 | <span style="background:red;color:#fff;padding:0 4px;border-radius:2px">FAIL</span> | 留出集（后30%），单盲验证 |
| RUN-302 | PA-Confluence-Baseline | ETH | 4h | blind-holdout | in-sample(70%) | +13.96 | 30.8 | 1.22 | -13.84 | 39 | <span style="background:#d4a000;color:#000;padding:0 4px;border-radius:2px">CANDIDATE</span> | 训练集（前70%），用于策略选择 |
| RUN-303 | PA-Confluence-Baseline | ETH | 4h | blind-holdout | out-of-sample(30%) | -3.54 | 22.7 | 0.80 | -23.16 | 22 | <span style="background:red;color:#fff;padding:0 4px;border-radius:2px">FAIL</span> | 留出集（后30%），单盲验证 |
| RUN-306 | PA-Fast-Trend | BTC | 4h | blind-holdout | in-sample(70%) | +10.07 | 30.2 | 1.12 | -15.08 | 53 | <span style="background:#d4a000;color:#000;padding:0 4px;border-radius:2px">CANDIDATE</span> | 训练集（前70%），用于策略选择 |
| RUN-307 | PA-Fast-Trend | BTC | 4h | blind-holdout | out-of-sample(30%) | +3.20 | 30.0 | 1.16 | -6.67 | 20 | <span style="background:green;color:#fff;padding:0 4px;border-radius:2px">PASS</span> | 留出集（后30%），单盲验证 |
| RUN-308 | PA-Fast-Trend | ETH | 4h | blind-holdout | in-sample(70%) | -1.95 | 26.1 | 0.97 | -17.50 | 46 | <span style="background:#d4a000;color:#000;padding:0 4px;border-radius:2px">CANDIDATE</span> | 训练集（前70%），用于策略选择 |
| RUN-309 | PA-Fast-Trend | ETH | 4h | blind-holdout | out-of-sample(30%) | -7.21 | 22.6 | 0.77 | -28.09 | 31 | <span style="background:red;color:#fff;padding:0 4px;border-radius:2px">FAIL</span> | 留出集（后30%），单盲验证 |