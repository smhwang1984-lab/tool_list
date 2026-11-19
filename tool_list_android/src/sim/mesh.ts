// Z-map → 화면 메시 — 원본 nc_sim.py display_grid / mesh_from_grid / sharpen_color_edges / edge_lines
import type { ZMapStock } from './zmap';

export const SIM_DISPLAY_GRID_MAX = 600;
export const SIM_DISPLAY_GRID_MAX_SAFE = 300;
export const SIM_EDGE_SEGMENT_LIMIT = 150000;
export const SIM_EDGE_SLOPE = 1.0;
export const DEFAULT_STOCK_COLOR: readonly [number, number, number] = [0.8, 0.87, 0.96];
export const EDGE_COLOR: readonly [number, number, number] = [0.16, 0.22, 0.32];

export interface DisplayGrid {
  xs: Float64Array;
  ys: Float64Array;
  nvx: number;
  nvy: number;
  Z: Float32Array; // nvy*nvx
  C: Int16Array;
}

/** 계산 격자를 화면용으로 줄인다. 블록마다 최솟값을 써서 좁은 홈이 사라지지 않게 한다. */
export function displayGrid(stock: ZMapStock, maxN = SIM_DISPLAY_GRID_MAX): DisplayGrid {
  const { nx, ny } = stock;
  const bx = Math.max(1, Math.ceil(nx / maxN));
  const by = Math.max(1, Math.ceil(ny / maxN));
  if (bx === 1 && by === 1) {
    return {
      xs: Float64Array.from({ length: nx }, (_, i) => stock.gridX(i)), ys: Float64Array.from({ length: ny }, (_, j) => stock.gridY(j)),
      nvx: nx, nvy: ny, Z: stock.heights, C: stock.colorIds,
    };
  }
  const nbx = Math.ceil(nx / bx);
  const nby = Math.ceil(ny / by);
  const blockZ = new Float32Array(nby * nbx);
  const blockC = new Int16Array(nby * nbx);
  for (let jb = 0; jb < nby; jb++) {
    for (let ib = 0; ib < nbx; ib++) {
      let best = Infinity;
      let bestC = -1;
      for (let j = jb * by; j < Math.min(jb * by + by, ny); j++) {
        for (let i = ib * bx; i < Math.min(ib * bx + bx, nx); i++) {
          const z = stock.heights[j * nx + i]!;
          if (z < best) { best = z; bestC = stock.colorIds[j * nx + i]!; }
        }
      }
      blockZ[jb * nbx + ib] = best;
      blockC[jb * nbx + ib] = bestC;
    }
  }
  const vx = nbx + 1;
  const vy = nby + 1;
  const Z = new Float32Array(vy * vx);
  const C = new Int16Array(vy * vx);
  const at = (jb: number, ib: number): [number, number] =>
    jb < 0 || ib < 0 || jb >= nby || ib >= nbx ? [Infinity, -1] : [blockZ[jb * nbx + ib]!, blockC[jb * nbx + ib]!];
  for (let j = 0; j < vy; j++) {
    for (let i = 0; i < vx; i++) {
      // 꼭짓점 둘레 네 블록 [왼위, 오른위, 왼아래, 오른아래] 중 최솟값(처음 만난 것)
      let best = Infinity;
      let bestC = -1;
      for (const [dj, di] of [[-1, -1], [-1, 0], [0, -1], [0, 0]] as const) {
        const [z, c] = at(j + dj, i + di);
        if (z < best) { best = z; bestC = c; }
      }
      Z[j * vx + i] = best;
      C[j * vx + i] = bestC;
    }
  }
  const xi = Array.from({ length: vx }, (_, i) => Math.min(i * bx, nx - 1));
  const yi = Array.from({ length: vy }, (_, j) => Math.min(j * by, ny - 1));
  let nvx = vx;
  let nvy = vy;
  if (xi[xi.length - 1] === xi[xi.length - 2]) { xi.pop(); nvx--; }
  if (yi[yi.length - 1] === yi[yi.length - 2]) { yi.pop(); nvy--; }
  const outZ = new Float32Array(nvy * nvx);
  const outC = new Int16Array(nvy * nvx);
  for (let j = 0; j < nvy; j++) {
    for (let i = 0; i < nvx; i++) { outZ[j * nvx + i] = Z[j * vx + i]!; outC[j * nvx + i] = C[j * vx + i]!; }
  }
  return {
    xs: Float64Array.from(xi, (i) => stock.x0 + i * stock.resolution), ys: Float64Array.from(yi, (j) => stock.y0 + j * stock.resolution),
    nvx, nvy, Z: outZ, C: outC,
  };
}

