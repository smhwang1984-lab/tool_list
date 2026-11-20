// 원본 v2.6.0~v2.6.3 따라가기: G68.2 해 선택(A 음수 / B 양수), 지난 경로 블록 수, 문자 검색 '이전'
import { describe, expect, it } from 'vitest';
import { aAxisPrefersNegative, toolpathFromText } from '../src/core/toolpath';
import { MACHINE_5AXIS_AC, MACHINE_5AXIS_BC } from '../src/core/machines';
import { clampTrailBlocks } from '../src/core/viewerSettings';
import { findPrevLiteralSpan } from '../src/core/search';

const g682 = (head: string): string =>
  ['M6 T6', head, 'G53.1', 'G43 Z50. H6', 'G00 X-20. Y0.', 'G01 Z-5. F500', 'G01 X20.', 'G69', 'M30'].join('\n');
const rotAt = (text: string, machine: string, line: number): unknown => {
  const r = toolpathFromText(text, machine);
  const keys = [...r.seq_to_table_rot!.keys()].sort((a, b) => a - b);
  const seq = r.line_to_seq.get(line)!;
  const k = keys.filter((x) => x <= seq).pop()!;
  return r.seq_to_table_rot!.get(k);
};

describe('G68.2 테이블 회전 해 선택 (원본 v2.6.1 / v2.6.2)', () => {
  it('A→C: I0 J-90 K0 = A-90 C0, I180 J-90 K0 = A-90 C180', () => {
    const a = rotAt(g682('G68.2 X0. Y0. Z0. I0. J-90. K0.'), MACHINE_5AXIS_AC, 6) as number[];
    expect(a[0]).toBe('ac');
    expect(a[1]).toBeCloseTo(-90, 4);
    expect(Math.abs(((a[3]! % 360) + 360) % 360)).toBeCloseTo(0, 4);
    const b = rotAt(g682('G68.2 X0. Y0. Z0. I180. J-90. K0.'), MACHINE_5AXIS_AC, 6) as number[];
    expect(b[1]).toBeCloseTo(-90, 4);
    expect(Math.abs(b[3]!)).toBeCloseTo(180, 4);
  });
  it('B→C: G68.2 P1 I0 J90 K-90 = B90 C-90', () => {
    const r = rotAt(g682('G68.2 P1 X0 Y0 Z0 I0 J90. K-90.'), MACHINE_5AXIS_BC, 6) as number[];
    expect(r[0]).toBe('bc');
    expect(r[2]).toBeCloseTo(90, 4);
    expect(r[3]).toBeCloseTo(-90, 4);
  });
  it('A축 범위로 음수 해를 고른다', () => {
    expect(aAxisPrefersNegative(undefined)).toBe(true);
    expect(aAxisPrefersNegative({ 'A축 범위': '-120~+30' })).toBe(true);
    expect(aAxisPrefersNegative({ 'A축 범위': '-30~+120' })).toBe(false);
  });
});

describe('지난 경로 블록 수 (원본 clamp_trail_blocks)', () => {
  it('100~500, 50 단위', () => {
    expect(clampTrailBlocks('abc')).toBe(200);
    expect(clampTrailBlocks(20)).toBe(100);
    expect(clampTrailBlocks(999)).toBe(500);
    expect(clampTrailBlocks(260)).toBe(250);
    expect(clampTrailBlocks(280)).toBe(300);
  });
});

describe("문자 검색 '이전' (원본 find_prev_literal_span)", () => {
  it('앞쪽 마지막 일치, 없으면 끝에서부터', () => {
    const text = 'G0 X1\nM6 T1\nG0 X2\nM6 T2\n';
    const at = text.lastIndexOf('M6');
    expect(findPrevLiteralSpan(text, 'm6', at)?.slice(0, 2)).toEqual([text.indexOf('M6'), text.indexOf('M6') + 2]);
    const wrapped = findPrevLiteralSpan(text, 'M6', 0);
    expect(wrapped?.[0]).toBe(at);
    expect(wrapped?.[2]).toBe(true);
  });
});
