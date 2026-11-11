// 턴밀 소재 — 원본 nc_lathe_sim.TurnMillStock: 선삭(축대칭 격자, 진실 원천) + 턴밀(3D 복셀) 하이브리드
import { finishMesh } from './mesh';
import { LatheStock, type LatheBounds, type SectionMode } from './latheStock';
import type { LatheProgram } from './latheSegments';
import type { Bounds } from './stock';
import { autoResolution3d, UNCUT_COLOR, VoxelStock } from './voxel';
import { buildVoxelMesh } from './voxelMesh';
import { precisionParams } from './precision';


export interface TurnMillSnapshot { lathe: ReturnType<LatheStock['snapshot']>; voxel: ReturnType<VoxelStock['snapshot']>; milled: boolean }

export function turnmillVoxelBounds(b: LatheBounds): Bounds {
  const r = b.r[1];
  return { X: b.z, Y: [-r, r], Z: [-r, r] };
}
export function turnmillVoxelResolution(b: LatheBounds): number { const p = precisionParams(); return autoResolution3d(turnmillVoxelBounds(b), p.voxels, p.voxelMinRes); }

export class TurnMillStock {
  readonly lathe: LatheStock;
  readonly voxel: VoxelStock;
  readonly resolution: number;
  readonly isLathe = true;
  rapidWarnings: { src: number | null; seq: number | null }[] = [];
  milled = false;
  private dirty = true;
  private iz: Int32Array;
  private ir: Int32Array;
  private sectionCache: { key: string; view: VoxelStock } | null = null;
  section: SectionMode = '3q';

  constructor(b: LatheBounds, resolution: number, voxelResolution: number) {
    this.lathe = new LatheStock(b, resolution);
    this.voxel = new VoxelStock(turnmillVoxelBounds(b), voxelResolution);
    this.resolution = resolution;
    const a = this.lathe, v = this.voxel;
    this.iz = new Int32Array(v.nx);
    for (let i = 0; i < v.nx; i++) {
      const z = v.x0 + (i + 0.5) * v.step[0];
      const k = Math.floor((z - a.z0) / a.dz);
      this.iz[i] = k >= 0 && k < a.nz ? k : -1;
    }
    this.ir = new Int32Array(v.ny * v.nz);
    for (let j = 0; j < v.ny; j++) {
      const y = v.y0 + (j + 0.5) * v.step[1];
      for (let k = 0; k < v.nz; k++) {
        const zz = v.z0 + (k + 0.5) * v.step[2];
        const q = Math.floor(Math.hypot(y, zz) / a.dr);
        this.ir[j * v.nz + k] = q < a.nr ? q : -1;
      }
    }
    this.sync();
  }

  get nx(): number { return this.voxel.nx; }
  get ny(): number { return this.voxel.ny; }
  get nz(): number { return this.voxel.nz; }
  cellCount(): number { return this.lathe.cellCount() + this.voxel.cellCount(); }
  anyCut(): boolean { return this.lathe.anyCut() || this.milled; }

  /** 선삭 결과를 복셀에 반영한다 — 선삭으로 사라진 복셀을 지우고 그 공정 색을 남긴다 */
  sync(): void {
    if (!this.dirty) return;
    const a = this.lathe, v = this.voxel;
    const { ny, nz } = v;
    let changed = false;
    for (let i = 0; i < v.nx; i++) {
      const iz = this.iz[i]!;
      const base = i * ny * nz;
      for (let q = 0; q < ny * nz; q++) {
        if (v.occ[base + q] !== 1) continue;
        const ir = this.ir[q]!;
        if (iz >= 0 && ir >= 0) {
          const ci = iz * a.nr + ir;
          if (a.occ[ci] === 1) continue;
          v.occ[base + q] = 0; v.col[base + q] = a.col[ci]!;
        } else { v.occ[base + q] = 0; v.col[base + q] = UNCUT_COLOR; }
        changed = true;
      }
    }
    if (changed) { v.version++; this.sectionCache = null; }
    this.dirty = false;
  }

  reset(): void {
    this.lathe.reset(); this.voxel.reset();
    this.rapidWarnings = []; this.milled = false; this.dirty = true; this.sectionCache = null;
    this.sync();
  }
  snapshot(): TurnMillSnapshot { this.sync(); return { lathe: this.lathe.snapshot(), voxel: this.voxel.snapshot(), milled: this.milled }; }
  restore(s: TurnMillSnapshot): void {
    this.lathe.restore(s.lathe); this.voxel.restore(s.voxel); this.milled = s.milled; this.dirty = false; this.sectionCache = null;
  }

  /** seg[from, to) 를 순서대로: 선삭 선분은 축대칭 격자, 턴밀 선분은 복셀 */
  cutRange(p: LatheProgram, from: number, to: number): void {
    let a = from;
    while (a < to) {
      const mill = p.mill[a] === 1;
      let b = a + 1;
      while (b < to && (p.mill[b] === 1) === mill) b++;
      if (mill) {
        this.sync();
        let before = 0;
        const o = this.voxel.occ;
        for (let i = 0; i < o.length; i++) before += o[i]!;
        this.voxel.cutRange(p.seg, p.millTools, p.axes0, p.axes1, a, b);
        let after = 0;
        for (let i = 0; i < o.length; i++) after += o[i]!;
        if (after < before) { this.milled = true; this.sectionCache = null; }
        this.rapidWarnings.push(...this.voxel.rapidWarnings);
        this.voxel.rapidWarnings = [];
      } else {
        this.lathe.cutRange(p.seg, p.tools, a, b, { pitch: p.threadPitch, height: p.threadHeight });
        this.dirty = true;
        this.rapidWarnings.push(...this.lathe.rapidWarnings);
        this.lathe.rapidWarnings = [];
      }
      a = b;
    }
  }

  /** 표시용 복셀 메쉬 — 3/4 단면(앞쪽 사분면 y<0, z>0 을 비운 사본) */
  displayView(section: SectionMode = '3q'): VoxelStock {
    this.sync();
    const key = `${this.voxel.version}/${section}`;
    if (this.sectionCache?.key === key) return this.sectionCache.view;
    const v = this.voxel;
    if (section === 'full') { this.sectionCache = { key, view: v }; return v; }
    const view = Object.assign(Object.create(Object.getPrototypeOf(v)) as VoxelStock, v);
    view.occ = v.occ.slice();
    const { ny, nz } = v;
    for (let i = 0; i < v.nx; i++) for (let j = 0; j < ny; j++) {
      if (v.y0 + (j + 0.5) * v.step[1] >= 0) continue;
      for (let k = 0; k < nz; k++) if (section === 'half' || v.z0 + (k + 0.5) * v.step[2] > 0) view.occ[(i * ny + j) * nz + k] = 0;
    }
    this.sectionCache = { key, view };
    return view;
  }
}

export function buildTurnMillMesh(
  stock: TurnMillStock, colorOf: (id: number) => readonly [number, number, number], quadsMax: number, section: SectionMode = '3q',
): { positions: Float32Array; colors: Float32Array; indices: Uint32Array; edges: Float32Array } {
  const vm = buildVoxelMesh(stock.displayView(section), quadsMax, true);
  const fin = finishMesh(vm.positions, vm.cid, vm.faces, colorOf);
  return { ...fin, edges: vm.edges };
}
