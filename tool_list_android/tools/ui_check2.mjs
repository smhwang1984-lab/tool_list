// 설정 창·필터 영역 확인. 사용: node tools/ui_check2.mjs <캡처폴더>
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';
const out = process.argv[2] ?? 'shots';
mkdirSync(out, { recursive: true });
const server = spawn('npx', ['vite', 'preview', '--port', '4181', '--strictPort'], { shell: true, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 3500));
const browser = await chromium.launch({ channel: 'msedge' });
try {
  const page = await browser.newPage({ viewport: { width: 1100, height: 760 } });
  page.on('pageerror', (e) => { throw new Error('pageerror ' + e.message); });
  await page.goto('http://localhost:4181/');
  await page.click('button[title="설정"]');
  await page.selectOption('.settings select', '60');
  await page.fill('.settings input[type=range] >> nth=0', '80');
  await page.screenshot({ path: `${out}/settings.png` });
  console.log('저장값', await page.evaluate(() => [localStorage.getItem('sumpath.toolpath_line_width_pct'), localStorage.getItem('sumpath.sensitivity_pct')]));
  await page.click('.settings >> text=닫기');
  await page.click('.tool-btn:has-text("Viewer")');
  await page.waitForTimeout(500);
  await page.click('text=텍스트 정지');
  await page.fill('.filter-panel input[type=text]', 'M30');
  await page.screenshot({ path: `${out}/filter.png` });
  console.log('정지옵션', await page.evaluate(() => ['stop_at_text', 'stop_text_value', 'stop_at_m00'].map((k) => localStorage.getItem('sumpath.' + k))));
} finally {
  await browser.close();
  server.kill();
}
