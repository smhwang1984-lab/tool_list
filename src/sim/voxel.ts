// 3D 소재(복셀) — 원본 nc_sim3d.py VoxelStock (경사면 G68.2·동시 5축 G43.4: 공구 축이 기운 이동)
// 복셀 (i,j,k) 의 중심 = (x0+(i+.5)rx, y0+(j+.5)ry, z0+(k+.5)rz). 인덱스 = (i*ny + j)*nz + k.
import type { Bounds } from './stock';
import type { ToolShape } from './toolShape';
import { SIM_CHUNK_SEGMENTS, type SimSegments } from './zmap';

export const SIM3D_TARGET_VOXELS = 3_000_000; // 원본 2천만의 모바일용(메모리·속도)
export const SIM3D_MAX_VOXELS = 8_000_000;
export const SIM3D_MIN_RES = 0.1;
export const SIM3D_MAX_RES = 2.0;
export const SIM3D_ANGLE_STEP_DEG = 2.0;
export const SIM3D_SUB_AXIAL = 0.25;
export const SIM3D_MAX_SUB = 400;
export const UNCUT_COLOR = 255;

export function autoResolution3d(bounds: Bounds, target = SIM3D_TARGET_VOXELS): number {
  const l = (['X', 'Y', 'Z'] as const).map((a) => Math.max(bounds[a][1] - bounds[a][0], 1e-6));
  const res = Math.cbrt((l[0]! * l[1]! * l[2]!) / Math.max(target, 1));
  return Math.round(Math.min(Math.max(res, SIM3D_MIN_RES), SIM3D_MAX_RES) * 1000) / 1000;
}

export function clampResolution3d(bounds: Bounds, resolution: number, maxVoxels = SIM3D_MAX_VOXELS): number {
  const l = (['X', 'Y', 'Z'] as const).map((a) => Math.max(bounds[a][1] - bounds[a][0], 1e-6));
  let res = resolution;
  while ((l[0]! / res) * (l[1]! / res) * (l[2]! / res) > maxVoxels) res *= 1.05;
  return Math.round(res * 1000) / 1000;
}

/** 선분 하나를 몇 조각으로 나눌지 (원본 _piece_count) */
export function pieceCount(
  dx: number, dy: number, dz: number, a0: readonly number[], a1: readonly number[], resMin: number,
): number {
  let nAng = 1;
  const cosang = Math.min(1, Math.max(-1, a0[0]! * a1[0]! + a0[1]! * a1[1]! + a0[2]! * a1[2]!));
  const ang = (Math.acos(cosang) * 180) / Math.PI;
  if (ang > 1e-9) nAng = Math.ceil(ang / SIM3D_ANGLE_STEP_DEG);
  let amx = a0[0]! + a1[0]!, amy = a0[1]! + a1[1]!, amz = a0[2]! + a1[2]!;
  const nm = Math.hypot(amx, amy, amz);
  if (nm > 1e-12) { amx /= nm; amy /= nm; amz /= nm; } else { amx = a0[0]!; amy = a0[1]!; amz = a0[2]!; }
  const dpar = dx * amx + dy * amy + dz * amz;
  const dperp = Math.hypot(dx - dpar * amx, dy - dpar * amy, dz - dpar * amz);
  const nAx = Math.ceil(Math.min(Math.abs(dpar), dperp) / (SIM3D_SUB_AXIAL * resMin));
  return Math.min(Math.max(1, nAng, nAx), SIM3D_MAX_SUB);
}

export class VoxelStock {
  readonly resolution: number;
  readonly nx: number;
  readonly ny: number;
  readonly nz: number;
  readonly step: [number, number, number];
  readonly x0: number;
  readonly y0: number;
  readonly z0: number;
  readonly zlo: number;
  readonly ztop: number;
  occ: Uint8Array;
  col: Uint8Array;
  rapidWarnings: { src: number | null; seq: number | null }[] = [];
  version = 0;

  constructor(bounds: Bounds, resolution: number) {
    this.resolution = resolution;
    const len = (['X', 'Y', 'Z'] as const).map((a) => Math.max(bounds[a][1] - bounds[a][0], 1e-6));
    this.nx = Math.max(2, Math.round(len[0]! / resolution));
    this.ny = Math.max(2, Math.round(len[1]! / resolution));
    this.nz = Math.max(2, Math.round(len[2]! / resolution));
    this.step = [len[0]! / this.nx, len[1]! / this.ny, len[2]! / this.nz];
    this.x0 = bounds.X[0];
    this.y0 = bounds.Y[0];
    this.z0 = bounds.Z[0];
    this.zlo = bounds.Z[0];
    this.ztop = bounds.Z[1];
    this.occ = new Uint8Array(this.nx * this.ny * this.nz).fill(1);
    this.col = new Uint8Array(this.nx * this.ny * this.nz).fill(UNCUT_COLOR);
  }

