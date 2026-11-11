// 3D 복셀 절삭 핵심 루프 (AssemblyScript → WASM). src/sim/voxel.ts 의 VoxelStock.stamp 와 같은 계산.
// 메모리: JS 가 만든 WebAssembly.Memory 를 가져다 쓴다(occ·col·lut 가 모두 그 안에 있다).

@inline function clamp01(v: f64): f64 { return v < 0 ? 0 : v > 1 ? 1 : v; }

function feasible(
  lutPtr: usize, lutLast: i32, wp2: f64, dot: f64, s0: f64, uu: f64, dpar: f64, dp2: f64,
  r2: f64, length: f64, invStep: f64,
): bool {
  const dd2u = max(wp2 - 2.0 * uu * dot + uu * uu * dp2, 0.0);
  const s = s0 - uu * dpar;
  if (!(dd2u <= r2) || !(s <= length)) return false;
  const pos = Math.sqrt(dd2u) * invStep;
  let kk = <i32>pos;
  if (kk > lutLast) kk = lutLast;
  const frac = pos - <f64>kk;
  const h = load<f64>(lutPtr + (<usize>kk << 3)) * (1.0 - frac) + load<f64>(lutPtr + ((<usize>kk + 1) << 3)) * frac;
  return s >= h;
}

export function stamp(
  occPtr: usize, colPtr: usize, nx: i32, ny: i32, nz: i32,
  x0: f64, y0: f64, z0: f64, rx: f64, ry: f64, rz: f64,
  ax: f64, ay: f64, az: f64, bx: f64, by: f64, bz: f64,
  ux: f64, uy: f64, uz: f64,
  lutPtr: usize, lutLen: i32, radius: f64, invStep: f64, length: f64, color: i32,
): i32 {
  const ext = radius + 1e-9;
  const tx = length * ux, ty = length * uy, tz = length * uz;
  const lox = min(min(ax, bx), min(ax + tx, bx + tx)) - ext, hix = max(max(ax, bx), max(ax + tx, bx + tx)) + ext;
  const loy = min(min(ay, by), min(ay + ty, by + ty)) - ext, hiy = max(max(ay, by), max(ay + ty, by + ty)) + ext;
  const loz = min(min(az, bz), min(az + tz, bz + tz)) - ext, hiz = max(max(az, bz), max(az + tz, bz + tz)) + ext;
  const i0 = max(<i32>Math.floor((lox - x0) / rx), 0), i1 = min(<i32>Math.ceil((hix - x0) / rx), nx - 1);
  const j0 = max(<i32>Math.floor((loy - y0) / ry), 0), j1 = min(<i32>Math.ceil((hiy - y0) / ry), ny - 1);
  const k0 = max(<i32>Math.floor((loz - z0) / rz), 0), k1 = min(<i32>Math.ceil((hiz - z0) / rz), nz - 1);
  if (i0 > i1 || j0 > j1 || k0 > k1) return 0;
  const dx = bx - ax, dy = by - ay, dz = bz - az;
  const dpar = dx * ux + dy * uy + dz * uz;
  const dpx = dx - dpar * ux, dpy = dy - dpar * uy, dpz = dz - dpar * uz;
  const dp2 = dpx * dpx + dpy * dpy + dpz * dpz;
  const r2 = radius * radius + 1e-9;
  const last = lutLen - 2;
  let removed: i32 = 0;
  for (let i = i0; i <= i1; i++) {
    const wx = x0 + (<f64>i + 0.5) * rx - ax;
    for (let j = j0; j <= j1; j++) {
      const wy = y0 + (<f64>j + 0.5) * ry - ay;
      const base = (<usize>i * <usize>ny + <usize>j) * <usize>nz;
      for (let k = k0; k <= k1; k++) {
        if (load<u8>(occPtr + base + <usize>k) == 0) continue;
        const wz = z0 + (<f64>k + 0.5) * rz - az;
        const s0 = wx * ux + wy * uy + wz * uz;
        const wpx = wx - s0 * ux, wpy = wy - s0 * uy, wpz = wz - s0 * uz;
        const wp2 = wpx * wpx + wpy * wpy + wpz * wpz;
        const dot = wpx * dpx + wpy * dpy + wpz * dpz;
        let t: f64 = 0.0;
        if (dp2 > 0.0) t = clamp01(dot / dp2);
        const dd2 = wp2 - 2.0 * t * dot + t * t * dp2;
        if (!(dd2 <= r2)) continue;
        let ok = feasible(lutPtr, last, wp2, dot, s0, t, dpar, dp2, r2, length, invStep);
        if (!ok) {
          if (Math.abs(dpar) > 1e-12) {
            ok = feasible(lutPtr, last, wp2, dot, s0, clamp01((s0 - length) / dpar), dpar, dp2, r2, length, invStep)
              || feasible(lutPtr, last, wp2, dot, s0, clamp01(s0 / dpar), dpar, dp2, r2, length, invStep);
          }
          if (!ok && dp2 > 0.0) {
            const disc = dot * dot - dp2 * (wp2 - r2);
            const sq = Math.sqrt(max(disc, 0.0));
            ok = feasible(lutPtr, last, wp2, dot, s0, clamp01((dot - sq) / dp2), dpar, dp2, r2, length, invStep)
              || feasible(lutPtr, last, wp2, dot, s0, clamp01((dot + sq) / dp2), dpar, dp2, r2, length, invStep);
          }
        }
        if (ok) {
          store<u8>(occPtr + base + <usize>k, 0);
          store<u8>(colPtr + base + <usize>k, <u8>color);
          removed++;
        }
      }
    }
  }
  return removed;
}
