// GPU 엔진 설정값(three 에 의존하지 않는다 — Web Worker 쪽 엔진도 가져다 쓴다). 원본 nc_sim_gpu.resolution_for_cells 와 같은 식.
import type { Bounds } from './stock';

/** 휴대폰은 그래픽 메모리가 작아 자동 = 2048 칸(원본은 4096, 안전 모드 2048). 이유 기록: 안드로이드 CLAUDE.md 4절 6번 */
export const GPU_AUTO_CELLS = 2048;
/** 화면에 그리는 격자 한 변의 상한(정점 수 제한). 계산 격자가 더 크면 블록 최솟값으로 줄인다 */
export const GPU_DISPLAY_GRID_MAX = 2048;
export const GPU_MIN_RESOLUTION = 0.01;

/** 소재 긴 변이 cells 칸이 되는 격자 간격(mm) */
export function resolutionForCells(bounds: Bounds, cells: number, minResolution = GPU_MIN_RESOLUTION): number {
  const long = Math.max(bounds.X[1] - bounds.X[0], bounds.Y[1] - bounds.Y[0], 1e-6);
  return Math.max(long / Math.max(Math.trunc(cells) - 1, 1), minResolution);
}

/** 계산 격자 → 표시 격자 블록 크기 */
export function displayBlock(nx: number, ny: number, cap = GPU_DISPLAY_GRID_MAX): [number, number] {
  return [Math.max(1, Math.ceil(nx / cap)), Math.max(1, Math.ceil(ny / cap))];
}
