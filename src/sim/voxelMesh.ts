// 복셀 → 화면 메시 — 원본 nc_sim3d.py surface_nets / _coarsen / crease_edges / _box_mesh
import { SIM_EDGE_SEGMENT_LIMIT } from './mesh';
import { UNCUT_COLOR, type VoxelStock } from './voxel';

export const SIM3D_DISPLAY_QUADS_MAX = 800_000; // 상한의 천장. 실제 상한은 정밀도 설정(precision.ts)이 정한다(원본 70만)
export const SIM3D_CREASE_DEG = 40;

export interface SurfaceNets {
  verts: Float32Array; // N*3
  col: Uint8Array; // N
  quads: Uint32Array; // Q*4
}

/** 복셀 factor^3 개를 하나로 합친다 — 절반 이상 차 있으면 소재, 색은 블록 안 최솟값(255=안 깎임) */
export function coarsen(occ: Uint8Array, col: Uint8Array, dims: [number, number, number], factor: number): { occ: Uint8Array; col: Uint8Array; dims: [number, number, number] } {
  const [nx, ny, nz] = dims;
  const mx = Math.ceil(nx / factor), my = Math.ceil(ny / factor), mz = Math.ceil(nz / factor);
  const o = new Uint8Array(mx * my * mz);
  const c = new Uint8Array(mx * my * mz).fill(UNCUT_COLOR);
  const sums = new Int32Array(mx * my * mz);
  for (let i = 0; i < nx; i++) {
    for (let j = 0; j < ny; j++) {
      for (let k = 0; k < nz; k++) {
        const src = (i * ny + j) * nz + k;
        const dst = ((Math.floor(i / factor) * my) + Math.floor(j / factor)) * mz + Math.floor(k / factor);
        sums[dst]! += occ[src]!;
        if (col[src]! < c[dst]!) c[dst] = col[src]!;
      }
    }
  }
  const full = factor ** 3;
  for (let n = 0; n < o.length; n++) o[n] = sums[n]! * 2 >= full ? 1 : 0;
  return { occ: o, col: c, dims: [mx, my, mz] };
}

const CORNERS: [number, number, number][] = [];
for (const di of [0, 1]) for (const dj of [0, 1]) for (const dk of [0, 1]) CORNERS.push([di, dj, dk]);
const CUBE_EDGES: [number, number][] = [];
for (let a = 0; a < 8; a++) for (let b = a + 1; b < 8; b++) {
  const da = CORNERS[a]!, db = CORNERS[b]!;
  if (Math.abs(da[0] - db[0]) + Math.abs(da[1] - db[1]) + Math.abs(da[2] - db[2]) === 1) CUBE_EDGES.push([a, b]);
}

