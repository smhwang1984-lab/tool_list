// 확대 고정밀(원본 v2.8.1 G8, nc_viewer_widget.NCViewerWidget._clip_zoom_bounds / apply_quality_zoom 과 같은 약속).
// 보이는 영역(XY)만 더 작은 셀로 다시 계산한다. Z-map 엔진 전용.
import type { Bounds } from './stock';

/** 확대 고정밀 GPU 긴 변 칸 수 / GPU를 못 쓸 때 기본 엔진(CPU) 긴 변 칸 수 */
export const ZOOM_CELLS = 4096;
export const ZOOM_CPU_CELLS = 1200;
/** 확대 고정밀은 GPU 최소 셀 0.01mm 보다 더 작게(0.002mm) 허용한다 */
export const ZOOM_MIN_RESOLUTION = 0.002;

export interface ZoomRegion { X: [number, number]; Y: [number, number] }

/** 소재 bounds 를 region(XY)으로 자른다. 겹치지 않거나 한 변이 0.05mm 보다 작으면 null */
export function clipZoomBounds(bounds: Bounds, region: ZoomRegion): Bounds | null {
  const out: Bounds = { X: [...bounds.X], Y: [...bounds.Y], Z: [...bounds.Z] } as Bounds;
  for (const axis of ['X', 'Y'] as const) {
    const lo = Math.max(bounds[axis][0], region[axis][0]);
    const hi = Math.min(bounds[axis][1], region[axis][1]);
    if (hi - lo < 0.05) return null;
    out[axis] = [lo, hi];
  }
  return out;
}
