"""
本地 Web 服务器：为量化看板提供 HTTP 服务 + 数据 API。

启动：python3 server.py
访问：http://localhost:8787

特性：
- 提供 index.html 操作面板
- REST API：/api/summary, /api/backtest/<symbol>, /api/research/latest
- 自动重新生成看板（如果结果有更新）
"""
import os
import json
import subprocess
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

BASE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = str(Path(BASE).parent.resolve())
RESULT_DIR = os.path.join(BASE, "..", "results")
DASH_HTML = os.path.join(BASE, "index.html")
RESEARCH_HTML = os.path.join(BASE, "research.html")
GEN_SCRIPT = os.path.join(BASE, "generate.py")

# 研究终端契约接口使用的 popular-universe 采集配置。
RESEARCH_CONFIG = os.path.join(REPO_ROOT, "configs", "experiments", "popular_universe_100u.yaml")

app = FastAPI(title="Price Action 量化系统", docs_url="/docs")
app.mount("/static", StaticFiles(directory=BASE), name="static")


def ensure_dashboard():
    """确保看板 HTML 已生成。"""
    if not os.path.exists(DASH_HTML):
        subprocess.run([sys.executable, GEN_SCRIPT], check=True)


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    ensure_dashboard()
    with open(DASH_HTML, encoding="utf-8") as f:
        return HTMLResponse(f.read())


@app.get("/api/summary")
async def api_summary():
    path = os.path.join(RESULT_DIR, "summary.json")
    if not os.path.exists(path):
        raise HTTPException(404, "summary not found, run run_backtest.py first")
    with open(path, encoding="utf-8") as f:
        return JSONResponse(json.load(f))


@app.get("/api/backtest/{symbol}")
async def api_backtest(symbol: str):
    symbol = symbol.upper()
    path = os.path.join(RESULT_DIR, f"backtest_{symbol}.json")
    if not os.path.exists(path):
        raise HTTPException(404, f"no backtest for {symbol}")
    with open(path, encoding="utf-8") as f:
        return JSONResponse(json.load(f))


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "price-action-quant"}


@app.get("/plotly.min.js")
async def plotly_js():
    path = os.path.join(BASE, "plotly.min.js")
    if not os.path.exists(path):
        raise HTTPException(404, "plotly.min.js not found")
    return FileResponse(path, media_type="application/javascript")


# ---------------------------------------------------------------------------
# 热门币研究终端 — 契约接口 GET /api/research/latest
# 对齐 docs/contracts/research-terminal-ui-contract.md v1 的 ResearchTerminalResponse。
# 成功时始终返回 HTTP 200，由响应体 state 字段决定终端渲染状态。
# ---------------------------------------------------------------------------


def _build_research_response():
    """懒加载 bian_quant 聚合器并构建契约响应；失败时返回 empty 态。"""
    # 确保 src 包可导入（editable install 未生效时的兜底）。
    src_dir = os.path.join(REPO_ROOT, "src")
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)
    from bian_quant.reporting.research_terminal import build_research_terminal_response

    return build_research_terminal_response(
        Path(RESEARCH_CONFIG),
        repo_root=Path(REPO_ROOT),
    )


@app.get("/api/research/latest")
async def api_research_latest():
    """返回最新 dual_horizon_derivatives 运行的研究终端契约响应。"""
    try:
        response = _build_research_response()
    except Exception as exc:  # 契约要求成功始终 200；聚合异常降级为 empty 态。
        return JSONResponse(
            {
                "schema_version": "research-terminal-v1",
                "state": "empty",
                "generated_at": __import__("datetime").datetime.now(
                    __import__("datetime").timezone.utc
                ).isoformat(),
                "run": {
                    "id": None,
                    "status": "empty",
                    "as_of": None,
                    "planned_objects": 0,
                    "availability_manifest_sha256": None,
                    "pre_listing_exclusion_count": 0,
                    "artifact_path": None,
                },
                "kpis": {
                    "popular_member_count": None,
                    "published_snapshot_count": 0,
                    "blocked_period_count": 0,
                    "temporary_blocker_count": 0,
                },
                "popular_universe": {"latest_date": None, "latest_members": [], "daily_counts": []},
                "market_cycle": {
                    "label": "insufficient_evidence",
                    "confidence": 0.0,
                    "probabilities": {"bull": 0.0, "neutral": 0.0, "risk_off": 0.0},
                    "decision_time": None,
                    "sample_count": 0,
                    "evidence_sha256": None,
                    "status": "missing",
                    "funding_alignment": {
                        "score": None,
                        "positive_rate_share": None,
                        "median_rate": None,
                        "coverage_ratio": None,
                        "source_sha256": None,
                        "status": "missing",
                    },
                },
                "coverage": [],
                "blockers": [],
                "pre_listing_exclusions": [],
                "snapshots": [],
                "single_asset_strategy_evaluations": [],
            }
        )
    return JSONResponse(response.model_dump(mode="json"))


@app.get("/research", response_class=HTMLResponse)
async def research_terminal():
    """研究终端页面入口。从 dashboard/research.html 提供完整 UI，对接 /api/research/latest。"""
    if not os.path.exists(RESEARCH_HTML):
        raise HTTPException(404, "research.html not found")
    with open(RESEARCH_HTML, encoding="utf-8") as f:
        return HTMLResponse(f.read())

if __name__ == "__main__":
    ensure_dashboard()
    print("=" * 50)
    print("  Price Action 量化交易系统 - Web 操作面板")
    print("  访问: http://localhost:8787")
    print("  API:  /api/summary, /api/backtest/BTCUSDT, /api/research/latest")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8787)