/** 이진 점유 격자의 표면을 surface nets 로 뽑는다(소재 바깥은 빈 칸 — 닫힌 메시, 법선은 바깥쪽). */
export function surfaceNets(
  occ: Uint8Array, col: Uint8Array, dims: [number, number, number], origin: [number, number, number], step: [number, number, number],
): SurfaceNets {
  const [sx, sy, sz] = dims;
  const nx = sx + 2, ny = sy + 2, nz = sz + 2; // 패딩된 격자
  const g = new Uint8Array(nx * ny * nz);
  const gc = new Uint8Array(nx * ny * nz).fill(UNCUT_COLOR);
  for (let i = 0; i < sx; i++) for (let j = 0; j < sy; j++) {
    const src = (i * sy + j) * sz;
    const dst = ((i + 1) * ny + (j + 1)) * nz + 1;
    for (let k = 0; k < sz; k++) { g[dst + k] = occ[src + k]!; gc[dst + k] = col[src + k]!; }
  }
  const cx = nx - 1, cy = ny - 1, cz = nz - 1;
  const cellId = new Int32Array(cx * cy * cz).fill(-1);
  const verts: number[] = [];
  const vcol: number[] = [];
  const [x0, y0, z0] = origin;
  const [rx, ry, rz] = step;
  const cv = new Uint8Array(8);
  for (let i = 0; i < cx; i++) for (let j = 0; j < cy; j++) for (let k = 0; k < cz; k++) {
    let sum = 0;
    for (let n = 0; n < 8; n++) {
      const c = CORNERS[n]!;
      const v = g[((i + c[0]) * ny + (j + c[1])) * nz + (k + c[2])]!;
      cv[n] = v;
      sum += v;
    }
    if (sum === 0 || sum === 8) continue;
    let tx = 0, ty = 0, tz = 0, cnt = 0;
    for (const [a, b] of CUBE_EDGES) {
      if (cv[a] !== cv[b]) {
        const da = CORNERS[a]!, db = CORNERS[b]!;
        tx += (da[0] + db[0]) * 0.5; ty += (da[1] + db[1]) * 0.5; tz += (da[2] + db[2]) * 0.5; cnt++;
      }
    }
    cnt = Math.max(cnt, 1);
    cellId[(i * cy + j) * cz + k] = verts.length / 3;
    verts.push(x0 + (i + tx / cnt - 1 + 0.5) * rx, y0 + (j + ty / cnt - 1 + 0.5) * ry, z0 + (k + tz / cnt - 1 + 0.5) * rz);
    let vc = UNCUT_COLOR;
    for (let n = 0; n < 8; n++) {
      const c = CORNERS[n]!;
      const cc = gc[((i + c[0]) * ny + (j + c[1])) * nz + (k + c[2])]!;
      if (cv[n] === 0 && cc !== UNCUT_COLOR && vc === UNCUT_COLOR) vc = cc;
    }
    vcol.push(vc);
  }
  const vid = (i: number, j: number, k: number): number => cellId[(i * cy + j) * cz + k]!;
  const quads: number[] = [];
  const push = (lower: boolean, a: number, b: number, c: number, d: number): void => {
    if (lower) quads.push(a, b, c, d); else quads.push(d, c, b, a);
  };
  const at = (i: number, j: number, k: number): number => g[(i * ny + j) * nz + k]!;
  for (let i = 0; i < nx - 1; i++) for (let j = 0; j < ny; j++) for (let k = 0; k < nz; k++) {
    if (at(i, j, k) !== at(i + 1, j, k)) push(at(i, j, k) === 1, vid(i, j - 1, k - 1), vid(i, j, k - 1), vid(i, j, k), vid(i, j - 1, k));
  }
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny - 1; j++) for (let k = 0; k < nz; k++) {
    if (at(i, j, k) !== at(i, j + 1, k)) push(at(i, j, k) === 1, vid(i - 1, j, k - 1), vid(i - 1, j, k), vid(i, j, k), vid(i, j, k - 1));
  }
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) for (let k = 0; k < nz - 1; k++) {
    if (at(i, j, k) !== at(i, j, k + 1)) push(at(i, j, k) === 1, vid(i - 1, j - 1, k), vid(i, j - 1, k), vid(i, j, k), vid(i - 1, j, k));
  }
  return { verts: Float32Array.from(verts), col: Uint8Array.from(vcol), quads: Uint32Array.from(quads) };
}

/** 이웃한 두 사각형의 법선이 angle 넘게 꺾이는 변 (끝점쌍 xyz) */
export function creaseEdges(verts: Float32Array, quads: Uint32Array, angleDeg: number): Float32Array {
  const q = quads.length / 4;
  if (q === 0) return new Float32Array(0);
  const normal = new Float64Array(q * 3);
  for (let n = 0; n < q; n++) {
    const a = quads[n * 4]!, b = quads[n * 4 + 1]!, c = quads[n * 4 + 2]!, d = quads[n * 4 + 3]!;
    const e1x = verts[c * 3]! - verts[a * 3]!, e1y = verts[c * 3 + 1]! - verts[a * 3 + 1]!, e1z = verts[c * 3 + 2]! - verts[a * 3 + 2]!;
    const e2x = verts[d * 3]! - verts[b * 3]!, e2y = verts[d * 3 + 1]! - verts[b * 3 + 1]!, e2z = verts[d * 3 + 2]! - verts[b * 3 + 2]!;
    let nx = e1y * e2z - e1z * e2y, ny = e1z * e2x - e1x * e2z, nz = e1x * e2y - e1y * e2x;
    const len = Math.hypot(nx, ny, nz) || 1;
    nx /= len; ny /= len; nz /= len;
    normal[n * 3] = nx; normal[n * 3 + 1] = ny; normal[n * 3 + 2] = nz;
  }
  const nv = verts.length / 3;
  const first = new Map<number, number>();
  const cosLimit = Math.cos((angleDeg * Math.PI) / 180);
  const sharp: number[] = [];
  for (let n = 0; n < q; n++) {
    for (let e = 0; e < 4; e++) {
      const a = quads[n * 4 + e]!, b = quads[n * 4 + ((e + 1) % 4)]!;
      const lo = Math.min(a, b), hi = Math.max(a, b);
      const key = lo * (nv + 1) + hi;
      const other = first.get(key);
      if (other === undefined) { first.set(key, n); continue; }
      const cos = normal[other * 3]! * normal[n * 3]! + normal[other * 3 + 1]! * normal[n * 3 + 1]! + normal[other * 3 + 2]! * normal[n * 3 + 2]!;
      if (cos < cosLimit) sharp.push(lo, hi);
    }
  }
  let list = sharp;
  const total = sharp.length / 2;
  if (total > SIM_EDGE_SEGMENT_LIMIT) {
    list = [];
    for (let k = 0; k < SIM_EDGE_SEGMENT_LIMIT; k++) {
      const idx = Math.trunc((k * (total - 1)) / (SIM_EDGE_SEGMENT_LIMIT - 1));
      list.push(sharp[idx * 2]!, sharp[idx * 2 + 1]!);
    }
  }
  const out = new Float32Array(list.length * 3);
  list.forEach((v, i) => { out[i * 3] = verts[v * 3]!; out[i * 3 + 1] = verts[v * 3 + 1]!; out[i * 3 + 2] = verts[v * 3 + 2]!; });
  return out;
}

