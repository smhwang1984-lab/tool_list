// Python 동작 맞추기 도우미 — 원본(Python) 로직을 TS로 옮길 때 결과가 1글자도 달라지지 않게 한다.
// (WORK_PLAN P1 §1.1 "Python과 JS의 차이 대응")
//
// - 정규식: Python re(str 패턴)의 \d \s \w \b 는 유니코드 기준, ^ $ . 는 '\n'만 줄바꿈으로 본다.
//   JS RegExp와 다르므로 pyRe()로 패턴을 번역해서 쓴다.
// - float(), str(float)(repr), str.strip()/split()/splitlines(), int 나머지 등.
// 위치(인덱스)는 JS 문자열 기준(UTF-16)이다. BMP 밖 글자(이모지 등)가 없으면 Python과 같다.

/** Python 예외를 흉내 낸다 (ValueError / TypeError / OverflowError ...). */
export class PyError extends Error {
  constructor(public readonly pyType: string, message = '') {
    super(`${pyType}${message ? ': ' + message : ''}`);
    this.name = 'PyError';
  }
}

// Python str.isspace() 글자 집합 (re의 \s 와 같다)
const WS_CHARS = '\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000';
const WORD_CHARS = '\\p{L}\\p{N}_';
const WS_RE = new RegExp(`[${WS_CHARS}]`, 'u');
const WS_RUN_RE = new RegExp(`[${WS_CHARS}]+`, 'gu');

export function pyIsSpace(ch: string): boolean {
  return WS_RE.test(ch);
}

function stripSet(chars: string | null | undefined): (ch: string) => boolean {
  if (chars === null || chars === undefined) return pyIsSpace;
  const set = new Set(Array.from(chars));
  return (ch) => set.has(ch);
}

export function pyStrip(s: string, chars?: string | null): string {
  return pyRstrip(pyLstrip(s, chars), chars);
}

export function pyLstrip(s: string, chars?: string | null): string {
  const test = stripSet(chars);
  const cps = Array.from(s);
  let i = 0;
  while (i < cps.length && test(cps[i]!)) i++;
  return cps.slice(i).join('');
}

export function pyRstrip(s: string, chars?: string | null): string {
  const test = stripSet(chars);
  const cps = Array.from(s);
  let j = cps.length;
  while (j > 0 && test(cps[j - 1]!)) j--;
  return cps.slice(0, j).join('');
}

/** str.split() (인자 없음): 공백 덩어리로 나누고 빈 조각은 버린다. */
export function pySplitWs(s: string): string[] {
  return s.split(WS_RUN_RE).filter((part) => part !== '');
}

const SPLITLINES_RE = /\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/g;

/** str.splitlines(): 끝의 줄바꿈 하나는 빈 줄을 만들지 않는다. */
export function pySplitlines(s: string): string[] {
  if (s === '') return [];
  const parts = s.split(SPLITLINES_RE);
  if (parts.length > 1 && parts[parts.length - 1] === '') parts.pop();
  return parts;
}

/** len(s) — 코드 포인트 수 */
export function pyLen(s: string): number {
  let n = 0;
  for (const _ of s) n++;
  return n;
}

/** Python truthiness (문자열/숫자/None/리스트/dict) */
export function pyTruthy(v: unknown): boolean {
  if (v === null || v === undefined || v === false || v === 0 || v === '') return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === 'object') return Object.keys(v as object).length > 0;
  return true;
}

// ---------------------------------------------------------------- 숫자
const NUMERIC_RE = /^[+-]?(?:(?:\d(?:_?\d)*)(?:\.(?:\d(?:_?\d)*)?)?|\.\d(?:_?\d)*)(?:[eE][+-]?\d(?:_?\d)*)?$/;
const SPECIAL_RE = /^([+-]?)(inf|infinity|nan)$/i;
const ND_RE = /\p{Nd}/u;

/** 유니코드 십진 숫자(Nd)를 ASCII 숫자로 바꾼다. Nd는 0~9가 연속 10자씩 붙어 있다. */
function asciiDigits(s: string): string {
  let out = '';
  for (const ch of s) {
    const cp = ch.codePointAt(0)!;
    if (cp < 128 || !ND_RE.test(ch)) {
      out += ch;
      continue;
    }
    let run = 0;
    while (ND_RE.test(String.fromCodePoint(cp - run - 1))) run++;
    out += String(run % 10);
  }
  return out;
}

