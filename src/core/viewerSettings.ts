// Viewer 표시 설정의 값 범위와 기본값 — 원본 nc_viewer_widget.py (v2.2.8 설정 창)
export const LINE_WIDTH_STEPS: readonly number[] = Array.from({ length: 10 }, (_, i) => (i + 1) * 10);
export const LINE_WIDTH_DEFAULT_PCT = 90;
export const CUT_LINE_BASE_WIDTH = 2.5;
export const TOOLPATH_LINE_WIDTH_MIN_PX = 1.0;
export const SENSITIVITY_MIN = 5;
export const SENSITIVITY_MAX = 200;
/** 원본 DEFAULT_NAVIGATION_SENSITIVITY 0.4 → 40% */
export const SENSITIVITY_DEFAULT = 40;
export const CUBE_MIN = 60;
export const CUBE_MAX = 240;
export const CUBE_DEFAULT = 160;
/** Android 추가 항목: 3D 화면의 시야각(도) */
export const FOV_MIN = 20;
export const FOV_MAX = 90;
export const FOV_DEFAULT = 45;

/** Python round(): 정확히 .5 면 짝수 쪽 */
function roundHalfEven(x: number): number {
  const r = Math.round(x);
  return Math.abs(x % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
}

/** 저장값/입력값을 10~100 사이 10 단위로 맞춘다. 읽을 수 없으면 기본값 (원본 clamp_line_width_pct). */
export function clampLineWidthPct(value: unknown): number {
  const n = value === null || value === undefined || (typeof value === 'string' && value.trim() === '') ? NaN : Number(value);
  if (!Number.isFinite(n)) return LINE_WIDTH_DEFAULT_PCT;
  const pct = roundHalfEven(n / 10) * 10;
  return Math.max(LINE_WIDTH_STEPS[0]!, Math.min(LINE_WIDTH_STEPS[LINE_WIDTH_STEPS.length - 1]!, pct));
}

/** 기준 굵기(=90%)를 pct(10~100)에 맞춘 실제 픽셀 굵기 — 원본 toolpath_line_width */
export function toolpathLineWidth(base: number, pct: number): number {
  const p = clampLineWidthPct(pct);
  if (p >= LINE_WIDTH_DEFAULT_PCT) return base * (1 + (0.1 * (p - LINE_WIDTH_DEFAULT_PCT)) / (100 - LINE_WIDTH_DEFAULT_PCT));
  const low = LINE_WIDTH_STEPS[0]!;
  const floor = Math.min(TOOLPATH_LINE_WIDTH_MIN_PX, base);
  return floor + ((base - floor) * (p - low)) / (LINE_WIDTH_DEFAULT_PCT - low);
}
