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

export interface EngineStatus {
  hasStock: boolean; busy: boolean; cells: number; nx: number; ny: number; nz: number; resolution: number;
  cutSegments: number; rapidLines: number[];
}

export type InMsg =
  | { t: 'program'; source: SimSource | null }
  | { t: 'stock'; bounds: Bounds | LatheBounds | null; resolution: number | null; enabled: boolean }
  | { t: 'enabled'; on: boolean }
  | { t: 'live'; on: boolean }
  | { t: 'section'; m: SectionMode }
  | { t: 'target'; seq: number | null; show: boolean };

export type OutMsg =
  | { t: 'mesh'; mesh: MeshData | null; status: EngineStatus }
  | { t: 'status'; status: EngineStatus }
  | { t: 'progress'; busy: boolean; pct: number };

type AnyStock = ZMapStock | VoxelStock | LatheStock | TurnMillStock;
type Post = (m: OutMsg, transfer?: Transferable[]) => void;

export class SimEngine {
  private program: SimProgram | LatheProgram | null = null;
  private stock: AnyStock | null = null;
  private stockBounds: Bounds | LatheBounds | null = null;
  private stockResolution: number | null = null;
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

  constructor(private readonly post: Post) {}

  handle(m: InMsg): void {
    switch (m.t) {
      case 'program': this.setProgram(m.source); break;
      case 'stock': this.setStock(m.bounds, m.resolution, m.enabled); break;
      case 'enabled': this.setEnabled(m.on); break;
      case 'live': this.live = m.on; break;
      case 'section':
        if (m.m !== this.section) { this.section = m.m; if (this.stock && this.enabled && !this.running) this.refreshMesh(); }
        break;
      case 'target': this.setTarget(m.seq, m.show); break;
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
      rapidLines: s ? [...new Set(s.rapidWarnings.flatMap((w) => (w.src !== null ? [w.src] : [])))].sort((a, b) => a - b) : [],
    };
  }

  private postStatus(): void { this.post({ t: 'status', status: this.status() }); }

  private refreshMesh(): void {
    const stock = this.stock;
    if (!stock || !this.enabled) { this.hasMesh = false; this.post({ t: 'mesh', mesh: null, status: this.status() }); return; }
    const colorOf = (id: number): readonly [number, number, number] => toolColorForIndex(id);
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
    if (this.stockBounds && !this.stockMatches()) { this.stock = this.makeStock(); this.enabled = this.enabled && !!this.stock; }
    if (this.stock) this.resetState();
    if (this.enabled) void this.pump();
    else this.postStatus();
  }

  private setStock(bounds: Bounds | LatheBounds | null, resolution: number | null, on: boolean): void {
    this.stockBounds = bounds;
    this.stockResolution = resolution;
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

  private setTarget(seq: number | null, show: boolean): void {
    if (show && this.enabled) this.showProgress = true;
    if (this.target === seq && !show) return;
    this.target = seq;
    if (this.enabled) void this.pump();
  }

  private async pump(): Promise<void> {
    if (this.running) return;
    this.running = true;
    let runFrom = this.cutIdx;
    this.lastYield = performance.now();
    try {
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
        if (snapAt.includes(this.cutIdx) && !this.snapshots.has(this.cutIdx) && this.snapBytes + bytes <= SNAPSHOT_MEMORY_BYTES) {
          this.snapshots.set(this.cutIdx, stock.snapshot());
          this.snapBytes += bytes;
        }
        // 3D 복셀·턴밀은 한 선분이 무거워 작게 나눈다(메시지를 받을 틈을 주기 위해서이기도 하다)
        const chunk = stock instanceof VoxelStock || stock instanceof TurnMillStock ? 150 : SIM_CHUNK_SEGMENTS;
        let end = Math.min(want, this.cutIdx + chunk);
        for (const pos of snapAt) if (pos > this.cutIdx && pos < end) { end = pos; break; }
        const from = this.cutIdx;
        if (stock instanceof TurnMillStock) stock.cutRange(program as LatheProgram, from, end);
        else if (stock instanceof LatheStock) stock.cutRange(program.seg, program.tools as (LatheTool | null)[], from, end, { pitch: (program as LatheProgram).threadPitch, height: (program as LatheProgram).threadHeight });
        else if (stock instanceof VoxelStock) stock.cutRange(program.seg, program.tools as never, (program as SimProgram).axes0, (program as SimProgram).axes1, from, end);
        else stock.cutRange(program.seg, program.tools as never, from, end);
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
    } finally {
      this.running = false;
    }
    if (this.showProgress) { this.showProgress = false; this.post({ t: 'progress', busy: false, pct: 1 }); }
    if (this.dirty || !this.hasMesh) this.refreshMesh();
    else this.postStatus();
  }
}