/** int(s) — 정규식으로 이미 숫자만 잡은 문자열(유니코드 숫자 포함)을 정수로 */
export function pyInt(s: string): number {
  const t = asciiDigits(pyStrip(s)).replace(/_/g, '');
  if (!/^[+-]?\d+$/.test(t)) throw new PyError('ValueError', `invalid literal for int(): '${s}'`);
  return Number(t);
}

/** float(x) — 숫자로 못 읽으면 PyError(ValueError/TypeError) */
export function pyFloat(x: unknown): number {
  if (typeof x === 'number') return x;
  if (typeof x === 'boolean') return x ? 1 : 0;
  if (typeof x !== 'string') throw new PyError('TypeError', 'float() argument');
  const s = asciiDigits(pyStrip(x));
  const special = SPECIAL_RE.exec(s);
  if (special) {
    if (special[2]!.toLowerCase() === 'nan') return NaN;
    return special[1] === '-' ? -Infinity : Infinity;
  }
  if (!NUMERIC_RE.test(s)) throw new PyError('ValueError', `could not convert string to float: '${x}'`);
  return Number(s.replace(/_/g, ''));
}

/** repr(float) / str(float) — 가장 짧은 왕복 표기, Python 규칙(1e-05, 1e+16, 10.0) */
export function pyFloatRepr(n: number): string {
  if (Number.isNaN(n)) return 'nan';
  if (n === Infinity) return 'inf';
  if (n === -Infinity) return '-inf';
  if (n === 0) return Object.is(n, -0) ? '-0.0' : '0.0';
  const sign = n < 0 ? '-' : '';
  const [mant, expText] = Math.abs(n).toExponential().split('e') as [string, string];
  const digits = mant.replace('.', '');
  const exp = Number(expText);
  if (exp < -4 || exp >= 16) {
    const m = digits.length > 1 ? digits[0] + '.' + digits.slice(1) : digits;
    const e = Math.abs(exp) < 10 ? '0' + Math.abs(exp) : String(Math.abs(exp));
    return `${sign}${m}e${exp < 0 ? '-' : '+'}${e}`;
  }
  if (exp < 0) return `${sign}0.${'0'.repeat(-exp - 1)}${digits}`;
  if (digits.length <= exp + 1) return `${sign}${digits}${'0'.repeat(exp + 1 - digits.length)}.0`;
  return `${sign}${digits.slice(0, exp + 1)}.${digits.slice(exp + 1)}`;
}

/** str(int(f)) — 큰 수도 정확한 정수 자릿수로 */
export function pyIntStr(f: number): string {
  if (!Number.isFinite(f)) throw new PyError(Number.isNaN(f) ? 'ValueError' : 'OverflowError');
  const t = Math.trunc(f);
  return Number.isSafeInteger(t) ? String(t === 0 ? 0 : t) : BigInt(t).toString();
}

/** repr(str) — 따옴표 고르기와 이스케이프 */
export function pyStrRepr(s: string): string {
  const quote = s.includes("'") && !s.includes('"') ? '"' : "'";
  let out = quote;
  for (const ch of s) {
    const cp = ch.codePointAt(0)!;
    if (ch === quote || ch === '\\') out += '\\' + ch;
    else if (ch === '\n') out += '\\n';
    else if (ch === '\r') out += '\\r';
    else if (ch === '\t') out += '\\t';
    else if (cp < 0x20 || cp === 0x7f) out += '\\x' + cp.toString(16).padStart(2, '0');
    else out += ch;
  }
  return out + quote;
}

/** repr(x) — 문자열/숫자/None/bool/list/dict */
export function pyRepr(x: unknown): string {
  if (typeof x === 'string') return pyStrRepr(x);
  if (Array.isArray(x)) return '[' + x.map(pyRepr).join(', ') + ']';
  if (x !== null && typeof x === 'object') {
    return '{' + Object.entries(x).map(([k, v]) => `${pyStrRepr(k)}: ${pyRepr(v)}`).join(', ') + '}';
  }
  return pyStr(x);
}

