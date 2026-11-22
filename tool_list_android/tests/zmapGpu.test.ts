// G4: 안드로이드 GPU 엔진 연결 시험 — 실제 GPU(WebGL)는 node 에서 못 쓰므로 가짜 GPU 소재로 엔진의 길 찾기만 확인한다.
// 실제 GPU 결과 정확도는 tools/gpu_check.mjs(Playwright, 브라우저의 WebGL2)가 기준 구현과 칸마다 비교한다.
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { processNcLines } from '../src/core/toolpath';
import { GPU_AUTO_CELLS, displayBlock, resolutionForCells } from '../src/sim/gpuCells';
import { SimEngine, type EngineStatus, type GpuStockLike, type OutMsg } from '../src/sim/simEngine';
import { buildSimProgram, toolpathBounds } from '../src/sim/segments';
import type { Bounds } from '../src/sim/stock';
import { type ToolValues } from '../src/sim/toolShape';
import { ZMapStock, type SimSegments } from '../src/sim/zmap';
import { buildPaletteData, stripIndex } from '../src/sim/zmapGpu';

const GOLD = join(__dirname, 'golden', 'zmap');
const FIX = join(__dirname, 'fixtures');
const TYPES = ['FLAT E/M', 'BALL E/M', 'FILLET E/M', 'DRILL', 'CHAMFER MILL'];

describe('GPU 격자 크기 계산 (원본 nc_sim_gpu.resolution_for_cells)', () => {
  it('긴 변이 cells 칸', () => {
    const b: Bounds = { X: [-60, 60], Y: [-40, 40], Z: [-10, 0] };
    expect(resolutionForCells(b, 4097)).toBeCloseTo(120 / 4096, 10);
    expect(resolutionForCells({ X: [0, 0.001], Y: [0, 0.001], Z: [-1, 0] }, 4096)).toBe(0.01); // 바닥 0.01mm
    expect(GPU_AUTO_CELLS).toBe(2048);
  });
  it('표시 격자는 상한을 넘으면 블록으로 줄인다', () => {
    expect(displayBlock(2048, 1000)).toEqual([1, 1]);
    expect(displayBlock(4096, 2731)).toEqual([2, 2]);
    expect(displayBlock(4096, 1000)).toEqual([2, 1]);
  });
});

describe('표시 보조', () => {
  it('띠 색인: 정점 번호 순서대로 삼각형(홀수 번째는 뒤집어 같은 쪽을 보게)', () => {
    expect([...stripIndex(4)]).toEqual([0, 1, 2, 2, 1, 3]);
    expect(stripIndex(2).length).toBe(0);
    expect(stripIndex(2 * 4096).length).toBe((2 * 4096 - 2) * 3);
  });
  it('팔레트는 기존 메시 경로와 같은 겉모습이 되도록 sRGB로 인코딩', () => {
    const d = buildPaletteData((id) => (id === 0 ? [1, 0, 0] : [0.5, 0.5, 0.5]), 2);
    expect([d[0], d[1], d[2], d[3]]).toEqual([1, 0, 0, 1]);
    expect(d[4]).toBeCloseTo(0.7354, 3);   // 선형 0.5 → sRGB 0.735
  });
});

// ── 엔진 연결 ──
function fakeShapeMap(): Map<string, ToolValues> {
  const map = new Map<string, ToolValues>();
  for (let n = 1; n < 100; n++) {
    const v: ToolValues = { type: TYPES[n % 5]!, D: 6 + (n % 5), FL: 20 + (n % 7), R: n % 5 === 2 ? 1 : null, SIG: n % 5 === 3 ? 118 : null, PL: n % 5 === 4 ? 0.5 : null, SO: null };
    for (const key of [`T${String(n).padStart(2, '0')}`, `T${n}`, String(n)]) map.set(key, v);
  }
  return map;
}
function decode(buf: Buffer): string {
  try { return new TextDecoder('utf-8', { fatal: true }).decode(buf).replace(/^﻿/, ''); } catch { return new TextDecoder('euc-kr').decode(buf); }
}
function loadSource() {
  const g = JSON.parse(readFileSync(join(GOLD, readdirSync(GOLD).find((f) => f.endsWith('.json') && !f.includes('__voxel'))!), 'utf-8'));
  const lines = decode(readFileSync(join(FIX, g.file))).split(/\r\n|\r|\n/).slice(0, 700);
  const res = processNcLines(lines, '3축 MCT (X Y Z)', {});
  const shapes = fakeShapeMap();
  const prog = buildSimProgram(res, shapes);
  return { res, shapes, prog, bounds: toolpathBounds(res, 2)! };
}

