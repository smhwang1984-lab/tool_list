// v2.1.0(안드로이드 전용) — 재생 정보 판 접기 · 프로그램 창 접기 · 회전 중 한 줄
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { icon } from '../src/icons';

const src = (p: string): string => readFileSync(new URL(p, import.meta.url), 'utf8');

describe('v2.1.0 접기 탭', () => {
  it('접기 탭 아이콘(chevron_left / right)이 서로 다른 선으로 그려진다', () => {
    const l = icon('chevron_left'), r = icon('chevron_right');
    expect(l).toContain('<polyline');
    expect(r).toContain('<polyline');
    expect(l).not.toBe(r);
  });
  it('회전 중 문구는 재생 정보 판(v-hud) 안의 한 줄(v-rot)이다 — 별도 v-hud 상자가 아니다', () => {
    const v = src('../src/viewer/viewer.ts');
    expect(v).toContain("el('div', { class: 'v-rot' })");
    expect(v).toMatch(/hud\.append\(rotInfo, coordRow/);
    expect(v).not.toMatch(/rotInfo = el\('div', \{ class: 'v-hud' \}\)/);
    expect(v).toContain('`회전 중 ${parts.join');
  });
  it('접으면 좌표 · 회전 중 줄만 남는다', () => {
    const css = src('../src/styles.css');
    expect(css).toMatch(/\.v-hud\.collapsed > :not\(\.v-coordrow\):not\(\.v-rot\) \{ display: none; \}/);
    expect(css).toMatch(/\.program-pane\.collapsed \{ display: none; \}/);
  });
});
