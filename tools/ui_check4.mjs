// 예제 → PDF 내려받기 + 복사. 사용: node tools/ui_check4.mjs <출력폴더>
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { mkdirSync, copyFileSync } from 'node:fs';
const out = process.argv[2] ?? 'shots';
mkdirSync(out, { recursive: true });
const server = spawn('npx', ['vite', 'preview', '--port', '4183', '--strictPort'], { shell: true, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 3500));
const browser = await chromium.launch({ channel: 'msedge' });
try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, acceptDownloads: true, permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await ctx.newPage();
  page.on('pageerror', (e) => { throw new Error('pageerror ' + e.message); });
  await page.goto('http://localhost:4183/');
  await page.click('text=예제');
  await page.waitForTimeout(600);
  await page.click('.tool-actions button:has-text("복사")').catch(() => page.click('button:has-text("복사")'));
  await page.waitForTimeout(300);
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  console.log('TSV lines', clip.split('\n').length, JSON.stringify(clip.split('\n')[0]).slice(0, 80));
  const [dl] = await Promise.all([page.waitForEvent('download', { timeout: 30000 }), page.click('button:has-text("PDF")')]);
  const p = await dl.path();
  copyFileSync(p, `${out}/tool_list.pdf`);
  console.log('PDF', dl.suggestedFilename());
} finally { await browser.close(); server.kill(); }
