// 가공 형상 계산 엔진 — THREE 에 의존하지 않는다. Web Worker 안에서(못 쓰는 환경에서는 메인 스레드에서) 돈다.
// 절삭 진행(pump)·스냅샷·메시 생성은 예전 simLayer 의 로직 그대로다.
import type { ToolpathResult } from '../core/toolpath';
import type { ToolGeometry } from '../core/latheInsertSpec';
import { toolColorForIndex } from '../viewer/segments';
import { buildSimMesh, finishMesh, SIM_DISPLAY_GRID_MAX_SAFE } from './mesh';
import { buildSimProgram, type SimProgram } from './segments';
import { autoResolution, type Bounds } from './stock';
import type { ToolValues } from './toolShape';
import { autoResolution3d, clampResolution3d, VoxelStock } from './voxel';
import { buildVoxelMesh } from './voxelMesh';
import { SIM_CHUNK_SEGMENTS, ZMapStock } from './zmap';
import { GPU_AUTO_CELLS, resolutionForCells } from './gpuCells';
import { ZOOM_MIN_RESOLUTION } from './zoomRegion';
import { buildLatheMesh, LatheStock, latheAutoResolution, type LatheBounds, type SectionMode } from './latheStock';
import { buildTurnMillMesh, TurnMillStock, turnmillVoxelResolution } from './turnMillStock';
import { buildLatheProgram, type LatheProgram } from './latheSegments';
import type { LatheTool } from './latheTool';

const SNAPSHOT_MEMORY_BYTES = 200 * 1024 * 1024;
const LIVE_MESH_INTERVAL_MS = 120;

/** 프로그램을 엔진 안에서 다시 만들기 위한 입력 (구조적 복제가 되는 값만) */
export type SimSource =
  | { kind: 'mill'; res: ToolpathResult; shapes: Map<string, ToolValues> }
  | { kind: 'lathe'; res: ToolpathResult; geometry: Record<string, ToolGeometry> };

export interface MeshData { positions: Float32Array; colors: Float32Array; indices: Uint32Array; edges: Float32Array }

/** GPU 소재(zmapGpu.GpuZMapStock)가 엔진에 보여 주는 모양 — 엔진은 three 를 가져오지 않는다 */
export interface GpuStockLike extends ZMapStock {
  readonly isGpu: true;
  readonly chunk: number;
  settle(): Promise<void>;
  dispose(): void;
}
const isGpuStock = (s: unknown): s is GpuStockLike => !!s && (s as { isGpu?: boolean }).isGpu === true;
/** GPU 소재를 만든다. 못 만들면 null(엔진은 기본 엔진으로 간다). 메인 스레드 엔진만 받는다. */
export type GpuStockFactory = (bounds: Bounds, resolution: number) => GpuStockLike | null;

export interface EngineStatus {
  hasStock: boolean; busy: boolean; cells: number; nx: number; ny: number; nz: number; resolution: number;
  cutSegments: number; rapidLines: number[];
  /** 고해상도 엔진(GPU)으로 깎고 있나 */
  gpu: boolean;
  /** 고해상도 엔진을 요청했지만 못 써서 기본 엔진으로 갔을 때의 이유(아니면 빈 글자) */
  gpuFallback: string;
  /** 마지막으로 목표까지 다 깎은 target 요청 번호 (재생이 계산을 기다리게 하는 용도) */
  ack: number;
}

export type InMsg =
  | { t: 'program'; source: SimSource | null }
  | { t: 'stock'; bounds: Bounds | LatheBounds | null; resolution: number | null; enabled: boolean; gpu?: { cells: number | null; zoom?: boolean } | null }
  | { t: 'enabled'; on: boolean }
  | { t: 'live'; on: boolean }
  | { t: 'section'; m: SectionMode }
  | { t: 'target'; seq: number | null; show: boolean; id: number };

export type OutMsg =
  /** gpu: GPU 소재를 화면 층이 직접 그린다(mesh 는 null) */
  | { t: 'mesh'; mesh: MeshData | null; status: EngineStatus; gpu?: GpuStockLike }
  | { t: 'status'; status: EngineStatus }
  | { t: 'progress'; busy: boolean; pct: number };

type AnyStock = ZMapStock | VoxelStock | LatheStock | TurnMillStock;
type Post = (m: OutMsg, transfer?: Transferable[]) => void;

