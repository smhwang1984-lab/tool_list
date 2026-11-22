// 확대 고정밀(G8)을 앱에서 실제로 돌려 본다 — 소재 적용 → 소재 창 → [보는 영역 정밀 계산] → 상태 줄 확인.
// 사용: node tools/gpu_zoom_check.mjs <캡처폴더> [nc파일] [--software]
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';

const args = process.argv.slice(2).filter((a) => !a.startsWith('--'));
const software = process.argv.includes('--software');
const out = args[0] ?? 'shots';
const file = args[1] ?? 'tests/fixtures/O4812.nc';
mkdirSync(out, { recursive: true });
const server = spawn('npx', ['vite', '--port', '4183', '--strictPort', '--host', '127.0.0.1'], { shell: true, stdio: 'ignore' });
for (let i = 0; i < 60; i++) {
  try { if ((await fetch('http://127.0.0.1:4183/')).ok) break; } catch { /* 아직 */ }
  await new Promise((r) => setTimeout(r, 500));
}
const browser = await chromium.launch({ channel: 'msedge', args: software ? ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] : [] });
let code = 1;
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.on('pageerror', (e) => console.log('PAGEERROR', e.message));
  await page.goto('http://127.0.0.1:4183/');
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.click('text=파일 열기')]);
  await chooser.setFiles(file);
  await page.waitForTimeout(800);
  await page.click('button:has-text("Viewer")');
  await page.waitForTimeout(1500);
  await page.click('.tool-btn:has-text("소재")');
  await page.waitForTimeout(500);
  const fit = page.locator('button:has-text("툴패스 범위에 맞추기")');
  if (await fit.count()) await fit.click();
  await page.click('button:has-text("적용")');
  await page.waitForTimeout(4000);
  await page.click('.tool-btn:has-text("소재")');
  await page.waitForTimeout(800);
  const status = async () => (await page.locator('.stock-status').first().innerText().catch(() => ''));
  const before = await status();
  console.log('전:', before.split('\n')[0]);
  await page.click('button:has-text("보는 영역 정밀 계산")');
  await page.waitForTimeout(6000);
  const after = await status();
  console.log('후:', after.split('\n')[0]);
  await page.screenshot({ path: `${out}/zoom.png` });
  const cell = /셀 ([0-9.e-]+)mm/;
  const b = Number((before.match(cell) ?? [])[1]), a = Number((after.match(cell) ?? [])[1]);
  console.log('셀(mm) 전/후', b, a, '확대 표시', after.includes('확대 고정밀'));
  await page.click('button:has-text("전체로 되돌리기")');
  await page.waitForTimeout(4000);
  const back = await status();
  console.log('복귀:', back.split('\n')[0]);
  code = a > 0 && a < b && after.includes('확대 고정밀') && !back.includes('확대 고정밀') ? 0 : 1;
} finally { await browser.close(); server.kill(); }
process.exit(code);
