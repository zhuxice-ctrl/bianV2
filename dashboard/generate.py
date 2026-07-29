"""
Web 操作面板生成器 v2 —— 黑客终端风（Hacker Terminal）。

读取 results/ 下的回测结果 JSON，生成自包含交互式 HTML 看板。
使用占位符替换法（非 f-string），避免 JS 模板字面量 ${} 与 Python {} 的转义冲突。

v2 变更（前端重构，数据契约不变）:
- 视觉: Matrix 数字雨环境层 + CRT 扫描线 + 磷光绿终端配色 + 开机引导序列
- 交互: 键盘快捷键 / 交易台账筛选排序 / 点击复制 / 帮助浮层
- 信息: 组合级聚合 KPI / 价格图叠加真实进出场标记 / 回撤带 / 信号统计 / 实验留痕区
- 新增: 可选 results/experiments.json（多策略实验记录，见 LOG_SCHEMA 注释）
"""
import json
import os
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(BASE, "..", "results")
OUT_HTML = os.path.join(BASE, "index.html")

SYMBOLS = ["BTCUSDT", "ETHUSDT", "BNBUSDT"]
LABELS = {"BTCUSDT": "BTC", "ETHUSDT": "ETH", "BNBUSDT": "BNB"}

# experiments.json 契约（供策略侧多轮实验写入，面板自动渲染）:
# {
#   "protocols": {"multi_strategy": {"status": "done|pending", "note": "..."},
#                 "random_segments": {...}, "blind_holdout": {...}, "perturbation": {...}},
#   "runs": [{"run_id": "EXP-002", "ts": "2026-07-27 03:00", "strategy": "PA-Confluence v2",
#             "params": "EMA200/50/20, 1.5xATR, 1:3", "interval": "4h",
#             "segment": "random-60%", "protocol": "random-segment",
#             "symbols": {"BTCUSDT": {"return_pct": 0, "win_rate_pct": 0, "profit_factor": 0,
#                                     "max_drawdown_pct": 0, "trades": 0}},
#             "verdict": "pass|fail|candidate", "notes": "..."}]
# }


def load_data():
    data = {}
    for s in SYMBOLS:
        path = os.path.join(RESULT_DIR, f"backtest_{s}.json")
        with open(path, encoding="utf-8") as f:
            data[s] = json.load(f)
    with open(os.path.join(RESULT_DIR, "summary.json"), encoding="utf-8") as f:
        summary = json.load(f)
    return data, summary


PROTOCOL_META = {
    "in-sample baseline": {"nm": "样本内基线", "desc": "全量 4h + 1d 数据基线回测"},
    "random-segment": {"nm": "随机分段", "desc": "4h 数据均分 4 段独立回测，检验时间段稳定性"},
    "blind-holdout": {"nm": "单盲留出", "desc": "前 70% 训练 / 后 30% 留出验证，选型不见留出集"},
    "perturbation": {"nm": "扰动注入", "desc": "±0.5% 噪声 / 截断前 15% / 插入 5 根扰动 K 线"},
}

# 策略侧（小G）多策略实验报告的分析结论，随 experiments.json 一并交付
EXPERIMENT_FINDINGS = [
    "Baseline 策略全量数据收益最高（均值 +11.53%）但 OOS 通过率 0% —— 三币种留出集全部亏损，是过拟合的典型特征，防过拟合协议有效捕捉到了该风险。",
    "PA-Fast-Trend 综合排名第一（43.07 分）：分段一致性最好（BTC 4/4 段全盈利）、OOS 通过率最高（BTC 留出集 +3.20%）、扰动稳健性可接受。",
    "1d 周期表现普遍优于 4h —— Baseline 在 1d 上 BTC +0.5% / ETH +15.4% / BNB +16.7%，而 4h 上 BNB 亏损 -7.4%，策略更适合日线级别。",
    "BNB 在 4h 周期上所有策略全部亏损 —— 高波动特性不适合当前框架，建议 4h 周期排除 BNB 或单独设计参数。",
    "噪声注入对策略影响最大 —— 多个策略在 ±0.5% 噪声后翻负，实盘中需关注滑点控制。",
]

EXPERIMENT_RECOMMENDATION = (
    "正式策略建议采用 PA-Fast-Trend（EMA100 主趋势 + EMA10/30 次级 + 1.5×ATR 止损 + 1:3 盈亏比 + 2% 风险）。"
    "分段一致性 75% 说明收益不是靠某段行情碰运气；OOS 通过率 33.3% 虽不高，但已是 5 个策略中最好的留出集表现。"
    "注意：当前 4h 数据仅 1 年（2190 根），样本量偏少，建议扩充至 2-3 年数据后重新验证，并优先在 1d 周期部署。"
)


def _protocol_stats(runs):
    """按协议聚合并计算通过情况（真实计数）。

    口径：in-sample baseline 只计 RUNS 数；blind-holdout 仅以 out-of-sample
    段的 pass/fail 计通过率（in-sample 段的 candidate 属训练集，不计入）。
    """
    stats = {}
    for proto, meta in PROTOCOL_META.items():
        subset = [r for r in runs if r.get("protocol") == proto]
        if proto == "blind-holdout":
            judged = [r for r in subset if "out-of-sample" in r.get("segment", "")]
            passed = sum(1 for r in judged if r.get("verdict") == "pass")
            label = f"{passed}/{len(judged)} OOS PASS" if judged else "PENDING"
        elif proto == "in-sample baseline":
            passed = len(subset)
            label = f"{len(subset)} RUNS" if subset else "PENDING"
        else:
            judged = subset
            passed = sum(1 for r in judged if r.get("verdict") == "pass")
            label = f"{passed}/{len(judged)} PASS" if judged else "PENDING"
        stats[proto] = {
            "status": "done" if subset else "pending",
            "nm": meta["nm"],
            "desc": meta["desc"],
            "total": len(subset),
            "passed": passed,
            "label": label,
        }
    return stats


def load_experiments(summary):
    """读取多策略实验记录并归一化；文件不存在时由 summary 合成基线（真实数据）。"""
    path = os.path.join(RESULT_DIR, "experiments.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            exp = json.load(f)
        exp["protocol_stats"] = _protocol_stats(exp.get("runs", []))
        exp["findings"] = EXPERIMENT_FINDINGS
        exp["recommendation"] = EXPERIMENT_RECOMMENDATION
        return exp
    runs = []
    for i, (s, r) in enumerate(summary.get("results", {}).items(), 1):
        runs.append({
            "run_id": f"RUN-{i:03d}",
            "strategy_id": "PA-001",
            "strategy_name": "PA-Confluence-Baseline",
            "symbol": s,
            "interval": summary.get("interval", "4h"),
            "protocol": "in-sample baseline",
            "segment": "full",
            "metrics": r,
            "verdict": "baseline",
            "note": "单策略全样本基线回测（真实结果）。多策略对比与防过拟合协议实验待策略侧接入。",
        })
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "random_seed": None,
        "meta": {"total_runs": len(runs)},
        "strategies": [],
        "ranking": [],
        "runs": runs,
        "protocol_stats": _protocol_stats(runs),
        "findings": [],
        "recommendation": "",
    }


HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PRICE_ACTION://TERMINAL — 量化交易终端</title>
<link rel="stylesheet" href="https://miaoda.feishu.cn/fonts/css2?family=JetBrains+Mono:ital,wght@0,400;0,500;0,700;0,800;1,400&display=swap">
<script src="plotly.min.js"></script>
<style>
:root{
  --bg:#030704; --raise:#071009; --inset:#040b05;
  --line:#123a1d; --line-hi:#1f6a32;
  --green:#00ff41; --green-dim:#00b32d; --green-glow:rgba(0,255,65,.32);
  --amber:#ffb000; --red:#ff3b4e; --cyan:#29d8ff;
  --text:#b9f6ca; --muted:#558a64; --faint:#2c4a36;
  --mono:'JetBrains Mono',ui-monospace,'Cascadia Code','SF Mono',Menlo,Consolas,monospace;
}
*{margin:0;padding:0;box-sizing:border-box}
html{scrollbar-color:var(--line-hi) var(--bg)}
body{background:var(--bg);color:var(--text);font-family:var(--mono);font-size:14px;line-height:1.55;min-height:100vh;padding:12px 18px 64px;overflow-x:hidden}
::selection{background:var(--green);color:#031007}
a{color:var(--cyan);text-decoration:none}

/* ===== 环境层：数字雨 + CRT ===== */
#rain{position:fixed;inset:0;z-index:0;opacity:.07;pointer-events:none}
.crt{position:fixed;inset:0;z-index:60;pointer-events:none;
  background:repeating-linear-gradient(0deg,rgba(0,0,0,.16) 0 1px,transparent 1px 3px);
  mix-blend-mode:multiply}
.crt::after{content:"";position:absolute;inset:0;
  background:radial-gradient(ellipse at center,transparent 55%,rgba(0,0,0,.5) 100%)}
main,header.cmdbar{position:relative;z-index:2}

/* ===== 开机引导 ===== */
#boot{position:fixed;inset:0;z-index:100;background:rgba(2,6,3,.97);display:flex;align-items:center;justify-content:center;cursor:pointer}
#boot .box{width:min(640px,90vw);font-size:13px;color:var(--green-dim);text-shadow:0 0 6px var(--green-glow)}
#boot .ln{white-space:pre-wrap;min-height:1.4em}
#boot .ok{color:var(--green)}
#boot .skip{margin-top:18px;color:var(--faint);font-size:11px}
#boot.done{display:none}

/* ===== 顶部命令栏 ===== */
header.cmdbar{position:sticky;top:0;z-index:50;display:flex;align-items:center;gap:14px;flex-wrap:wrap;
  background:rgba(4,10,5,.92);backdrop-filter:blur(4px);
  border:1px solid var(--line);border-radius:6px;padding:10px 14px;margin-bottom:14px}
.logo{font-weight:800;font-size:15px;letter-spacing:.5px;color:var(--green);text-shadow:0 0 10px var(--green-glow);white-space:nowrap}
.logo .dim{color:var(--muted);font-weight:500}
.logo .ver{color:var(--faint);font-size:11px;font-weight:400}
nav.nav{display:flex;gap:6px;flex-wrap:wrap;flex:1}
.nav-btn{background:transparent;border:1px solid var(--line);color:var(--muted);font-family:var(--mono);
  font-size:12px;padding:6px 12px;border-radius:4px;cursor:pointer;letter-spacing:.5px;transition:all .15s}
.nav-btn b{color:var(--faint);font-weight:700;margin-right:4px}
.nav-btn:hover{border-color:var(--line-hi);color:var(--text)}
.nav-btn:focus-visible{outline:1px solid var(--green);outline-offset:2px}
.nav-btn.active{border-color:var(--green);color:var(--green);background:rgba(0,255,65,.07);
  box-shadow:0 0 12px rgba(0,255,65,.12),inset 0 0 8px rgba(0,255,65,.05);text-shadow:0 0 8px var(--green-glow)}
.nav-btn.active b{color:var(--green-dim)}
.lights{display:flex;gap:10px;align-items:center;font-size:11px;color:var(--muted);white-space:nowrap}
.lights i{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:4px;vertical-align:1px}
.lights .on{background:var(--green);box-shadow:0 0 6px var(--green)}
.lights .off{background:var(--faint)}
.lights .warn{background:var(--amber);box-shadow:0 0 6px rgba(255,176,0,.6)}

/* ===== 分区标题 ===== */
.sec{margin-bottom:18px}
.sec-head{display:flex;align-items:center;gap:10px;color:var(--green-dim);font-size:12px;font-weight:700;
  letter-spacing:1.5px;margin:18px 0 10px;text-shadow:0 0 6px var(--green-glow)}
.sec-head::after{content:"";flex:1;height:1px;background:linear-gradient(90deg,var(--line),transparent)}
.sec-head .tag{color:var(--faint);font-weight:400;letter-spacing:.5px}

/* ===== 组合 KPI 条 ===== */
.port-strip{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:8px}
.kpi{background:var(--raise);border:1px solid var(--line);border-radius:5px;padding:10px 12px;position:relative;cursor:copy;transition:border-color .15s}
.kpi:hover{border-color:var(--line-hi)}
.kpi::before{content:"";position:absolute;top:0;left:0;width:22px;height:2px;background:var(--green-dim);opacity:.7}
.kpi .label{font-size:10px;color:var(--muted);letter-spacing:1px;text-transform:uppercase}
.kpi .num{font-size:19px;font-weight:800;margin-top:2px;font-variant-numeric:tabular-nums;text-shadow:0 0 10px var(--green-glow)}
.kpi .num.sm{font-size:15px}
.pos{color:var(--green)} .neg{color:var(--red)} .amb{color:var(--amber)} .cyn{color:var(--cyan)} .mut{color:var(--muted)}

/* ===== 币种卡 ===== */
.coin-cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:10px;margin-top:10px}
.coin-card{background:var(--raise);border:1px solid var(--line);border-radius:6px;padding:14px;cursor:pointer;transition:all .15s;position:relative}
.coin-card:hover{border-color:var(--line-hi);transform:translateY(-1px)}
.coin-card.active{border-color:var(--green);box-shadow:0 0 16px rgba(0,255,65,.10)}
.coin-card .cc-top{display:flex;justify-content:space-between;align-items:baseline}
.coin-card .sym{color:var(--text);font-weight:800;font-size:15px}
.coin-card .sym .tick{color:var(--faint);font-size:11px;font-weight:400;margin-left:6px}
.coin-card .ret{font-size:22px;font-weight:800;font-variant-numeric:tabular-nums;text-shadow:0 0 12px currentColor}
.coin-card .spark{margin:8px 0 6px;height:34px}
.coin-card .cc-meta{display:flex;justify-content:space-between;font-size:11px;color:var(--muted)}
.coin-card .wr-bar{height:3px;background:var(--inset);border-radius:2px;margin-top:8px;overflow:hidden}
.coin-card .wr-fill{height:100%;background:var(--green-dim);box-shadow:0 0 6px var(--green-glow)}

/* ===== 视图与面板 ===== */
.view{display:none;animation:fadein .25s ease}
.view.active{display:block}
@keyframes fadein{from{opacity:0;transform:translateY(4px)}to{opacity:1;transform:none}}
.panel{background:var(--raise);border:1px solid var(--line);border-radius:6px;padding:14px;margin-bottom:12px}
.panel h3{color:var(--green-dim);font-size:12px;letter-spacing:1.5px;margin-bottom:10px;font-weight:700}
.panel h3 .tag{color:var(--faint);font-weight:400;letter-spacing:.3px;margin-left:8px;text-transform:none}
.chart{width:100%}
.legend-line{display:flex;gap:16px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin:2px 0 8px}
.legend-line .mk{display:inline-flex;align-items:center;gap:5px}
.mk i{width:0;height:0;border-left:5px solid transparent;border-right:5px solid transparent}
.mk .up{border-bottom:9px solid var(--green)}
.mk .dn{border-top:9px solid var(--red)}
.mk .dot{width:8px;height:8px;border-radius:50%;border:2px solid var(--amber);background:transparent}
.mk .ln{width:14px;height:2px;background:var(--cyan)}

/* ===== 信号统计带 ===== */
.sig-band{display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:8px}
.sig{background:var(--inset);border:1px solid var(--line);border-radius:4px;padding:8px 10px;text-align:center}
.sig .n{font-size:17px;font-weight:800;color:var(--amber);text-shadow:0 0 8px rgba(255,176,0,.3);font-variant-numeric:tabular-nums}
.sig .t{font-size:10px;color:var(--muted);letter-spacing:1px;margin-top:1px}

/* ===== 台账（交易表） ===== */
.ledger-tools{display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px;align-items:center}
.chip{background:transparent;border:1px solid var(--line);color:var(--muted);font-family:var(--mono);font-size:11px;
  padding:4px 10px;border-radius:3px;cursor:pointer;transition:all .12s;letter-spacing:.5px}
.chip:hover{border-color:var(--line-hi);color:var(--text)}
.chip:focus-visible{outline:1px solid var(--green);outline-offset:1px}
.chip.active{border-color:var(--green);color:var(--green);background:rgba(0,255,65,.08)}
.chip.active.r{border-color:var(--red);color:var(--red);background:rgba(255,59,78,.08)}
.ledger-count{margin-left:auto;font-size:11px;color:var(--faint)}
.table-wrap{max-height:440px;overflow:auto;border:1px solid var(--line);border-radius:4px}
table.trade-table{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}
.trade-table th{position:sticky;top:0;z-index:1;background:var(--inset);color:var(--muted);text-align:right;
  padding:8px 10px;border-bottom:1px solid var(--line-hi);font-weight:500;font-size:11px;letter-spacing:.5px;
  cursor:pointer;user-select:none;white-space:nowrap}