export class SimEngine {
  private program: SimProgram | LatheProgram | null = null;
  private stock: AnyStock | null = null;
  private stockBounds: Bounds | LatheBounds | null = null;
  private stockResolution: number | null = null;
  private gpuRequest: { cells: number | null; zoom?: boolean } | null = null;
  private gpuFallback = '';
  private enabled = false;
  private section: SectionMode = '3q';
  private live = false;
  private cutIdx = 0;
  private target: number | null = null;
  private running = false;
  private showProgress = false;
  private lastYield = 0;
  private dirty = false;
  private hasMesh = false;
  private lastMesh = 0;
  private snapshots = new Map<number, unknown>();
  private snapBytes = 0;
  private targetId = 0;
  private ackId = 0;

  constructor(private readonly post: Post, private readonly gpuFactory: GpuStockFactory | null = null) {}

  handle(m: InMsg): void {
    switch (m.t) {
      case 'program': this.setProgram(m.source); break;
      case 'stock': this.setStock(m.bounds, m.resolution, m.enabled, m.gpu ?? null); break;
      case 'enabled': this.setEnabled(m.on); break;
      case 'live': this.live = m.on; break;
      case 'section':
        if (m.m !== this.section) { this.section = m.m; if (this.stock && this.enabled && !this.running) this.refreshMesh(); }
        break;
      case 'target': this.setTarget(m.seq, m.show, m.id); break;
    }
  }

  private makeStock(): AnyStock | null {
    const program = this.program, bounds = this.stockBounds, res = this.stockResolution;
    if (!bounds) return null;
    if (program?.engine === 'lathe3d') {
      const lb = bounds as LatheBounds;
      if ('X' in lb) return null;
      return new TurnMillStock(lb, res === null ? latheAutoResolution(lb) : res, turnmillVoxelResolution(lb));
    }
    if (program?.engine === 'lathe') {
      const lb = bounds as LatheBounds;
      return new LatheStock(lb, res === null ? latheAutoResolution(lb) : res);
    }
    const sb = bounds as Bounds;
    if (!('X' in sb)) return null; // 선반 소재 사양인데 밀링 프로그램: 만들지 않는다
    if (program?.engine === 'voxel') return new VoxelStock(sb, res === null ? autoResolution3d(sb) : clampResolution3d(sb, res));
    if (this.gpuRequest) {
      const gs = this.gpuFactory?.(sb, resolutionForCells(sb, this.gpuRequest.cells ?? GPU_AUTO_CELLS, this.gpuRequest.zoom ? ZOOM_MIN_RESOLUTION : undefined)) ?? null;
      if (gs) { this.gpuFallback = ''; return gs; }
      this.gpuFallback = this.gpuFactory ? '이 기기에서 GPU를 쓸 수 없습니다' : '이 계산 경로는 GPU를 쓰지 않습니다';
    }
    return new ZMapStock(sb, res === null ? autoResolution(sb, 1_000_000, true) : res);
  }

  private static engineOf(s: AnyStock | null): string {
    return s instanceof TurnMillStock ? 'lathe3d' : s instanceof LatheStock ? 'lathe' : s instanceof VoxelStock ? 'voxel' : s ? 'zmap' : '';
  }

  private stockMatches(): boolean { return !!this.stock && SimEngine.engineOf(this.stock) === (this.program?.engine ?? 'zmap'); }

  private status(): EngineStatus {
    const s = this.stock;
    return {
      hasStock: !!s, busy: this.running, cells: s?.cellCount() ?? 0, nx: s?.nx ?? 0, ny: s?.ny ?? 0,
      nz: s instanceof VoxelStock || s instanceof TurnMillStock ? s.nz : 1, resolution: s?.resolution ?? 0, cutSegments: this.cutIdx,
      ack: this.ackId, gpu: isGpuStock(s), gpuFallback: this.gpuFallback,
      rapidLines: s ? [...new Set(s.rapidWarnings.flatMap((w) => (w.src !== null ? [w.src] : [])))].sort((a, b) => a - b) : [],
    };
  }

  private postStatus(): void { this.post({ t: 'status', status: this.status() }); }