  cellCount(): number { return this.nx * this.ny * this.nz; }
  anyCut(): boolean { for (let i = 0; i < this.occ.length; i++) if (!this.occ[i]) return true; return false; }
  allFull(): boolean { return !this.anyCut(); }

  reset(): void {
    this.occ.fill(1);
    this.col.fill(UNCUT_COLOR);
    this.rapidWarnings = [];
    this.version++;
  }
  snapshot(): { o: Uint8Array; c: Uint8Array } { return { o: this.occ.slice(), c: this.col.slice() }; }
  restore(s: { o: Uint8Array; c: Uint8Array }): void { this.occ.set(s.o); this.col.set(s.c); this.version++; }
  snapshotBytes(): number { return this.occ.length * 2; }

  /** 이동 조각(A→B, 공구 축 u 고정)으로 깎는다. 깎은 복셀 수 */
  private stamp(
    ax: number, ay: number, az: number, bx: number, by: number, bz: number,
    ux: number, uy: number, uz: number, lut: Float64Array, radius: number, invStep: number, length: number, color: number,
  ): number {
    const { nx, ny, nz } = this;
    const [rx, ry, rz] = this.step;
    const ext = radius + 1e-9;
    const tx = length * ux, ty = length * uy, tz = length * uz;
    const lox = Math.min(ax, bx, ax + tx, bx + tx) - ext, hix = Math.max(ax, bx, ax + tx, bx + tx) + ext;
    const loy = Math.min(ay, by, ay + ty, by + ty) - ext, hiy = Math.max(ay, by, ay + ty, by + ty) + ext;
    const loz = Math.min(az, bz, az + tz, bz + tz) - ext, hiz = Math.max(az, bz, az + tz, bz + tz) + ext;
    const i0 = Math.max(Math.floor((lox - this.x0) / rx), 0), i1 = Math.min(Math.ceil((hix - this.x0) / rx), nx - 1);
    const j0 = Math.max(Math.floor((loy - this.y0) / ry), 0), j1 = Math.min(Math.ceil((hiy - this.y0) / ry), ny - 1);
    const k0 = Math.max(Math.floor((loz - this.z0) / rz), 0), k1 = Math.min(Math.ceil((hiz - this.z0) / rz), nz - 1);
    if (i0 > i1 || j0 > j1 || k0 > k1) return 0;
    const dx = bx - ax, dy = by - ay, dz = bz - az;
    const dpar = dx * ux + dy * uy + dz * uz;
    const dpx = dx - dpar * ux, dpy = dy - dpar * uy, dpz = dz - dpar * uz;
    const dp2 = dpx * dpx + dpy * dpy + dpz * dpz;
    const r2 = radius * radius + 1e-9;
    const last = lut.length - 2;
    const feasible = (wp2: number, dot: number, s0: number, uu: number): boolean => {
      const dd2u = Math.max(wp2 - 2 * uu * dot + uu * uu * dp2, 0);
      const s = s0 - uu * dpar;
      if (!(dd2u <= r2) || !(s <= length)) return false;
      const pos = Math.sqrt(dd2u) * invStep;
      let kk = Math.trunc(pos);
      if (kk > last) kk = last;
      const frac = pos - kk;
      const h = lut[kk]! * (1 - frac) + lut[kk + 1]! * frac;
      return s >= h;
    };
    let removed = 0;
    for (let i = i0; i <= i1; i++) {
      const wx = this.x0 + (i + 0.5) * rx - ax;
      for (let j = j0; j <= j1; j++) {
        const wy = this.y0 + (j + 0.5) * ry - ay;
        const base = (i * ny + j) * nz;
        for (let k = k0; k <= k1; k++) {
          if (!this.occ[base + k]) continue;
          const wz = this.z0 + (k + 0.5) * rz - az;
          const s0 = wx * ux + wy * uy + wz * uz;
          const wpx = wx - s0 * ux, wpy = wy - s0 * uy, wpz = wz - s0 * uz;
          const wp2 = wpx * wpx + wpy * wpy + wpz * wpz;
          const dot = wpx * dpx + wpy * dpy + wpz * dpz;
          let t = 0;
          if (dp2 > 0) { t = dot / dp2; t = t < 0 ? 0 : t > 1 ? 1 : t; }
          const dd2 = wp2 - 2 * t * dot + t * t * dp2;
          if (!(dd2 <= r2)) continue;
          let ok = feasible(wp2, dot, s0, t);
          if (!ok) {
            const cl = (v: number): number => (v < 0 ? 0 : v > 1 ? 1 : v);
            if (Math.abs(dpar) > 1e-12) {
              ok = feasible(wp2, dot, s0, cl((s0 - length) / dpar)) || feasible(wp2, dot, s0, cl(s0 / dpar));
            }
            if (!ok && dp2 > 0) {
              const disc = dot * dot - dp2 * (wp2 - r2);
              const sq = Math.sqrt(Math.max(disc, 0));
              ok = feasible(wp2, dot, s0, cl((dot - sq) / dp2)) || feasible(wp2, dot, s0, cl((dot + sq) / dp2));
            }
          }
          if (ok) { this.occ[base + k] = 0; this.col[base + k] = color; removed++; }
        }
      }
    }
    return removed;
  }

