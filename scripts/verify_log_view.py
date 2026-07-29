"""启本地服务 → playwright 截图 LOG 视图 → 退出。"""
import os, sys, time, subprocess, threading, http.server, socketserver, functools

ROOT = os.path.dirname(os.path.abspath(__file__))
DASH = os.path.join(ROOT, "..", "dashboard")
PORT = 8788  # 避开可能占用
OUT_DIR = os.path.join(ROOT, "..", "artifacts")
os.makedirs(OUT_DIR, exist_ok=True)

# 启 server
os.chdir(DASH)
handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=DASH)
httpd = socketserver.TCPServer(("127.0.0.1", PORT), handler)
threading.Thread(target=httpd.serve_forever, daemon=True).start()
print(f"server up: http://127.0.0.1:{PORT}/")

from playwright.sync_api import sync_playwright

with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=["--no-sandbox"])
    ctx = browser.new_context(viewport={"width": 1440, "height": 2400}, device_scale_factor=1.5)
    page = ctx.new_page()
    page.goto(f"http://127.0.0.1:{PORT}/index.html", wait_until="networkidle", timeout=30000)
    page.wait_for_timeout(1500)  # 开机序列
    # 切到 LOG 视图
    page.evaluate("show('LOG')")
    page.wait_for_timeout(800)
    # 1) 完整 LOG 区块全屏
    page.screenshot(path=os.path.join(OUT_DIR, "dash_LOG_full.png"), full_page=True)
    # 2) 仅 LOG 视图
    el = page.locator("#view-LOG")
    el.screenshot(path=os.path.join(OUT_DIR, "dash_LOG_view.png"))
    # 3) 排名 + 协议 + 结论区
    page.locator("#view-LOG .panel").screenshot(path=os.path.join(OUT_DIR, "dash_LOG_panel.png"))
    # 4) RUN HISTORY 表格应用一次筛选：按"blind-holdout"
    page.select_option("#fProto", "blind-holdout")
    page.wait_for_timeout(300)
    el.screenshot(path=os.path.join(OUT_DIR, "dash_LOG_filter_holdout.png"))
    # 5) 排序演示：点收益降序
    page.select_option("#fProto", "")
    page.wait_for_timeout(200)
    page.click('th[data-sort="total_return_pct"]')
    page.click('th[data-sort="total_return_pct"]')  # 第二次降序
    page.wait_for_timeout(200)
    page.locator("#view-LOG").screenshot(path=os.path.join(OUT_DIR, "dash_LOG_sorted.png"))
    print("screenshots saved to", OUT_DIR)
    browser.close()

httpd.shutdown()