  private refreshMesh(): void {
    const stock = this.stock;
    if (!stock || !this.enabled) { this.hasMesh = false; this.post({ t: 'mesh', mesh: null, status: this.status() }); return; }
    const colorOf = (id: number): readonly [number, number, number] => toolColorForIndex(id);
    if (isGpuStock(stock)) {
      this.hasMesh = true;
      this.lastMesh = performance.now();
      this.dirty = false;
      this.post({ t: 'mesh', mesh: null, gpu: stock, status: this.status() });
      return;
    }
    const live = this.live;
    let m: MeshData;
    if (stock instanceof TurnMillStock) m = buildTurnMillMesh(stock, colorOf, live ? 50_000 : 150_000, this.section);
    else if (stock instanceof LatheStock) m = buildLatheMesh(stock, colorOf, live ? 300 : 500, this.section);
    else if (stock instanceof VoxelStock) {
      const vm = buildVoxelMesh(stock, live ? 50_000 : 150_000, true);
      const fin = finishMesh(vm.positions, vm.cid, vm.faces, colorOf);
      m = { ...fin, edges: vm.edges };
    } else m = buildSimMesh(stock, colorOf, SIM_DISPLAY_GRID_MAX_SAFE, true);
    this.hasMesh = true;
    this.lastMesh = performance.now();
    this.dirty = false;
    this.post({ t: 'mesh', mesh: m, status: this.status() }, [m.positions.buffer, m.colors.buffer, m.indices.buffer, m.edges.buffer] as Transferable[]);
  }

  /** 엔진이 쥔 GPU 자원을 놓는다 */
  release(): void { this.disposeStock(); this.stock = null; }

  private disposeStock(): void { if (isGpuStock(this.stock)) this.stock.dispose(); }

  /** GPU 소재가 계산 도중 실패했을 때(공구 형상을 모름·문맥 손실 등) 기본 엔진으로 처음부터 다시 한다 */
  private fallBackToCpu(why: string): void {
    this.disposeStock();
    this.gpuRequest = null;
    this.stock = this.makeStock();
    this.gpuFallback = why;
    this.resetState();
    this.dirty = true;
  }

  private resetState(): void {
    this.snapshots.clear();
    this.snapBytes = 0;
    this.cutIdx = 0;
    this.stock?.reset();
  }