export interface VoxelMesh {
  positions: Float32Array;
  cid: Int16Array;
  faces: Uint32Array; // 삼각형
  edges: Float32Array;
}

function estimateQuads(occ: Uint8Array, dims: [number, number, number]): number {
  const [nx, ny, nz] = dims;
  let count = 0;
  const at = (i: number, j: number, k: number): number => occ[(i * ny + j) * nz + k]!;
  for (let i = 0; i < nx; i++) for (let j = 0; j < ny; j++) for (let k = 0; k < nz; k++) {
    const v = at(i, j, k);
    if (i + 1 < nx && v !== at(i + 1, j, k)) count++;
    if (j + 1 < ny && v !== at(i, j + 1, k)) count++;
    if (k + 1 < nz && v !== at(i, j, k + 1)) count++;
    if (v) {
      if (i === 0) count++;
      if (i === nx - 1) count++;
      if (j === 0) count++;
      if (j === ny - 1) count++;
      if (k === 0) count++;
      if (k === nz - 1) count++;
    }
  }
  return count;
}

/** 표시용 메시. 표면 사각형이 상한을 넘으면 복셀을 2배씩 합쳐 거칠게 뽑는다. */
export function buildVoxelMesh(stock: VoxelStock, quadsMax = 150_000, edges = true): VoxelMesh {
  const dims: [number, number, number] = [stock.nx, stock.ny, stock.nz];
  if (stock.allFull()) return boxMesh(stock, edges);
  const limit = Math.min(quadsMax, SIM3D_DISPLAY_QUADS_MAX);
  let factor = 1;
  const est = estimateQuads(stock.occ, dims);
  while (est / (factor * factor) > limit && factor < 16) factor *= 2;
  let occ = stock.occ, col = stock.col, d = dims;
  let step = stock.step;
  if (factor > 1) {
    const c = coarsen(occ, col, dims, factor);
    occ = c.occ; col = c.col; d = c.dims;
    step = [step[0] * factor, step[1] * factor, step[2] * factor];
  }
  const s = surfaceNets(occ, col, d, [stock.x0, stock.y0, stock.z0], step);
  const faces = new Uint32Array((s.quads.length / 4) * 6);
  for (let q = 0; q < s.quads.length / 4; q++) {
    const a = s.quads[q * 4]!, b = s.quads[q * 4 + 1]!, c = s.quads[q * 4 + 2]!, dd = s.quads[q * 4 + 3]!;
    faces.set([a, b, c, a, c, dd], q * 6);
  }
  const cid = new Int16Array(s.col.length);
  for (let i = 0; i < cid.length; i++) cid[i] = s.col[i] === UNCUT_COLOR ? -1 : s.col[i]!;
  return { positions: s.verts, cid, faces, edges: edges ? creaseEdges(s.verts, s.quads, SIM3D_CREASE_DEG) : new Float32Array(0) };
}

function boxMesh(stock: VoxelStock, edges: boolean): VoxelMesh {
  const x1 = stock.x0 + stock.nx * stock.step[0], y1 = stock.y0 + stock.ny * stock.step[1], z1 = stock.z0 + stock.nz * stock.step[2];
  const pts: number[] = [];
  for (const z of [stock.z0, z1]) for (const y of [stock.y0, y1]) for (const x of [stock.x0, x1]) pts.push(x, y, z);
  const quads = [[0, 2, 3, 1], [4, 5, 7, 6], [0, 1, 5, 4], [2, 6, 7, 3], [0, 4, 6, 2], [1, 3, 7, 5]];
  const faces: number[] = [];
  for (const [a, b, c, d] of quads) faces.push(a!, b!, c!, a!, c!, d!);
  const pairs = [[0, 1], [1, 3], [3, 2], [2, 0], [4, 5], [5, 7], [7, 6], [6, 4], [0, 4], [1, 5], [2, 6], [3, 7]];
  const e: number[] = [];
  if (edges) for (const [a, b] of pairs) e.push(pts[a! * 3]!, pts[a! * 3 + 1]!, pts[a! * 3 + 2]!, pts[b! * 3]!, pts[b! * 3 + 1]!, pts[b! * 3 + 2]!);
  return { positions: Float32Array.from(pts), cid: new Int16Array(8).fill(-1), faces: Uint32Array.from(faces), edges: Float32Array.from(e) };
}
