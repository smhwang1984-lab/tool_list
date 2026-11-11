import { beforeAll, describe, expect, it } from 'vitest';
import { setSimWasmDisabled, initSimWasm, simWasmReady } from '../src/sim/wasm/kernel';
import { VoxelStock } from '../src/sim/voxel';
import { ZMapStock, type SimSegments } from '../src/sim/zmap';
import { toolShapeFromValues } from '../src/sim/toolShape';

function segs(n: number, tilt: boolean): { seg: SimSegments; a0: Float64Array; a1: Float64Array } {
  let seed = 11; const rnd = (): number => (seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648;
  const seg: SimSegments = { count: n, p0: new Float64Array(n * 3), p1: new Float64Array(n * 3), seq1: new Int32Array(n), src: new Int32Array(n), rapid: new Uint8Array(n), slot: new Int32Array(n), color: new Int16Array(n) };
  const a0 = new Float64Array(n * 3), a1 = new Float64Array(n * 3);
  for (let m = 0; m < n; m++) {
    const x = -20 + rnd() * 40, y = -20 + rnd() * 40, z = -rnd() * 8;
    seg.p0.set([x, y, z], m * 3);
    seg.p1.set([x + (rnd() - 0.5) * 10, y + (rnd() - 0.5) * 10, z - rnd() * 3], m * 3);
    seg.color[m] = m % 5;
    const u = tilt ? [0.3 * rnd(), 0.2, 1] : [0, 0, 1];
    const nn = Math.hypot(u[0]!, u[1]!, u[2]!);
    a0.set([u[0]! / nn, u[1]! / nn, u[2]! / nn], m * 3);
    a1.set([u[0]! / nn, u[1]! / nn, u[2]! / nn], m * 3);
  }
  return { seg, a0, a1 };
}
const tool = toolShapeFromValues({ type: 'BALL E/M', D: 6, FL: null, R: null, SIG: null, PL: null, SO: 20 })!;

describe('WASM 절삭 핵심 루프 = JS 와 같은 결과', () => {
  beforeAll(async () => { await initSimWasm(); });

  it('컴파일된다', () => { expect(simWasmReady()).toBe(true); });

  it('3D 복셀', () => {
    const run = (off: boolean): { occ: Uint8Array; col: Uint8Array; wasm: boolean } => {
      setSimWasmDisabled(off);
      const st = new VoxelStock({ X: [-25, 25], Y: [-25, 25], Z: [-12, 0] }, 0.5);
      const { seg, a0, a1 } = segs(120, true);
      st.cutRange(seg, [tool], a0, a1, 0, 120);
      return { occ: st.occ.slice(), col: st.col.slice(), wasm: !!st.kernel };
    };
    const w = run(false), j = run(true);
    setSimWasmDisabled(false);
    expect(w.wasm).toBe(true);
    expect(j.wasm).toBe(false);
    expect(Array.from(w.occ)).toEqual(Array.from(j.occ));
    expect(Array.from(w.col)).toEqual(Array.from(j.col));
  });

  it('Z-map', () => {
    const run = (off: boolean): { h: Float32Array; c: Int16Array; wasm: boolean } => {
      setSimWasmDisabled(off);
      const st = new ZMapStock({ X: [-25, 25], Y: [-25, 25], Z: [-12, 0] }, 0.2);
      const { seg } = segs(200, false);
      st.cutRange(seg, [tool], 0, 200);
      return { h: st.heights.slice(), c: st.colorIds.slice(), wasm: !!st.kernel };
    };
    const w = run(false), j = run(true);
    setSimWasmDisabled(false);
    expect(w.wasm).toBe(true);
    expect(Array.from(w.h)).toEqual(Array.from(j.h));
    expect(Array.from(w.c)).toEqual(Array.from(j.c));
  });
});
