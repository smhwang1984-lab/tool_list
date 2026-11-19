import { describe, expect, it } from 'vitest';
import { entryAxes } from '../src/sim/latheEntry';
import { TurnMillStock } from '../src/sim/turnMillStock';
import type { LatheProgram } from '../src/sim/latheSegments';
import { toolShapeFromValues } from '../src/sim/toolShape';

describe('턴밀 소재', () => {
  it('진입 벡터의 반대 방향이 공구 축, G19 은 C 각도의 기계 +X', () => {
    const r = entryAxes({
      p0: [[0, 0, 10]], p1: [[-5, 0, 10]], rapid: [false], breaks: [true], planes: ['G17'], cAngles: [0], cStart: [0], cEnd: [0],
    });
    expect(r.axes0[0]![0]).toBeCloseTo(1, 9);
    const g = entryAxes({
      p0: [[0, 0, 20]], p1: [[0, 0, 10]], rapid: [false], breaks: [true], planes: ['G19'], cAngles: [90], cStart: [90], cEnd: [90],
    });
    expect(g.axes0[0]![1]).toBeCloseTo(1, 6);
  });
  it('앞면 드릴(턴밀)은 중심에서 벗어난 위치만 깎고 선삭 격자는 그대로', () => {
    const st = new TurnMillStock({ z: [-20, 0], r: [0, 15] }, 0.25, 0.5);
    const shape = toolShapeFromValues({ type: 'FLAT E/M', D: 4, FL: null, R: null, SIG: null, PL: null, SO: 30 })!;
    const seg = {
      count: 1, p0: Float64Array.of(2, 0, 8), p1: Float64Array.of(-10, 0, 8), seq1: Int32Array.of(1), src: Int32Array.of(1),
      rapid: Uint8Array.of(0), slot: Int32Array.of(0), color: Int16Array.of(0),
    };
    const prog = { seg, tools: [null], millTools: [shape], mill: Uint8Array.of(1), threadPitch: new Float64Array(1), threadHeight: new Float64Array(1), axes0: Float64Array.of(1, 0, 0), axes1: Float64Array.of(1, 0, 0) } as unknown as LatheProgram;
    st.cutRange(prog, 0, 1);
    expect(st.milled).toBe(true);
    const v = st.voxel;
    const at = (x: number, y: number, z: number): number => v.occ[(Math.floor((x - v.x0) / v.step[0]) * v.ny + Math.floor((y - v.y0) / v.step[1])) * v.nz + Math.floor((z - v.z0) / v.step[2])]!;
    expect(at(-5, 0, 8)).toBe(0);
    expect(at(-5, 0, 0)).toBe(1);
    expect(at(-5, 0, 14)).toBe(1);
    expect(at(-5, 14, 14)).toBe(0); // 반경 밖 모서리
  });
});
