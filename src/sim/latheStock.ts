// 선반 소재 — 원본 nc_lathe_sim.LatheStock (반단면 점유 격자 z × r, 공구 단면 다각형이 쓸고 간 볼록 껍질을 지운다)
import { DEFAULT_STOCK_COLOR } from './mesh';
import { convexHull, type LatheTool } from './latheTool';
import type { SimSegments } from './zmap';

export const UNCUT = 255;
export const LATHE_TARGET_CELLS = 2_000_000;
const LATHE_MIN_RES = 0.02;
const LATHE_MAX_RES = 0.25;
const RAPID_HIT_MIN_AREA = 0.5;
const CAP_COLOR: readonly [number, number, number] = [0.66, 0.74, 0.86];

export interface LatheBounds { z: [number, number]; r: [number, number] }

export function latheAutoResolution(b: LatheBounds, target = LATHE_TARGET_CELLS): number {
  const zl = Math.max(b.z[1] - b.z[0], 1e-6);
  const rl = Math.max(b.r[1], 1e-6);
  const res = Math.sqrt((zl * rl) / Math.max(target, 1));
  return Math.round(Math.min(Math.max(res, LATHE_MIN_RES), LATHE_MAX_RES) * 1e4) / 1e4;
}

/** 소재 사양: 지름·길이·앞면 Z·내경 (앞면에서 -Z 쪽으로 length) */
export class LatheStockSpec {
  readonly diameter: number; readonly length: number; readonly frontZ: number; readonly bore: number;
  constructor(diameter: number, length: number, frontZ = 0, bore = 0) {
    this.diameter = diameter; this.length = length; this.frontZ = frontZ; this.bore = Math.max(0, bore);
  }
  bounds(): LatheBounds { return { z: [this.frontZ - this.length, this.frontZ], r: [this.bore / 2, this.diameter / 2] }; }
}

export interface LatheSnapshot { occ: Uint8Array; col: Uint8Array }

export class LatheStock {
  readonly resolution: number;
  readonly z0: number; readonly zTop: number; readonly rMin: number; readonly rMax: number;
  readonly nz: number; readonly nr: number; readonly dz: number; readonly dr: number;
  occ: Uint8Array;
  col: Uint8Array;
  private readonly occ0: Uint8Array;
  rapidWarnings: { src: number | null; seq: number | null }[] = [];
  readonly isLathe = true;

  constructor(b: LatheBounds, resolution: number) {
    this.resolution = resolution;
    this.z0 = b.z[0]; this.zTop = b.z[1]; this.rMin = b.r[0]; this.rMax = b.r[1];
    this.nz = Math.max(2, Math.round((b.z[1] - b.z[0]) / resolution));
    this.nr = Math.max(2, Math.round(b.r[1] / resolution));
    this.dz = (b.z[1] - b.z[0]) / this.nz;
    this.dr = b.r[1] / this.nr;
    this.occ0 = new Uint8Array(this.nz * this.nr);
    for (let iz = 0; iz < this.nz; iz++) for (let ir = 0; ir < this.nr; ir++) this.occ0[iz * this.nr + ir] = (ir + 0.5) * this.dr >= this.rMin ? 1 : 0;
    this.occ = this.occ0.slice();
    this.col = new Uint8Array(this.nz * this.nr).fill(UNCUT);
  }
  get nx(): number { return this.nz; }
  get ny(): number { return this.nr; }
  cellCount(): number { return this.nz * this.nr; }
  anyCut(): boolean { for (let i = 0; i < this.occ.length; i++) if (this.occ[i] !== this.occ0[i]) return true; return false; }
  reset(): void { this.occ = this.occ0.slice(); this.col.fill(UNCUT); this.rapidWarnings = []; this.threadCutCount = 0; }
  snapshot(): LatheSnapshot { return { occ: this.occ.slice(), col: this.col.slice() }; }
  restore(s: LatheSnapshot): void { this.occ = s.occ.slice(); this.col = s.col.slice(); }

