import { cpSync, mkdtempSync, readFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
// @ts-expect-error — .mjs 도구 스크립트(타입 선언 없음)
import * as bump from '../tools/bump_version.mjs';

describe('bump_version', () => {
  it('각 자리 0~9 자리올림', () => {
    expect(bump.nextVersion('1.0.0')).toBe('1.0.1');
    expect(bump.nextVersion('1.0.9')).toBe('1.1.0');
    expect(bump.nextVersion('1.9.9')).toBe('2.0.0');
    expect(bump.nextVersion('1.0.3', 'minor')).toBe('1.1.0');
    expect(bump.nextVersion('1.9.3', 'minor')).toBe('2.0.0');
  });
  it('versionCode = M×100 + m×10 + p', () => {
    expect(bump.versionCode('1.2.3')).toBe(123);
  });
  it('규칙에 맞지 않는 버전은 거부한다', () => {
    expect(bump.isValidVersion('1.10.0')).toBe(false);
    expect(bump.isValidVersion('1.2')).toBe(false);
    expect(bump.isValidVersion('1.2.3')).toBe(true);
  });
  it('세 파일을 한 번에 바꾼다 (임시 복사본에서)', () => {
    const root = mkdtempSync(join(tmpdir(), 'bump-'));
    const src = new URL('..', import.meta.url);
    for (const f of ['package.json', 'src/version.ts', 'android/app/build.gradle']) {
      cpSync(new URL(f, src), join(root, f), { recursive: true });
    }
    const before = bump.currentVersions(root)['package.json'];
    const next = bump.nextVersion(before);
    bump.applyVersion(next, root);
    const after = bump.currentVersions(root);
    expect(after['package.json']).toBe(next);
    expect(after['src/version.ts']).toBe(next);
    expect(after['android/app/build.gradle']).toBe(next);
    expect(after.versionCode).toBe(bump.versionCode(next));
    // 원본 파일은 그대로
    expect(JSON.parse(readFileSync(new URL('package.json', src), 'utf8')).version).toBe(before);
  });
});
