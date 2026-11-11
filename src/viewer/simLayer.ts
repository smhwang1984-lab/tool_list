// 가공 형상(소재) 층 — 계산은 Web Worker(SimEngine)에서 하고, 여기서는 결과 메시를 화면(THREE)에 올린다.
// Worker 를 못 만드는 환경이면 같은 엔진을 메인 스레드에서 돌린다.
import * as THREE from 'three';
import type { SimProgram } from '../sim/segments';
import type { Bounds } from '../sim/stock';
import type { LatheBounds, SectionMode } from '../sim/latheStock';
import type { LatheProgram } from '../sim/latheSegments';
import { SimEngine, type EngineStatus, type InMsg, type MeshData, type OutMsg, type SimSource } from '../sim/simEngine';
import { writeStlBinary } from '../sim/stl';

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
  /** 계산이 목표 위치를 아직 못 따라온 상태 (재생을 잠깐 기다리게 하는 용도) */
  lagging(): boolean;
  dispose(): void;
}

/** pct: 0~1, busy=false 이면 끝난 것 */
export type SimProgress = (busy: boolean, pct: number) => void;

const EMPTY: EngineStatus = { hasStock: false, busy: false, cells: 0, nx: 0, ny: 0, nz: 1, resolution: 0, cutSegments: 0, rapidLines: [], ack: 0 };

/** 소재 범위가 지금 프로그램 종류에 맞아 소재를 만들 수 있나 (SimEngine.makeStock 의 null 조건과 같다) */
function canMake(program: SimProgram | LatheProgram | null, bounds: Bounds | LatheBounds | null): boolean {
  if (!bounds) return false;
  const lathe = program?.engine === 'lathe' || program?.engine === 'lathe3d';
  return lathe ? !('X' in bounds) : 'X' in bounds;
}

export function createSimLayer(parent: THREE.Object3D, onChange: () => void, onProgress: SimProgress = () => {}): SimLayer {
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

  const onMessage = (m: OutMsg): void => {
    if (m.t === 'progress') { onProgress(m.busy, m.pct); return; }
    remote = m.status;
    if (m.t === 'mesh') {
      if (m.mesh && enabled) showMesh(m.mesh);
      else { disposeMesh(); group.visible = false; }
    }
    onChange();
  };

  // Worker 로 계산한다. 못 만들면(오래된 WebView 등) 같은 엔진을 메인 스레드에서 돌린다.
  let send: (m: InMsg) => void;
  let terminate = (): void => {};
  try {
    const worker = new Worker(new URL('../sim/simWorker.ts', import.meta.url), { type: 'module' });
    worker.onmessage = (e: MessageEvent<OutMsg>) => onMessage(e.data);
    worker.onerror = () => { /* 계산 오류가 화면을 멈추지 않게 한다 */ };
    send = (m) => worker.postMessage(m);
    terminate = () => worker.terminate();
  } catch {
    const engine = new SimEngine((m) => onMessage(m));
    send = (m) => engine.handle(m);
  }

  return {
    setProgram(p, source) {
      program = p;
      if (bounds && !canMake(program, bounds)) enabled = false;
      send({ t: 'program', source });
    },
    setStock(b, resolution, on) {
      bounds = b;
      enabled = on && canMake(program, b);
      if (!canMake(program, b)) { disposeMesh(); group.visible = false; }
      send({ t: 'stock', bounds: b, resolution, enabled: on });
    },
    setEnabled(on) {
      enabled = on && canMake(program, bounds);
      group.visible = enabled;
      send({ t: 'enabled', on });
      onChange();
    },
    setLive(on) { live = on; send({ t: 'live', on }); },
    setSection(m) { send({ t: 'section', m }); },
    setTarget(seq, show = false) { send({ t: 'target', seq, show, id: ++sentId }); },
    lagging: () => enabled && canMake(program, bounds) && remote.ack !== sentId,
    status() {
      const engine = (program?.engine ?? 'zmap') as SimStatus['engine'];
      return {
        enabled, live, busy: remote.busy, cells: remote.cells, nx: remote.nx, ny: remote.ny, nz: remote.nz, engine,
        resolution: remote.resolution, cutSegments: remote.cutSegments, totalSegments: program?.seg.count ?? 0,
        tilted: program?.tilted ?? 0, excluded: program?.excluded ?? [], noToolMoves: program?.noToolMoves ?? 0,
        rapidLines: remote.rapidLines, hasStock: canMake(program, bounds),
      };
    },
    hasStock: () => canMake(program, bounds),
    exportStl() {
      if (!mesh || !enabled) return null;
      const pos = mesh.geometry.getAttribute('position');
      const idx = mesh.geometry.getIndex();
      if (!idx) return null;
      return writeStlBinary(pos.array as Float32Array, idx.array as Uint32Array);
    },
    dispose() { terminate(); disposeMesh(); parent.remove(group); },
  };
}
