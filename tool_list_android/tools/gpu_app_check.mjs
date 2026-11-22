// 앱 전체에서 고해상도 엔진(GPU)을 실제로 돌려 본다 — 파일 열기 → Viewer → 소재 → GPU 해상도 → 적용 → 캡처.
// 사용: node tools/gpu_app_check.mjs <캡처폴더> [nc파일] [gpu키(기본 gpu:2048)] [--software]
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';

const args = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const software = process.argv.includes('--software');
const out = args[0] ?? 'shots';
const file = args[1] ?? 'tests/fixtures/O4812.nc';
const key = args[2] ?? 'gpu:2048';
mkdirSync(out, { recursive: true });
const server = spawn('npx', ['vite', '--port', '4182', '--strictPort', '--host', '127.0.0.1'], { shell: true, stdio: 'ignore' });
for (let i = 0; i < 60; i++) {
  try { if ((await fetch('http://127.0.0.1:4182/')).ok) break; } catch { /* 아직 */ }
  await new Promise((r) => setTimeout(r, 500));
}
const browser = await chromium.launch({
  channel: 'msedge',
  args: software ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] : [],
});
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
  page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log('CONSOLE', m.text().slice(0, 200)); });
  await page.goto('http://127.0.0.1:4182/');
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.click('text=파일 열기')]);
  await chooser.setFiles(file);
  await page.waitForTimeout(800);
  await page.click('button:has-text("Viewer")');
  await page.waitForTimeout(1500);
  await page.click('.tool-btn:has-text("소재")');
  await page.waitForTimeout(500);
  // 소재 치수는 주석에서 읽힌 값을 쓴다. [툴패스 범위에 맞추기]로 확실히 채운다.
  const fit = page.locator('button:has-text("툴패스 범위에 맞추기")');
  if (await fit.count()) await fit.click();
  const sel = page.locator('select').filter({ has: page.locator('optgroup') }).first();
  const opts = await sel.locator('option').evaluateAll((os) => os.map((o) => `${o.value}${o.disabled ? '(비활성)' : ''}`));
  console.log('해상도 목록', opts.join(' '));
  console.log('툴팁', (await sel.getAttribute('title'))?.replace(/\n/g, ' / '));
  await sel.selectOption(key);
  await page.screenshot({ path: `${out}/dialog.png` });
  await page.click('button:has-text("적용")');
  await page.waitForTimeout(6000);
  await page.screenshot({ path: `${out}/gpu_applied.png` });
  // 재생 위치를 끝으로 옮겨 전부 깎인 모습을 본다
  await page.evaluate(() => {
    const r = document.querySelector('input[type=range]');
    r.value = r.max; r.dispatchEvent(new Event('input', { bubbles: true })); r.dispatchEvent(new Event('change', { bubbles: true }));
  });
  const t0 = Date.now();
  await page.waitForTimeout(3000);
  await page.click('button:has-text("ISO")');
  await page.waitForTimeout(2500);
  console.log('끝까지 보기까지', Date.now() - t0, 'ms');
  await page.screenshot({ path: `${out}/gpu_end_iso.png` });
  await page.click('.tool-btn:has-text("소재")');
  await page.waitForTimeout(1800);
  const status = await page.locator('.stock-status, .dialog pre, .dialog-body').first().innerText().catch(() => '');
  console.log('상태 창:\n' + status.split('\n').filter((l) => /격자|GPU|엔진|선분/.test(l)).join('\n'));
  await page.screenshot({ path: `${out}/status.png` });
} finally { await browser.close(); server.kill(); }