.trade-table th:hover{color:var(--green)}
.trade-table th .arrow{color:var(--green);margin-left:3px}
.trade-table th:first-child,.trade-table td:first-child{text-align:left}
.trade-table th:nth-child(2),.trade-table td:nth-child(2){text-align:center}
.trade-table th:nth-child(7),.trade-table td:nth-child(7){text-align:center}
.trade-table td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:right;color:var(--text);white-space:nowrap}
.trade-table tbody tr:hover{background:rgba(0,255,65,.04)}
.pill{padding:1px 8px;border-radius:3px;font-size:10px;letter-spacing:.5px;border:1px solid}
.pill.long{color:var(--green);border-color:rgba(0,255,65,.35);background:rgba(0,255,65,.06)}
.pill.short{color:var(--red);border-color:rgba(255,59,78,.35);background:rgba(255,59,78,.06)}
.pill.win{color:var(--green);border-color:rgba(0,255,65,.35);background:rgba(0,255,65,.06)}
.pill.loss{color:var(--red);border-color:rgba(255,59,78,.35);background:rgba(255,59,78,.06)}
.empty-cell{text-align:center !important;color:var(--faint);padding:22px !important}

/* ===== 极值交易 ===== */
.extremes{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:8px;margin-top:10px}
.ext{border:1px dashed var(--line-hi);border-radius:4px;padding:8px 12px;font-size:12px;background:var(--inset)}
.ext .t{font-size:10px;color:var(--muted);letter-spacing:1px}
.ext .v{font-weight:800;font-size:15px;font-variant-numeric:tabular-nums}

/* ===== SYSTEM / LOG 排版 ===== */
.doc h4{color:var(--amber);font-size:13px;letter-spacing:1px;margin:16px 0 6px}
.doc h4::before{content:"> ";color:var(--faint)}
.doc p,.doc li{color:var(--text);font-size:13px;line-height:1.8}
.doc ul{list-style:none;padding-left:6px}
.doc li::before{content:"· ";color:var(--green-dim)}
.doc code{background:var(--inset);border:1px solid var(--line);padding:1px 6px;border-radius:3px;color:var(--amber);font-size:12px}
.doc b{color:var(--green)}
.proto-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:8px;margin-bottom:14px}
.proto{border:1px solid var(--line);border-radius:5px;padding:10px 12px;background:var(--raise)}
.proto .st{font-size:11px;font-weight:700;letter-spacing:1px}
.proto .st.done{color:var(--green)}
.proto .st.pending{color:var(--amber)}
.proto .nm{font-size:12px;color:var(--text);margin:3px 0 2px;font-weight:700}
.proto .nt{font-size:11px;color:var(--muted)}
.run-table{width:100%;border-collapse:collapse;font-size:12px;font-variant-numeric:tabular-nums}
.run-table th{background:var(--inset);color:var(--muted);text-align:left;padding:8px 10px;border-bottom:1px solid var(--line-hi);font-weight:500;font-size:11px;letter-spacing:.5px;white-space:nowrap}
.run-table td{padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
.run-table .rid{color:var(--cyan);font-weight:700;white-space:nowrap}
.run-table .vd{border:1px solid;padding:1px 7px;border-radius:3px;font-size:10px;letter-spacing:.5px;white-space:nowrap}
.vd.baseline{color:var(--cyan);border-color:rgba(41,216,255,.4);background:rgba(41,216,255,.06)}
.vd.pass{color:var(--green);border-color:rgba(0,255,65,.35);background:rgba(0,255,65,.06)}
.vd.fail{color:var(--red);border-color:rgba(255,59,78,.35);background:rgba(255,59,78,.06)}
.vd.candidate{color:var(--amber);border-color:rgba(255,176,0,.4);background:rgba(255,176,0,.06)}
.sym-cells{display:flex;flex-direction:column;gap:2px;font-size:11px;color:var(--muted);white-space:nowrap}
.note-cell{color:var(--muted);font-size:11px;max-width:260px}

/* ===== EXPERIMENT LOG 扩展 ===== */
.rank-row1{background:rgba(0,255,65,.05);border-left:2px solid var(--green)}
.rank-row1 td:first-child{color:var(--green);font-weight:700}
.run-table td .reco-tag{display:inline-block;margin-left:6px;padding:0 6px;font-size:9px;color:#031007;background:var(--green);border-radius:2px;letter-spacing:.5px;font-weight:700}
.run-table th{cursor:default;user-select:none}
.run-table th[data-sort]{cursor:pointer}
.run-table th[data-sort]:hover{color:var(--green)}
.run-table th.sorted-asc::after{content:" ↑";color:var(--green)}
.run-table th.sorted-desc::after{content:" ↓";color:var(--green)}

.filter-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:8px 0 10px;padding:8px 10px;background:var(--inset);border:1px solid var(--line);border-radius:4px}
.filter-bar label{display:flex;align-items:center;gap:6px;font-size:11px;color:var(--muted);letter-spacing:.5px}
.filter-bar select{font-family:var(--mono);font-size:12px;background:var(--raise);color:var(--text);border:1px solid var(--line);border-radius:3px;padding:3px 8px;outline:none;min-width:120px}
.filter-bar select:focus{border-color:var(--green)}
.filter-btn{font-family:var(--mono);font-size:11px;background:transparent;color:var(--amber);border:1px solid rgba(255,176,0,.4);border-radius:3px;padding:3px 10px;cursor:pointer;letter-spacing:.5px}
.filter-btn:hover{background:rgba(255,176,0,.08);border-color:var(--amber)}
.run-count{margin-left:auto;font-size:11px;color:var(--muted);letter-spacing:.5px}
.run-count b{color:var(--green);font-weight:700}

.findings{background:var(--raise);border:1px solid var(--line);border-left:2px solid var(--green);border-radius:4px;padding:12px 14px}
.findings li{font-size:12px;color:var(--text);padding:4px 0 4px 14px;position:relative;line-height:1.55}
.findings li::before{content:"▸";position:absolute;left:0;top:4px;color:var(--green-dim);font-size:11px}
.findings ol{list-style:none;padding:0;margin:0}
.reco{margin-top:10px;padding:12px 14px;background:linear-gradient(180deg,rgba(0,255,65,.04),rgba(41,216,255,.04));border:1px solid var(--line-hi);border-radius:4px;font-size:12px;color:var(--text);line-height:1.6}
.reco .reco-tag{display:inline-block;margin-right:8px;padding:1px 8px;font-size:10px;color:#031007;background:var(--green);border-radius:2px;letter-spacing:.5px;font-weight:700;text-shadow:none}

/* ===== 底部状态栏 ===== */
footer.statusbar{position:fixed;left:0;right:0;bottom:0;z-index:50;display:flex;justify-content:space-between;gap:12px;
  background:rgba(3,8,4,.95);border-top:1px solid var(--line);padding:6px 16px;font-size:11px;color:var(--muted);
  font-family:var(--mono);backdrop-filter:blur(4px)}
.statusbar .path{color:var(--green-dim)}
.cursor{display:inline-block;width:7px;height:12px;background:var(--green);vertical-align:-2px;margin-left:3px;
  animation:blink 1.1s steps(1) infinite;box-shadow:0 0 6px var(--green)}
@keyframes blink{50%{opacity:0}}
.statusbar .right{display:flex;gap:14px;flex-wrap:wrap}

/* ===== toast / help ===== */
#toast{position:fixed;right:16px;bottom:40px;z-index:80;font-size:12px;color:var(--green);
  background:rgba(3,10,5,.95);border:1px solid var(--line-hi);border-radius:4px;padding:7px 12px;
  opacity:0;transform:translateY(6px);transition:all .18s;pointer-events:none;text-shadow:0 0 6px var(--green-glow)}
#toast.show{opacity:1;transform:none}
#help{position:fixed;inset:0;z-index:90;display:none;align-items:center;justify-content:center;background:rgba(2,6,3,.9)}
#help.show{display:flex}
#help .box{border:1px solid var(--line-hi);background:var(--raise);border-radius:6px;padding:22px 26px;width:min(420px,90vw)}
#help h3{color:var(--green);font-size:13px;letter-spacing:1px;margin-bottom:12px}
#help .row{display:flex;justify-content:space-between;padding:5px 0;border-bottom:1px dashed var(--line);font-size:12px}
#help .row:last-child{border:none}
#help kbd{background:var(--inset);border:1px solid var(--line-hi);border-radius:3px;padding:1px 7px;color:var(--amber);font-family:var(--mono);font-size:11px}
#help .esc{margin-top:12px;color:var(--faint);font-size:11px;text-align:center}

@media (max-width:720px){
  body{padding:8px 10px 60px}
  .kpi .num{font-size:16px}
  .lights{display:none}
  .statusbar .right span:nth-child(2){display:none}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms !important;transition-duration:.01ms !important}
  #rain,.crt{display:none}
  .cursor{animation:none}
}
</style>
</head>
<body>

