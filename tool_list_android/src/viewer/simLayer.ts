// 가공 형상(소재) 층 — 계산은 Web Worker(SimEngine)에서 하고, 여기서는 결과 메시를 화면(THREE)에 올린다.
// Worker 를 못 만드는 환경이면 같은 엔진을 메인 스레드에서 돌린다.
import * as THREE from 'three';
import type { SimProgram } from '../sim/segments';
import type { Bounds } from '../sim/stock';
import type { LatheBounds, SectionMode } from '../sim/latheStock';
import type { LatheProgram } from '../sim/latheSegments';
import { SimEngine, type EngineStatus, type GpuStockLike, type InMsg, type MeshData, type OutMsg, type SimSource } from '../sim/simEngine';
import { writeStlBinary } from '../sim/stl';
import { clipZoomBounds, ZOOM_CELLS, ZOOM_CPU_CELLS, type ZoomRegion } from '../sim/zoomRegion';
import { resolutionForCells } from '../sim/gpuCells';
import { setGpuAvailability, type SimResolution } from '../sim/resolutionKeys';
import { buildSimMesh } from '../sim/mesh';
import { GpuSurface, GpuZMapStock, gpuProbe, type GpuProbe } from '../sim/zmapGpu';
import { toolColorForIndex } from './segments';

export type { SimSource } from '../sim/simEngine';

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
  /** 고해상도 엔진(GPU)으로 깎고 있나 / 요청했지만 못 써서 기본 엔진으로 간 이유 */
  gpu: boolean;
  gpuFallback: string;
  /** 확대 고정밀(보이는 영역만 더 작은 셀) 중인가 */
  zoom: boolean;
  cutSegments: number;
  totalSegments: number;
  tilted: number;
  excluded: string[];
  noToolMoves: number;
  rapidLines: number[];
  hasStock: boolean;
}

export interface SimLayer {
  /** p: 화면 쪽 요약(구간 수·제외 공구 등), source: 엔진이 같은 프로그램을 다시 만들 입력 */
  setProgram(p: SimProgram | LatheProgram | null, source: SimSource | null): void;
  /** resolution null = 기본 엔진 자동, 숫자 = 기본 엔진 셀 크기(mm), { gpu } = 고해상도 엔진(긴 변 칸 수, null이면 자동) */
  setStock(bounds: Bounds | LatheBounds | null, resolution: SimResolution, enabled: boolean): void;
  /** 확대 고정밀: region(XY)만 더 작은 셀로 다시 계산. 쓸 수 없으면(경사·5축·선반·소재 밖) false */
  setZoom(region: ZoomRegion | null): boolean;
  canZoom(): boolean;
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
  /** 계산이 목표 위치를 아직 못 따라온 상태 (재생을 잠깐 기다리게 하는 용도) */
  lagging(): boolean;
  dispose(): void;
}

/** pct: 0~1, busy=false 이면 끝난 것 */
export type SimProgress = (busy: boolean, pct: number) => void;

const EMPTY: EngineStatus = { hasStock: false, busy: false, cells: 0, nx: 0, ny: 0, nz: 1, resolution: 0, cutSegments: 0, rapidLines: [], gpu: false, gpuFallback: '', ack: 0 };

/** 소재 범위가 지금 프로그램 종류에 맞아 소재를 만들 수 있나 (SimEngine.makeStock 의 null 조건과 같다) */
function canMake(program: SimProgram | LatheProgram | null, bounds: Bounds | LatheBounds | null): boolean {
  if (!bounds) return false;
  const lathe = program?.engine === 'lathe' || program?.engine === 'lathe3d';
  return lathe ? !('X' in bounds) : 'X' in bounds;
}

/** 프로그램에 나오는 색 id 개수(팔레트 크기) */
function colorCountOf(program: SimProgram | LatheProgram | null): number {
  if (!program) return 1;
  let max = 0;
  const c = program.seg.color;
  for (let i = 0; i < program.seg.count; i++) if (c[i]! > max) max = c[i]!;
  return Math.min(max + 1, 4096);
}

