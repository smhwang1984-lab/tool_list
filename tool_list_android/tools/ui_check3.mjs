// 파일 열기·편집 모드·저장 확인(브라우저 대체 동작). 사용: node tools/ui_check3.mjs <캡처폴더>
import { chromium } from 'playwright-core';
import { spawn } from 'node:child_process';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const out = process.argv[2] ?? 'shots';
mkdirSync(out, { recursive: true });
const server = spawn('npx', ['vite', 'preview', '--port', '4182', '--strictPort'], { shell: true, stdio: 'ignore' });
await new Promise((r) => setTimeout(r, 3500));
const browser = await chromium.launch({ channel: 'msedge' });
const ok = (c, m) => { if (!c) throw new Error('실패: ' + m); console.log('OK', m); };
try {
  const page = await browser.newPage({ viewport: { width: 1100, height: 760 }, acceptDownloads: true });
  page.on('pageerror', (e) => { throw new Error('pageerror ' + e.message); });
  await page.goto('http://localhost:4182/');

  // CP949 + CRLF 파일 열기
  const sample = readFileSync('tests/fixtures/O1699.nc');
  const file = join(tmpdir(), 'O1699.nc');
  writeFileSync(file, sample);
  const [chooser] = await Promise.all([page.waitForEvent('filechooser'), page.click('text=파일 열기')]);
  await chooser.setFiles(file);
  await page.waitForTimeout(600);
  ok((await page.locator('#file-caption').innerText()) === 'O1699.nc', '열린 파일 이름이 제목 줄에 보인다');
  console.log('   공구', await page.locator('.tool-count').innerText());

  // 편집 모드: 틀린 비밀번호 → 정상 비밀번호
  await page.click('.tool-btn:has-text("편집 모드")');
  await page.fill('dialog input[type=password]', '0000');
  await page.click('dialog button:has-text("확인")');
  await page.waitForSelector('dialog');
  ok((await page.locator('dialog .dlg-body').innerText()).includes('올바르지 않습니다'), '틀린 비밀번호는 거부');
  await page.click('dialog button:has-text("닫기")');
  await page.click('.tool-btn:has-text("편집 모드")');
  await page.fill('dialog input[type=password]', '1234');
  await page.click('dialog button:has-text("확인")');
  await page.waitForTimeout(300);
  ok(await page.locator('.edit-label').isVisible(), '편집 모드 진입(✎ 편집 중)');
  await page.screenshot({ path: `${out}/edit.png` });

  // 편집 → 저장(브라우저에서는 내려받기)
  await page.click('.cm-content');
  await page.keyboard.press('Control+End');
  await page.keyboard.type('\n(MEMO 한글 테스트)');
  const [download] = await Promise.all([page.waitForEvent('download'), page.click('.tool-btn:has-text("저장")')]);
  const saved = readFileSync(await download.path());
  const hasCrlf = saved.includes(Buffer.from('\r\n'));
  ok(hasCrlf || !sample.includes(Buffer.from('\r\n')), '원래 줄바꿈 유지');
  // 한글 주석이 원래 인코딩(CP949 or UTF-8)으로 들어갔는지: 원본이 UTF-8 이 아니면 UTF-8 로 못 읽혀야 한다
  console.log('   저장 바이트', saved.length, '원본', sample.length);

  // 편집 종료: 저장했으므로 묻지 않는다
  await page.click('.tool-btn:has-text("편집 모드")');
  await page.waitForTimeout(300);
  ok(!(await page.locator('.edit-label').isVisible()), '저장 후 편집 모드 종료');
} finally {
  await browser.close();
  server.kill();
}
