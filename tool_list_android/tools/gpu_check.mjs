// 실제 GPU(WebGL2) 절삭 결과를 기준 구현과 비교한다. 사용: node tools/gpu_check.mjs [--software]
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';

const software = process.argv.includes('--software');
const server = spawn('npx', ['vite', '--port', '4181', '--strictPort', '--host', '127.0.0.1'], { shell: true, stdio: 'ignore' });
for (let i = 0; i < 60; i++) {
  try { if ((await fetch('http://127.0.0.1:4181/')).ok) break; } catch { /* 아직 안 떴다 */ }
  await new Promise((r) => setTimeout(r, 500));
}
const browser = await chromium.launch({ channel: 'msedge', args: software ? ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] : [] });
try {
  const page = await browser.newPage();
  page.on('console', (m) => console.log('[브라우저]', m.text()));
  page.on('pageerror', (e) => console.log('[pageerror]', e.message));
  await page.goto('http://127.0.0.1:4181/tools/gpu/gpu_check.html' + (software ? '?perf=0' : ''));
  await page.waitForFunction(() => window.__gpuCheck !== undefined, null, { timeout: 120000 });
  const r = await page.evaluate(() => window.__gpuCheck);
  console.log(JSON.stringify(r, null, 1));
  const bad = r.error || r.reduce?.bad > 0 || JSON.stringify(r.rapid) !== '[2]' || Object.values(r.results ?? {}).some((x) => x.badCells > Math.max(2, x.cut * 1e-4) || x.cut === 0);
  process.exitCode = bad ? 1 : 0;
} finally {
  await browser.close();
  server.kill();
}
