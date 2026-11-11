// 가공 형상(소재) 층 — 원본 NCViewerWidget 의 sim_* 상태 (_sim_advance_to_seq / 스냅샷 / 메시 갱신)
import * as THREE from 'three';
import { buildSimMesh, finishMesh, SIM_DISPLAY_GRID_MAX_SAFE } from '../sim/mesh';
import type { SimProgram } from '../sim/segments';
import { autoResolution, type Bounds } from '../sim/stock';
import { autoResolution3d, clampResolution3d, VoxelStock } from '../sim/voxel';
import { buildVoxelMesh } from '../sim/voxelMesh';
import { SIM_CHUNK_SEGMENTS, ZMapStock } from '../sim/zmap';
import { buildLatheMesh, LatheStock, latheAutoResolution, type LatheBounds, type SectionMode } from '../sim/latheStock';
import { buildTurnMillMesh, TurnMillStock, turnmillVoxelResolution } from '../sim/turnMillStock';
import type { LatheProgram } from '../sim/latheSegments';
import type { LatheTool } from '../sim/latheTool';
import { writeStlBinary } from '../sim/stl';
import { toolColorForIndex } from './segments';

const SNAPSHOT_MEMORY_BYTES = 200 * 1024 * 1024;
const LIVE_MESH_INTERVAL_MS = 120;

export interface SimStatus {
  enabled: boolean;
  live: boolean;
  busy: boolean;
  cells: number;
  nx: number;
  ny: number;
  nz: number;
  engine: 'zmap' | 'voxel' | 'lathe' | 'lathe3d';
  resolution: number;
  cutSegments: number;
  totalSegments: number;
  tilted: number;
  excluded: string[];
  noToolMoves: number;
  rapidLines: number[];
  hasStock: boolean;
}

export interface SimLayer {
  setProgram(p: SimProgram | LatheProgram | null): void;
  /** resolution null = 자동 */
  setStock(bounds: Bounds | LatheBounds | null, resolution: number | null, enabled: boolean): void;
  setEnabled(on: boolean): void;
  setLive(on: boolean): void;
  /** 선반 소재 단면: 3/4 · 1/2 · 원통(전체) */
  setSection(m: SectionMode): void;
  /** 지금 화면에 보이는 가공 형상을 바이너리 STL 로. 형상이 없으면 null */
  exportStl(): Uint8Array | null;
  /** 목표 seq 까지 깎는다(null 이면 아무 것도 안 깎은 상태) */
  setTarget(seq: number | null, showProgress?: boolean): void;
  status(): SimStatus;
  hasStock(): boolean;
  dispose(): void;
}

/** pct: 0~1, busy=false 이면 끝난 것 */
export type SimProgress = (busy: boolean, pct: number) => void;