  /** 껍질 안에 중심이 든 칸을 센다(cut 이면 지운다) */
  private fillHull(hull: [number, number][], color: number, cut: boolean, lo: Float64Array, hi: Float64Array): number {
    const { nz, nr, z0, dz, dr } = this;
    if (!hull.length) return 0;
    let zmin = Infinity, zmax = -Infinity;
    for (const p of hull) { zmin = Math.min(zmin, p[0]); zmax = Math.max(zmax, p[0]); }
    const iz0 = Math.max(Math.ceil((zmin - z0) / dz - 0.5), 0);
    const iz1 = Math.min(Math.floor((zmax - z0) / dz - 0.5), nz - 1);
    if (iz1 < iz0) return 0;
    const n = iz1 - iz0 + 1;
    for (let k = 0; k < n; k++) { lo[k] = Infinity; hi[k] = -Infinity; }
    const cnt = hull.length;
    for (let i = 0; i < cnt; i++) {
      const [za, ra] = hull[i]!;
      const [zb, rb] = hull[i + 1 < cnt ? i + 1 : 0]!;
      const zl = Math.min(za, zb), zh = Math.max(za, zb);
      const ka = Math.max(Math.ceil((zl - z0) / dz - 0.5), iz0);
      const kb = Math.min(Math.floor((zh - z0) / dz - 0.5), iz1);
      for (let iz = ka; iz <= kb; iz++) {
        const zc = z0 + (iz + 0.5) * dz;
        const r = za === zb ? undefined : ra + ((zc - za) / (zb - za)) * (rb - ra);
        const k = iz - iz0;
        if (r === undefined) { lo[k] = Math.min(lo[k]!, ra, rb); hi[k] = Math.max(hi[k]!, ra, rb); } else { lo[k] = Math.min(lo[k]!, r); hi[k] = Math.max(hi[k]!, r); }
      }
    }
    let removed = 0;
    for (let k = 0; k < n; k++) {
      if (hi[k]! < lo[k]!) continue;
      const ir0 = Math.max(Math.ceil(lo[k]! / dr - 0.5), 0);
      const ir1 = Math.min(Math.floor(hi[k]! / dr - 0.5), nr - 1);
      const base = (iz0 + k) * nr;
      for (let ir = ir0; ir <= ir1; ir++) {
        if (this.occ[base + ir] === 1) {
          removed++;
          if (cut) { this.occ[base + ir] = 0; this.col[base + ir] = color; }
        }
      }
    }
    return removed;
  }

  private scratchLo = new Float64Array(0);
  private scratchHi = new Float64Array(0);

  threadCutCount = 0;

  /** G76 나사 — z 구간에 피치 간격으로 V홈 고리를 판다(원본 _cut_thread). rEnd = 나사 골(외경)/큰 지름(내경) */
  private cutThread(zA: number, zB: number, rEnd: number, tool: LatheTool, pitch: number, height: number, color: number): void {
    const half = ((tool.threadAngle || 60) * Math.PI) / 360;
    const depth = height > 0 ? height : pitch * 0.6134;
    const flat = pitch / 8;
    const sign = zA >= zB ? 1 : -1;
    const count = Math.floor(Math.abs(zA - zB) / pitch + 1e-9) + 1;
    const tanHalf = Math.tan(half);
    const reach = depth * 2.0;
    const wmax = flat / 2 + reach * tanHalf;
    const rEndA = Math.abs(rEnd);
    const { nz, nr, z0, dz, dr } = this;
    for (let k = 0; k < count; k++) {
      const zk = zB + sign * pitch * k;
      const iz0 = Math.max(Math.ceil((zk - wmax - z0) / dz - 0.5), 0);
      const iz1 = Math.min(Math.floor((zk + wmax - z0) / dz - 0.5), nz - 1);
      for (let iz = iz0; iz <= iz1; iz++) {
        const zc = z0 + (iz + 0.5) * dz;
        const climb = Math.max(Math.abs(zc - zk) - flat / 2, 0) / tanHalf;
        for (let ir = 0; ir < nr; ir++) {
          const row = (ir + 0.5) * dr;
          const inside = tool.internal ? row <= rEndA - climb && row >= rEndA - reach : row >= rEndA + climb && row <= rEndA + reach;
          if (inside && this.occ[iz * nr + ir] === 1) { this.occ[iz * nr + ir] = 0; this.col[iz * nr + ir] = color; }
        }
      }
    }
    this.threadCutCount++;
  }

