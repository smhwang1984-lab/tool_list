import { describe, expect, it } from 'vitest';
import { findProcessMarker, pickRelativeMarker } from '../src/core/processMarker';

const PROG = ['O0001', 'N1 (T01 FACE MILL)', '(ROUGH FACE)', 'T1 M6', 'G0 X0. Y0.', 'G1 Z-1. F300', 'G0 Z50.', 'M5', 'G91 G28 Z0.', 'M01',
  'N2 (T05 D10 ENDMILL)', '(SIDE ROUGH) (EXTRA)', 'G91 G28 Z0.', 'T5 M6', 'G0 X5. Y5.'];

describe('processMarker (원본 v2.6.6과 같은 결과)', () => {
  it('앞 공정 마지막 이동 줄 뒤의 첫 N 줄', () => {
    expect(findProcessMarker(PROG, 13, 3)).toEqual({ seq: 10, comments: ['T05 D10 ENDMILL', 'SIDE ROUGH'] });
    expect(findProcessMarker(PROG, 3, -1)).toEqual({ seq: 1, comments: ['T01 FACE MILL', 'ROUGH FACE'] });
  });
  it('N 줄이 없으면 공구 교체 줄', () => {
    expect(findProcessMarker(['G0 X1. Y1.', 'G0 Z50.', 'T7 M6 (DRILL)', 'G0 X2.'], 2, -1)).toEqual({ seq: 2, comments: ['DRILL'] });
  });
  it('교체 줄에 N이 같이 있으면 그 줄', () => {
    expect(findProcessMarker(['G1 X1. Y1. F100', 'N20 T3 M6 (TAP)', 'G0 X2.'], 1, -1)).toEqual({ seq: 1, comments: ['TAP'] });
  });
  it('이전/다음 목표', () => {
    const m = [1, 10, 30];
    expect(pickRelativeMarker(m, 1, 1)).toBe(10);
    expect(pickRelativeMarker(m, 12, 1)).toBe(30);
    expect(pickRelativeMarker(m, 40, 1)).toBe(30);
    expect(pickRelativeMarker(m, 12, -1)).toBe(10);
    expect(pickRelativeMarker(m, 10, -1)).toBe(1);
    expect(pickRelativeMarker(m, 1, -1)).toBe(1);
  });
});
