// 원본 tests/test_v269_d_check.py 와 같은 기대값 — 공구명 D ↔ 주석 DC 불일치, TAP 타입
import { describe, expect, it } from 'vitest';
import { dRowAlert } from '../src/core/alerts';
import { parseProgram } from '../src/core/millParser';
import { deriveType } from '../src/core/nameTypes';

const tool = (n: number, name: string, dc: string): string =>
  `N${n}(#${n}: Tool Change)\n (T${n} // ${name} // T${n} BT40-SK10-90 )\n (LCF 20.0 FL 10.0 GL 100.0 F 2)\n` +
  ` (DC ${dc} RE 0.0 SIG PL )\n (SPINDL 10000.0 FEED 3000.0)\nM6 T${n}\n`;
const rows = (...tools: [string, string][]) => {
  const text = 'O0001\n' + tools.map(([name, dc], i) => tool(i + 1, name, dc)).join('') + 'M30\n';
  const out = parseProgram(text) as Record<string, unknown>[];
  return Object.fromEntries(out.filter((r) => r.NO).map((r) => [String(r.NO), r]));
};

describe('v2.6.9 공구명 D ↔ 주석 DC', () => {
  it('다르면 안내 문구, 숫자로 비교', () => {
    const r = rows(['D10 F.EM [SO 40]', '10.000000'], ['D6 B.EM [SO 30]', '8.000000'], ['D2.3 DRILL [SO 20]', '2.300000']);
    expect(r.T01!.D_ALERT).toBe('');
    expect(r.T02!.D_ALERT).toBe('공구명 D6 / 주석 DC 8');
    expect(r.T03!.D_ALERT).toBe('');
  });
  it('공구명에 D가 없거나 주석에 DC가 없으면 경고 없음', () => {
    const r = rows(['M10 TAP [SO 35]', '10.000000'], ['D8 DRILL [SO 20]', '']);
    expect(r.T01!.D_ALERT).toBe('');
    expect(r.T02!.D_ALERT).toBe('');
  });
  it('[수정]으로 D_ALERT가 지워지면 공구명 D와 표 D를 다시 비교', () => {
    expect(dRowAlert({ NAME: 'D6 B.EM', D: '8' })).toBe('공구명 D6 / 표 D8');
    expect(dRowAlert({ NAME: 'D6 B.EM', D: '6.0' })).toBe('');
  });
  it('TAP은 TYPE이 TAP', () => {
    expect(deriveType('M10 TAP [SO 35]')).toBe('TAP');
  });
});
