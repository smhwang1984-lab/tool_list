// v2.3.7 (원본 test_v237_probe_remark): REMARK 의 M300/M200 표기와 H번호 일치 검사
import { describe, expect, it } from 'vitest';
import { N_RE } from '../src/core/patterns';
import { RADIUS_COMP_MISMATCH_RE, radiusCompByN } from '../src/core/radiusComp';

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
