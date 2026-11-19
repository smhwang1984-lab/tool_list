// 공구 리스트 표 열 정의 — 원본 NC_Tool_List.py COLUMNS / LATHE_COLUMNS / 칸 폭 상수
export type Column = readonly [key: string, label: string];

/** 밀링 16열 (내부키, 표시라벨) — 엑셀 A~P 순서와 같다 */
export const COLUMNS: readonly Column[] = [
  ['NO', 'NO'], ['TYPE', 'TYPE'], ['NAME', 'NAME'], ['D', 'D'],
  ['FL', 'FL'], ['LCF', 'LCF'], ['F', 'F'], ['R', 'R'],
  ['SIG', 'SIG'], ['PL', 'PL'], ['SO', 'SO'], ['GL', 'GL'],
  ['HOLDER', '홀더'], ['SPINDL', 'SPINDL'], ['FEED', 'FEED'], ['REMARK', 'REMARK'],
];

/** 선반 14열 */
export const LATHE_COLUMNS: readonly Column[] = [
  ['NO', 'TOOL NO'], ['INSERT', 'INSERT'], ['R', 'R'], ['T', 'T'], ['PITCH', 'PITCH'],
  ['HOLDER', '홀더'], ['SO', 'SO'], ['KIND', '종류'], ['DIR', '방향'], ['TIP', '인선'],
  ['D', 'D'], ['SPINDL', 'SPINDL'], ['FEED', 'FEED'], ['REMARK', 'REMARK'],
];

/** 자동 추천 값을 사용자가 고칠 수 있는 선반 열 */
export const LATHE_SPEC_KEYS = ['R', 'T', 'PITCH', 'KIND', 'DIR', 'TIP', 'D'] as const;

// 칸 폭: 기준값 × COPY_TABLE_SCALE + 좌우 여백 (원본 v1.5.9 / v1.6.0 / v1.6.2)
export const COPY_TABLE_SCALE = 0.85;
export const TABLE_FONT_PT = 14 * COPY_TABLE_SCALE;
export const TABLE_CELL_PADDING_PX = Math.round(8 * COPY_TABLE_SCALE);
/** 표 폭에 맞춰 줄일 때의 하한 */
export const TOOL_TABLE_MIN_SCALE = 0.45;

const COL_WIDTH_BASE: Record<string, number> = {
  NO: 72, TYPE: 128, NAME: 152, D: 72, FL: 72, LCF: 80, F: 56,
  R: 72, SIG: 72, PL: 88, SO: 72, GL: 80, HOLDER: 192,
  SPINDL: 96, FEED: 88, REMARK: 176,
};
const LATHE_COL_WIDTH_BASE: Record<string, number> = {
  NO: 88, INSERT: 220, R: 52, T: 52, PITCH: 68, HOLDER: 220, SO: 64,
  KIND: 96, DIR: 56, TIP: 60, D: 56, SPINDL: 128, FEED: 104, REMARK: 140,
};

// Python round(): 정확히 .5면 짝수 쪽. 여기 값(×0.85)은 .5가 되는 경우가 없지만 같은 규칙을 쓴다.
function scaleWidth(width: number): number {
  const y = width * COPY_TABLE_SCALE;
  const r = Math.round(y);
  const v = Math.abs(y % 1) === 0.5 && r % 2 !== 0 ? r - 1 : r;
  return v + TABLE_CELL_PADDING_PX * 2;
}

const mapValues = (o: Record<string, number>) =>
  Object.fromEntries(Object.entries(o).map(([k, v]) => [k, scaleWidth(v)]));

export const COL_WIDTH: Readonly<Record<string, number>> = mapValues(COL_WIDTH_BASE);
export const LATHE_COL_WIDTH: Readonly<Record<string, number>> = mapValues(LATHE_COL_WIDTH_BASE);

/** 빈 행 (없는 공구번호 자리) */
export function blankRow(columns: readonly Column[]): Record<string, string> {
  return Object.fromEntries(columns.map(([key]) => [key, '']));
}