/** 격자 테두리 정점 번호(위에서 봐서 반시계, 시작 (0,0), 반복 없음) */
function perimeter(nvy: number, nvx: number): number[] {
  const out: number[] = [];
  for (let i = 0; i < nvx; i++) out.push(i);
  for (let j = 1; j < nvy; j++) out.push(j * nvx + nvx - 1);
  for (let i = nvx - 2; i >= 0; i--) out.push((nvy - 1) * nvx + i);
  for (let j = nvy - 2; j >= 1; j--) out.push(j * nvx);
  return out;
}

export interface SimMesh {
  positions: Float32Array;
  colors: Float32Array; // rgb
  indices: Uint32Array;
  edges: Float32Array; // 선분 끝점쌍 xyz
}

/** 공정 색 경계 선명화: 색 id 가 섞인 삼각형은 정점을 복제해 한 가지 색으로 칠한다(원본 sharpen_color_edges) */
export function finishMesh(
  positions: Float32Array, cid: Int16Array, faces: Uint32Array, colorOf: (id: number) => readonly [number, number, number],
): { positions: Float32Array; colors: Float32Array; indices: Uint32Array } {
  const vertCount = positions.length / 3;
  const faceCount = faces.length / 3;
  const extraPos: number[] = [];
  const extraCid: number[] = [];
  const idx = faces.slice();
  let nextV = vertCount;
  for (let t = 0; t < faceCount; t++) {
    const a = idx[t * 3]!, b = idx[t * 3 + 1]!, c = idx[t * 3 + 2]!;
    const ca = cid[a]!, cb = cid[b]!, cc = cid[c]!;
    if (ca === cb && cb === cc) continue;
    let pick: number;
    if (ca === cb || ca === cc) pick = ca;
    else if (cb === cc) pick = cb;
    else pick = ca !== -1 ? ca : cb !== -1 ? cb : cc;
    for (let q = 0; q < 3; q++) {
      const v = idx[t * 3 + q]!;
      extraPos.push(positions[v * 3]!, positions[v * 3 + 1]!, positions[v * 3 + 2]!);
      extraCid.push(pick);
      idx[t * 3 + q] = nextV++;
    }
  }
  const total = nextV;
  const outPos = new Float32Array(total * 3);
  outPos.set(positions);
  outPos.set(extraPos, vertCount * 3);
  const outColors = new Float32Array(total * 3);
  for (let v = 0; v < total; v++) {
    const id = v < vertCount ? cid[v]! : extraCid[v - vertCount]!;
    const col = id < 0 ? DEFAULT_STOCK_COLOR : colorOf(id);
    outColors[v * 3] = col[0]; outColors[v * 3 + 1] = col[1]; outColors[v * 3 + 2] = col[2];
  }
  return { positions: outPos, colors: outColors, indices: idx };
}

export function buildSimMesh(
  stock: ZMapStock, colorOf: (id: number) => readonly [number, number, number], maxN: number, edges = true,
): SimMesh {
  const g = displayGrid(stock, maxN);
  const { nvx, nvy } = g;
  const nt = nvx * nvy;
  const perim = perimeter(nvy, nvx);
  const p = perim.length;
  const vertCount = nt + p + 1;
  const positions = new Float32Array(vertCount * 3);
  const cid = new Int16Array(vertCount);
  for (let j = 0; j < nvy; j++) {
    for (let i = 0; i < nvx; i++) {
      const v = j * nvx + i;
      positions[v * 3] = g.xs[i]!; positions[v * 3 + 1] = g.ys[j]!; positions[v * 3 + 2] = g.Z[v]!;
      cid[v] = g.C[v]!;
    }
  }
  for (let k = 0; k < p; k++) {
    const src = perim[k]!;
    const v = nt + k;
    positions[v * 3] = positions[src * 3]!; positions[v * 3 + 1] = positions[src * 3 + 1]!; positions[v * 3 + 2] = stock.zlo;
    cid[v] = cid[src]!;
  }
  const cv = nt + p;
  positions[cv * 3] = (g.xs[0]! + g.xs[nvx - 1]!) / 2; positions[cv * 3 + 1] = (g.ys[0]! + g.ys[nvy - 1]!) / 2; positions[cv * 3 + 2] = stock.zlo;
  cid[cv] = -1;

  const faceCount = (nvy - 1) * (nvx - 1) * 2 + p * 3;
  const faces = new Uint32Array(faceCount * 3);
  let f = 0;
  const push = (a: number, b: number, c: number): void => { faces[f++] = a; faces[f++] = b; faces[f++] = c; };
  for (let j = 0; j < nvy - 1; j++) {
    for (let i = 0; i < nvx - 1; i++) {
      const a = j * nvx + i, b = a + 1, c = (j + 1) * nvx + i + 1;
      push(a, b, c);
    }
  }
  for (let j = 0; j < nvy - 1; j++) {
    for (let i = 0; i < nvx - 1; i++) {
      const a = j * nvx + i, c = (j + 1) * nvx + i + 1, d = (j + 1) * nvx + i;
      push(a, c, d);
    }
  }
  for (let k = 0; k < p; k++) push(perim[k]!, nt + k, nt + ((k + 1) % p));
  for (let k = 0; k < p; k++) push(perim[k]!, nt + ((k + 1) % p), perim[(k + 1) % p]!);
  for (let k = 0; k < p; k++) push(cv, nt + ((k + 1) % p), nt + k);

  const fin = finishMesh(positions, cid, faces, colorOf);
  const spacing = nvx > 1 ? (g.xs[nvx - 1]! - g.xs[0]!) / (nvx - 1) : stock.resolution;
  return {
    positions: fin.positions, colors: fin.colors, indices: fin.indices,
    edges: edges ? edgeLines(g, stock.zlo, spacing * SIM_EDGE_SLOPE) : new Float32Array(0),
  };
}

