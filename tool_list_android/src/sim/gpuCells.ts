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

// '최고' 해상도(키 gpu:max, 원본 nc_sim_gpu.max_quality_cells 와 같은 식): 상용 CAM 검증 프로그램이 쓰는 0.01mm급 셀을 목표로
// 소재 크기에 맞춰 칸 수를 자동으로 키운다. 원본과 다른 점(안드로이드 CLAUDE.md 4절 6번): 상한 4096칸(원본 8192) — 휴대폰 그래픽 메모리.
export const MAX_QUALITY_TARGET_CELL = 0.01;
export const MAX_QUALITY_CELLS_MIN = 2048;
export const MAX_QUALITY_CELLS_CAP = 4096;

export function maxQualityCells(bounds: Bounds, cap = MAX_QUALITY_CELLS_CAP, target = MAX_QUALITY_TARGET_CELL): number {
  const long = Math.max(bounds.X[1] - bounds.X[0], bounds.Y[1] - bounds.Y[0], 1e-6);
  const top = Math.max(Math.trunc(cap), MAX_QUALITY_CELLS_MIN);
  return Math.min(Math.max(Math.ceil(long / target) + 1, MAX_QUALITY_CELLS_MIN), top);
}
