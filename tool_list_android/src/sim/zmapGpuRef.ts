// GPU Z-map 절삭 셰이더(sim_shaders/cut.vert, cut.frag)의 CPU 기준 구현 — 원본 nc_sim_gpu_ref.py (v2.8.0, G1).
//
// 셰이더가 화소 하나에서 하는 계산을 칸 단위로 그대로 옮겼다. 셰이더의 정답표(실제 GPU 결과는 이 구현과 비교)이자
// GPU를 못 쓰는 환경·시험에서 같은 "연속 선분 훑기" 결과를 얻는 느린 경로다. 식·상수는 cut.frag 와 같아야 한다.
//
// 칸 중심 c, 선분 a→b, 공구 반지름 r, 팁 높이 z(t) = az + t*(bz - az) 일 때
//     f(t) = z(t) + h(|c - p(t)|)  을  p(t)가 공구 안(|c - p(t)| <= r)인 t 구간에서 최소화한다.
// h는 d에 대해 볼록·증가, d(t)는 볼록 → f가 볼록이라 황금분할 탐색이 정확하다. 구간 양 끝은 따로 정확히 잰다.
//
// 지금 CPU 엔진(zmap.ts ZMapStock)과의 차이는 원본 nc_sim_gpu_ref.py 머리말과 같다:
// 경사 이동은 CPU가 조각 크기(격자 간격 x SUB_Z)만큼 더 깊게 깎고, 공구 가장자리 칸은 반경 표(LUT) 보간 오차가 있다.
import { ZMapStock, type SimSegments } from './zmap';
import type { ProfileParams, ToolShape } from './toolShape';
import type { Bounds } from './stock';
import { PROFILE_CHAMFER, PROFILE_CONE, PROFILE_CORNER } from './toolShape';

// cut.frag 의 같은 이름 상수와 같아야 한다.
export const GOLD_ITER = 24;
export const INV_PHI = 0.6180339887498949;
export const R2_EPS = 1e-9;
export const R2_REL_EPS = 1e-5; // float32에서 "칸 중심이 정확히 반지름 위"인 줄이 반올림으로 빠지지 않게 하는 상대 여유
export const VERTICAL_LEN2 = 1e-18;

/** cut.frag profile_h() — 팁 기준 공구 높이 */
export function profileH(d: number, p: ProfileParams): number {
  const kind = Math.floor(p[0] + 0.5);
  if (kind === PROFILE_CORNER) {
    const a = p[1], b = p[2];
    const dr = Math.min(Math.max(d - a, 0), b);
    return d > a ? b - Math.sqrt(Math.max(b * b - dr * dr, 0)) : 0;
  }
  if (kind === PROFILE_CONE) return d * p[1];
  if (kind === PROFILE_CHAMFER) return Math.max(d - p[1], 0);
  return 0;
}

export interface SweepOut {
  /** 새 윗면 높이. 선분이 이 칸에 닿지 않으면 Infinity */
  value: number;
  /** 최솟값이 생긴 지점의 수평 거리(공구 가장자리 칸 판별용) */
  dmin: number;
}

/** 선분 하나가 칸 하나(중심이 a에서 (qx, qy)만큼)에 만드는 새 윗면 높이 (원본 sweep_min_height 한 칸 분) */
export function sweepMinHeight(
  qx: number, qy: number, dx: number, dy: number, az: number, dz: number,
  radius: number, params: ProfileParams, out: SweepOut,
): SweepOut {
  const r2 = radius * radius * (1 + R2_REL_EPS) + R2_EPS;
  const len2 = dx * dx + dy * dy;
  const qq = qx * qx + qy * qy;
  const f =(t: number): number => {
    const wx = qx - t * dx, wy = qy - t * dy;
    return az + dz * t + profileH(Math.sqrt(wx * wx + wy * wy), params);
  };

  let lo = 0, hi = 1;
  if (len2 < VERTICAL_LEN2) {
    if (qq > r2) { out.value = Infinity; out.dmin = 0; return out; }
  } else {
    const qd = qx * dx + qy * dy;
    const disc = qd * qd - len2 * (qq - r2);
    if (disc < 0) { out.value = Infinity; out.dmin = 0; return out; }
    const sq = Math.sqrt(disc);
    lo = Math.max((qd - sq) / len2, 0);
    hi = Math.min((qd + sq) / len2, 1);
    if (lo > hi) { out.value = Infinity; out.dmin = 0; return out; }
  }

  const fLo = f(lo), fHi = f(hi);
  let best = fLo <= fHi ? fLo : fHi;
  let bestT = fLo <= fHi ? lo : hi;

  if (len2 >= VERTICAL_LEN2) {
    let ta = lo, tb = hi;
    let tc = tb - (tb - ta) * INV_PHI;
    let td = ta + (tb - ta) * INV_PHI;
    let fc = f(tc), fd = f(td);
    if (fc < best) { best = fc; bestT = tc; }
    if (fd < best) { best = fd; bestT = td; }
    for (let k = 0; k < GOLD_ITER; k++) {
      if (fc < fd) {
        tb = td; td = tc; fd = fc;
        tc = tb - (tb - ta) * INV_PHI;
        fc = f(tc);
        if (fc < best) { best = fc; bestT = tc; }
      } else {
        ta = tc; tc = td; fc = fd;
        td = ta + (tb - ta) * INV_PHI;
        fd = f(td);
        if (fd < best) { best = fd; bestT = td; }
      }
    }
  }
  const wx = qx - bestT * dx, wy = qy - bestT * dy;
  out.value = best;
  out.dmin = Math.sqrt(wx * wx + wy * wy);
  return out;
}