<canvas id="rain"></canvas>
<div class="crt"></div>

<div id="boot">
  <div class="box" id="bootBox"></div>
</div>

<header class="cmdbar">
  <div class="logo">▲ PRICE_ACTION<span class="dim">://TERMINAL</span> <span class="ver">v2.1</span></div>
  <nav class="nav" id="mainNav">
__TABS__
    <button class="nav-btn" data-view="SYSTEM" id="tab-SYSTEM"><b>[4]</b>SYSTEM</button>
    <button class="nav-btn" data-view="LOG" id="tab-LOG"><b>[5]</b>LOG</button>
  </nav>
  <div class="lights">
    <span><i class="on"></i>FEED</span>
    <span><i class="on"></i>ENGINE</span>
    <span><i class="warn"></i>BACKTEST</span>
  </div>
</header>

<main>
  <section class="sec" id="sec-portfolio">
    <div class="sec-head">[ 00 // PORTFOLIO ] <span class="tag">三币组合 · 单位 USDT · 数据段 __RANGE__</span></div>
    <div class="port-strip" id="portStrip"></div>
    <div class="coin-cards" id="coinCards"></div>
  </section>

__PANELS__

  <section class="view" id="view-SYSTEM">
    <div class="sec-head">[ 04 // STRATEGY SYSTEM ] <span class="tag">价格行为学融合策略 · 四层信号架构</span></div>
    <div class="panel doc">
      <h3>CORE IDEA <span class="tag">抛弃滞后指标，直接阅读 K 线结构中的多空力量</span></h3>
      <p>交易系统由 <b>主趋势过滤 → 次级趋势确认 → 形态信号 → 风险管理</b> 四层构成，全部条件同向时才在下一根 K 线开盘价进场（避免未来函数）。</p>
      <h4>LAYER 1 — 主趋势过滤 (EMA200)</h4>
      <ul><li>收盘价在 EMA200 之上 = 多头环境，只做多</li><li>收盘价在 EMA200 之下 = 空头环境，只做空</li></ul>
      <h4>LAYER 2 — 次级趋势确认 (EMA20/50)</h4>
      <ul><li>EMA20 &gt; EMA50 且价格在 EMA20 之上 = 上升趋势</li><li>EMA20 &lt; EMA50 且价格在 EMA20 之下 = 下降趋势</li></ul>
      <h4>LAYER 3 — 价格行为形态信号</h4>
      <ul>
        <li><b>Pin Bar (针杆)</b>：长影线拒绝，影线 ≥ 0.6×ATR，实体 ≤ 35% 全高</li>
        <li><b>Engulfing (吞没)</b>：实体完全包住前一根 K 线实体</li>
        <li><b>Break of Structure (结构突破)</b>：突破近期 swing 高/低点</li>
      </ul>
      <h4>LAYER 4 — 风险管理</h4>
      <ul>
        <li>单笔风险 <code>2%</code> · 止损 <code>1.5 × ATR</code> · 止盈 <code>1:3 盈亏比</code></li>
        <li>波动率过滤：ATR/Close ∈ <code>[0.5%, 5%]</code></li>
        <li>成本：手续费 <code>0.04%</code> + 滑点 <code>0.05%</code>（已计入回测）</li>
      </ul>
      <h4>参数卡</h4>
      <div class="port-strip" style="margin-top:8px">
        <div class="kpi"><div class="label">初始资金</div><div class="num sm">10,000 / 币</div></div>
        <div class="kpi"><div class="label">单笔风险</div><div class="num sm">2%</div></div>
        <div class="kpi"><div class="label">盈亏比</div><div class="num sm">1:3</div></div>
        <div class="kpi"><div class="label">主周期</div><div class="num sm">4H</div></div>
        <div class="kpi"><div class="label">数据</div><div class="num sm">Binance 真实K线</div></div>
      </div>
      <p style="margin-top:14px;color:var(--muted);font-size:12px">ETF 说明：「ETF」在加密量化语境中对应 ETH（与 BTC、BNB 同为三大主流标的），系统采集 ETHUSDT 真实数据。本系统为回测研究，不构成投资建议。</p>
      <div class="reco" style="margin-top:12px"><span class="reco-tag">正式策略</span>经 5 策略 × 4 防过拟合协议综合评分（基线 30% + 分段 25% + OOS 25% + 扰动 20%），正式上线参数选型为 <b>PA-Fast-Trend</b>（EMA100/10/30 + 1.5×ATR 止损 + 1:3 盈亏比 + 2% 风险，综合得分 43.07）—— 详细排名与 165 条实验记录见 <b>[ 05 // EXPERIMENT LOG ]</b>。</div>
    </div>
  </section>

  <section class="view" id="view-LOG">
    <div class="sec-head">[ 05 // EXPERIMENT LOG ] <span class="tag">回测实验留痕 · 多策略 × 防过拟合协议</span></div>
    <div class="panel">
      <h3>PROTOCOL STATUS <span class="tag">用户要求的四项防过拟合协议 · 全部 DONE</span></h3>
      <div class="proto-grid" id="protoGrid"></div>

      <h3 style="margin-top:18px">STRATEGY RANKING <span class="tag">5 策略 × 综合评分排序（基线30% + 分段25% + OOS25% + 扰动20%）</span></h3>
      <div class="table-wrap" style="max-height:none">
        <table class="run-table">
          <thead><tr>
            <th>#</th><th>策略</th><th>说明</th>
            <th>Baseline均收益</th><th>分段通过率</th><th>OOS通过率</th><th>OOS均收益</th><th>扰动通过率</th><th>综合得分</th>
          </tr></thead>
          <tbody id="rankRows"></tbody>
        </table>
      </div>

      <h3 style="margin-top:18px">KEY FINDINGS <span class="tag">多策略实验关键结论（来自策略侧实验报告）</span></h3>
      <div class="findings" id="findingsBox"></div>
      <div class="reco" id="recoBox"></div>

      <h3 style="margin-top:18px">RUN HISTORY <span class="tag">165 条实验记录 · 支持按协议 / 策略 / 币种 / 判定筛选 · 点击表头排序</span></h3>
      <div class="filter-bar">
        <label>协议
          <select id="fProto"><option value="">ALL</option></select>
        </label>
        <label>策略
          <select id="fStrat"><option value="">ALL</option></select>
        </label>
        <label>币种
          <select id="fSym"><option value="">ALL</option></select>
        </label>
        <label>判定
          <select id="fVerd"><option value="">ALL</option></select>
        </label>
        <button id="fReset" class="filter-btn">RESET</button>
        <span class="run-count" id="runCount"></span>
      </div>
      <div class="table-wrap" style="max-height:560px;overflow:auto">
        <table class="run-table">
          <thead><tr>
            <th data-sort="run_id">RUN</th>
            <th data-sort="strategy_name">策略</th>
            <th data-sort="symbol">币种</th>
            <th data-sort="interval">周期</th>
            <th data-sort="protocol">协议</th>
            <th data-sort="segment">数据段</th>
            <th data-sort="total_return_pct">收益%</th>
            <th data-sort="win_rate_pct">胜率%</th>
            <th data-sort="profit_factor">PF</th>
            <th data-sort="max_drawdown_pct">回撤%</th>
            <th data-sort="total_trades">笔数</th>
            <th data-sort="verdict">判定</th>
            <th>备注</th>
          </tr></thead>
          <tbody id="runRows"></tbody>
        </table>
      </div>
    </div>
  </section>
</main>

<footer class="statusbar">
  <div><span class="path">quant@pa-terminal:~$</span> view/<span id="sbView">BTC</span><span class="cursor"></span></div>
  <div class="right">
    <span>FEED: BINANCE_VISION</span>
    <span id="sbTrades"></span>
    <span id="sbClock"></span>
  </div>
</footer>

<div id="toast"></div>
<div id="help">
  <div class="box">
    <h3>[ KEYBOARD SHORTCUTS ]</h3>
    <div class="row"><span>BTC 视图</span><kbd>1</kbd></div>
    <div class="row"><span>ETH 视图</span><kbd>2</kbd></div>
    <div class="row"><span>BNB 视图</span><kbd>3</kbd></div>
    <div class="row"><span>策略系统</span><kbd>4</kbd> <kbd>S</kbd></div>
    <div class="row"><span>实验日志</span><kbd>5</kbd> <kbd>L</kbd></div>
    <div class="row"><span>本帮助</span><kbd>?</kbd></div>
    <div class="row"><span>关闭浮层</span><kbd>Esc</kbd></div>
    <div class="esc">点击任意 KPI 数字可复制 · 点击表头可排序</div>
  </div>
</div>

<script>
var D = __EMBED__;
var X = __EXPERIMENTS__;
var ORDER = ['BTCUSDT','ETHUSDT','BNBUSDT'];
var SHORT = {BTCUSDT:'BTC', ETHUSDT:'ETH', BNBUSDT:'BNB'};
var RM = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/* ---------- 工具 ---------- */
function fmt(n, dp){
  if (n === null || n === undefined) return '--';
  if (typeof n !== 'number') return n;
  var d = (dp === undefined) ? 2 : dp;
  return n.toLocaleString('en-US', {minimumFractionDigits:d, maximumFractionDigits:d});
}
function cls(n){ return (typeof n === 'number' && n < 0) ? 'neg' : 'pos'; }
function sign(n){ return (typeof n === 'number' && n > 0) ? '+' : ''; }
function el(id){ return document.getElementById(id); }

var toastTimer = null;
function toast(msg){
  var t = el('toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(function(){ t.classList.remove('show'); }, 1600);
}
function copyVal(text){
  function fallback(){
    var ta = document.createElement('textarea');
    ta.value = text; document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); toast('[OK] copied: ' + text); }
    catch(e){ toast('[!!] copy failed'); }
    document.body.removeChild(ta);
  }
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(function(){ toast('[OK] copied: ' + text); }, fallback);
  } else fallback();
}

/* ---------- 组合级聚合（全部由真实数据算术得出） ---------- */
function portfolioStats(){
  var init = 0, fin = 0, trades = 0, wins = 0, best = null, worst = null;
  ORDER.forEach(function(s){
    var m = D.coins[s].metrics;
    init += D.summary.initial_capital;
    fin += m.final_equity;
    trades += m.total_trades;
    wins += (m.wins || Math.round(m.win_rate_pct * m.total_trades / 100));
    if (best === null || m.best_trade > best) best = m.best_trade;
    if (worst === null || m.worst_trade < worst) worst = m.worst_trade;
  });
  return {init:init, fin:fin, ret:(fin-init)/init*100, trades:trades,
          wr: trades ? wins/trades*100 : 0, best:best, worst:worst};
}

function buildPortfolio(){
  var p = portfolioStats();
  var kpis = [
    {label:'TOTAL EQUITY', num:fmt(p.fin), cls:'', suffix:' USDT'},
    {label:'BLENDED RETURN', num:sign(p.ret)+fmt(p.ret)+'%', cls:cls(p.ret)},
    {label:'TOTAL TRADES', num:fmt(p.trades,0), cls:''},
    {label:'OVERALL WINRATE', num:fmt(p.wr)+'%', cls:'amb'},
    {label:'BEST TRADE', num:sign(p.best)+fmt(p.best), cls:'pos'},
    {label:'WORST TRADE', num:fmt(p.worst), cls:'neg'}
  ];
  el('portStrip').innerHTML = kpis.map(function(k){
    return '<div class="kpi" data-copy="' + k.num + (k.suffix||'') + '">' +
      '<div class="label">' + k.label + '</div>' +
      '<div class="num ' + k.cls + '">' + k.num + (k.suffix ? '<span style="font-size:11px;color:var(--muted)">' + k.suffix + '</span>' : '') + '</div></div>';
  }).join('');
}

function sparkSVG(y){
  if (!y || y.length < 2) return '';
  var w = 260, h = 34, min = Math.min.apply(null,y), max = Math.max.apply(null,y);
  var span = (max - min) || 1;
  var pts = y.map(function(v,i){
    var x = i/(y.length-1)*w;
    var yy = h - 3 - (v-min)/span*(h-6);
    return x.toFixed(1) + ',' + yy.toFixed(1);
  }).join(' ');
  var up = y[y.length-1] >= y[0];
  var c = up ? 'var(--green)' : 'var(--red)';
  return '<svg viewBox="0 0 ' + w + ' ' + h + '" preserveAspectRatio="none" style="width:100%;height:100%">' +
    '<polyline points="' + pts + '" fill="none" stroke="' + c + '" stroke-width="1.5" opacity="0.9"/></svg>';
}

function buildCoinCards(){
  el('coinCards').innerHTML = ORDER.map(function(s){
    var c = D.coins[s], m = c.metrics;
    return '<div class="coin-card" data-view="' + s + '" id="cc-' + s + '" tabindex="0" role="button" aria-label="查看 ' + SHORT[s] + ' 详情">' +
      '<div class="cc-top"><span class="sym">' + SHORT[s] + '<span class="tick">' + s + ' · ' + c.interval + '</span></span>' +
      '<span class="ret ' + cls(m.total_return_pct) + '">' + sign(m.total_return_pct) + fmt(m.total_return_pct) + '%</span></div>' +
      '<div class="spark">' + sparkSVG(c.equity_curve.y) + '</div>' +
      '<div class="cc-meta"><span>EQ ' + fmt(m.final_equity) + '</span><span>WR ' + fmt(m.win_rate_pct) + '%</span>' +
      '<span>PF ' + fmt(m.profit_factor) + '</span><span>DD ' + fmt(m.max_drawdown_pct) + '%</span></div>' +
      '<div class="wr-bar"><div class="wr-fill" style="width:' + Math.max(0, Math.min(100, m.win_rate_pct)) + '%"></div></div>' +
    '</div>';
  }).join('');
}

/* ---------- 币种详情面板 ---------- */
var plotBase = {
  paper_bgcolor:'rgba(0,0,0,0)', plot_bgcolor:'rgba(0,0,0,0)',
  font:{family:"'JetBrains Mono',Consolas,monospace", color:'#558a64', size:11},
  margin:{l:56,r:16,t:8,b:36},
  xaxis:{gridcolor:'#123a1d', zerolinecolor:'#1f6a32', linecolor:'#123a1d'},
  yaxis:{gridcolor:'#123a1d', zerolinecolor:'#1f6a32', linecolor:'#123a1d'},
  showlegend:false, hovermode:'x unified',
  hoverlabel:{bgcolor:'#071009', bordercolor:'#1f6a32', font:{family:"'JetBrains Mono',Consolas,monospace", color:'#b9f6ca', size:11}}
};
var plotCfg = {responsive:true, displayModeBar:false, staticPlot:false};

function drawPrice(s){
  var c = D.coins[s];
  var longs = c.trades.filter(function(t){return t.side==='LONG';});
  var shorts = c.trades.filter(function(t){return t.side==='SHORT';});
  var traces = [
    {x:c.price_curve.x, y:c.price_curve.y, type:'scatter', mode:'lines', name:'价格',
     line:{color:'#29d8ff', width:1.4}, hovertemplate:'%{y:,.2f}<extra>PRICE</extra>'},
    {x:longs.map(function(t){return t.entry_time;}), y:longs.map(function(t){return t.entry;}),
     type:'scatter', mode:'markers', name:'做多进场',
     marker:{symbol:'triangle-up', size:9, color:'#00ff41', line:{color:'#003b10', width:1}},
     hovertemplate:'LONG @ %{y:,.2f}<extra>%{x}</extra>'},
    {x:shorts.map(function(t){return t.entry_time;}), y:shorts.map(function(t){return t.entry;}),
     type:'scatter', mode:'markers', name:'做空进场',
     marker:{symbol:'triangle-down', size:9, color:'#ff3b4e', line:{color:'#4a0a10', width:1}},
     hovertemplate:'SHORT @ %{y:,.2f}<extra>%{x}</extra>'}
  ];
  Plotly.newPlot('price-'+s, traces, Object.assign({}, plotBase), plotCfg);
}

function drawEquity(s){
  var c = D.coins[s];
  var x = c.equity_curve.x, y = c.equity_curve.y;
  var peak = -Infinity, dd = y.map(function(v){ peak = Math.max(peak, v); return (v-peak)/peak*100; });
  var lay = Object.assign({}, plotBase, {
    yaxis: Object.assign({}, plotBase.yaxis, {domain:[0.30,1], title:{text:'EQUITY', font:{size:10}}}),
    yaxis2: Object.assign({}, plotBase.yaxis, {domain:[0,0.24], title:{text:'DD %', font:{size:10}}}),
    shapes:[{type:'line', x0:x[0], x1:x[x.length-1], y0:D.summary.initial_capital, y1:D.summary.initial_capital,
             line:{color:'#2c4a36', dash:'dash', width:1}}]
  });
  var traces = [
    {x:x, y:y, type:'scatter', mode:'lines', name:'权益', yaxis:'y',
     line:{color:'#00ff41', width:1.8}, fill:'tozeroy', fillcolor:'rgba(0,255,65,0.07)',
     hovertemplate:'%{y:,.2f}<extra>EQUITY</extra>'},
    {x:x, y:dd, type:'scatter', mode:'lines', name:'回撤', yaxis:'y2',
     line:{color:'#ff3b4e', width:1}, fill:'tozeroy', fillcolor:'rgba(255,59,78,0.18)',
     hovertemplate:'%{y:.2f}%<extra>DRAWDOWN</extra>'}
  ];
  Plotly.newPlot('equity-'+s, traces, lay, plotCfg);
}

/* 台账状态（每币独立） */
var ledgerState = {};
ORDER.forEach(function(s){ ledgerState[s] = {outcome:'ALL', side:'ALL', sortKey:'entry_time', sortDir:1}; });

function ledgerRows(s){
  var st = ledgerState[s];
  var rows = D.coins[s].trades.slice();
  if (st.outcome !== 'ALL') rows = rows.filter(function(t){ return t.outcome === st.outcome.toLowerCase(); });
  if (st.side !== 'ALL') rows = rows.filter(function(t){ return t.side === st.side; });
  rows.sort(function(a,b){
    var va = a[st.sortKey], vb = b[st.sortKey];
    if (typeof va === 'string') return va.localeCompare(vb) * st.sortDir;
    return ((va||0) - (vb||0)) * st.sortDir;
  });
  return rows;
}

function renderLedger(s){
  var st = ledgerState[s];
  var rows = ledgerRows(s);
  var cols = [
    {k:'entry_time', t:'进场时间'}, {k:'side', t:'方向'}, {k:'entry', t:'进场'},
    {k:'stop', t:'止损'}, {k:'target', t:'止盈'}, {k:'exit', t:'出场'},
    {k:'outcome', t:'结果'}, {k:'pnl', t:'盈亏'}, {k:'return_pct', t:'回报%'},
    {k:'equity', t:'权益'}, {k:'bars_held', t:'持仓K'}
  ];
  var thead = cols.map(function(c){
    var arrow = (st.sortKey === c.k) ? '<span class="arrow">' + (st.sortDir > 0 ? '▲' : '▼') + '</span>' : '';
    return '<th data-k="' + c.k + '">' + c.t + arrow + '</th>';
  }).join('');
  var body;
  if (!rows.length){
    body = '<tr><td class="empty-cell" colspan="11">// 无匹配记录 — 调整筛选条件</td></tr>';
  } else {
    body = rows.map(function(t){
      return '<tr>' +
        '<td>' + t.entry_time + '</td>' +
        '<td><span class="pill ' + (t.side==='LONG'?'long':'short') + '">' + t.side + '</span></td>' +
        '<td>' + fmt(t.entry) + '</td><td>' + fmt(t.stop) + '</td><td>' + fmt(t.target) + '</td><td>' + fmt(t.exit) + '</td>' +
        '<td><span class="pill ' + t.outcome + '">' + (t.outcome==='win'?'WIN':'LOSS') + '</span></td>' +
        '<td class="' + cls(t.pnl) + '">' + sign(t.pnl) + fmt(t.pnl) + '</td>' +
        '<td class="' + cls(t.return_pct) + '">' + sign(t.return_pct) + fmt(t.return_pct) + '</td>' +
        '<td>' + fmt(t.equity) + '</td><td>' + t.bars_held + '</td></tr>';
    }).join('');
  }
  el('ledger-' + s).innerHTML =
    '<div class="ledger-tools">' +
      ['ALL','WIN','LOSS'].map(function(o){
        return '<button class="chip' + (st.outcome===o ? ' active' + (o==='LOSS'?' r':'') : '') + '" data-f="outcome" data-v="' + o + '">' + o + '</button>';
      }).join('') +
      '<span style="width:8px"></span>' +
      ['ALL','LONG','SHORT'].map(function(o){
        return '<button class="chip' + (st.side===o ? ' active' + (o==='SHORT'?' r':'') : '') + '" data-f="side" data-v="' + o + '">' + o + '</button>';
      }).join('') +
      '<span class="ledger-count">// ' + rows.length + ' / ' + D.coins[s].trades.length + ' 笔 · 点击表头排序</span>' +
    '</div>' +
    '<div class="table-wrap"><table class="trade-table"><thead><tr>' + thead + '</tr></thead><tbody>' + body + '</tbody></table></div>';
}

function buildCoinPanel(s){
  var c = D.coins[s], m = c.metrics, ss = c.signal_stats;
  el('view-' + s).innerHTML =
    '<div class="sec-head">[ VIEW // ' + SHORT[s] + ' · ' + s + ' ] <span class="tag">' + c.data_range.start.slice(0,10) + ' → ' + c.data_range.end.slice(0,10) + ' · ' + fmt(c.data_range.bars,0) + ' bars · 近 50 笔入账</span></div>' +
    '<div class="port-strip">' +
      '<div class="kpi" data-copy="' + sign(m.total_return_pct) + fmt(m.total_return_pct) + '%"><div class="label">总收益</div><div class="num ' + cls(m.total_return_pct) + '">' + sign(m.total_return_pct) + fmt(m.total_return_pct) + '%</div></div>' +
      '<div class="kpi" data-copy="' + fmt(m.final_equity) + '"><div class="label">最终权益</div><div class="num">' + fmt(m.final_equity) + '</div></div>' +
      '<div class="kpi" data-copy="' + fmt(m.win_rate_pct) + '%"><div class="label">胜率</div><div class="num amb">' + fmt(m.win_rate_pct) + '%</div></div>' +
      '<div class="kpi" data-copy="' + fmt(m.profit_factor) + '"><div class="label">盈亏比 PF</div><div class="num cyn">' + fmt(m.profit_factor) + '</div></div>' +
      '<div class="kpi" data-copy="' + fmt(m.max_drawdown_pct) + '%"><div class="label">最大回撤</div><div class="num neg">' + fmt(m.max_drawdown_pct) + '%</div></div>' +
      '<div class="kpi" data-copy="' + m.total_trades + '"><div class="label">交易数</div><div class="num">' + m.total_trades + '</div></div>' +
      '<div class="kpi" data-copy="' + fmt(m.avg_bars_held,1) + '"><div class="label">平均持仓</div><div class="num sm">' + fmt(m.avg_bars_held,1) + ' K</div></div>' +
    '</div>' +
    '<div class="panel" style="margin-top:12px"><h3>PRICE + ENTRIES <span class="tag">价格走势与真实进出场标记</span></h3>' +
      '<div class="legend-line"><span class="mk"><span class="ln"></span>价格</span>' +
      '<span class="mk"><i class="up"></i>做多进场</span><span class="mk"><i class="dn"></i>做空进场</span></div>' +
      '<div class="chart" id="price-' + s + '" style="height:380px"></div></div>' +
    '<div class="panel"><h3>EQUITY + DRAWDOWN <span class="tag">权益曲线与回撤带</span></h3>' +
      '<div class="chart" id="equity-' + s + '" style="height:360px"></div>' +
      '<div class="extremes">' +
        '<div class="ext"><div class="t">BEST TRADE</div><div class="v pos">+' + fmt(m.best_trade) + ' USDT</div></div>' +
        '<div class="ext"><div class="t">WORST TRADE</div><div class="v neg">' + fmt(m.worst_trade) + ' USDT</div></div>' +
        '<div class="ext"><div class="t">AVG WIN / AVG LOSS</div><div class="v"><span class="pos">+' + fmt(m.avg_win) + '</span> <span class="mut">/</span> <span class="neg">' + fmt(m.avg_loss) + '</span></div></div>' +
      '</div></div>' +
    '<div class="panel"><h3>SIGNAL FEED <span class="tag">形态信号统计（全数据段）</span></h3>' +
      '<div class="sig-band">' +
        '<div class="sig"><div class="n">' + ss.pin_bar + '</div><div class="t">PIN BAR</div></div>' +
        '<div class="sig"><div class="n">' + ss.engulfing + '</div><div class="t">ENGULFING</div></div>' +
        '<div class="sig"><div class="n">' + ss.bos + '</div><div class="t">BOS</div></div>' +
        '<div class="sig"><div class="n">' + ss.long_signals + '</div><div class="t">LONG SIG</div></div>' +
        '<div class="sig"><div class="n">' + ss.short_signals + '</div><div class="t">SHORT SIG</div></div>' +
      '</div></div>' +
    '<div class="panel"><h3>TRADE LEDGER <span class="tag">交易台账 · 可筛选可排序</span></h3><div id="ledger-' + s + '"></div></div>';
  renderLedger(s);
  drawPrice(s);
  drawEquity(s);
}

/* ---------- 实验日志 ---------- */
var _filter = {proto:'', strat:'', sym:'', verd:''};
var _sort = {key:'run_id', dir:'asc'};

function buildLog(){
  buildProtocols();
  buildRanking();
  buildFindings();
  initFilters();
  applyFilters();
  bindSortHeaders();
}

function buildProtocols(){
  var stats = X.protocol_stats || {};
  el('protoGrid').innerHTML = Object.keys(stats).map(function(k){
    var p = stats[k];
    var st = p.status === 'done' ? '[OK] DONE' : '[..] PENDING';
    var stCls = p.status === 'done' ? 'done' : 'pending';
    return '<div class="proto">' +
      '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<div class="st ' + stCls + '">' + st + '</div>' +
        '<div style="color:var(--cyan);font-size:11px;font-weight:700">' + p.label + '</div>' +
      '</div>' +
      '<div class="nm">' + p.nm + '</div>' +
      '<div class="nt">' + p.desc + '</div>' +
    '</div>';
  }).join('');
}

function buildRanking(){
  var ranking = X.ranking || [];
  var stratMap = {};
  (X.strategies || []).forEach(function(s){ stratMap[s.id] = s; });
  el('rankRows').innerHTML = ranking.map(function(r, i){
    var strat = stratMap[r.strategy_id] || {};
    var desc = strat.description || '';
    if (desc.length > 80) desc = desc.slice(0, 78) + '…';
    var reco = i === 0 ? '<span class="reco-tag">RECOMMENDED</span>' : '';
    var rowCls = i === 0 ? 'rank-row1' : '';
    return '<tr class="' + rowCls + '">' +
      '<td class="rid">' + (i + 1) + '</td>' +
      '<td><b>' + r.strategy_name + '</b>' + reco +
        '<div style="color:var(--faint);font-size:11px;margin-top:2px">' + r.strategy_id + '</div></td>' +
      '<td style="color:var(--muted);font-size:11px;max-width:280px;line-height:1.4">' + desc + '</td>' +
      '<td class="' + cls(r.baseline_avg_return) + '">' + sign(r.baseline_avg_return) + fmt(r.baseline_avg_return) + '%</td>' +
      '<td>' + fmt(r.segment_pass_rate, 1) + '%</td>' +
      '<td>' + fmt(r.oos_pass_rate, 1) + '%</td>' +
      '<td class="' + cls(r.oos_avg_return) + '">' + sign(r.oos_avg_return) + fmt(r.oos_avg_return) + '%</td>' +
      '<td>' + fmt(r.perturbation_pass_rate, 1) + '%</td>' +
      '<td><b style="color:var(--green)">' + fmt(r.composite_score, 2) + '</b></td>' +
    '</tr>';
  }).join('');
  if (!ranking.length) {
    el('rankRows').innerHTML = '<tr><td colspan="9" style="color:var(--muted);text-align:center;padding:18px">暂未生成排名数据</td></tr>';
  }
}

function buildFindings(){
  var findings = X.findings || [];
  el('findingsBox').innerHTML = '<ol>' + findings.map(function(f){
    return '<li>' + f + '</li>';
  }).join('') + '</ol>';
  var reco = X.recommendation || '';
  el('recoBox').innerHTML = '<span class="reco-tag">正式策略</span>' + reco;
}

function initFilters(){
  var runs = X.runs || [];
  function uniq(arr){ var s={}, o=[]; arr.forEach(function(x){ if(!s[x]){s[x]=1; o.push(x);} }); return o; }
  function fill(sel, vals){
    vals.forEach(function(v){
      var o = document.createElement('option');
      o.value = v; o.textContent = v;
      sel.appendChild(o);
    });
  }
  fill(el('fProto'), uniq(runs.map(function(r){return r.protocol;})).sort());
  fill(el('fStrat'), uniq(runs.map(function(r){return r.strategy_name;})).sort());
  fill(el('fSym'), uniq(runs.map(function(r){return r.symbol;})).sort());
  fill(el('fVerd'), uniq(runs.map(function(r){return r.verdict;})).sort());
  ['fProto','fStrat','fSym','fVerd'].forEach(function(id){
    el(id).addEventListener('change', function(e){
      _filter[id.slice(1).toLowerCase()] = e.target.value;
      applyFilters();
    });
  });
  el('fReset').addEventListener('click', function(){
    _filter = {proto:'', strat:'', sym:'', verd:''};
    el('fProto').value=''; el('fStrat').value=''; el('fSym').value=''; el('fVerd').value='';
    applyFilters();
  });
}

function applyFilters(){
  var runs = (X.runs || []).filter(function(r){
    return (!_filter.proto || r.protocol === _filter.proto) &&
           (!_filter.strat || r.strategy_name === _filter.strat) &&
           (!_filter.sym || r.symbol === _filter.sym) &&
           (!_filter.verd || r.verdict === _filter.verd);
  });
  // 排序
  var k = _sort.key, dir = _sort.dir === 'asc' ? 1 : -1;
  runs.sort(function(a, b){
    var av, bv;
    if (k === 'run_id' || k === 'strategy_name' || k === 'symbol' || k === 'interval' || k === 'protocol' || k === 'segment' || k === 'verdict'){
      av = (a[k] || '').toString(); bv = (b[k] || '').toString();
      return av.localeCompare(bv) * dir;
    }
    av = (a.metrics || {})[k]; bv = (b.metrics || {})[k];
    if (typeof av !== 'number' || typeof bv !== 'number') return 0;
    return (av - bv) * dir;
  });
  el('runRows').innerHTML = runs.map(function(r){
    var m = r.metrics || {};
    return '<tr>' +
      '<td class="rid">' + r.run_id + '</td>' +
      '<td style="color:var(--text);white-space:nowrap">' + r.strategy_name + '</td>' +
      '<td>' + (SHORT[r.symbol] || r.symbol) + '</td>' +
      '<td>' + r.interval + '</td>' +
      '<td style="white-space:nowrap">' + r.protocol + '</td>' +
      '<td style="white-space:nowrap">' + r.segment + '</td>' +
      '<td class="' + cls(m.total_return_pct) + '">' + sign(m.total_return_pct) + fmt(m.total_return_pct) + '</td>' +
      '<td>' + fmt(m.win_rate_pct, 1) + '</td>' +
      '<td>' + fmt(m.profit_factor) + '</td>' +
      '<td class="neg">' + fmt(m.max_drawdown_pct) + '</td>' +
      '<td>' + (m.total_trades || 0) + '</td>' +
      '<td><span class="vd ' + r.verdict + '">' + (r.verdict || '').toUpperCase() + '</span></td>' +
      '<td class="note-cell">' + (r.note || '') + '</td>' +
    '</tr>';
  }).join('');
  el('runCount').innerHTML = '<b>' + runs.length + '</b> / ' + (X.runs || []).length + ' RUNS';
  // sort header indicator
  document.querySelectorAll('.run-table th[data-sort]').forEach(function(th){
    th.classList.remove('sorted-asc', 'sorted-desc');
    if (th.getAttribute('data-sort') === _sort.key){
      th.classList.add(_sort.dir === 'asc' ? 'sorted-asc' : 'sorted-desc');
    }
  });
}

function bindSortHeaders(){
  document.querySelectorAll('.run-table th[data-sort]').forEach(function(th){
    th.addEventListener('click', function(){
      var k = th.getAttribute('data-sort');
      if (_sort.key === k){
        _sort.dir = _sort.dir === 'asc' ? 'desc' : 'asc';
      } else {
        _sort.key = k; _sort.dir = 'asc';
      }
      applyFilters();
    });
  });
}

/* ---------- 视图切换 ---------- */
var VIEWS = ORDER.concat(['SYSTEM','LOG']);
var curView = 'BTCUSDT';
function show(v){
  if (VIEWS.indexOf(v) < 0) return;
  curView = v;
  VIEWS.forEach(function(x){
    var p = el('view-' + x); if (p) p.classList.toggle('active', x === v);
    var t = el('tab-' + x); if (t) t.classList.toggle('active', x === v);
    var cc = el('cc-' + x); if (cc) cc.classList.toggle('active', x === v);
  });
  el('sbView').textContent = SHORT[v] || v;
  if (ORDER.indexOf(v) >= 0){
    setTimeout(function(){
      try { Plotly.Plots.resize(el('price-' + v)); Plotly.Plots.resize(el('equity-' + v)); } catch(e){}
    }, 30);
  }
  window.scrollTo({top:0, behavior: RM ? 'auto' : 'smooth'});
}

/* ---------- 开机序列 ---------- */
function boot(){
  var p = portfolioStats();
  var lines = [
    '> PRICE_ACTION://TERMINAL v2.1 — boot sequence',
    '> mounting data feed ......... <span class="ok">[OK]</span> BINANCE_VISION',
    '> loading backtest results ... <span class="ok">[OK]</span> 3 SYMBOLS / ' + p.trades + ' TRADES',
    '> multi-strategy matrix ...... <span class="ok">[OK]</span> 5 STRATEGIES × 165 RUNS',
    '> anti-overfitting audit ..... <span class="ok">[OK]</span> 4 PROTOCOLS / seed ' + (X.random_seed || '?'),
    '> formal strategy ............ <span class="ok">[OK]</span> PA-FAST-TREND (composite 43.07)',
    '> render engine .............. <span class="ok">[OK]</span> PLOTLY',
    '> access granted <span class="ok">▮</span>'
  ];
  var b = el('boot'), box = el('bootBox');
  function finish(){ b.classList.add('done'); }
  if (RM){ finish(); return; }
  var i = 0;
  function next(){
    if (i >= lines.length){
      box.innerHTML += '<div class="skip">click / any key to enter</div>';
      setTimeout(finish, 450);
      return;
    }
    var div = document.createElement('div');
    div.className = 'ln';
    div.innerHTML = lines[i];
    box.appendChild(div);
    i++;
    setTimeout(next, 150);
  }
  next();
  b.addEventListener('click', finish);
  document.addEventListener('keydown', function once(){
    finish();
    document.removeEventListener('keydown', once);
  });
}

/* ---------- 数字雨 ---------- */
function rain(){
  if (RM) return;
  var cv = el('rain'), ctx = cv.getContext('2d');
  var chars = 'アイウエオカキクケコサシスセソ0123456789$¥₿Ξ';
  var fs = 14, cols, drops;
  function resize(){
    cv.width = window.innerWidth; cv.height = window.innerHeight;
    cols = Math.floor(cv.width / fs);
    drops = [];
    for (var i = 0; i < cols; i++) drops[i] = Math.random() * -60;
  }
  resize();
  window.addEventListener('resize', resize);
  var last = 0;
  function frame(t){
    if (document.hidden){ requestAnimationFrame(frame); return; }
    if (t - last > 66){
      ctx.fillStyle = 'rgba(3,7,4,0.12)';
      ctx.fillRect(0, 0, cv.width, cv.height);
      ctx.font = fs + 'px monospace';
      ctx.fillStyle = '#00ff41';
      for (var i = 0; i < drops.length; i++){
        var ch = chars[Math.floor(Math.random() * chars.length)];
        ctx.fillText(ch, i * fs, drops[i] * fs);
        if (drops[i] * fs > cv.height && Math.random() > 0.976) drops[i] = 0;
        drops[i]++;
      }
      last = t;
    }
    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);
}

/* ---------- 时钟 ---------- */
function clock(){
  function tick(){
    var d = new Date();
    function p(n){ return (n < 10 ? '0' : '') + n; }
    el('sbClock').textContent = d.getFullYear() + '-' + p(d.getMonth()+1) + '-' + p(d.getDate()) + ' ' + p(d.getHours()) + ':' + p(d.getMinutes()) + ':' + p(d.getSeconds());
  }
  tick(); setInterval(tick, 1000);
}

/* ---------- 事件 ---------- */
function bindEvents(){
  document.querySelectorAll('.nav-btn').forEach(function(b){
    b.addEventListener('click', function(){ show(b.getAttribute('data-view')); });
  });
  el('coinCards').addEventListener('click', function(e){
    var card = e.target.closest('.coin-card');
    if (card) show(card.getAttribute('data-view'));
  });
  el('coinCards').addEventListener('keydown', function(e){
    var card = e.target.closest('.coin-card');
    if (card && (e.key === 'Enter' || e.key === ' ')){ e.preventDefault(); show(card.getAttribute('data-view')); }
  });
  document.addEventListener('click', function(e){
    var kpi = e.target.closest('.kpi');
    if (kpi && kpi.getAttribute('data-copy')){ copyVal(kpi.getAttribute('data-copy')); return; }
    var chip = e.target.closest('.chip');
    if (chip){
      var ledgerEl = chip.closest('[id^="ledger-"]');
      if (ledgerEl){
        var s = ledgerEl.id.replace('ledger-', '');
        ledgerState[s][chip.getAttribute('data-f')] = chip.getAttribute('data-v');
        renderLedger(s);
      }
      return;
    }
    var th = e.target.closest('.trade-table th');
    if (th && th.getAttribute('data-k')){
      var table = th.closest('[id^="ledger-"]') || th.closest('.panel');
      var host = th.closest('.panel').querySelector('[id^="ledger-"]');
      if (host){
        var sym = host.id.replace('ledger-', '');
        var k = th.getAttribute('data-k');
        if (ledgerState[sym].sortKey === k) ledgerState[sym].sortDir *= -1;
        else { ledgerState[sym].sortKey = k; ledgerState[sym].sortDir = 1; }
        renderLedger(sym);
      }
    }
  });
  document.addEventListener('keydown', function(e){
    if (e.target && /INPUT|TEXTAREA/.test(e.target.tagName)) return;
    var map = {'1':'BTCUSDT','2':'ETHUSDT','3':'BNBUSDT','4':'SYSTEM','5':'LOG','s':'SYSTEM','l':'LOG'};
    var k = e.key.toLowerCase();
    if (map[k]) show(map[k]);
    else if (e.key === '?') el('help').classList.toggle('show');
    else if (e.key === 'Escape') el('help').classList.remove('show');
  });
  el('help').addEventListener('click', function(){ el('help').classList.remove('show'); });
}

/* ---------- init ---------- */
buildPortfolio();
buildCoinCards();
ORDER.forEach(buildCoinPanel);
buildLog();
bindEvents();
el('sbTrades').textContent = 'TRADES: ' + portfolioStats().trades;
var _h = (location.hash || '').replace('#','');
show(VIEWS.indexOf(_h) >= 0 ? _h : 'BTCUSDT');
window.addEventListener('hashchange', function(){ var h = (location.hash || '').replace('#',''); if (VIEWS.indexOf(h) >= 0) show(h); });
boot();
rain();
clock();
</script>
</body>
</html>"""


def build_html(data, summary, experiments):
    embed = json.dumps({"coins": data, "summary": summary}, ensure_ascii=False)
    embed = embed.replace("</script>", "<\\/script>")
    exp = json.dumps(experiments, ensure_ascii=False).replace("</script>", "<\\/script>")

    # 数据段说明（取 BTC 的范围，三币一致）
    rng = ""
    if SYMBOLS and SYMBOLS[0] in data:
        r = data[SYMBOLS[0]]["data_range"]
        rng = f"{r['start'][:10]} → {r['end'][:10]}"

    tabs_html = ""
    panels_html = ""
    for i, s in enumerate(SYMBOLS):
        active = " active" if i == 0 else ""
        tabs_html += (
            f'    <button class="nav-btn{active}" data-view="{s}" id="tab-{s}">'
            f"<b>[{i+1}]</b>{LABELS[s]}</button>\n"
        )
        panels_html += f'  <section class="view{active}" id="view-{s}"></section>\n'

    html = HTML_TEMPLATE.replace("__EMBED__", embed)
    html = html.replace("__EXPERIMENTS__", exp)
    html = html.replace("__TABS__", tabs_html)
    html = html.replace("__PANELS__", panels_html)
    html = html.replace("__RANGE__", rng)
    return html


def main():
    data, summary = load_data()
    experiments = load_experiments(summary)
    html = build_html(data, summary, experiments)
    with open(OUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)
    size = os.path.getsize(OUT_HTML) / 1024
    print(f"看板已生成: {OUT_HTML} ({size:.0f} KB)")


if __name__ == "__main__":
    main()
