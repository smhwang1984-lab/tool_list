// G1: GPU 절삭 셰이더의 CPU 기준 구현(zmapGpuRef.ts) 시험 — 원본 tests/test_nc_sim_gpu_ref.py 와 같은 약속.
// 셰이더 상수가 기준 구현과 같고, 연속 선분 훑기가 촘촘한 표본 탐색과 같고, 수평·수직 이동은 지금 CPU 엔진
// (zmap.ts ZMapStock)과 칸마다 1e-3mm 안에서 같다. 경사 이동은 CPU가 조각 크기(격자 간격 x SUB_Z)만큼 더 깊게 깎는다.
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import type { Bounds } from '../src/sim/stock';
import {
  PROFILE_CHAMFER, PROFILE_CONE, PROFILE_CORNER, PROFILE_FLAT, toolShapeFromValues, ToolShape,
  type ToolValues,
} from '../src/sim/toolShape';
import { SUB_Z, ZMapStock, type SimSegments } from '../src/sim/zmap';
import {
  GOLD_ITER, INV_PHI, R2_EPS, R2_REL_EPS, VERTICAL_LEN2, ZMapGpuRef, profileH, sweepMinHeight, type SweepOut,
} from '../src/sim/zmapGpuRef';

const ROOT = join(__dirname, '..', '..');
const BOUNDS: Bounds = { X: [-20, 20], Y: [-12, 12], Z: [-10, 0] };
const RES = 0.2;
const TOL = 1e-3;
type Pt = [number, number, number];
type Path = [Pt, Pt][];

const KINDS = ['flat', 'ball', 'fillet', 'drill', 'chamfer'] as const;
type Kind = (typeof KINDS)[number];
const val = (type: string, D: number, extra: Partial<ToolValues> = {}): ToolValues =>
  ({ type, D, FL: null, R: null, SIG: null, PL: null, SO: null, ...extra });
function makeTool(kind: Kind): ToolShape {
  const v = {
    flat: val('FLAT E/M', 6), ball: val('BALL E/M', 6), fillet: val('FILLET E/M', 8, { R: 1 }),
    drill: val('DRILL', 6, { SIG: 118 }), chamfer: val('CHAMFER', 8, { PL: 1.5 }),
  }[kind];
  return toolShapeFromValues(v)!;
}

const LEVEL: Record<string, Path> = {
  horizontal: [[[-12, -3, -4], [12, -3, -4]], [[12, 3, -4], [-12, 3, -4]]],
  vertical: [[[0, 0, 0], [0, 0, -6]], [[0, 0, -6], [0, 0, 0]]],
  zigzag: Array.from({ length: 6 }, (_, k) => [[-12, -6 + 2 * k, -3 - 0.5 * (k % 2)], [12, -6 + 2 * k, -3 - 0.5 * (k % 2)]] as [Pt, Pt]),
};
const RAMP: Record<string, Path> = {
  gentle: [[[-12, 0, -1], [12, 0, -3]]],
  steep: [[[-10, 0, -0.5], [10, 0, -7]]],
  diagonal: [[[-12, -8, -1], [12, 8, -6]]],
};

function segments(path: Path, colors: number[] = [], rapid: boolean[] = []): SimSegments {
  const n = path.length;
  const seg: SimSegments = {
    count: n, p0: new Float64Array(n * 3), p1: new Float64Array(n * 3), seq1: new Int32Array(n).map((_, i) => i + 1),
    src: new Int32Array(n).map((_, i) => 10 + i), rapid: new Uint8Array(n), slot: new Int32Array(n), color: new Int16Array(n),
  };
  path.forEach(([a, b], i) => {
    seg.p0.set(a, i * 3);
    seg.p1.set(b, i * 3);
    seg.color[i] = colors[i] ?? 0;
    seg.rapid[i] = rapid[i] ? 1 : 0;
  });
  return seg;
}

function cutBoth(kind: Kind, path: Path) {
  const tool = makeTool(kind);
  const seg = segments(path);
  const cpu = new ZMapStock(BOUNDS, RES);
  cpu.cutRange(seg, [tool], 0, seg.count);
  const gpu = new ZMapGpuRef(BOUNDS, RES);
  gpu.cutRange(seg, [tool], 0, seg.count);
  const cut = new Uint8Array(cpu.heights.length);
  const diff = new Float64Array(cpu.heights.length);
  for (let i = 0; i < diff.length; i++) {
    diff[i] = gpu.heights[i]! - cpu.heights[i]!;
    cut[i] = gpu.heights[i]! < gpu.ztop - 1e-6 || cpu.heights[i]! < cpu.ztop - 1e-6 ? 1 : 0;
  }
  return { cpu, gpu, diff, cut };
}
const range = (diff: Float64Array, pick: (i: number) => boolean): [number, number, number] => {
  let lo = Infinity, hi = -Infinity, n = 0;
  for (let i = 0; i < diff.length; i++) if (pick(i)) { lo = Math.min(lo, diff[i]!); hi = Math.max(hi, diff[i]!); n++; }
  return [lo, hi, n];
};