/** 모서리 선: 소재 외곽 + 45° 넘게 꺾이는 단차 (원본 edge_lines) */
export function edgeLines(g: DisplayGrid, zlo: number, thr: number, limit = SIM_EDGE_SEGMENT_LIMIT): Float32Array {
  const { nvx, nvy, xs, ys } = g;
  const Z = g.Z;
  const out: number[] = [];
  const line = (a: readonly number[], b: readonly number[]): void => { out.push(a[0]!, a[1]!, a[2]!, b[0]!, b[1]!, b[2]!); };
  const perim = perimeter(nvy, nvx);
  const loop = perim.map((v) => [xs[v % nvx]!, ys[Math.floor(v / nvx)]!, Z[v]!]);
  loop.forEach((pt, i) => line(pt, loop[(i + 1) % loop.length]!));
  const xl = xs[0]!, xh = xs[nvx - 1]!, yl = ys[0]!, yh = ys[nvy - 1]!;
  const corners: [number, number][] = [[xl, yl], [xh, yl], [xh, yh], [xl, yh]];
  const bottom = corners.map(([x, y]) => [x, y, zlo]);
  bottom.forEach((pt, i) => line(pt, bottom[(i + 1) % 4]!));
  const cornerZ = [Z[0]!, Z[nvx - 1]!, Z[(nvy - 1) * nvx + nvx - 1]!, Z[(nvy - 1) * nvx]!];
  corners.forEach(([x, y], i) => line(bottom[i]!, [x, y, cornerZ[i]!]));
  const creaseX = new Uint8Array(nvx * nvy);
  const creaseY = new Uint8Array(nvx * nvy);
  if (nvx > 2) for (let j = 0; j < nvy; j++) for (let i = 1; i < nvx - 1; i++) {
    creaseX[j * nvx + i] = Math.abs(Z[j * nvx + i + 1]! - 2 * Z[j * nvx + i]! + Z[j * nvx + i - 1]!) > thr ? 1 : 0;
  }
  if (nvy > 2) for (let j = 1; j < nvy - 1; j++) for (let i = 0; i < nvx; i++) {
    creaseY[j * nvx + i] = Math.abs(Z[(j + 1) * nvx + i]! - 2 * Z[j * nvx + i]! + Z[(j - 1) * nvx + i]!) > thr ? 1 : 0;
  }
  const segs: number[] = []; // ay,ax,by,bx
  for (let j = 0; j < nvy - 1; j++) for (let i = 0; i < nvx; i++) {
    if (creaseX[j * nvx + i] && creaseX[(j + 1) * nvx + i]) segs.push(j, i, j + 1, i);
  }
  for (let j = 0; j < nvy; j++) for (let i = 0; i < nvx - 1; i++) {
    if (creaseY[j * nvx + i] && creaseY[j * nvx + i + 1]) segs.push(j, i, j, i + 1);
  }
  const n = segs.length / 4;
  const pickIdx: number[] = [];
  if (n > limit) for (let k = 0; k < limit; k++) pickIdx.push(Math.trunc((k * (n - 1)) / (limit - 1)));
  else for (let k = 0; k < n; k++) pickIdx.push(k);
  for (const k of pickIdx) {
    const ay = segs[k * 4]!, ax = segs[k * 4 + 1]!, by = segs[k * 4 + 2]!, bx = segs[k * 4 + 3]!;
    line([xs[ax]!, ys[ay]!, Z[ay * nvx + ax]!], [xs[bx]!, ys[by]!, Z[by * nvx + bx]!]);
  }
  return Float32Array.from(out);
}