/** str(x). JS 숫자는 정수면 int, 아니면 float로 본다. */
export function pyStr(x: unknown): string {
  if (x === null || x === undefined) return 'None';
  if (x === true) return 'True';
  if (x === false) return 'False';
  if (typeof x === 'number') return Number.isInteger(x) && !Object.is(x, -0) ? String(x) : pyFloatRepr(x);
  if (typeof x === 'string') return x;
  return pyRepr(x);
}

/** '%02d' % n */
export function pad2(n: number): string {
  const s = String(Math.abs(Math.trunc(n))).padStart(2, '0');
  return n < 0 ? '-' + s : s;
}

// ---------------------------------------------------------------- 정규식
export const RE_I = 2;
export const RE_M = 8;
export const RE_S = 16;

const SYNTAX_CHARS = new Set(Array.from('^$\\.*+?()[]{}|/'));
const QUANT_RE = /^\{\d+(,\d*)?\}|^\{,\d+\}/;

/** Python re 패턴 → JS(u 플래그) 패턴 소스 */
export function translatePyPattern(src: string, flags = 0): string {
  const dotAll = (flags & RE_S) !== 0;
  const multi = (flags & RE_M) !== 0;
  const W = `[${WORD_CHARS}]`;
  let out = '';
  let inClass = false;
  let classStart = false;
  const chars = Array.from(src);
  for (let i = 0; i < chars.length; i++) {
    const c = chars[i]!;
    if (c === '\\') {
      const n = chars[++i];
      if (n === undefined) throw new Error('잘못된 패턴: 끝의 \\');
      if (inClass) {
        classStart = false;
        if (n === 'd') out += '\\p{Nd}';
        else if (n === 's') out += WS_CHARS;
        else if (n === 'w') out += WORD_CHARS;
        else if (n === 'D' || n === 'S' || n === 'W') throw new Error(`지원하지 않는 패턴: [\\${n}]`);
        else if (/[A-Za-z0-9]/.test(n) || SYNTAX_CHARS.has(n) || n === '-') out += '\\' + n;
        else out += n;
        continue;
      }
      if (n === 'd') out += '\\p{Nd}';
      else if (n === 'D') out += '\\P{Nd}';
      else if (n === 's') out += `[${WS_CHARS}]`;
      else if (n === 'S') out += `[^${WS_CHARS}]`;
      else if (n === 'w') out += W;
      else if (n === 'W') out += `[^${WORD_CHARS}]`;
      else if (n === 'b') out += `(?:(?<=${W})(?!${W})|(?<!${W})(?=${W}))`;
      else if (n === 'B') out += `(?:(?<=${W})(?=${W})|(?<!${W})(?!${W}))`;
      else if (n === 'A') out += '^';
      else if (n === 'Z') out += '$';
      else if (/[A-Za-z0-9]/.test(n) || SYNTAX_CHARS.has(n)) out += '\\' + n;
      else out += n; // re.escape 가 붙인 \- \& \~ \# \  등 → 그냥 글자
      continue;
    }
    if (inClass) {
      if (c === ']' && !classStart) {
        inClass = false;
        out += ']';
      } else if (c === ']' || c === '[') {
        out += '\\' + c;
      } else {
        out += c;
      }
      classStart = false;
      continue;
    }
    if (c === '[') {
      inClass = true;
      out += '[';
      if (chars[i + 1] === '^') {
        out += '^';
        i++;
      }
      classStart = true;
      continue;
    }
    if (c === '.') out += dotAll ? '[\\s\\S]' : '[^\\n]';
    else if (c === '^') out += multi ? '(?<![^\\n])' : '^';
    else if (c === '$') out += multi ? '(?![^\\n])' : '(?=\\n?$)';
    else if (c === '(' && chars[i + 1] === '?' && chars[i + 2] === 'P' && chars[i + 3] === '<') {
      out += '(?<';
      i += 3;
    } else if (c === '{') {
      const rest = chars.slice(i).join('');
      const q = QUANT_RE.exec(rest);
      if (q) {
        const text = q[0].startsWith('{,') ? '{0' + q[0].slice(1) : q[0];
        out += text;
        i += Array.from(q[0]).length - 1;
      } else out += '\\{';
    } else if (c === '}') out += '\\}';
    else out += c;
  }
  return out;
}

const RE_CACHE = new Map<string, RegExp>();

