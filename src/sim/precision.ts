// 가공 형상 정밀도 — 낮음/보통/높음/최고. "자동" 해상도와 표시 상한을 한꺼번에 정한다.
import { getPref, setPref } from '../platform/prefs';

export type Precision = 'low' | 'normal' | 'high' | 'max';
export const PRECISIONS: readonly Precision[] = ['low', 'normal', 'high', 'max'];
export const PRECISION_LABEL: Record<Precision, string> = { low: '낮음(빠름)', normal: '보통', high: '높음', max: '최고(느림·메모리 큼)' };

export interface PrecisionParams {
  /** 밀링 Z-map 자동 해상도의 목표 칸 수 */
  zmapCells: number;
  /** 밀링 Z-map 화면 격자 한 변 상한 */
  zmapGrid: number;
  /** 3D 복셀(경사면·5축·턴밀) 자동 해상도의 목표 칸 수 */
  voxels: number;
  /** 3D 복셀 전체 칸 수 상한(직접 고른 해상도 포함) */
  voxelMax: number;
  /** 3D 복셀 해상도 하한(mm) */
  voxelMinRes: number;
  /** 3D 표면 표시 사각형 상한 */
  quads: number;
  /** 선반 자동 해상도의 목표 칸 수 */
  latheCells: number;
  /** 선반 화면 격자 상한 */
  latheGrid: number;
  /** 되감기용 저장 메모리(바이트) */
  snapshotBytes: number;
}

const MB = 1024 * 1024;
const TABLE: Record<Precision, PrecisionParams> = {
  low: { zmapCells: 100_000, zmapGrid: 200, voxels: 1_500_000, voxelMax: 4_000_000, voxelMinRes: 0.1, quads: 80_000, latheCells: 1_000_000, latheGrid: 350, snapshotBytes: 200 * MB },
  normal: { zmapCells: 250_000, zmapGrid: 300, voxels: 3_000_000, voxelMax: 8_000_000, voxelMinRes: 0.1, quads: 150_000, latheCells: 2_000_000, latheGrid: 500, snapshotBytes: 200 * MB },
  high: { zmapCells: 1_000_000, zmapGrid: 500, voxels: 6_000_000, voxelMax: 12_000_000, voxelMinRes: 0.07, quads: 300_000, latheCells: 4_000_000, latheGrid: 700, snapshotBytes: 250 * MB },
  max: { zmapCells: 3_000_000, zmapGrid: 700, voxels: 12_000_000, voxelMax: 20_000_000, voxelMinRes: 0.05, quads: 500_000, latheCells: 8_000_000, latheGrid: 900, snapshotBytes: 300 * MB },
};

const KEY = 'sim_precision';
let current: Precision | null = null;

export function getPrecision(): Precision {
  if (current) return current;
  let v: string | null = null;
  try { v = getPref(KEY); } catch { /* 저장값을 못 읽으면 보통 */ }
  current = (PRECISIONS as readonly string[]).includes(v ?? '') ? (v as Precision) : 'normal';
  return current;
}
export function setPrecision(p: Precision): void {
  current = p;
  try { setPref(KEY, p); } catch { /* 저장 실패는 무시 */ }
}
export const precisionParams = (): PrecisionParams => TABLE[getPrecision()];