  cutRange(seg: SimSegments, tools: (LatheTool | null)[], from: number, to: number, thread?: { pitch: Float64Array; height: Float64Array }): void {
    if (this.scratchLo.length < this.nz + 2) { this.scratchLo = new Float64Array(this.nz + 2); this.scratchHi = new Float64Array(this.nz + 2); }
    const minHit = Math.max(1, Math.ceil(RAPID_HIT_MIN_AREA / (this.dz * this.dr)));
    for (let m = from; m < to; m++) {
      const tool = tools[seg.slot[m]!];
      if (!tool || !tool.poly) continue;
      const a0 = m * 3;
      const y0 = seg.p0[a0 + 1]!, y1 = seg.p1[a0 + 1]!;
      const r0 = Math.abs(y0) < 1e-9 ? seg.p0[a0 + 2]! : Math.hypot(y0, seg.p0[a0 + 2]!);
      const r1 = Math.abs(y1) < 1e-9 ? seg.p1[a0 + 2]! : Math.hypot(y1, seg.p1[a0 + 2]!);
      const z0 = seg.p0[a0]!, z1 = seg.p1[a0]!;
      if (thread && thread.pitch[m]! > 0) { this.cutThread(z0, z1, r1, tool, thread.pitch[m]!, thread.height[m]!, Math.min(Math.max(seg.color[m]!, 0), UNCUT - 1)); continue; }
      const pts: [number, number][] = [];
      const poly = tool.poly;
      // 날 길이가 무제한(1000mm)인 드릴 등은 소재 길이 + 20mm 로 잘라 계산량을 줄인다(그 너머는 소재와 만나지 않는다)
      const lim = this.zTop - this.z0 + 20;
      for (let i = 0; i < poly.length; i += 2) { const pz = Math.max(-lim, Math.min(lim, poly[i]!)); pts.push([pz + z0, poly[i + 1]! + r0], [pz + z1, poly[i + 1]! + r1]); }
      const hull = convexHull(pts);
      const rapid = seg.rapid[m] === 1;
      const hit = this.fillHull(hull, Math.min(Math.max(seg.color[m]!, 0), UNCUT - 1), !rapid, this.scratchLo, this.scratchHi);
      if (rapid && hit >= minHit) this.rapidWarnings.push({ src: seg.src[m]! >= 0 ? seg.src[m]! : null, seq: seg.seq1[m]! });
    }
  }
}

// ---------------------------------------------------------------- 표시 메쉬(회전체)
export type SectionMode = '3q' | 'half' | 'full';
const SECTIONS: Record<SectionMode, [number, number, boolean]> = { '3q': [0, 270, true], half: [0, 180, true], full: [0, 360, false] };

interface Coarse { occ: Uint8Array; cid: Uint8Array; nz: number; nr: number; dz: number; dr: number }

function coarsen(s: LatheStock, maxN: number): Coarse {
  const fz = Math.max(1, Math.ceil(s.nz / (2 * maxN)));
  const fr = Math.max(1, Math.ceil(s.nr / maxN));
  if (fz === 1 && fr === 1) return { occ: s.occ, cid: s.col, nz: s.nz, nr: s.nr, dz: s.dz, dr: s.dr };
  const nz = Math.ceil(s.nz / fz), nr = Math.ceil(s.nr / fr);
  const occ = new Uint8Array(nz * nr), cid = new Uint8Array(nz * nr).fill(UNCUT);
  for (let bz = 0; bz < nz; bz++) for (let br = 0; br < nr; br++) {
    let sum = 0, tot = 0, best = -1;
    for (let iz = bz * fz; iz < Math.min(s.nz, (bz + 1) * fz); iz++) for (let ir = br * fr; ir < Math.min(s.nr, (br + 1) * fr); ir++) {
      tot++; sum += s.occ[iz * s.nr + ir]!;
      const c = s.col[iz * s.nr + ir]!; if (c !== UNCUT && c > best) best = c;
    }
    // 원본: 패딩 칸은 빈 칸으로 센다
    const full = fz * fr;
    occ[bz * nr + br] = sum / full >= 0.5 ? 1 : 0;
    cid[bz * nr + br] = best < 0 ? UNCUT : best;
    void tot;
  }
  return { occ, cid, nz, nr, dz: s.dz * fz, dr: s.dr * fr };
}

interface Seg { z1: number; r1: number; z2: number; r2: number; c: number }

function boundarySegments(c: Coarse, z0: number): Seg[] {
  const { occ, cid, nz, nr, dz, dr } = c;
  const out: Seg[] = [];
  const O = (iz: number, ir: number): number => (iz < 0 || iz >= nz ? 0 : occ[iz * nr + ir]!);
  const C = (iz: number, ir: number): number => (iz < 0 || iz >= nz ? UNCUT : cid[iz * nr + ir]!);
  // z 방향 경계
  for (let k = 0; k <= nz; k++) {
    let start = -1, cur = 0;
    const flush = (end: number): void => { if (start >= 0) { out.push({ z1: z0 + k * dz, r1: start * dr, z2: z0 + k * dz, r2: end * dr, c: cur }); start = -1; } };
    for (let ir = 0; ir < nr; ir++) {
      const a = O(k - 1, ir), b = O(k, ir);
      if (a !== b) {
        const col = a ? C(k, ir) : C(k - 1, ir);
        if (start >= 0 && col !== cur) flush(ir);
        if (start < 0) { start = ir; cur = col; }
      } else flush(ir);
    }
    flush(nr);
  }
  // r 방향 경계(축 쪽 k=0 은 표면이 아님)
  for (let k = 1; k <= nr; k++) {
    let start = -1, cur = 0;
    const flush = (end: number): void => { if (start >= 0) { out.push({ z1: z0 + start * dz, r1: k * dr, z2: z0 + end * dz, r2: k * dr, c: cur }); start = -1; } };
    for (let iz = 0; iz < nz; iz++) {
      const a = occ[iz * nr + (k - 1)]!, b = k < nr ? occ[iz * nr + k]! : 0;
      if (a !== b) {
        const col = a ? (k < nr ? cid[iz * nr + k]! : UNCUT) : cid[iz * nr + (k - 1)]!;
        if (start >= 0 && col !== cur) flush(iz);
        if (start < 0) { start = iz; cur = col; }
      } else flush(iz);
    }
    flush(nz);
  }
  return out;
}

