// Z-map 소재 — 원본 nc_sim.py ZMapStock (3축, 공구 축 = +Z). numpy 경로와 같은 산식·같은 순서.
import type { Bounds } from './stock';
import type { ToolShape } from './toolShape';

export const SUB_Z = 0.25;
export const MAX_SUB = 400;
export const SIM_CHUNK_SEGMENTS = 2000;

export interface SimSegments {
  count: number;
  p0: Float64Array; // count*3
  p1: Float64Array;
  seq1: Int32Array;
  src: Int32Array;
  rapid: Uint8Array;
  slot: Int32Array;
  color: Int16Array;
}

export class ZMapStock {
  readonly resolution: number;
  readonly x0: number;
  readonly y0: number;
  readonly nx: number;
  readonly ny: number;
  readonly zlo: number;
  readonly ztop: number;
  heights: Float32Array;
  colorIds: Int16Array;
  rapidWarnings: { src: number | null; seq: number | null }[] = [];

  constructor(bounds: Bounds, resolution: number) {
    this.resolution = resolution;
    this.x0 = bounds.X[0];
    this.y0 = bounds.Y[0];
    this.nx = Math.max(2, Math.round((bounds.X[1] - bounds.X[0]) / resolution) + 1);
    this.ny = Math.max(2, Math.round((bounds.Y[1] - bounds.Y[0]) / resolution) + 1);
    this.zlo = bounds.Z[0];
    this.ztop = bounds.Z[1];
    this.heights = new Float32Array(this.nx * this.ny).fill(Math.fround(this.ztop));
    this.colorIds = new Int16Array(this.nx * this.ny).fill(-1);
  }

  gridX(i: number): number { return this.x0 + i * this.resolution; }
  gridY(j: number): number { return this.y0 + j * this.resolution; }
  cellCount(): number { return this.nx * this.ny; }

  anyCut(): boolean {
    const lim = this.ztop - 1e-6;
    for (let i = 0; i < this.heights.length; i++) if (this.heights[i]! < lim) return true;
    return false;
  }

  reset(): void {
    this.heights.fill(Math.fround(this.ztop));
    this.colorIds.fill(-1);
    this.rapidWarnings = [];
  }

  snapshot(): { h: Float32Array; c: Int16Array } {
    return { h: this.heights.slice(), c: this.colorIds.slice() };
  }

  restore(s: { h: Float32Array; c: Int16Array }): void {
    this.heights.set(s.h);
    this.colorIds.set(s.c);
  }

  /** 수평 선분 (ax,ay)->(bx,by) 를 팁 높이 z 로 훑는다. 깎인 칸이 있으면 true. */
  private stamp(
    ax: number, ay: number, bx: number, by: number, z: number,
    lut: Float64Array, radius: number, invStep: number, color: number, zlo32: number,
  ): boolean {
    const res = this.resolution;
    const dx = bx - ax;
    const dy = by - ay;
    const len2 = dx * dx + dy * dy;
    const r2 = radius * radius + 1e-9;
    const ix0 = Math.max(Math.floor((Math.min(ax, bx) - radius - this.x0) / res), 0);
    const ix1 = Math.min(Math.ceil((Math.max(ax, bx) + radius - this.x0) / res), this.nx - 1);
    const iy0 = Math.max(Math.floor((Math.min(ay, by) - radius - this.y0) / res), 0);
    const iy1 = Math.min(Math.ceil((Math.max(ay, by) + radius - this.y0) / res), this.ny - 1);
    if (ix0 > ix1 || iy0 > iy1) return false;
    const nx = this.nx;
    const last = lut.length - 2;
    let any = false;
    for (let iy = iy0; iy <= iy1; iy++) {
      const py = this.y0 + iy * res - ay;
      const row = iy * nx;
      for (let ix = ix0; ix <= ix1; ix++) {
        const px = this.x0 + ix * res - ax;
        let qx = px;
        let qy = py;
        if (len2 > 0) {
          let t = (px * dx + py * dy) / len2;
          t = t < 0 ? 0 : t > 1 ? 1 : t;
          qx = px - t * dx;
          qy = py - t * dy;
        }
        const d2 = qx * qx + qy * qy;
        if (!(d2 <= r2)) continue;
        const pos = Math.sqrt(d2) * invStep;
        let k = Math.trunc(pos);
        if (k > last) k = last;
        const frac = pos - k;
        const h = lut[k]! * (1 - frac) + lut[k + 1]! * frac;
        let nv = Math.fround(z + h);
        if (nv < zlo32) nv = zlo32;
        const idx = row + ix;
        if (nv < this.heights[idx]!) {
          this.heights[idx] = nv;
          this.colorIds[idx] = color;
          any = true;
        }
      }
    }
    return any;
  }

  /** seg[from, to) 를 순서대로 깎는다. */
  cutRange(seg: SimSegments, tools: readonly (ToolShape | null)[], from: number, to: number): void {
    const res = this.resolution;
    const ztop = this.ztop;
    const zlo32 = Math.fround(this.zlo);
    for (let m = from; m < to; m++) {
      const t = seg.slot[m]!;
      const tool = t >= 0 ? tools[t] ?? null : null;
      if (!tool) continue;
      const ax = seg.p0[m * 3]!, ay = seg.p0[m * 3 + 1]!, az = seg.p0[m * 3 + 2]!;
      const bx = seg.p1[m * 3]!, by = seg.p1[m * 3 + 1]!, bz = seg.p1[m * 3 + 2]!;
      if (Math.min(az, bz) >= ztop) continue;
      const dx = bx - ax, dy = by - ay, dz = bz - az;
      const nSub = dx * dx + dy * dy < 1e-18 ? 1 : Math.min(Math.max(1, Math.ceil(Math.abs(dz) / (res * SUB_Z))), MAX_SUB);
      const { lut, invStep } = tool.radialLut(res);
      const color = seg.color[m]!;
      let anyLow = false;
      for (let k = 0; k < nSub; k++) {
        const ta = k / nSub, tb = (k + 1) / nSub;
        const z = Math.min(az + dz * ta, az + dz * tb);
        if (z >= ztop) continue;
        if (this.stamp(ax + dx * ta, ay + dy * ta, ax + dx * tb, ay + dy * tb, z, lut, tool.radius, invStep, color, zlo32)) anyLow = true;
      }
      if (anyLow && seg.rapid[m]) this.rapidWarnings.push({ src: seg.src[m]! >= 0 ? seg.src[m]! : null, seq: seg.seq1[m]! });
    }
  }
}
