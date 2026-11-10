import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { APP_VERSION } from '../src/version';

const VERSION_RE = /^[0-9]\.[0-9]\.[0-9]$/; // 각 자리 0~9 (CLAUDE.md 2절)

describe('버전', () => {
  it('src/version.ts 와 package.json 이 같다', () => {
    const pkg = JSON.parse(readFileSync(new URL('../package.json', import.meta.url), 'utf8'));
    expect(pkg.version).toBe(APP_VERSION);
  });
  it('각 자리가 0~9 이다', () => {
    expect(APP_VERSION).toMatch(VERSION_RE);
  });
  it('android versionName 도 같다', () => {
    const gradle = readFileSync(new URL('../android/app/build.gradle', import.meta.url), 'utf8');
    expect(gradle).toContain(`versionName "${APP_VERSION}"`);
  });
});
