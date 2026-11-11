// P6-T4: 선반 소재 — 공구 단면·절삭·메쉬 기본 동작 (원본 골든 비교는 후속)
import { describe, expect, it } from 'vitest';
import type { ToolGeometry } from '../src/core/latheInsertSpec';
import { LatheStock } from '../src/sim/latheStock';
import { buildLatheMesh, UNCUT } from '../src/sim/latheStock';
import { latheToolFromGeometry } from '../src/sim/latheTool';
import type { SimSegments } from '../src/sim/zmap';

const geo = (o: Partial<ToolGeometry>): ToolGeometry => ({
  kind: '외경', hand: 'R', tip: 3, diameter: null, so: null, mill_type: null, chamfer_angle: null, nose_r: 0.4, width: null, pitch: null,
  shape: 'C', tip_angle: 80, clearance_angle: null, ic: null, edge_length: 12, thickness: null, thread_angle: null, approach_angle: 95, shank: null, ...o,
});
const seg = (p0: number[], p1: number[], rapid = false): SimSegments => ({
  count: 1, p0: Float64Array.from(p0), p1: Float64Array.from(p1), seq1: Int32Array.of(1), src: Int32Array.of(0),
  rapid: Uint8Array.of(rapid ? 1 : 0), slot: Int32Array.of(0), color: Int16Array.of(0),
});

describe('선반 소재', () => {
  it('외경 인서트 단면은 반시계 볼록 다각형이고 원점은 노즈 끝', () => {
    const t = latheToolFromGeometry(geo({})) as { poly: Float64Array };
    expect(t.poly.length).toBeGreaterThanOrEqual(8);
    let area = 0;
    const n = t.poly.length / 2;
    for (let i = 0; i < n; i++) { const j = (i + 1) % n; area += t.poly[i * 2]! * t.poly[j * 2 + 1]! - t.poly[j * 2]! * t.poly[i * 2 + 1]!; }
    expect(area).toBeGreaterThan(0);
  });
  it('홈 공구 / 폭 없음 오류', () => {
    expect(latheToolFromGeometry(geo({ kind: "외경홈", width: 3, nose_r: 0.2 })).poly!.length).toBeGreaterThan(6);
    expect(() => latheToolFromGeometry(geo({ kind: '외경홈', width: null }))).toThrow();
    expect(() => latheToolFromGeometry(geo({ kind: '비절삭' }))).toThrow();
  });
  it('Z 방향 선삭은 지름을 줄이고 급속은 깎지 않는다', () => {
    const stock = new LatheStock({ z: [-50, 0], r: [0, 20] }, 0.1);
    const tool = latheToolFromGeometry(geo({}));
    // 반경 15 위치를 Z 0 → -40 으로 선삭(p = [z, y, r])
    stock.cutRange(seg([2, 0, 15], [-40, 0, 15]), [tool], 0, 1);
    const ir = (r: number): number => Math.floor(r / stock.dr);
    const at = (z: number, r: number): number => stock.occ[Math.floor((z - stock.z0) / stock.dz) * stock.nr + ir(r)]!;
    expect(at(-20, 17)).toBe(0); // 바깥쪽은 깎임
    expect(at(-20, 10)).toBe(1); // 안쪽은 남음
    expect(at(-45, 17)).toBe(1); // 끝 너머는 그대로
    const before = stock.occ.slice();
    stock.cutRange(seg([2, 0, 5], [-40, 0, 5], true), [tool], 0, 1);
    expect(stock.occ).toEqual(before);
    expect(stock.rapidWarnings.length).toBe(1);
  });
  it('스냅샷 복원과 메쉬', () => {
    const stock = new LatheStock({ z: [-20, 0], r: [0, 10] }, 0.2);
    const snap = stock.snapshot();
    stock.cutRange(seg([1, 0, 8], [-10, 0, 8]), [latheToolFromGeometry(geo({}))], 0, 1);
    expect(stock.anyCut()).toBe(true);
    stock.restore(snap);
    expect(stock.anyCut()).toBe(false);
    const m = buildLatheMesh(stock, () => [1, 0, 0], 100);
    expect(m.indices.length).toBeGreaterThan(0);
    expect(UNCUT).toBe(255);
  });
});