/** 셰이더와 같은 식으로 깎는 Z-map 소재. ZMapStock 과 같은 인터페이스(cutRange 등)를 쓴다. */
export class ZMapGpuRef extends ZMapStock {
  static readonly EDGE_BAND_CELLS = 1.5;
  /** 마지막으로 그 칸을 낮춘 선분에서 최솟값 지점이 공구 가장자리(d > r - EDGE_BAND_CELLS*res)였던 칸 */
  edgeMask: Uint8Array;

  constructor(bounds: Bounds, resolution: number) {
    super(bounds, resolution);
    this.edgeMask = new Uint8Array(this.nx * this.ny);
  }

  override reset(): void {
    super.reset();
    this.edgeMask.fill(0);
  }

  override restore(s: { h: Float32Array; c: Int16Array }): void {
    super.restore(s);
    this.edgeMask.fill(0);
  }

  override cutRange(seg: SimSegments, tools: readonly (ToolShape | null)[], from: number, to: number): void {
    const res = this.resolution;
    const ztop = this.ztop;
    const zlo32 = Math.fround(this.zlo);
    const out: SweepOut = { value: 0, dmin: 0 };
    for (let m = from; m < to; m++) {
      const t = seg.slot[m]!;
      const tool = t >= 0 ? tools[t] ?? null : null;
      if (!tool) continue;
      const params = tool.profileParams();
      if (!params) throw new Error(`GPU 엔진이 모르는 공구 형상입니다(${tool.typeName}) — CPU 엔진으로 깎아야 합니다`);
      const ax = seg.p0[m * 3]!, ay = seg.p0[m * 3 + 1]!, az = seg.p0[m * 3 + 2]!;
      const bx = seg.p1[m * 3]!, by = seg.p1[m * 3 + 1]!, bz = seg.p1[m * 3 + 2]!;
      if (Math.min(az, bz) >= ztop) continue;
      const radius = tool.radius;
      const ix0 = Math.max(Math.floor((Math.min(ax, bx) - radius - this.x0) / res), 0);
      const ix1 = Math.min(Math.ceil((Math.max(ax, bx) + radius - this.x0) / res), this.nx - 1);
      const iy0 = Math.max(Math.floor((Math.min(ay, by) - radius - this.y0) / res), 0);
      const iy1 = Math.min(Math.ceil((Math.max(ay, by) + radius - this.y0) / res), this.ny - 1);
      if (ix0 > ix1 || iy0 > iy1) continue;
      const color = seg.color[m]!;
      const edgeDist = radius - ZMapGpuRef.EDGE_BAND_CELLS * res;
      let anyLow = false;
      for (let iy = iy0; iy <= iy1; iy++) {
        const qy = this.y0 + iy * res - ay;
        for (let ix = ix0; ix <= ix1; ix++) {
          const qx = this.x0 + ix * res - ax;
          sweepMinHeight(qx, qy, bx - ax, by - ay, az, bz - az, radius, params, out);
          if (!(out.value < ztop)) continue;
          let nv = Math.fround(out.value);
          if (nv < zlo32) nv = zlo32;
          const idx = iy * this.nx + ix;
          if (nv < this.heights[idx]!) {
            this.heights[idx] = nv;
            this.colorIds[idx] = color;
            this.edgeMask[idx] = out.dmin > edgeDist ? 1 : 0;
            anyLow = true;
          }
        }
      }
      if (anyLow && seg.rapid[m]) this.rapidWarnings.push({ src: seg.src[m]! >= 0 ? seg.src[m]! : null, seq: seg.seq1[m]! });
    }
  }
}