export function createSimLayer(parent: THREE.Object3D, onChange: () => void, onProgress: SimProgress = () => {}, renderer: THREE.WebGLRenderer | null = null): SimLayer {
  const group = new THREE.Group();
  group.renderOrder = -1;
  parent.add(group);
  let mesh: THREE.Mesh | null = null;
  let edges: THREE.LineSegments | null = null;

  let program: SimProgram | LatheProgram | null = null;
  let bounds: Bounds | LatheBounds | null = null;
  let enabled = false;
  let live = false;
  let remote: EngineStatus = EMPTY;
  let sentId = 0;

  // 고해상도 엔진(GPU): 이 화면의 WebGL 문맥을 같이 써야 하므로 메인 스레드에서 돈다(기본 엔진은 Worker).
  const probe: GpuProbe | null = renderer ? gpuProbe(renderer) : null;
  setGpuAvailability(!!probe?.ok, probe ? probe.reason : 'WebGL 화면이 없습니다', probe?.renderer ?? '');
  let surface: GpuSurface | null = null;
  let gpuStock: GpuStockLike | null = null;
  let useGpu = false;
  let lastSource: SimSource | null = null;

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
  const hideGpu = (): void => { if (surface) surface.visible = false; gpuStock = null; };

  const showGpu = (stock: GpuStockLike): void => {
    disposeMesh();
    gpuStock = stock;
    if (!surface) { surface = new GpuSurface(); group.add(surface); }
    surface.visible = true;
    try { surface.update(stock as GpuZMapStock, toolColorForIndex, colorCountOf(program)); }
    catch { /* 그리기 실패는 화면만 비운다(다음 갱신에서 다시 시도) */ }
    group.visible = true;
  };

  const showMesh = (m: MeshData): void => {
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
    group.visible = true;
  };

  const onMessage = (m: OutMsg, from: 'cpu' | 'gpu'): void => {
    if ((from === 'gpu') !== useGpu) return;      // 지금 쓰지 않는 엔진의 늦은 메시지는 버린다
    if (m.t === 'progress') { onProgress(m.busy, m.pct); return; }
    remote = m.status;
    if (m.t === 'mesh') {
      if (m.gpu && enabled) { showGpu(m.gpu); }
      else if (m.mesh && enabled) { hideGpu(); showMesh(m.mesh); }
      else { disposeMesh(); hideGpu(); group.visible = false; }
    }
    onChange();
  };

  // Worker 로 계산한다. 못 만들면(오래된 WebView 등) 같은 엔진을 메인 스레드에서 돌린다.
  let sendCpu: (m: InMsg) => void;
  let terminate = (): void => {};
  try {
    const worker = new Worker(new URL('../sim/simWorker.ts', import.meta.url), { type: 'module' });
    worker.onmessage = (e: MessageEvent<OutMsg>) => onMessage(e.data, 'cpu');
    worker.onerror = () => { /* 계산 오류가 화면을 멈추지 않게 한다 */ };
    sendCpu = (m) => worker.postMessage(m);
    terminate = () => worker.terminate();
  } catch {
    const engine = new SimEngine((m) => onMessage(m, 'cpu'));
    sendCpu = (m) => engine.handle(m);
  }
  let gpuEngine: SimEngine | null = null;
  const gpuFactory = (b: Bounds, res: number): GpuStockLike | null => {
    if (!renderer || !probe?.ok) return null;
    try { return new GpuZMapStock(renderer, b, res); } catch { return null; }
  };
  const ensureGpuEngine = (): SimEngine => {
    if (!gpuEngine) {
      gpuEngine = new SimEngine((m) => onMessage(m, 'gpu'), gpuFactory);
      if (lastSource) gpuEngine.handle({ t: 'program', source: lastSource });
    }
    return gpuEngine;
  };
  /** 지금 쓰는 엔진으로 보낸다 */
  const send = (m: InMsg): void => { if (useGpu) ensureGpuEngine().handle(m); else sendCpu(m); };

  let req: { bounds: Bounds | LatheBounds | null; resolution: SimResolution; on: boolean } | null = null;
  let zoomed = false;
  const applyStock = (b: Bounds | LatheBounds | null, resolution: SimResolution, on: boolean, zoom: boolean): void => {
    bounds = b;
    enabled = on && canMake(program, b);
    if (!canMake(program, b)) { disposeMesh(); hideGpu(); group.visible = false; }
    const wantGpu = typeof resolution === 'object' && resolution !== null && !!probe?.ok && !!b && 'X' in b;
    if (wantGpu !== useGpu) {
      // 엔진이 바뀌면 쓰던 쪽 소재를 놓는다
      send({ t: 'stock', bounds: null, resolution: null, enabled: false });
      disposeMesh(); hideGpu();
      useGpu = wantGpu;
    }
    const cpuRes = typeof resolution === 'object' ? null : resolution;
    send({ t: 'stock', bounds: b, resolution: cpuRes, enabled: on, gpu: wantGpu ? { cells: (resolution as { gpu: number | null }).gpu, zoom, max: !zoom && !!(resolution as { max?: boolean }).max } : null });
  };

  return {
    setProgram(p, source) {
      program = p;
      lastSource = source;
      if (bounds && !canMake(program, bounds)) enabled = false;
      sendCpu({ t: 'program', source });          // 두 엔진 모두 같은 프로그램을 가진다(엔진을 바꿔도 다시 보낼 필요가 없게)
      gpuEngine?.handle({ t: 'program', source });
    },
    setStock(b, resolution, on) {
      req = { bounds: b, resolution, on };
      zoomed = false;
      applyStock(b, resolution, on, false);
    },
    canZoom: () => !!req && !!req.bounds && 'X' in req.bounds && program?.engine === 'zmap',
    setZoom(region) {
      if (!region) {
        if (!zoomed || !req) return false;
        zoomed = false;
        applyStock(req.bounds, req.resolution, req.on, false);
        return true;
      }
      if (!req || !req.bounds || !('X' in req.bounds) || program?.engine !== 'zmap') return false;
      const clipped = clipZoomBounds(req.bounds as Bounds, region);
      if (!clipped) return false;
      zoomed = true;
      // GPU가 되면 4096 칸(셀 0.002mm까지), 안 되면 기본 엔진 1200 칸
      const res: SimResolution = probe?.ok ? { gpu: ZOOM_CELLS } : resolutionForCells(clipped, ZOOM_CPU_CELLS, 0.01);
      applyStock(clipped, res, req.on, true);
      return true;
    },
    setEnabled(on) {
      enabled = on && canMake(program, bounds);
      group.visible = enabled;
      send({ t: 'enabled', on });
      onChange();
    },
    setLive(on) { live = on; sendCpu({ t: 'live', on }); gpuEngine?.handle({ t: 'live', on }); },
    setSection(m) { sendCpu({ t: 'section', m }); gpuEngine?.handle({ t: 'section', m }); },
    setTarget(seq, show = false) { send({ t: 'target', seq, show, id: ++sentId }); },
    lagging: () => enabled && canMake(program, bounds) && remote.ack !== sentId,
    status() {
      const engine = (program?.engine ?? 'zmap') as SimStatus['engine'];
      return {
        enabled, live, busy: remote.busy, cells: remote.cells, nx: remote.nx, ny: remote.ny, nz: remote.nz, engine,
        resolution: remote.resolution, gpu: remote.gpu, gpuFallback: remote.gpuFallback, zoom: zoomed, cutSegments: remote.cutSegments, totalSegments: program?.seg.count ?? 0,
        tilted: program?.tilted ?? 0, excluded: program?.excluded ?? [], noToolMoves: program?.noToolMoves ?? 0,
        rapidLines: remote.rapidLines, hasStock: canMake(program, bounds),
      };
    },
    hasStock: () => canMake(program, bounds),
    exportStl() {
      if (gpuStock && enabled && useGpu) {
        // GPU 상태를 읽어 와 기본 엔진과 같은 방식으로 메시로 만든다(STL은 표시보다 격자를 줄여 크기를 억제한다)
        (gpuStock as GpuZMapStock).sync();
        const m = buildSimMesh(gpuStock, toolColorForIndex, 1000, false);
        return writeStlBinary(m.positions, m.indices);
      }
      if (!mesh || !enabled) return null;
      const pos = mesh.geometry.getAttribute('position');
      const idx = mesh.geometry.getIndex();
      if (!idx) return null;
      return writeStlBinary(pos.array as Float32Array, idx.array as Uint32Array);
    },
    dispose() { terminate(); gpuEngine?.release(); surface?.dispose(); disposeMesh(); parent.remove(group); },
  };
}
