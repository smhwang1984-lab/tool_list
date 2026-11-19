// Viewer: 예제를 열고 Viewer 모드로 → 경로·공정 목록·재생을 확인한다. 사용: node tools/ui_check5.mjs <캡처폴더>
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
const out = process.argv[2] ?? 'shots';
mkdirSync(out, { recursive: true });
const server = spawn('npx', ['vite', 'preview', '--port', '4184', '--strictPort'], { shell: true, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 3500));
const browser = await chromium.launch({ channel: 'msedge', args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader', '--ignore-gpu-blocklist'] });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });
  page.on('pageerror', (e) => { console.log('PAGEERROR', e.message); });
  page.on('console', (m) => { if (m.type() === 'error') console.log('CONSOLE', m.text()); });
  await page.goto('http://localhost:4184/');
  const file = process.argv[3] ?? 'tests/fixtures/O4812.nc';
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.click('text=파일 열기')]);
  await chooser.setFiles(file);
  await page.waitForTimeout(800);
  await page.click('button:has-text("Viewer")');
  await page.click('.machine-toggle');
  await page.selectOption('select[aria-label="장비 타입"]', { label: process.argv[4] ?? 'CNC 선반 (턴밀 포함)' });
  await page.click('.machine-toggle');
  await page.waitForTimeout(2500);
  await page.screenshot({ path: `${out}/viewer.png` });
  console.log('공정 목록', await page.locator('.filter-list li, .filter-list .item').count());
  await page.click('.v-play button:has-text("▶")');
  await page.waitForTimeout(1500);
  console.log('시간', await page.locator('.v-time').innerText(), '좌표', await page.locator('.v-coord').innerText());
  await page.screenshot({ path: `${out}/viewer_play.png` });
} finally { await browser.close(); server.kill(); }
