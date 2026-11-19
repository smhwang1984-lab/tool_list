// v2.3.7 (원본 test_v237_probe_remark): REMARK 의 M300/M200 표기와 H번호 일치 검사
import { describe, expect, it } from 'vitest';
import { N_RE } from '../src/core/patterns';
import { RADIUS_COMP_DISPLAY_RE, RADIUS_COMP_MISMATCH_RE, formatRemark, radiusCompByN } from '../src/core/radiusComp';

const TEXT = `N1 (#1: Tool Change)
M6 T3
G43 H3 Z100
M300H3
N2 (#2: Tool Change)
M6 T2
M300H5
M200
G41 D1
`;

describe('M300/M200 REMARK', () => {
  it('H 일치·불일치·H 없음', () => {
    const r = radiusCompByN(TEXT.split('\n'), N_RE);
    expect(r['N1']).toBe('(M300H3)');
    expect(r['N2']).toBe('(G41)(M300H5≠H2)(M200)');
    expect(RADIUS_COMP_MISMATCH_RE.test(r['N2']!)).toBe(true);
    expect(RADIUS_COMP_MISMATCH_RE.test(r['N1']!)).toBe(false);
  });
});

describe('v2.5.9 REMARK 한 줄 표기', () => {
  it('모두 쓰면 "M300 N1", 안 쓰는 N 이 섞이면 "N1, M300H1:N2"', () => {
    const comp = { N3: '(G41)(M300H3)(M200)', N7: '(M300H3)', N5: '(M300H6≠H5)', N9: '', N1: '', N2: '(M300H1)' };
    expect(formatRemark(['N2', 'N4'], { N2: '(M300)', N4: '(M300)' })).toBe('M300 N2, N4');
    expect(formatRemark(['N1', 'N2', 'N4'], { N2: '(M300)', N4: '(M300)' })).toBe('N1, M300:N2, N4');
    expect(formatRemark(['N1', 'N2'], comp)).toBe('N1, M300H1:N2');
    expect(formatRemark(['N3', 'N7'], comp)).toBe('M300H3:N3(G41), N7 · M200:N3(G41)');
    expect(formatRemark(['N5'], comp)).toBe('M300H6≠H5 N5');
    expect(formatRemark(['N9'], comp)).toBe('N9');
    expect(formatRemark(['N1', 'N3'], { N1: '', N3: '(M300H1)(M200)' })).toBe('N1, M300H1·M200:N3');
    expect(formatRemark(['N1', 'N2', 'N3'], { N2: '(M300)', N3: '(M200)' })).toBe('N1, M300:N2 · M200:N3');
    const hits = [...'N4, M300H6≠H5:N5'.matchAll(new RegExp(RADIUS_COMP_DISPLAY_RE.source, 'gu'))].map((m) => m[0]);
    expect(hits).toEqual(['M300H6≠H5']);
    expect(RADIUS_COMP_MISMATCH_RE.test(hits[0]!)).toBe(true);
  });
});

import { fitRemarkLine } from '../src/core/pdfLayout';

describe('v2.5.9 PDF REMARK 겹침 방지', () => {
  it('칸에 들어가면 그대로, 넘치면 글자를 줄인다', () => {
    expect(fitRemarkLine('N1, M300H3:N3', 100, 5)).toEqual({ line: 'N1, M300H3:N3', size: 5 });
    const r = fitRemarkLine('N1, M300H3:N3, N7, N12', 55, 5);
    expect(r.line).toBe('N1, M300H3:N3, N7, N12');
    expect(r.size).toBeLessThan(5);
    expect(r.size).toBeGreaterThanOrEqual(4.2);
  });
  it('많이 넘치면 N 나열을 "N3 외2"로 줄인다', () => {
    const r = fitRemarkLine('N1, M300H3:N3, N7, N12 · M200:N3, N7, N12, N15, N21, N30', 80, 5);
    expect(r.line).toBe('N1, M300H3:N3 외2 · M200:N3 외5');
  });
});
