// 실제 GPU(WebGL2) 절삭 결과를 CPU 기준 구현(zmapGpuRef.ts)과 칸마다 비교한다 — tools/gpu_check.mjs 가 Playwright 로 연다.
import * as THREE from 'three';
import { GpuZMapStock, gpuProbe } from '../../src/sim/zmapGpu';
import { ZMapGpuRef } from '../../src/sim/zmapGpuRef';
import { toolShapeFromValues, type ToolValues } from '../../src/sim/toolShape';
import type { SimSegments } from '../../src/sim/zmap';

const val = (type: string, D: number, extra: Partial<ToolValues> = {}): ToolValues =>
  ({ type, D, FL: null, R: null, SIG: null, PL: null, SO: null, ...extra });

type Pt = [number, number, number];
function segs(path: [Pt, Pt, boolean?][]): SimSegments {
  const n = path.length;
  const s: SimSegments = {
    count: n, p0: new Float64Array(n * 3), p1: new Float64Array(n * 3), seq1: new Int32Array(n).map((_, i) => i + 1),
    src: new Int32Array(n).map((_, i) => i), rapid: new Uint8Array(n), slot: new Int32Array(n), color: new Int16Array(n).map((_, i) => i % 4),
  };
  path.forEach(([a, b, rapid], i) => { s.p0.set(a, i * 3); s.p1.set(b, i * 3); s.rapid[i] = rapid ? 1 : 0; });
  return s;
}

