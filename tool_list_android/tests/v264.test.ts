// 원본 tests/test_v264_modal_info.py 와 같은 기대값 — 재생 바 [모달 정보]
import { describe, expect, it } from 'vitest';
import { feedUnit, ModalTimeline, normalizeCode, summaryText } from '../src/core/modal';

const MILL = `%
O1000
N1 (FACE)
T2 M6
G0 G90 G54 X-20. Y0. S10000 M3
G43.4 Z50. H2 M8
G68.2 X0 Y0 Z0 I0 J-90 K0
G53.1
G1 Z-1. F3600
X20.
G69
M1
N2
T3 M6
G0 G90 G54 X0. Y0. S3800 M3
G43 Z50. H3 M8
G83 G98 Z-12. R2. Q2. F152
X15.
G80
M30
%`;

const timeline = (text: string, lathe = false): ModalTimeline =>
  new ModalTimeline(text.split('\n').map((l, i) => [i, l] as const), lathe);

describe('v2.6.4 모달 정보', () => {
  it('그룹별 마지막 지령', () => {
    const { state, changed } = timeline(MILL).at(8);
    expect(state.S).toBe('10000');
    expect(state.F).toBe('3600');
    expect(state.m).toMatchObject({ spindle: 'M03', coolant: 'M08' });
    expect(state.groups).toMatchObject({ '01': 'G01', '03': 'G90', '14': 'G54', '08': 'G43.4 H02', '16': 'G68.2' });
    expect([...changed].sort()).toEqual(['01', 'F']);
    expect(summaryText(state, false)).toBe('S10000 M03 · F3600 · G01 G68.2');
    expect(feedUnit(state, false)).toBe('mm/min');
  });
  it('바뀌지 않은 줄', () => {
    const { state, changed } = timeline(MILL).at(9);
    expect(state.groups['01']).toBe('G01');
    expect(changed.size).toBe(0);
  });
  it('사이클 · 해제 · 정지', () => {
    const tl = timeline(MILL);
    let { state } = tl.at(16);
    expect(state.groups).toMatchObject({ '09': 'G83', '10': 'G98', '16': 'G69', '08': 'G43 H03' });
    expect(state.m.stop).toBe('M01');
    expect(summaryText(state, false)).toBe('S3800 M03 · F152 · G00 G83');
    ({ state } = tl.at(18));
    expect(summaryText(state, false)).toBe('S3800 M03 · F152 · G00');
  });
  it('지령 전', () => {
    const { state } = timeline(MILL).at(0);
    expect(state.S).toBeNull();
    expect(summaryText(state, false)).toBe('지령 전');
  });
  it('주석 · M98 무시', () => {
    const { state } = timeline('G0 (G1 S500 M8) X1.\nM98 P1000\nG1 X2. F100 ; M9').at(2);
    expect(state.groups['01']).toBe('G01');
    expect(state.S).toBeNull();
    expect(state.m.coolant).toBeUndefined();
    expect(state.m.other).toBeUndefined();
  });
  it('선반 G50 S는 최고 회전수, G99 회전당 이송', () => {
    const { state } = timeline('G50 S3000\nG96 S180 M3\nG99 G1 X10. F0.15', true).at(2);
    expect(state.S).toBe('180');
    expect(state.F).toBe('0.15');
    expect(feedUnit(state, true)).toBe('mm/rev');
  });
  it('선반 G71은 한 줄짜리, / 블록 스킵 줄도 읽는다', () => {
    const tl = timeline(['G0 X50. Z2.', 'G71 U1. R0.5', 'G83 Z-10. F0.1', '/M8'].join('\n'), true);
    expect(tl.at(1).state.groups['10']).toBeUndefined();
    expect(tl.at(2).state.groups['10']).toBe('G83');
    expect(tl.at(3).state.m.coolant).toBe('M08');
  });
  it('코드 정리', () => {
    expect(normalizeCode('G', '1')).toBe('G01');
    expect(normalizeCode('G', '43.4')).toBe('G43.4');
    expect(normalizeCode('G', '68.20')).toBe('G68.2');
    expect(normalizeCode('M', '3')).toBe('M03');
  });
});
