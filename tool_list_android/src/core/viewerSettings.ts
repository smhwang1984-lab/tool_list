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
/** 원본 v2.6.0: 지난 경로 숨김 — 재생 중 지금 줄 기준 앞쪽 N블록만(100~500, 50 단위, 기본 200) */
export const TRAIL_BLOCKS_MIN = 100;
export const TRAIL_BLOCKS_MAX = 500;
export const TRAIL_BLOCKS_STEP = 50;
export const TRAIL_BLOCKS_DEFAULT = 200;
/** 원본 v2.6.7: 회전축(A·B·C) 인덱스 속도(°/초, 5~180, 5 단위, 기본 30). G0 인덱스 회전에만 적용 —
 * 여러 축은 가장 큰 회전량 기준으로 동시에 끝나고, 회전이 끝날 때까지 재생은 다음 줄로 넘어가지 않는다. 동시 5축(G43.4)은 재생을 따른다 */
export const ROTARY_SPEED_MIN = 5;
export const ROTARY_SPEED_MAX = 180;
export const ROTARY_SPEED_STEP = 5;
export const ROTARY_SPEED_DEFAULT = 30;

/** 원본 clamp_rotary_speed */
export function clampRotarySpeed(value: unknown): number {
  const n = value === null || value === undefined || (typeof value === 'string' && value.trim() === '') ? NaN : Number(value);
  if (!Number.isFinite(n)) return ROTARY_SPEED_DEFAULT;
  const v = Math.max(ROTARY_SPEED_MIN, Math.min(ROTARY_SPEED_MAX, roundHalfEven(n)));
  return ROTARY_SPEED_MIN + roundHalfEven((v - ROTARY_SPEED_MIN) / ROTARY_SPEED_STEP) * ROTARY_SPEED_STEP;
}

/** 원본 clamp_trail_blocks: 100~500, 50 단위. 읽을 수 없으면 기본값 */
export function clampTrailBlocks(value: unknown): number {
  const n = value === null || value === undefined || (typeof value === 'string' && value.trim() === '') ? NaN : Number(value);
  if (!Number.isFinite(n)) return TRAIL_BLOCKS_DEFAULT;
  const v = Math.max(TRAIL_BLOCKS_MIN, Math.min(TRAIL_BLOCKS_MAX, roundHalfEven(n)));
  return TRAIL_BLOCKS_MIN + roundHalfEven((v - TRAIL_BLOCKS_MIN) / TRAIL_BLOCKS_STEP) * TRAIL_BLOCKS_STEP;
}

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
