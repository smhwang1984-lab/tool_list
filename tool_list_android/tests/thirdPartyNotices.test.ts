// v2.1.1: 오픈소스 라이선스 고지 — 배포용 패키지가 모두 고지문에 들어가는지 확인한다.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
// @ts-expect-error — .mjs 도구 스크립트(타입 선언 없음)
import * as collect from '../tools/collect_licenses.mjs';
import { loadNoticeText, NOTICE_SUMMARY } from '../src/ui/thirdPartyNotices';

const buildNotices = collect.buildNotices as () => { text: string };
const COMPONENTS = collect.COMPONENTS as [string, string, string, string][];

const root = join(__dirname, '..');

describe('third party notices', () => {
  it('lists every production package from package-lock', () => {
    const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
    const { text } = buildNotices();
    for (const [key, v] of Object.entries<{ dev?: boolean; devOptional?: boolean; version: string }>(lock.packages)) {
      if (!key || v.dev || v.devOptional) continue;
      expect(text).toContain(`${key.replace(/^.*node_modules\//, '')} ${v.version}`);
    }
    expect(text).toContain('SIL OPEN FONT LICENSE Version 1.1');
    expect(text).toContain('Apache License');
  });

  it('committed public file is up to date with package-lock', () => {
    const committed = readFileSync(join(root, 'public', 'THIRD_PARTY_NOTICES.txt'), 'utf8').replace(/\r\n?/g, '\n');
    expect(committed).toBe(buildNotices().text);
  });

  it('About summary matches the component list', () => {
    expect(NOTICE_SUMMARY.length).toBe(COMPONENTS.length);
    COMPONENTS.forEach(([, license], i) => expect(NOTICE_SUMMARY[i]).toContain(license));
  });

  it('falls back to the summary when the file cannot be read', async () => {
    const text = await loadNoticeText((async () => { throw new Error('offline'); }) as unknown as typeof fetch);
    expect(text).toContain('three.js — MIT');
  });
});
