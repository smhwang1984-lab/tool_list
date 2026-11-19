// NC 코드 색 구간 계산 — 원본 nc_color_line (v2.2.7)
//
// 모달 색: G0~G3/사이클을 만나면 다음 모달 색 코드(또는 G80/M30/%)까지 뒤 글자가 그 색이다.
// 스핀들(S, M3/4/5/19)·냉각(M8/M9)은 그 글자만 칠하고 모달 색은 바꾸지 않는다.
// 괄호 주석과 ; 뒤는 칠하지 않는다. 입력창(CodeMirror)이 줄마다 이 함수를 불러 색을 입힌다.
import { RE_I, pyInt, pyRe, reFinditer } from './py';

/** 테마 색 키 (THEMES 의 nc_* 와 같은 이름) */
export type NcColorKey = 'nc_g0' | 'nc_g1' | 'nc_g2' | 'nc_g3' | 'nc_cycle' | 'nc_spindle' | 'nc_coolant';

/** [시작, 끝, 색 키] — 위치는 줄 안의 인덱스 */
export type ColorSpan = [start: number, end: number, key: NcColorKey];

const NC_COLOR_CODE_RE = pyRe(
  String.raw`(?<![A-Za-z])(?:([GM])\s*0*(\d+)(?!\d)|(S\s*[-+]?(?:\d+\.?\d*|\.\d+))|(%))`, RE_I);
const NC_MODAL_BY_G: Readonly<Record<number, NcColorKey>> = { 0: 'nc_g0', 1: 'nc_g1', 2: 'nc_g2', 3: 'nc_g3' };

const range = (from: number, to: number): number[] => Array.from({ length: to - from }, (_, i) => from + i);
const NC_CYCLE_G_MILL: ReadonlySet<number> = new Set([73, 74, 76, ...range(81, 90)]);
const NC_CYCLE_G_LATHE: ReadonlySet<number> = new Set([...range(70, 77), 90, 92, 94]);
const NC_SPINDLE_M: ReadonlySet<number> = new Set([3, 4, 5, 19]);
const NC_COOLANT_M: ReadonlySet<number> = new Set([8, 9]);
const NC_RESET_M: ReadonlySet<number> = new Set([2, 30]);
/** 모달 색 번호 0~5 -> 색 키 (0 = 색 없음) */
const NC_MODE_KEYS: readonly (NcColorKey | null)[] = [null, 'nc_g0', 'nc_g1', 'nc_g2', 'nc_g3', 'nc_cycle'];

/**
 * 한 줄의 색 구간 계산. state 는 (모달 색 번호 0~5) + 8*(괄호 주석 안 여부).
 * 돌려줌: [색 구간 목록, 다음 줄 state]. 순수 함수라 화면 없이 시험한다.
 */
export function ncColorLine(
  line: string, state: number | null | undefined, lathe = false,
): [spans: ColorSpan[], nextState: number] {
  const st = state === null || state === undefined || state < 0 ? 0 : state;
  let mode = st & 7;
  let inParen = Boolean(st & 8);
  const cycles = lathe ? NC_CYCLE_G_LATHE : NC_CYCLE_G_MILL;
  const spans: ColorSpan[] = [];

  const emit = (start: number, end: number, modeIndex: number): void => {
    if (end > start && modeIndex) spans.push([start, end, NC_MODE_KEYS[modeIndex]!]);
  };

  let pos = 0;
  const length = line.length;
  while (pos < length) {
    if (inParen) {
      const close = line.indexOf(')', pos);
      if (close < 0) {
        pos = length;
        break;
      }
      pos = close + 1;
      inParen = false;
      continue;
    }
    // 코드 구간: 다음 '(' 또는 ';' 까지
    const stops = [line.indexOf('(', pos), line.indexOf(';', pos)].filter((i) => i >= 0);
    const end = stops.length ? Math.min(...stops) : length;
    let cursor = pos;
    for (const match of reFinditer(NC_COLOR_CODE_RE, line, pos, end)) {
      emit(cursor, match.index, mode);
      let tokenMode = mode;
      let tokenKey: NcColorKey | null = null;
      if (match[4]) {
        tokenMode = 0;
      } else if (match[3]) {
        tokenKey = 'nc_spindle';
      } else {
        const number = pyInt(match[2]!);
        if (match[1]!.toUpperCase() === 'G') {
          if (number in NC_MODAL_BY_G) tokenMode = NC_MODE_KEYS.indexOf(NC_MODAL_BY_G[number]!);
          else if (cycles.has(number)) tokenMode = 5;
          else if (number === 80) tokenMode = 0;
        } else if (NC_SPINDLE_M.has(number)) {
          tokenKey = 'nc_spindle';
        } else if (NC_COOLANT_M.has(number)) {
          tokenKey = 'nc_coolant';
        } else if (NC_RESET_M.has(number)) {
          tokenMode = 0;
        }
      }
      mode = tokenMode;
      const matchEnd = match.index + match[0].length;
      if (tokenKey) spans.push([match.index, matchEnd, tokenKey]);
      else emit(match.index, matchEnd, mode);
      cursor = matchEnd;
    }
    emit(cursor, end, mode);
    pos = end;
    if (pos < length) {
      if (line[pos] === ';') break;
      inParen = true;
      pos += 1;
    }
  }
  return [spans, mode | (inParen ? 8 : 0)];
}
