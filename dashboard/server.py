"""
本地 Web 服务器：为量化看板提供 HTTP 服务 + 数据 API。

启动：python3 server.py
访问：http://localhost:8787

特性：
- 提供 index.html 操作面板
- REST API：/api/summary, /api/backtest/<symbol>
- 自动重新生成看板（如果结果有更新）
"""
import os
import json
import subprocess
import sys

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

BASE = os.path.dirname(os.path.abspath(__file__))
RESULT_DIR = os.path.join(BASE, "..", "results")
DASH_HTML = os.path.join(BASE, "index.html")
GEN_SCRIPT = os.path.join(BASE, "generate.py")

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


if __name__ == "__main__":
    ensure_dashboard()
    print("=" * 50)
    print("  Price Action 量化交易系统 - Web 操作面板")
    print("  访问: http://localhost:8787")
    print("  API:  /api/summary, /api/backtest/BTCUSDT")
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=8787)