  private targetIndex(): number {
    if (!this.program || this.target === null) return 0;
    const s = this.program.seg.seq1;
    let lo = 0, hi = this.program.seg.count;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (s[mid]! <= this.target) lo = mid + 1; else hi = mid; }
    return lo;
  }

  private setProgram(source: SimSource | null): void {
    this.program = !source ? null : source.kind === 'lathe' ? buildLatheProgram(source.res, source.geometry) : buildSimProgram(source.res, source.shapes);
    if (this.stockBounds && !this.stockMatches()) { this.disposeStock(); this.stock = this.makeStock(); this.enabled = this.enabled && !!this.stock; }
    if (this.stock) this.resetState();
    if (this.enabled) void this.pump();
    else this.postStatus();
  }

  private setStock(bounds: Bounds | LatheBounds | null, resolution: number | null, on: boolean, gpu: { cells: number | null; zoom?: boolean } | null): void {
    this.stockBounds = bounds;
    this.stockResolution = resolution;
    this.gpuRequest = gpu;
    this.gpuFallback = '';
    this.disposeStock();
    this.stock = this.makeStock();
    this.resetState();
    this.enabled = on && !!this.stock;
    if (!this.stock) { this.hasMesh = false; this.post({ t: 'mesh', mesh: null, status: this.status() }); return; }
    this.refreshMesh();
    void this.pump();
  }

  private setEnabled(on: boolean): void {
    this.enabled = on && !!this.stock;
    if (!this.enabled) { this.post({ t: 'mesh', mesh: null, status: this.status() }); return; }
    void this.pump();
  }

  private setTarget(seq: number | null, show: boolean, id: number): void {
    this.targetId = id;
    if (show && this.enabled) this.showProgress = true;
    if (this.target === seq && !show) { if (!this.running) { this.ackId = id; this.postStatus(); } return; }
    this.target = seq;
    if (this.enabled) void this.pump();
    else { this.ackId = id; this.postStatus(); }
  }

  private async pump(): Promise<void> {
    if (this.running) return;
    this.running = true;
    let runFrom = this.cutIdx;
    this.lastYield = performance.now();
    try {
     for (;;) {
      while (this.stock && this.program && this.enabled) {
        const stock = this.stock, program = this.program;
        const want = this.targetIndex();
        if (want < this.cutIdx) runFrom = 0;
        if (want < this.cutIdx) {
          // 뒤로: 가장 가까운 스냅샷에서 다시 시작
          let best = -1;
          for (const pos of this.snapshots.keys()) if (pos <= want && pos > best) best = pos;
          if (best >= 0) { (stock as { restore(s: unknown): void }).restore(this.snapshots.get(best)); this.cutIdx = best; } else { stock.reset(); this.cutIdx = 0; }
          this.dirty = true;
        }
        if (this.cutIdx === want) break;
        const snapAt = program.snapPositions;
        const bytes = stock.cellCount() * (stock instanceof VoxelStock || stock instanceof LatheStock || stock instanceof TurnMillStock ? 2 : 6);
        if (!isGpuStock(stock) && snapAt.includes(this.cutIdx) && !this.snapshots.has(this.cutIdx) && this.snapBytes + bytes <= SNAPSHOT_MEMORY_BYTES) {
          this.snapshots.set(this.cutIdx, stock.snapshot());
          this.snapBytes += bytes;
        }
        // 3D 복셀·턴밀은 한 선분이 무거워 작게 나눈다(메시지를 받을 틈을 주기 위해서이기도 하다)
        const chunk = stock instanceof VoxelStock || stock instanceof TurnMillStock ? 150 : isGpuStock(stock) ? stock.chunk : SIM_CHUNK_SEGMENTS;
        let end = Math.min(want, this.cutIdx + chunk);
        for (const pos of snapAt) if (pos > this.cutIdx && pos < end) { end = pos; break; }
        const from = this.cutIdx;
        if (stock instanceof TurnMillStock) stock.cutRange(program as LatheProgram, from, end);
        else if (stock instanceof LatheStock) stock.cutRange(program.seg, program.tools as (LatheTool | null)[], from, end, { pitch: (program as LatheProgram).threadPitch, height: (program as LatheProgram).threadHeight });
        else if (stock instanceof VoxelStock) stock.cutRange(program.seg, program.tools as never, (program as SimProgram).axes0, (program as SimProgram).axes1, from, end);
        else {
          try { stock.cutRange(program.seg, program.tools as never, from, end); }
          catch (e) {
            if (!isGpuStock(stock)) throw e;
            this.fallBackToCpu((e as Error).message);
            runFrom = 0;
            continue;
          }
        }
        this.cutIdx = end;
        this.dirty = true;
        const nowMs = performance.now();
        if ((this.live || this.showProgress) && nowMs - this.lastMesh > (stock instanceof TurnMillStock ? 1500 : this.showProgress ? 350 : LIVE_MESH_INTERVAL_MS)) this.refreshMesh();
        // 30ms 마다 한 번 양보해 새 요청(목표 변경 등)을 받고 진행률을 알린다
        if (this.cutIdx !== want && nowMs - this.lastYield > 30) {
          if (this.showProgress) this.post({ t: 'progress', busy: true, pct: Math.min(1, (this.cutIdx - runFrom) / Math.max(1, want - runFrom)) });
          await new Promise<void>((r) => setTimeout(r, 0));
          this.lastYield = performance.now();
        }
      }
      // GPU 급속 선분 질의는 작업이 끝난 뒤에야 결과가 나온다 — 다 모일 때까지 기다린다
      const last = this.stock;
      if (isGpuStock(last)) { try { await last.settle(); } catch { /* 문맥이 사라졌으면 경고 없이 넘어간다 */ } }
      // 기다리는 사이 목표가 바뀌었으면(이 동안 들어온 요청은 running 때문에 무시됐다) 이어서 깎는다
      if (!this.stock || !this.program || !this.enabled || this.cutIdx === this.targetIndex()) break;
     }
    } finally {
      this.running = false;
      this.ackId = this.targetId;
    }
    if (this.showProgress) { this.showProgress = false; this.post({ t: 'progress', busy: false, pct: 1 }); }
    if (this.dirty || !this.hasMesh) this.refreshMesh();
    else this.postStatus();
  }
}