describe('셰이더 원본과 기준 구현', () => {
  const frag = readFileSync(join(ROOT, 'sim_shaders', 'cut.frag'), 'utf-8');

  it('셰이더 상수가 기준 구현과 같다', () => {
    expect(Number(/const int GOLD_ITER = (\d+);/.exec(frag)![1])).toBe(GOLD_ITER);
    expect(Number(/const float INV_PHI = ([\d.]+);/.exec(frag)![1])).toBe(INV_PHI);
    expect(Number(/const float R2_EPS = ([\d.e+-]+);/.exec(frag)![1])).toBe(R2_EPS);
    expect(Number(/const float R2_REL_EPS = ([\d.e+-]+);/.exec(frag)![1])).toBe(R2_REL_EPS);
    expect(Number(/const float VERTICAL_LEN2 = ([\d.e+-]+);/.exec(frag)![1])).toBe(VERTICAL_LEN2);
  });

  it('셰이더 파일에는 버전·정밀도 줄이 없다(로더가 붙인다)', () => {
    for (const name of ['cut.vert', 'cut.frag']) {
      for (const line of readFileSync(join(ROOT, 'sim_shaders', name), 'utf-8').split(/\r?\n/)) {
        expect(/^\s*(#version|precision)/.test(line), `${name}: ${line}`).toBe(false);
      }
    }
  });

  it('형상 종류 번호가 셰이더와 같다', () => {
    expect([PROFILE_FLAT, PROFILE_CORNER, PROFILE_CONE, PROFILE_CHAMFER]).toEqual([0, 1, 2, 3]);
    for (const n of [1, 2, 3]) expect(frag).toContain(`kind == ${n}`);
  });
});

describe('공구 형상 매개변수', () => {
  it('profileH 가 CPU 공구 형상과 같다', () => {
    for (const kind of KINDS) {
      const tool = makeTool(kind);
      const p = tool.profileParams()!;
      // radialLut 의 첫 칸들이 profile 값 — 같은 d 에서 비교한다
      const { lut, invStep } = tool.radialLut(0.2);
      for (let k = 0; k < lut.length - 1; k++) expect(profileH(k / invStep, p), `${kind} ${k}`).toBeCloseTo(lut[k]!, 12);
    }
  });

  it('코너 R 0 은 평바닥, 볼은 코너 R = 반지름', () => {
    expect(toolShapeFromValues(val('FILLET E/M', 8, { R: 0 }))!.profileParams()![0]).toBe(PROFILE_FLAT);
    expect(makeTool('ball').profileParams()).toEqual([PROFILE_CORNER, 0, 3, 0]);
  });

  it('형상 함수를 직접 만든 공구는 매개변수가 없고 기준 구현이 거부한다', () => {
    const tool = new ToolShape(3, () => 0, 20);
    expect(tool.profileParams()).toBeNull();
    const stock = new ZMapGpuRef(BOUNDS, RES);
    const seg = segments([[[0, 0, -1], [1, 0, -1]]]);
    expect(() => stock.cutRange(seg, [tool], 0, 1)).toThrow();
  });
});

describe('연속 선분 훑기', () => {
  it('t 를 4만 번 훑은 값과 같다(경사·볼·코너 R 모두)', () => {
    let seed = 7;
    const rnd = (): number => { seed = (seed * 1664525 + 1013904223) >>> 0; return seed / 4294967296; };
    const uni = (a: number, b: number): number => a + (b - a) * rnd();
    const out: SweepOut = { value: 0, dmin: 0 };
    const N = 40000;
    for (const kind of KINDS) {
      const tool = makeTool(kind);
      const p = tool.profileParams()!;
      for (let trial = 0; trial < 4; trial++) {
        const ax = uni(-8, 8), ay = uni(-8, 8), bx = uni(-8, 8), by = uni(-8, 8), az = uni(-6, 0), bz = uni(-6, 0);
        for (let k = 0; k < 25; k++) {
          const u = rnd();
          const cx = ax + (bx - ax) * u + uni(-1.3 * tool.radius, 1.3 * tool.radius);
          const cy = ay + (by - ay) * u + uni(-1.3 * tool.radius, 1.3 * tool.radius);
          const qx = cx - ax, qy = cy - ay;
          sweepMinHeight(qx, qy, bx - ax, by - ay, az, bz - az, tool.radius, p, out);
          let brute = Infinity;
          for (let i = 0; i <= N; i++) {
            const t = i / N;
            const wx = qx - t * (bx - ax), wy = qy - t * (by - ay);
            const d = Math.sqrt(wx * wx + wy * wy);
            if (d * d <= tool.radius * tool.radius * (1 + R2_REL_EPS) + R2_EPS) brute = Math.min(brute, az + (bz - az) * t + profileH(d, p));
          }
          if (!Number.isFinite(brute)) { expect(out.value, `${kind} ${trial} ${k}`).toBe(Infinity); continue; }
          // 꺾이는 형상(챔퍼·원뿔)은 황금분할 24회가 최대 2r*1e-5*기울기(1e-4 미만)만큼 높을 수 있다
          expect(out.value, `${kind} ${trial} ${k}`).toBeLessThanOrEqual(brute + 1e-4);
          expect(brute - out.value, `${kind} ${trial} ${k}`).toBeLessThan(2e-3);
        }
      }
    }
  });

  it('멀리 있는 칸은 닿지 않는다', () => {
    const out: SweepOut = { value: 0, dmin: 0 };
    expect(sweepMinHeight(50, 0, 10, 0, -1, 0, 3, makeTool('flat').profileParams()!, out).value).toBe(Infinity);
  });
});

describe('지금 CPU 엔진과 비교', () => {
  it('수평·수직 이동은 공구 가장자리 칸까지 모든 칸이 1e-3mm 안에서 같다', () => {
    for (const kind of KINDS) {
      for (const [name, path] of Object.entries(LEVEL)) {
        const { diff, cut } = cutBoth(kind, path);
        const [lo, hi, n] = range(diff, (i) => cut[i] === 1);
        expect(n, `${kind} ${name}`).toBeGreaterThan(500);
        expect(Math.max(Math.abs(lo), Math.abs(hi)), `${kind} ${name}`).toBeLessThanOrEqual(TOL);
      }
    }
  });

  it('수평 이동 후 깎인 칸·색 id 가 같다', () => {
    for (const kind of KINDS) {
      const { cpu, gpu } = cutBoth(kind, LEVEL.zigzag!);
      for (let i = 0; i < cpu.colorIds.length; i++) expect(gpu.colorIds[i]! < 0, `${kind} ${i}`).toBe(cpu.colorIds[i]! < 0);
    }
  });

  it('경사 이동은 CPU 조각 크기(격자 간격 x SUB_Z)만큼 같거나 더 깊게 깎는 차이뿐이다', () => {
    const limit = RES * SUB_Z + TOL;
    for (const kind of KINDS) {
      for (const [name, path] of Object.entries(RAMP)) {
        const { gpu, diff, cut } = cutBoth(kind, path);
        const [iLo, iHi] = range(diff, (i) => cut[i] === 1 && gpu.edgeMask[i] === 0);
        expect(iLo, `${kind} ${name} 안쪽`).toBeGreaterThanOrEqual(-TOL);
        expect(iHi, `${kind} ${name} 안쪽`).toBeLessThanOrEqual(limit);
        const [eLo, eHi, eN] = range(diff, (i) => cut[i] === 1 && gpu.edgeMask[i] === 1);
        if (eN > 0) {
          // 공구 가장자리 칸: CPU 반경 표(LUT) 보간 오차가 더해진다(볼·코너 R 끝은 기울기가 커서 수 마이크로미터~)
          expect(eLo, `${kind} ${name} 가장자리`).toBeGreaterThanOrEqual(-0.02);
          expect(eHi, `${kind} ${name} 가장자리`).toBeLessThanOrEqual(limit);
        }
      }
    }
  });

  it('평바닥이 경사를 훑을 때 가장자리가 아닌 칸은 CPU도 정확하다', () => {
    const { gpu, diff, cut } = cutBoth('flat', RAMP.gentle!);
    const [lo, hi, n] = range(diff, (i) => cut[i] === 1 && gpu.edgeMask[i] === 0);
    expect(n).toBeGreaterThan(500);
    expect(Math.max(Math.abs(lo), Math.abs(hi))).toBeLessThanOrEqual(TOL);
  });

  it('칸의 색 id 는 그 칸을 낮춘 선분을 따른다', () => {
    const stock = new ZMapGpuRef(BOUNDS, RES);
    const seg = segments([[[-5, 0, -2], [5, 0, -2]], [[-5, 4, -4], [5, 4, -4]]], [3, 7]);
    stock.cutRange(seg, [makeTool('flat')], 0, 2);
    const at = (x: number, y: number): number => stock.colorIds[Math.round((y - stock.y0) / RES) * stock.nx + Math.round((x - stock.x0) / RES)]!;
    expect(at(0, 0)).toBe(3);
    expect(at(0, 4)).toBe(7);
    expect(at(0, -11)).toBe(-1);
  });

  it('급속 이동이 소재를 깎으면 경고를 남긴다', () => {
    const stock = new ZMapGpuRef(BOUNDS, RES);
    const seg = segments([[[-5, 0, -2], [5, 0, -2]]], [0], [true]);
    stock.cutRange(seg, [makeTool('flat')], 0, 1);
    expect(stock.rapidWarnings).toEqual([{ src: 10, seq: 1 }]);
  });

  it('소재 윗면보다 위의 선분은 깎지 않고, 바닥 아래로는 깎지 않는다', () => {
    const above = new ZMapGpuRef(BOUNDS, RES);
    above.cutRange(segments([[[-5, 0, 1], [5, 0, 2]]]), [makeTool('ball')], 0, 1);
    expect(above.anyCut()).toBe(false);
    const deep = new ZMapGpuRef(BOUNDS, RES);
    deep.cutRange(segments([[[-5, 0, -30], [5, 0, -30]]]), [makeTool('flat')], 0, 1);
    expect(Math.min(...deep.heights)).toBeCloseTo(-10, 6);
  });
});