class FakeGpuStock extends ZMapStock implements GpuStockLike {
  readonly isGpu = true as const;
  readonly chunk = 700;
  ranges: [number, number][] = [];
  resets = 0;
  restores = 0;
  snapshots = 0;
  settled = 0;
  disposed = false;
  constructor(b: Bounds, res: number, private readonly failOn: number | null = null) { super(b, res, false); }
  override reset(): void { this.resets++; this.rapidWarnings = []; }
  override restore(): void { this.restores++; }
  override snapshot(): { h: Float32Array; c: Int16Array } { this.snapshots++; return { h: new Float32Array(0), c: new Int16Array(0) }; }
  override cutRange(_seg: SimSegments, _tools: unknown, from: number, to: number): void {
    if (this.failOn !== null && to > this.failOn) throw new Error('GPU 엔진이 모르는 공구 형상입니다(시험)');
    this.ranges.push([from, to]);
  }
  async settle(): Promise<void> { this.settled++; }
  dispose(): void { this.disposed = true; }
}

async function waitFor(cond: () => boolean, ms = 4000): Promise<void> {
  const t0 = Date.now();
  while (!cond()) {
    if (Date.now() - t0 > ms) throw new Error('시간 초과');
    await new Promise((r) => setTimeout(r, 2));
  }
}

function setup(makeStock: ((b: Bounds, r: number) => GpuStockLike | null) | null) {
  const { res, shapes, prog, bounds } = loadSource();
  const msgs: OutMsg[] = [];
  const made: { bounds: Bounds; resolution: number }[] = [];
  const engine = new SimEngine((m) => msgs.push(m), makeStock ? (b, r) => { made.push({ bounds: b, resolution: r }); return makeStock(b, r); } : null);
  engine.handle({ t: 'program', source: { kind: 'mill', res, shapes } });
  const last = (): EngineStatus => [...msgs].reverse().find((m) => m.t !== 'progress')!.status as EngineStatus;
  let id = 0;
  const goto = async (seq: number | null): Promise<void> => {
    const my = ++id;
    engine.handle({ t: 'target', seq, show: false, id: my });
    await waitFor(() => last().ack === my && !last().busy);
  };
  return { engine, msgs, made, prog, bounds, last, goto };
}