function thetaSteps(rMax: number, spanDeg: number): number {
  const r = Math.max(rMax, 1);
  const step = 2 * (Math.acos(Math.max(1 - 0.1 / r, 0.5)) * 180) / Math.PI;
  const perTurn = Math.min(Math.max(Math.ceil(360 / Math.max(step, 1e-3)), 36), 144);
  return Math.max(4, Math.ceil((perTurn * spanDeg) / 360));
}

export interface LatheMesh { positions: Float32Array; colors: Float32Array; indices: Uint32Array; edges: Float32Array }

/** 회전체 메쉬. 월드 점 = (z, r sinθ, r cosθ) */
export function buildLatheMesh(s: LatheStock, colorOf: (id: number) => readonly [number, number, number], maxN = 500, section: SectionMode = '3q'): LatheMesh {
  const c = coarsen(s, maxN);
  const [t0, t1, caps] = SECTIONS[section];
  const segs = boundarySegments(c, s.z0).filter((g) => g.r1 > 0 || g.r2 > 0);
  const nt = thetaSteps(s.rMax, t1 - t0);
  const thetas = Array.from({ length: nt + 1 }, (_, i) => ((t0 + ((t1 - t0) * i) / nt) * Math.PI) / 180);
  const sin = thetas.map(Math.sin), cos = thetas.map(Math.cos);
  // 캡(단면) 사각형
  const quads: number[][] = [];
  if (caps) {
    let start = 0;
    const colKey = (iz: number): string => Array.prototype.join.call(c.occ.subarray(iz * c.nr, (iz + 1) * c.nr), '');
    let prev = colKey(0);
    for (let iz = 1; iz <= c.nz; iz++) {
      const cur = iz < c.nz ? colKey(iz) : null;
      if (cur !== prev) {
        let ir = 0;
        while (ir < c.nr) {
          if (c.occ[start * c.nr + ir]) { let e = ir; while (e < c.nr && c.occ[start * c.nr + e]) e++; quads.push([s.z0 + start * c.dz, s.z0 + iz * c.dz, ir * c.dr, e * c.dr]); ir = e; } else ir++;
        }
        start = iz; prev = cur ?? '';
      }
    }
  }
  const capAngles = [thetas[0]!, thetas[nt]!];
  const nSurfV = segs.length * 2 * (nt + 1);
  const nVert = nSurfV + (caps ? quads.length * 2 * 4 : 0);
  const positions = new Float32Array(nVert * 3), colors = new Float32Array(nVert * 3);
  const indices = new Uint32Array(segs.length * nt * 6 + (caps ? quads.length * 2 * 6 : 0));
  let vi = 0, ii = 0;
  for (const g of segs) {
    const rgb = g.c === UNCUT ? DEFAULT_STOCK_COLOR : colorOf(g.c);
    const base = vi;
    for (const [z, r] of [[g.z1, g.r1], [g.z2, g.r2]] as const) {
      for (let j = 0; j <= nt; j++) {
        positions.set([z, r * sin[j]!, r * cos[j]!], vi * 3); colors.set(rgb, vi * 3); vi++;
      }
    }
    for (let j = 0; j < nt; j++) {
      const a = base + j, b = base + nt + 1 + j;
      indices.set([a, b, b + 1, a, b + 1, a + 1], ii); ii += 6;
    }
  }
  const edge: number[] = [];
  if (caps) {
    for (const th of capAngles) {
      const st = Math.sin(th), ct = Math.cos(th);
      for (const [za, zb, ra, rb] of quads) {
        const k = vi;
        for (const [z, r] of [[za!, ra!], [zb!, ra!], [zb!, rb!], [za!, rb!]] as const) { positions.set([z, r * st, r * ct], vi * 3); colors.set(CAP_COLOR, vi * 3); vi++; }
        indices.set([k, k + 1, k + 2, k, k + 2, k + 3], ii); ii += 6;
      }
      for (const g of segs) edge.push(g.z1, g.r1 * st, g.r1 * ct, g.z2, g.r2 * st, g.r2 * ct);
    }
  }
  return { positions, colors, indices: indices.subarray(0, ii), edges: new Float32Array(edge) };
}
