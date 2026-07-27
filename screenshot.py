#!/usr/bin/env python3
"""在线程中启动 FastAPI 服务器，用 chromium headless 截图，然后退出。"""
import threading
import time
import subprocess
import os
import sys
import socket

BASE = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(BASE, "dashboard")
SHOTS = os.path.join(DASH, "screenshots")
os.makedirs(SHOTS, exist_ok=True)

# 确保看板已生成
gen = os.path.join(DASH, "generate.py")
subprocess.run([sys.executable, gen], cwd=DASH, capture_output=True)

# 在线程中启动 uvicorn
import uvicorn
from server import app

config = uvicorn.Config(app, host="0.0.0.0", port=8787, log_level="error")
server_inst = uvicorn.Server(config)
thread = threading.Thread(target=server_inst.run, daemon=True)
thread.start()
print("服务器线程已启动，等待就绪...")
time.sleep(4)

# 验证
import urllib.request
try:
    r = urllib.request.urlopen("http://localhost:8787/api/health", timeout=5)
    print(f"服务器就绪: {r.read().decode()}")
except Exception as e:
    print(f"服务器未就绪: {e}")
    sys.exit(1)

# 截图
shots = [
    ("dashboard_overview", "http://localhost:8787/"),
]
for name, url in shots:
    out = os.path.join(SHOTS, f"{name}.png")
    cmd = [
        "chromium-browser", "--headless", "--no-sandbox", "--disable-gpu",
        f"--screenshot={out}", "--window-size=1400,2200",
        "--hide-scrollbars", "--virtual-time-budget=20000",
        url,
    ]
    print(f"截图 {name} ...")
    result = subprocess.run(cmd, timeout=90, capture_output=True, text=True)
    if os.path.exists(out) and os.path.getsize(out) > 1000:
        sz = os.path.getsize(out) / 1024
        print(f"  -> {out} ({sz:.0f} KB)")
    else:
        print(f"  -> 截图失败或为空")
        if result.stderr:
            print(f"     stderr: {result.stderr[:300]}")

print("完成")