describe('SimEngine + GPU 소재(가짜)', () => {
  it('gpu 요청이면 GPU 소재로 깎고, 표시는 소재를 그대로 넘긴다(메시를 만들지 않는다)', async () => {
    let stock!: FakeGpuStock;
    const { engine, msgs, made, prog, bounds, last, goto } = setup((b, r) => (stock = new FakeGpuStock(b, r)));
    engine.handle({ t: 'stock', bounds, resolution: null, enabled: true, gpu: { cells: 512 } });
    await goto(prog.seg.seq1[prog.seg.count - 1]!);
    expect(made).toHaveLength(1);
    expect(made[0]!.resolution).toBeCloseTo(resolutionForCells(bounds, 512), 10);
    // 선분 전부를 순서대로, 소재가 정한 크기(700)로 나눠 깎았다
    expect(stock.ranges[0]![0]).toBe(0);
    expect(stock.ranges.at(-1)![1]).toBe(prog.seg.count);
    for (let i = 1; i < stock.ranges.length; i++) expect(stock.ranges[i]![0]).toBe(stock.ranges[i - 1]![1]);
    expect(Math.max(...stock.ranges.map(([a, b]) => b - a))).toBeLessThanOrEqual(700);
    expect(stock.settled).toBeGreaterThan(0);
    const mesh = [...msgs].reverse().find((m) => m.t === 'mesh');
    expect(mesh && mesh.t === 'mesh' && mesh.gpu === stock && mesh.mesh === null).toBe(true);
    expect(last().gpu).toBe(true);
    expect(last().gpuFallback).toBe('');
    expect(last().cutSegments).toBe(prog.seg.count);
  });

  it('자동은 GPU_AUTO_CELLS 칸', async () => {
    const { engine, made, prog, bounds, goto } = setup((b, r) => new FakeGpuStock(b, r));
    engine.handle({ t: 'stock', bounds, resolution: null, enabled: true, gpu: { cells: null } });
    await goto(prog.seg.seq1[10]!);
    expect(made[0]!.resolution).toBeCloseTo(resolutionForCells(bounds, GPU_AUTO_CELLS), 10);
  });

  it('되감기는 스냅샷 없이 처음부터 다시 깎는다', async () => {
    let stock!: FakeGpuStock;
    const { engine, prog, bounds, last, goto } = setup((b, r) => (stock = new FakeGpuStock(b, r)));
    engine.handle({ t: 'stock', bounds, resolution: null, enabled: true, gpu: { cells: 512 } });
    await goto(prog.seg.seq1[prog.seg.count - 1]!);
    const before = stock.resets;
    await goto(prog.seg.seq1[Math.floor(prog.seg.count / 2)]!);
    expect(stock.resets).toBeGreaterThan(before);
    expect(stock.snapshots).toBe(0);
    expect(stock.restores).toBe(0);
    expect(last().cutSegments).toBeLessThan(prog.seg.count);
  });

  it('GPU 소재를 못 만들면 기본 엔진으로 가고 이유를 알린다', async () => {
    const { engine, msgs, prog, bounds, last, goto } = setup(() => null);
    engine.handle({ t: 'stock', bounds, resolution: null, enabled: true, gpu: { cells: 512 } });
    await goto(prog.seg.seq1[20]!);
    expect(last().gpu).toBe(false);
    expect(last().gpuFallback).not.toBe('');
    const mesh = [...msgs].reverse().find((m) => m.t === 'mesh');
    expect(mesh && mesh.t === 'mesh' && mesh.mesh !== null && !mesh.gpu).toBe(true);
  });

  it('GPU 경로가 없는 엔진(Worker)은 gpu 요청을 받아도 기본 엔진으로 간다', async () => {
    const { engine, prog, bounds, last, goto } = setup(null);
    engine.handle({ t: 'stock', bounds, resolution: null, enabled: true, gpu: { cells: 512 } });
    await goto(prog.seg.seq1[20]!);
    expect(last().gpu).toBe(false);
    expect(last().gpuFallback).toContain('GPU');
  });

  it('깎는 도중 GPU가 실패하면 기본 엔진으로 처음부터 다시 깎는다', async () => {
    let stock!: FakeGpuStock;
    const { engine, prog, bounds, last, goto } = setup((b, r) => (stock = new FakeGpuStock(b, r, 40)));
    engine.handle({ t: 'stock', bounds, resolution: null, enabled: true, gpu: { cells: 512 } });
    await goto(prog.seg.seq1[prog.seg.count - 1]!);
    expect(stock.disposed).toBe(true);
    expect(last().gpu).toBe(false);
    expect(last().gpuFallback).toContain('모르는 공구');
    expect(last().cutSegments).toBe(prog.seg.count);
  });

  it('소재를 바꾸거나 놓으면 GPU 자원을 해제한다', async () => {
    const made: FakeGpuStock[] = [];
    const { engine, prog, bounds, goto } = setup((b, r) => { const s = new FakeGpuStock(b, r); made.push(s); return s; });
    engine.handle({ t: 'stock', bounds, resolution: null, enabled: true, gpu: { cells: 512 } });
    await goto(prog.seg.seq1[5]!);
    engine.handle({ t: 'stock', bounds, resolution: 0.5, enabled: true, gpu: null });
    expect(made[0]!.disposed).toBe(true);
    engine.handle({ t: 'stock', bounds, resolution: null, enabled: true, gpu: { cells: 512 } });
    engine.release();
    expect(made[1]!.disposed).toBe(true);
  });
});
