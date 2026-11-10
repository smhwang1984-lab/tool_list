// 화면 확인용: 빌드된 앱(dist)을 vite preview 로 띄워 Edge 로 캡처한다. 사용: node tools/shot.mjs <출력폴더>
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { mkdirSync } from 'node:fs';

const out = process.argv[2] ?? 'shots';
mkdirSync(out, { recursive: true });
const server = spawn('npx', ['vite', 'preview', '--port', '4179', '--strictPort'], { shell: true, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 3500));
const browser = await chromium.launch({ channel: 'msedge' });
try {
  for (const [name, w, h, theme] of [['phone', 390, 800, 'light'], ['land', 900, 420, 'dark'], ['tablet', 1100, 700, 'light']]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    await page.addInitScript((t) => localStorage.setItem('sumpath.theme', t), theme);
    await page.goto('http://localhost:4179/');
    await page.click('text=예제');
    await page.waitForTimeout(400);
    await page.click('text=다음 공구');
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${out}/${name}.png` });
    console.log(name, await page.locator('.search-status').innerText());
  }
} finally {
  await browser.close();
  server.kill();
}
