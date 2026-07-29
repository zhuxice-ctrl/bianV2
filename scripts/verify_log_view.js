// 启本地服务 + puppeteer-core 截图 LOG 视图
const { spawn } = require('child_process');
const path = require('path');
const http = require('http');
const fs = require('fs');

const ROOT = path.resolve(__dirname, '..', 'dashboard');
const OUT = path.resolve(__dirname, '..', 'artifacts');
fs.mkdirSync(OUT, { recursive: true });

const PORT = 8788;
const server = spawn('python3', ['-m', 'http.server', String(PORT), '--directory', ROOT, '--bind', '127.0.0.1'], {
  stdio: 'ignore'
});

function waitReady(cb) {
  const tick = () => http.get({ host: '127.0.0.1', port: PORT, path: '/' }, res => {
    res.resume(); cb();
  }).on('error', () => setTimeout(tick, 200));
  setTimeout(tick, 200);
}

async function shotEl(page, sel, outName) {
  const box = await page.evaluate((s) => {
    const el = document.querySelector(s);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y, width: r.width, height: r.height };
  }, sel);
  if (!box) { console.log('miss', sel); return; }
  await page.screenshot({
    path: path.join(OUT, outName),
    clip: { x: box.x, y: box.y, width: box.width, height: Math.min(box.height, 4000) }
  });
  console.log('shot', outName, box.width.toFixed(0), 'x', Math.min(box.height, 4000).toFixed(0));
}

(async () => {
  await new Promise(r => waitReady(r));
  console.log('server up');
  const puppeteer = require('/home/gem/.npm-global/lib/node_modules/puppeteer-core');
  const browser = await puppeteer.launch({
    executablePath: '/opt/chromium.org/chromium/chromium-browser',
    headless: 'new',
    args: ['--no-sandbox', '--disable-dev-shm-usage']
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1440, height: 900, deviceScaleFactor: 1.5 });
  await page.goto(`http://127.0.0.1:${PORT}/index.html`, { waitUntil: 'networkidle0', timeout: 30000 });
  await new Promise(r => setTimeout(r, 1800));
  await page.evaluate(() => { show('LOG'); });
  await new Promise(r => setTimeout(r, 700));

  await page.screenshot({ path: path.join(OUT, 'dash_LOG_full.png'), fullPage: true });
  await shotEl(page, '#view-LOG .panel', 'dash_LOG_panel.png');

  await page.select('#fProto', 'blind-holdout');
  await new Promise(r => setTimeout(r, 300));
  await shotEl(page, '#view-LOG', 'dash_LOG_filter_holdout.png');

  await page.click('#fReset');
  await new Promise(r => setTimeout(r, 200));
  await page.click('th[data-sort="total_return_pct"]');
  await page.click('th[data-sort="total_return_pct"]');
  await new Promise(r => setTimeout(r, 200));
  await shotEl(page, '#view-LOG', 'dash_LOG_sorted.png');

  await page.evaluate(() => { show('BTCUSDT'); });
  await new Promise(r => setTimeout(r, 1200));
  await page.screenshot({ path: path.join(OUT, 'dash_BTC_home.png'), fullPage: false });

  await page.evaluate(() => { show('SYSTEM'); });
  await new Promise(r => setTimeout(r, 500));
  await shotEl(page, '#view-SYSTEM', 'dash_SYSTEM.png');

  console.log('OK');
  await browser.close();
  server.kill();
  process.exit(0);
})().catch(e => { console.error(e); server.kill(); process.exit(1); });