const out: Record<string, unknown> = {};
await (async () => {
try {
  const canvas = document.getElementById('c') as HTMLCanvasElement;
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: false });
  out.probe = gpuProbe(renderer, true);
  const bounds = { X: [-20, 20] as [number, number], Y: [-12, 12] as [number, number], Z: [-10, 0] as [number, number] };
  const res = 0.2;
  const kinds: Record<string, ToolValues> = {
    flat: val('FLAT E/M', 6), ball: val('BALL E/M', 6), fillet: val('FILLET E/M', 8, { R: 1 }),
    drill: val('DRILL', 6, { SIG: 118 }), chamfer: val('CHAMFER', 8, { PL: 1.5 }),
  };
  const paths: Record<string, [Pt, Pt, boolean?][]> = {
    horizontal: [[[-12, -3, -4], [12, -3, -4]], [[12, 3, -4], [-12, 3, -4]]],
    vertical: [[[0, 0, 0], [0, 0, -6]]],
    sloped: [[[-12, 0, -2], [12, 4, -7]], [[-10, -6, -1], [8, 6, -5]]],
    zigzag: Array.from({ length: 6 }, (_, k) => [[-12, -6 + 2 * k, -3 - 0.5 * (k % 2)], [12, -6 + 2 * k, -3 - 0.5 * (k % 2)]] as [Pt, Pt]),
  };
  const results: Record<string, { maxDiff: number; badCells: number; cut: number; colorMismatch: number }> = {};
  for (const [kn, kv] of Object.entries(kinds)) {
    const tool = toolShapeFromValues(kv)!;
    for (const [pn, path] of Object.entries(paths)) {
      const seg = segs(path);
      const gpu = new GpuZMapStock(renderer, bounds, res);
      const ref = new ZMapGpuRef(bounds, res);
      gpu.cutRange(seg, [tool], 0, seg.count);
      ref.cutRange(seg, [tool], 0, seg.count);
      const { heights, colorIds } = gpu.cutter.read();
      let maxDiff = 0, bad = 0, cut = 0, cm = 0;
      for (let i = 0; i < heights.length; i++) {
        const d = Math.abs(heights[i]! - ref.heights[i]!);
        if (ref.heights[i]! < bounds.Z[1] - 1e-6) cut++;
        if (ref.edgeMask[i]) continue;
        if (d > maxDiff) maxDiff = d;
        if (d > 1e-3) bad++;
        if (colorIds[i] !== ref.colorIds[i] && d <= 1e-3) cm++;
      }
      results[`${kn}/${pn}`] = { maxDiff, badCells: bad, cut, colorMismatch: cm };
      gpu.dispose();
    }
  }
  out.results = results;
  // 표시 격자 줄이기: GPU 블록 최솟값 == 기준 구현 높이의 블록 최솟값
  {
    const tool = toolShapeFromValues(kinds.ball!)!;
    const seg = segs(paths.zigzag!);
    const g = new GpuZMapStock(renderer, bounds, res);
    const ref = new ZMapGpuRef(bounds, res);
    g.cutRange(seg, [tool], 0, seg.count);
    ref.cutRange(seg, [tool], 0, seg.count);
    const block: [number, number] = [3, 2];
    const dnx = Math.ceil(g.nx / 3), dny = Math.ceil(g.ny / 2);
    const target = new THREE.WebGLRenderTarget(dnx, dny, { count: 2, type: THREE.FloatType, format: THREE.RGBAFormat, minFilter: THREE.NearestFilter, magFilter: THREE.NearestFilter, depthBuffer: false });
    g.cutter.convertTo(target, block);
    const buf = new Float32Array(dnx * dny * 4);
    renderer.readRenderTargetPixels(target, 0, 0, dnx, dny, buf, undefined, 0);
    let bad = 0;
    for (let j = 0; j < dny; j++) for (let i = 0; i < dnx; i++) {
      let best = Infinity;
      for (let dj = 0; dj < 2; dj++) for (let di = 0; di < 3; di++) {
        const x = i * 3 + di, y = j * 2 + dj;
        if (x < g.nx && y < g.ny) best = Math.min(best, ref.heights[y * g.nx + x]!);
      }
      if (Math.abs(buf[(j * dnx + i) * 4]! - best) > 1e-3) bad++;
    }
    out.reduce = { dnx, dny, bad };
    target.dispose(); g.dispose();
  }
  // 속도: 선분 13k개를 4096칸 소재에 깎고 읽을 때까지(G6 측정의 가벼운 사전 확인 — 정식 측정은 G6). ?perf=0 이면 건너뛴다(소프트웨어 GL은 매우 느리다)
  if (!location.search.includes('perf=0')) {
    const tool = toolShapeFromValues(kinds.ball!)!;
    const big = { X: [-60, 60] as [number, number], Y: [-40, 40] as [number, number], Z: [-10, 0] as [number, number] };
    const path: [Pt, Pt][] = [];
    for (let k = 0; k < 13000; k++) { const y = -36 + (k % 130) * 0.55; const x = -50 + (k % 7) * 3; path.push([[x, y, -3 - (k % 5) * 0.2], [x + 25, y + 0.3, -3 - (k % 5) * 0.2]]); }
    const seg = segs(path);
    for (const cells of [2048, 4096]) {
      const rr = 120 / (cells - 1);
      const g = new GpuZMapStock(renderer, big, rr);
      const t0 = performance.now();
      g.cutRange(seg, [tool], 0, seg.count);
      g.cutter.read();
      (out as Record<string, unknown>)['perf' + cells] = { ms: Math.round(performance.now() - t0), nx: g.nx, ny: g.ny };
      g.dispose();
    }
  }
  // 급속 선분 질의: 소재 밖(안 낮춤) / 소재를 파고듦(낮춤)
  const tool = toolShapeFromValues(kinds.flat!)!;
  const g = new GpuZMapStock(renderer, bounds, res);
  const seg = segs([[[-12, 0, 5], [12, 0, 5], true], [[-12, 0, -4], [12, 0, -4], true], [[-12, 0, -4], [12, 0, -4], true]]);
  g.cutRange(seg, [tool], 0, 3);
  await g.settle();
  out.rapid = g.rapidWarnings.map((w) => w.seq);
  g.dispose();
} catch (e) {
  out.error = String((e as Error).stack ?? e);
}
})();
(window as unknown as { __gpuCheck: unknown }).__gpuCheck = out;