export function createSimLayer(parent: THREE.Object3D, onChange: () => void, onProgress: SimProgress = () => {}): SimLayer {
  const group = new THREE.Group();
  group.renderOrder = -1;
  parent.add(group);
  let mesh: THREE.Mesh | null = null;
  let edges: THREE.LineSegments | null = null;

  let program: SimProgram | LatheProgram | null = null;
  type AnyStock = ZMapStock | VoxelStock | LatheStock | TurnMillStock;
  let stock: AnyStock | null = null;
  let stockBounds: Bounds | LatheBounds | null = null;
  let stockResolution: number | null = null;
  const makeStock = (): AnyStock | null => {
    if (!stockBounds) return null;
    if (program?.engine === 'lathe3d') {
      const lb = stockBounds as LatheBounds;
      if ('X' in lb) return null;
      return new TurnMillStock(lb, stockResolution === null ? latheAutoResolution(lb) : stockResolution, turnmillVoxelResolution(lb));
    }
    if (program?.engine === 'lathe') {
      const lb = stockBounds as LatheBounds;
      return new LatheStock(lb, stockResolution === null ? latheAutoResolution(lb) : stockResolution);
    }
    const sb = stockBounds as Bounds;
    if (!('X' in sb)) return null; // 선반 소재 사양인데 밀링 프로그램: 만들지 않는다
    if (program?.engine === 'voxel') {
      return new VoxelStock(sb, stockResolution === null ? autoResolution3d(sb) : clampResolution3d(sb, stockResolution));
    }
    return new ZMapStock(sb, stockResolution === null ? autoResolution(sb, 1_000_000, true) : stockResolution);
  };
  const engineOf = (s: AnyStock | null): string => (s instanceof TurnMillStock ? 'lathe3d' : s instanceof LatheStock ? 'lathe' : s instanceof VoxelStock ? 'voxel' : s ? 'zmap' : '');
  const stockMatches = (): boolean => !!stock && engineOf(stock) === (program?.engine ?? 'zmap');
  let enabled = false;
  let section: SectionMode = '3q';
  let live = false;
  let cutIdx = 0;
  let target: number | null = null;
  let running = false;
  let showProgress = false;
  let lastYield = 0;
  let dirty = false;
  let lastMesh = 0;
  const snapshots = new Map<number, ReturnType<AnyStock['snapshot']>>();
  let snapBytes = 0;

  const colorOf = (id: number): readonly [number, number, number] => toolColorForIndex(id);

  const disposeMesh = (): void => {
    for (const o of [mesh, edges]) {
      if (!o) continue;
      group.remove(o);
      o.geometry.dispose();
      (o.material as THREE.Material).dispose();
    }
    mesh = null;
    edges = null;
  };

  const refreshMesh = (): void => {
    if (!stock || !enabled) { disposeMesh(); group.visible = false; onChange(); return; }
    let m: { positions: Float32Array; colors: Float32Array; indices: Uint32Array; edges: Float32Array };
    if (stock instanceof TurnMillStock) {
      m = buildTurnMillMesh(stock, colorOf, live ? 50_000 : 150_000, section);
    } else if (stock instanceof LatheStock) {
      m = buildLatheMesh(stock, colorOf, live ? 300 : 500, section);
    } else if (stock instanceof VoxelStock) {
      const vm = buildVoxelMesh(stock, live ? 50_000 : 150_000, true);
      const fin = finishMesh(vm.positions, vm.cid, vm.faces, colorOf);
      m = { ...fin, edges: vm.edges };
    } else {
      m = buildSimMesh(stock, colorOf, SIM_DISPLAY_GRID_MAX_SAFE, true);
    }
    group.visible = true;
    const geo = new THREE.BufferGeometry();
    geo.setAttribute('position', new THREE.BufferAttribute(m.positions, 3));
    geo.setAttribute('color', new THREE.BufferAttribute(m.colors, 3));
    geo.setIndex(new THREE.BufferAttribute(m.indices, 1));
    const egeo = new THREE.BufferGeometry();
    egeo.setAttribute('position', new THREE.BufferAttribute(m.edges, 3));
    disposeMesh();
    mesh = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({
      vertexColors: true, side: THREE.DoubleSide, polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,
    }));
    edges = new THREE.LineSegments(egeo, new THREE.LineBasicMaterial({ color: new THREE.Color(0.16, 0.22, 0.32) }));
    group.add(mesh, edges);
    lastMesh = performance.now();
    dirty = false;
    onChange();
  };

  const yieldToUi = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

  const resetState = (): void => {
    snapshots.clear();
    snapBytes = 0;
    cutIdx = 0;
    stock?.reset();
  };

  const targetIndex = (): number => {
    if (!program || target === null) return 0;
    const s = program.seg.seq1;
    let lo = 0, hi = program.seg.count;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (s[mid]! <= target) lo = mid + 1; else hi = mid; }
    return lo;
  };

  async function pump(): Promise<void> {
    if (running) return;
    running = true;
    let runFrom = cutIdx;
    lastYield = performance.now();
    try {
      while (stock && program && enabled) {
        const want = targetIndex();
        if (want < cutIdx) runFrom = 0;
        if (want < cutIdx) {
          // 뒤로: 가장 가까운 스냅샷에서 다시 시작
          let best = -1;
          for (const pos of snapshots.keys()) if (pos <= want && pos > best) best = pos;
          if (best >= 0) { (stock as { restore(s: unknown): void }).restore(snapshots.get(best)); cutIdx = best; } else { stock.reset(); cutIdx = 0; }
          dirty = true;
        }
        if (cutIdx === want) break;
        const snapAt = program.snapPositions;
        const bytes = stock.cellCount() * (stock instanceof VoxelStock || stock instanceof LatheStock || stock instanceof TurnMillStock ? 2 : 6);
        if (snapAt.includes(cutIdx) && !snapshots.has(cutIdx) && snapBytes + bytes <= SNAPSHOT_MEMORY_BYTES) {
          snapshots.set(cutIdx, stock.snapshot());
          snapBytes += bytes;
        }
        // 3D 복셀·턴밀은 한 선분이 무거워 작게 나눠 화면이 멈추지 않게 한다
        const chunk = stock instanceof VoxelStock || stock instanceof TurnMillStock ? 150 : SIM_CHUNK_SEGMENTS;
        let end = Math.min(want, cutIdx + chunk);
        for (const pos of snapAt) if (pos > cutIdx && pos < end) { end = pos; break; }
        if (stock instanceof TurnMillStock) stock.cutRange(program as LatheProgram, cutIdx, end);
        else if (stock instanceof LatheStock) stock.cutRange(program.seg, program.tools as (LatheTool | null)[], cutIdx, end, { pitch: (program as LatheProgram).threadPitch, height: (program as LatheProgram).threadHeight });
        else if (stock instanceof VoxelStock) stock.cutRange(program.seg, program.tools as never, (program as SimProgram).axes0, (program as SimProgram).axes1, cutIdx, end);
        else stock.cutRange(program.seg, program.tools as never, cutIdx, end);
        cutIdx = end;
        dirty = true;
        const nowMs = performance.now();
        if ((live || showProgress) && nowMs - lastMesh > (stock instanceof TurnMillStock ? 1500 : showProgress ? 350 : LIVE_MESH_INTERVAL_MS)) refreshMesh();
        // 화면이 멈추지 않게 30ms 마다 한 번 양보하고 진행률을 알린다
        if (cutIdx !== want && nowMs - lastYield > 30) {
          if (showProgress) onProgress(true, Math.min(1, (cutIdx - runFrom) / Math.max(1, want - runFrom)));
          await yieldToUi();
          lastYield = performance.now();
        }
      }
    } finally {
      running = false;
    }
    if (showProgress) { showProgress = false; onProgress(false, 1); }
    if (dirty || !mesh) refreshMesh();
    else onChange();
  }

  return {
    setProgram(p) {
      program = p;
      if (stockBounds && !stockMatches()) { stock = makeStock(); enabled = enabled && !!stock; }
      if (stock) { resetState(); }
      if (enabled) void pump();
      else onChange();
    },
    setStock(bounds, resolution, on) {
      stockBounds = bounds;
      stockResolution = resolution;
      stock = makeStock();
      resetState();
      enabled = on && !!stock;
      if (!stock) { disposeMesh(); group.visible = false; onChange(); return; }
      refreshMesh();
      void pump();
    },
    setEnabled(on) {
      enabled = on && !!stock;
      if (!enabled) { group.visible = false; onChange(); return; }
      group.visible = true;
      void pump();
    },
    setLive(on) { live = on; },
    setSection(m) { if (m === section) return; section = m; if (stock && enabled && !running) refreshMesh(); },
    setTarget(seq, show = false) {
      if (show && enabled) showProgress = true;
      if (target === seq && !show) return;
      target = seq;
      if (enabled) void pump();
    },
    status() {
      return {
        enabled, live, busy: running, cells: stock?.cellCount() ?? 0, nx: stock?.nx ?? 0, ny: stock?.ny ?? 0,
        nz: stock instanceof VoxelStock || stock instanceof TurnMillStock ? stock.nz : 1, engine: (engineOf(stock) || 'zmap') as SimStatus['engine'],
        resolution: stock?.resolution ?? 0, cutSegments: cutIdx, totalSegments: program?.seg.count ?? 0,
        tilted: program?.tilted ?? 0, excluded: program?.excluded ?? [], noToolMoves: program?.noToolMoves ?? 0,
        rapidLines: stock ? [...new Set(stock.rapidWarnings.flatMap((w) => (w.src !== null ? [w.src] : [])))].sort((a, b) => a - b) : [],
        hasStock: !!stock,
      };
    },
    hasStock: () => !!stock,
    exportStl() {
      if (!mesh || !enabled) return null;
      const pos = mesh.geometry.getAttribute('position');
      const idx = mesh.geometry.getIndex();
      if (!idx) return null;
      return writeStlBinary(pos.array as Float32Array, idx.array as Uint32Array);
    },
    dispose() { disposeMesh(); parent.remove(group); },
  };
}
