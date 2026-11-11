// Z-map 절삭 핵심 루프 (AssemblyScript → WASM). src/sim/zmap.ts 의 ZMapStock.stamp 와 같은 계산.
export function zstamp(
  hPtr: usize, cPtr: usize, nx: i32, ny: i32, x0: f64, y0: f64, res: f64,
  ax: f64, ay: f64, bx: f64, by: f64, z: f64,
  lutPtr: usize, lutLen: i32, radius: f64, invStep: f64, color: i32, zlo32: f32,
): i32 {
  const dx = bx - ax;
  const dy = by - ay;
  const len2 = dx * dx + dy * dy;
  const r2 = radius * radius + 1e-9;
  const ix0 = max(<i32>Math.floor((min(ax, bx) - radius - x0) / res), 0);
  const ix1 = min(<i32>Math.ceil((max(ax, bx) + radius - x0) / res), nx - 1);
  const iy0 = max(<i32>Math.floor((min(ay, by) - radius - y0) / res), 0);
  const iy1 = min(<i32>Math.ceil((max(ay, by) + radius - y0) / res), ny - 1);
  if (ix0 > ix1 || iy0 > iy1) return 0;
  const last = lutLen - 2;
  let any: i32 = 0;
  for (let iy = iy0; iy <= iy1; iy++) {
    const py = y0 + <f64>iy * res - ay;
    const row = <usize>iy * <usize>nx;
    for (let ix = ix0; ix <= ix1; ix++) {
      const px = x0 + <f64>ix * res - ax;
      let qx = px;
      let qy = py;
      if (len2 > 0.0) {
        let t = (px * dx + py * dy) / len2;
        t = t < 0.0 ? 0.0 : t > 1.0 ? 1.0 : t;
        qx = px - t * dx;
        qy = py - t * dy;
      }
      const d2 = qx * qx + qy * qy;
      if (!(d2 <= r2)) continue;
      const pos = Math.sqrt(d2) * invStep;
      let k = <i32>pos;
      if (k > last) k = last;
      const frac = pos - <f64>k;
      const h = load<f64>(lutPtr + (<usize>k << 3)) * (1.0 - frac) + load<f64>(lutPtr + ((<usize>k + 1) << 3)) * frac;
      let nv = <f32>(z + h);
      if (nv < zlo32) nv = zlo32;
      const idx = row + <usize>ix;
      if (nv < load<f32>(hPtr + (idx << 2))) {
        store<f32>(hPtr + (idx << 2), nv);
        store<i16>(cPtr + (idx << 1), <i16>color);
        any = 1;
      }
    }
  }
  return any;
}
