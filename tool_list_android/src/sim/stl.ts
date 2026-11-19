// 바이너리 STL — 원본 write_stl_binary (화면에 보이는 가공 형상 삼각형을 그대로 내보낸다)
export function writeStlBinary(positions: ArrayLike<number>, indices: ArrayLike<number>, header = 'Sum Path'): Uint8Array {
  const tris = Math.floor(indices.length / 3);
  const buf = new ArrayBuffer(84 + tris * 50);
  const dv = new DataView(buf);
  for (let i = 0; i < Math.min(80, header.length); i++) dv.setUint8(i, header.charCodeAt(i) & 0x7f);
  dv.setUint32(80, tris, true);
  let o = 84;
  for (let t = 0; t < tris; t++) {
    const a = indices[t * 3]! * 3, b = indices[t * 3 + 1]! * 3, c = indices[t * 3 + 2]! * 3;
    const ux = positions[b]! - positions[a]!, uy = positions[b + 1]! - positions[a + 1]!, uz = positions[b + 2]! - positions[a + 2]!;
    const vx = positions[c]! - positions[a]!, vy = positions[c + 1]! - positions[a + 1]!, vz = positions[c + 2]! - positions[a + 2]!;
    let nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    const len = Math.hypot(nx, ny, nz);
    if (len > 0) { nx /= len; ny /= len; nz /= len; }
    for (const v of [nx, ny, nz, positions[a]!, positions[a + 1]!, positions[a + 2]!, positions[b]!, positions[b + 1]!, positions[b + 2]!, positions[c]!, positions[c + 1]!, positions[c + 2]!]) {
      dv.setFloat32(o, v, true);
      o += 4;
    }
    dv.setUint16(o, 0, true);
    o += 2;
  }
  return new Uint8Array(buf);
}