/** Python re.compile(src, flags) 와 같은 의미의 JS RegExp (g·u 플래그, lastIndex로 위치 지정) */
export function pyRe(src: string, flags = 0): RegExp {
  const key = `${flags}\u0000${src}`;
  let rx = RE_CACHE.get(key);
  if (!rx) {
    rx = new RegExp(translatePyPattern(src, flags), 'gu' + ((flags & RE_I) !== 0 ? 'i' : ''));
    RE_CACHE.set(key, rx);
  }
  return rx;
}

export type PyMatch = RegExpExecArray;

/** pattern.search(text, pos, endpos) */
export function reSearch(rx: RegExp, text: string, pos = 0, endpos?: number): PyMatch | null {
  const s = endpos !== undefined && endpos < text.length ? text.slice(0, Math.max(0, endpos)) : text;
  if (pos > s.length) return null;
  rx.lastIndex = Math.max(0, pos);
  return rx.exec(s);
}

const STICKY_CACHE = new WeakMap<RegExp, RegExp>();
const FULL_CACHE = new WeakMap<RegExp, RegExp>();

/** pattern.match(text, pos) — pos에서 시작하는 매치만 */
export function reMatch(rx: RegExp, text: string, pos = 0): PyMatch | null {
  let y = STICKY_CACHE.get(rx);
  if (!y) {
    y = new RegExp(rx.source, rx.flags.replace('g', '') + 'y');
    STICKY_CACHE.set(rx, y);
  }
  y.lastIndex = pos;
  return y.exec(text);
}

/** pattern.fullmatch(text) */
export function reFullmatch(rx: RegExp, text: string): PyMatch | null {
  let f = FULL_CACHE.get(rx);
  if (!f) {
    f = new RegExp(`^(?:${rx.source})$`, rx.flags.replace('g', ''));
    FULL_CACHE.set(rx, f);
  }
  return f.exec(text);
}

/** pattern.finditer(text, pos, endpos) */
export function* reFinditer(rx: RegExp, text: string, pos = 0, endpos?: number): Generator<PyMatch> {
  const s = endpos !== undefined && endpos < text.length ? text.slice(0, Math.max(0, endpos)) : text;
  // 같은 RegExp를 중첩해 돌려도 서로 lastIndex를 건드리지 않게 복사본을 쓴다.
  const local = new RegExp(rx.source, rx.flags);
  local.lastIndex = Math.max(0, pos);
  while (local.lastIndex <= s.length) {
    const m = local.exec(s);
    if (!m) return;
    if (m[0] === '') {
      const cp = s.codePointAt(local.lastIndex);
      local.lastIndex += cp !== undefined && cp > 0xffff ? 2 : 1;
    }
    yield m;
  }
}

/** pattern.findall(text) — 그룹이 하나면 그 그룹, 없으면 전체, 여럿이면 튜플(배열) */
export function reFindall(rx: RegExp, text: string): (string | string[])[] {
  const out: (string | string[])[] = [];
  for (const m of reFinditer(rx, text)) {
    if (m.length === 1) out.push(m[0]);
    else if (m.length === 2) out.push(m[1] ?? '');
    else out.push(m.slice(1).map((g) => g ?? ''));
  }
  return out;
}

/** pattern.sub(repl, text) — repl은 고정 문자열(역참조 없음) 또는 함수 */
export function reSub(rx: RegExp, repl: string | ((m: PyMatch) => string), text: string): string {
  let out = '';
  let last = 0;
  for (const m of reFinditer(rx, text)) {
    out += text.slice(last, m.index) + (typeof repl === 'string' ? repl : repl(m));
    last = m.index + m[0].length;
  }
  return out + text.slice(last);
}

/** 매치 그룹 (없으면 Python처럼 null) */
export function grp(m: PyMatch, n: number): string | null {
  return m[n] ?? null;
}

/** Python round(x, ndigits) — 은행가 반올림(정확히 반일 때 짝수 쪽) */
export function pyRound(x: number, ndigits = 0): number {
  if (!Number.isFinite(x)) return x;
  const factor = 10 ** ndigits;
  const y = x * factor;
  const r = Math.round(y);
  const exactHalf = Math.abs(y % 1) === 0.5;
  const v = exactHalf ? (r % 2 === 0 ? r : r - 1) : r;
  return v / factor;
}
