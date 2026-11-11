import { describe, expect, it } from 'vitest';
import { toolProfile } from '../src/viewer/toolMesh';
import { toolShapeFromValues } from '../src/sim/toolShape';

describe('공구 모양 프로파일', () => {
  it('볼 엔드밀: 팁이 0 이고 둘레가 높다', () => {
    const s = toolShapeFromValues({ type: 'BALL E/M', D: 10, FL: 20, R: null, SIG: null, PL: null, SO: 30 })!;
    const p = toolProfile(s);
    expect(p[0]).toEqual([0, 0]);
    expect(p[8]![1]).toBeGreaterThan(4.5);
    expect(p[p.length - 1]![0]).toBe(0);
    expect(p[p.length - 1]![1]).toBeCloseTo(20, 6);
  });
  it('날 길이가 매우 길어도 지름의 8배까지만', () => {
    const s = toolShapeFromValues({ type: 'FLAT E/M', D: 6, FL: null, R: null, SIG: null, PL: null, SO: 1000 })!;
    expect(toolProfile(s).at(-1)![1]).toBeCloseTo(48, 6);
  });
});
