// 화면 확인용(가로 전용): 빌드된 앱(dist)을 vite preview 로 띄워 Edge 로 캡처한다. 사용: node tools/shot.mjs <출력폴더>
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';

const out = process.argv[2] ?? 'shots';
mkdirSync(out, { recursive: true });
const server = spawn('npx', ['vite', 'preview', '--port', '4179', '--strictPort'], { shell: true, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 3500));
const browser = await chromium.launch({ channel: 'msedge' });
try {
  for (const [name, w, h, theme] of [['phone', 800, 360, 'light'], ['phone_dark', 740, 340, 'dark'], ['tablet', 1280, 800, 'light']]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    page.on('pageerror', (e) => { throw new Error('pageerror ' + e.message); });
    await page.addInitScript((t) => localStorage.setItem('sumpath.theme', t), theme);
    await page.goto('http://localhost:4179/');
    await page.click('text=예제');
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${out}/${name}_tool.png` });
    await page.click('.tool-btn:has-text("Viewer")');
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${out}/${name}_viewer.png` });
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth || document.documentElement.scrollHeight > innerHeight);
    console.log(name, w + 'x' + h, '페이지 넘침:', overflow);
  }
} finally {
  await browser.close();
  server.kill();
}
