# Price Action Confluence | 量化交易系统

> 基于价格行为学 (Price Action) 的加密货币量化交易系统，覆盖 BTC / ETH / BNB 三个标的，含真实数据采集、策略开发、回测引擎与 Web 操作面板。

## Research platform development

The reproducible research platform is being built alongside the frozen PA baseline. The PA system remains Baseline-0; new data, factors, models and backtests must use the common contracts under `src/bian_quant`.

```bash
uv sync --extra dev
uv run bian-quant init
bash scripts/check.sh
```

See `docs/superpowers/specs/2026-07-29-quant-research-platform-design.md` for approved scope.

## 项目结构

```
quant_price_action/
├── data_collector.py      # 数据采集器（Binance 公开 API）
├── run_backtest.py        # 回测主脚本
├── data/                  # 真实历史 K 线数据 (CSV)
│   ├── BTCUSDT_1h.csv / 4h.csv / 1d.csv
│   ├── ETHUSDT_1h.csv / 4h.csv / 1d.csv
│   └── BNBUSDT_1h.csv / 4h.csv / 1d.csv
├── strategies/            # 价格行为学策略
│   ├── indicators.py      # 技术指标 (ATR / EMA / swing 结构)
│   └── price_action.py    # 形态识别 + 融合信号系统
├── backtest/
│   └── engine.py          # 事件驱动回测引擎
├── results/               # 回测结果 (JSON)
├── dashboard/             # Web 操作面板
│   ├── generate.py        # 看板生成器
│   ├── server.py          # FastAPI 本地服务器
│   └── index.html         # 自包含交互式看板
└── docs/
    └── TRADING_SYSTEM.md  # 交易系统文档
```

## 快速开始

### 1. 安装依赖

```bash
pip install pandas numpy plotly fastapi uvicorn
```

### 2. 采集数据（真实 Binance 历史 K 线）

```bash
python3 data_collector.py
```
采集 BTC/ETH/BNB 的 1h/4h/1d 周期数据，约 21,000 根 K 线。

### 3. 运行回测

```bash
python3 run_backtest.py
```
对三个币种执行价格行为学策略回测，输出绩效指标和结果 JSON。

### 4. 启动 Web 操作面板

```bash
python3 dashboard/server.py
```
浏览器访问 `http://localhost:8787` 即可看到交互式量化看板。

## 回测结果摘要

| 币种 | 总收益 | 胜率 | 盈亏比 | 最大回撤 | 交易数 |
|------|--------|------|--------|----------|--------|
| BTC | +27.85% | 33.33% | 1.247 | -17.64% | 63 |
| ETH | +16.04% | 29.51% | 1.128 | -28.37% | 61 |
| BNB | -7.39% | 26.15% | 0.938 | -23.61% | 65 |

## 策略概述

**价格行为学融合策略 (Price Action Confluence)**

四层信号系统：
1. **主趋势过滤**：EMA200 多空分水岭
2. **次级趋势确认**：EMA20/EMA50 结构
3. **形态信号**：Pin Bar / Engulfing / Break of Structure
4. **风险管理**：2% 单笔风险，1.5×ATR 止损，1:3 盈亏比

详见 `docs/TRADING_SYSTEM.md`。

## 技术说明

- 数据源：Binance 公开数据端点 `data-api.binance.vision`
- 回测引擎：自研事件驱动，含手续费(0.04%)和滑点(0.05%)
- ETF 说明：用户提及的"ETF"对应 ETH（加密量化三大主流标的之一）
- 本系统为回测研究，不构成投资建议