  /** seg[from, to) 를 순서대로 깎는다. axes0/axes1 은 선분 시작/끝의 공구 축(단위벡터, count*3) */
  cutRange(
    seg: SimSegments, tools: readonly (ToolShape | null)[], axes0: Float64Array, axes1: Float64Array, from: number, to: number,
  ): void {
    const resMin = Math.min(...this.step);
    const x1 = this.x0 + this.nx * this.step[0], y1 = this.y0 + this.ny * this.step[1], z1 = this.z0 + this.nz * this.step[2];
    for (let m = from; m < to; m++) {
      const t = seg.slot[m]!;
      const tool = t >= 0 ? tools[t] ?? null : null;
      if (!tool) continue;
      const ax = seg.p0[m * 3]!, ay = seg.p0[m * 3 + 1]!, az = seg.p0[m * 3 + 2]!;
      const bx = seg.p1[m * 3]!, by = seg.p1[m * 3 + 1]!, bz = seg.p1[m * 3 + 2]!;
      const radius = tool.radius;
      const length = tool.cutLength;
      const reach = radius + length;
      if (Math.max(ax, bx) + reach < this.x0 || Math.min(ax, bx) - reach > x1
        || Math.max(ay, by) + reach < this.y0 || Math.min(ay, by) - reach > y1
        || Math.max(az, bz) + reach < this.z0 || Math.min(az, bz) - reach > z1) continue;
      const a0 = [axes0[m * 3]!, axes0[m * 3 + 1]!, axes0[m * 3 + 2]!];
      const a1 = [axes1[m * 3]!, axes1[m * 3 + 1]!, axes1[m * 3 + 2]!];
      const dx = bx - ax, dy = by - ay, dz = bz - az;
      const nSub = pieceCount(dx, dy, dz, a0, a1, resMin);
      const { lut, invStep } = tool.radialLut(resMin);
      const color = Math.min(Math.max(seg.color[m]!, 0), UNCUT_COLOR - 1);
      let removed = 0;
      for (let k = 0; k < nSub; k++) {
        const ta = k / nSub, tb = (k + 1) / nSub, mid = (k + 0.5) / nSub;
        let ux = a0[0]! + (a1[0]! - a0[0]!) * mid, uy = a0[1]! + (a1[1]! - a0[1]!) * mid, uz = a0[2]! + (a1[2]! - a0[2]!) * mid;
        const nu = Math.hypot(ux, uy, uz);
        if (nu > 1e-12) { ux /= nu; uy /= nu; uz /= nu; } else { ux = a0[0]!; uy = a0[1]!; uz = a0[2]!; }
        removed += this.stamp(ax + dx * ta, ay + dy * ta, az + dz * ta, ax + dx * tb, ay + dy * tb, az + dz * tb, ux, uy, uz, lut, radius, invStep, length, color);
      }
      if (removed > 0 && seg.rapid[m]) this.rapidWarnings.push({ src: seg.src[m]! >= 0 ? seg.src[m]! : null, seq: seg.seq1[m]! });
    }
    this.version++;
  }
}

export { SIM_CHUNK_SEGMENTS };
