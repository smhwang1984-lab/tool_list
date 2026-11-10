// 공구 이동·문자 검색·재생 정지 판정 — 원본 find_next/prev_regex_span ~ find_next_literal_span
//
// 위치(start/end)는 JS 문자열 인덱스(UTF-16)다. 입력창(CodeMirror)이 쓰는 위치와 같다.
// 한글 등 BMP 글자만 있으면 원본의 위치와 같다.
import { LATHE_T_SEARCH_RE, M6_SEARCH_RE } from './patterns';
import {
  PyError, RE_I, pyIntFrom, pyReEscape, pyReOnce, pyRe, pyStr, reFinditer, reSearch, reSub,
} from './py';

/** [시작, 끝, 처음/끝을 넘어 되돌아와서 찾았는가(wrapped)] */
export type Span = [start: number, end: number, wrapped: boolean];

const M00_STOP_RE = pyRe(String.raw`M0?0(?!\d)`, RE_I);
const M01_STOP_RE = pyRe(String.raw`M0?1(?!\d)`, RE_I);
const PAREN_COMMENT_RE = pyRe(String.raw`\([^)]*\)`);

/** start 를 int 로. 못 읽으면(TypeError/ValueError) 0, 범위를 벗어나면 [0, 길이]로 맞춘다. */
function clampStart(start: unknown, length: number): number {
  let n: number;
  try {
    n = pyIntFrom(start);
  } catch (error) {
    if (!(error instanceof PyError) || error.pyType === 'OverflowError') throw error;
    n = 0;
  }
  return Math.max(0, Math.min(n, length));
}

/** start 위치부터 다음 매치. 없으면 처음부터 다시(wrapped=true). */
export function findNextRegexSpan(text: string | null | undefined, pattern: RegExp, start: unknown = 0): Span | null {
  const s = text || '';
  if (!s) return null;
  const from = clampStart(start, s.length);
  let match = reSearch(pattern, s, from);
  if (match) return [match.index, match.index + match[0].length, false];
  match = reSearch(pattern, s, 0, from);
  if (match) return [match.index, match.index + match[0].length, true];
  return null;
}

/** start 보다 앞에서 시작하는 마지막 매치. 없으면 끝에서부터 다시(wrapped=true). */
export function findPrevRegexSpan(text: string | null | undefined, pattern: RegExp, start: unknown = 0): Span | null {
  const s = text || '';
  if (!s) return null;
  const from = clampStart(start, s.length);
  let before: RegExpExecArray | null = null;
  let last: RegExpExecArray | null = null;
  for (const match of reFinditer(pattern, s)) {
    if (match.index < from) before = match;
    last = match;
  }
  if (before) return [before.index, before.index + before[0].length, false];
  if (last) return [last.index, last.index + last[0].length, true];
  return null;
}

/** '다음공구검색'이 찾을 다음 공구 교체 지점. 선반은 Tnn00 기준이다. */
export function findNextToolChangeSpan(text: string | null | undefined, start: unknown = 0, lathe = false): Span | null {
  return findNextRegexSpan(text, lathe ? LATHE_T_SEARCH_RE : M6_SEARCH_RE, start);
}

/** '이전공구검색' — 다음공구검색과 같은 기준(밀링 M6T, 선반 Tnn00)으로 위쪽을 찾는다. */
export function findPrevToolChangeSpan(text: string | null | undefined, start: unknown = 0, lathe = false): Span | null {
  return findPrevRegexSpan(text, lathe ? LATHE_T_SEARCH_RE : M6_SEARCH_RE, start);
}

/** 정지 코드 검사를 위해 주석(괄호/세미콜론 이후)을 제거하고 공백을 없앤다. */
function stopScanCode(line: unknown): string {
  const code = reSub(PAREN_COMMENT_RE, ' ', line ? pyStr(line) : '').split(';')[0]!;
  return code.split(' ').join('');
}

/** M00/M0 (프로그램 정지)가 있는 줄인지. 주석은 제외. */
export function lineHasM00Stop(line: unknown): boolean {
  return reSearch(M00_STOP_RE, stopScanCode(line)) !== null;
}

/** M01/M1 (옵셔널 정지)이 있는 줄인지. 주석은 제외. */
export function lineHasM01Stop(line: unknown): boolean {
  return reSearch(M01_STOP_RE, stopScanCode(line)) !== null;
}

/** M00/M0/M01/M1 (프로그램 정지·옵셔널 정지)가 있는 줄인지. 주석은 제외. */
export function lineHasProgramStop(line: unknown): boolean {
  return lineHasM00Stop(line) || lineHasM01Stop(line);
}

/** PG 매칭 자동 재생이 이 줄에서 멈춰야 하는지. 세 옵션 모두 해제면 멈추지 않는다. */
export function lineStopsPlayback(
  line: unknown, needle: unknown = '', stopText = false, stopM00 = true, stopM01 = true,
): boolean {
  if (stopM00 && lineHasM00Stop(line)) return true;
  if (stopM01 && lineHasM01Stop(line)) return true;
  if (stopText && needle) return (line ? pyStr(line) : '').toLowerCase().includes(pyStr(needle).toLowerCase());
  return false;
}

/** 대소문자를 가리지 않는 글자 그대로 검색 (정규식 특수 문자는 그냥 글자) */
export function findNextLiteralSpan(text: string | null | undefined, needle: unknown, start: unknown = 0): Span | null {
  const n = needle ? pyStr(needle) : '';
  if (!n) return null;
  return findNextRegexSpan(text, pyReOnce(pyReEscape(n), RE_I), start);
}
