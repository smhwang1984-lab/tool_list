// 화면 동작 확인: 예제 산출 → 행 추가/수정/삭제/이름 경우의 수. 사용: node tools/ui_check.mjs <캡처폴더>
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';

const out = process.argv[2] ?? 'shots';
mkdirSync(out, { recursive: true });
const server = spawn('npx', ['vite', 'preview', '--port', '4180', '--strictPort'], { shell: true, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 3500));
const browser = await chromium.launch({ channel: 'msedge' });
const fail = (m) => { throw new Error(m); };
try {
  const page = await browser.newPage({ viewport: { width: 1100, height: 760 } });
  page.on('pageerror', (e) => fail('pageerror ' + e.message));
  await page.goto('http://localhost:4180/');
  await page.click('text=예제');
  await page.waitForTimeout(300);
  const count = async () => (await page.locator('.tool-count').innerText());
  console.log('초기', await count());
  // 행 추가
  await page.click('.tool-actions >> text=행 추가');
  await page.fill('.row-form label:nth-child(3) input', 'D8 F.EM');
  await page.screenshot({ path: `${out}/editor.png` });
  await page.click('dialog >> text=저장');
  console.log('추가 후', await count(), '/ 마지막 행:', await page.locator('tbody tr:last-child').innerText());
  // 수정: 두 번 탭
  await page.dblclick('tbody tr:nth-child(3) td:nth-child(3)');
  await page.waitForSelector('dialog');
  await page.fill('.row-form label:nth-child(3) input', 'D99 B.EM');
  await page.click('dialog >> text=저장');
  console.log('수정 후 3행:', (await page.locator('tbody tr:nth-child(3)').innerText()).replace(/\s+/g, ' '));
  // 삭제
  await page.click('tbody tr:nth-child(2)');
  await page.click('.tool-actions >> text=삭제');
  await page.click('dialog button:has-text("삭제")');
  await page.waitForTimeout(300); console.log('삭제 후', await count());
  // 이름 경우의 수
  await page.click('.tool-actions >> text=이름 경우의 수');
  await page.waitForSelector('.type-rows');
  await page.screenshot({ path: `${out}/types.png` });
  console.log('이름 경우 행 수', await page.locator('.type-row').count());
} finally {
  await browser.close();
  server.kill();
}
