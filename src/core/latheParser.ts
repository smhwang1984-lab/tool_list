// 선반 공구 리스트 산출 — 원본 parse_lathe_program (v1.6.5 ~ v2.2.0) 과 보조 함수
//
// 밀링 parse_program 의 N#(#: Tool Change)/[SO ..]/M6 규약과는 완전히 다른, 선반 실제 프로그램
// 양식(O1699.nc)에 맞춘 별도 파서다 — 서로 재사용하지 않는다.
//
// N<번호> 줄 바로 다음에 오는(빈 줄은 건너뛴) 통짜 괄호 주석 최대 두 줄을 홀더(1번째)/인서트(2번째)로 읽는다.
// 그 블록(다음 N 줄 전까지) 안에서 옵셋이 살아있는 Tnnnn(뒤 두 자리 != '00', T0000 제외)을 TOOL NO로 삼고,
// 그런 T워드가 없으면 옵셋 00짜리 T워드를 그대로 쓴다. 같은 TOOL NO가 여러 N 블록에서 쓰이면 한 행으로
// 합치고 REMARK에 N번호를 누적한다 — 옵셋이 다르면(T0101 vs T0111) 별도 행으로 남는다.
import { LATHE_COLUMNS, blankRow } from './columns';
import {
  type FieldSources, type SpecStore, findTags, mergeHints, programHints, resolveFields, stripTags,
} from './latheInsertSpec';
import { formatRemark, radiusCompByN } from './radiusComp';
import { codeWithoutComments } from './text';
import {
  PyError, RE_I, pyFloat, pyInt, pyRe, pySplitlines, pyStr, pyStrip, reFinditer, reFullmatch, reMatch, reSearch, reSub,
} from './py';

export const LATHE_MACHINE_KEYWORD = '선반';

/** N 단독 줄: "N1" */
export const LATHE_N_RE = pyRe(String.raw`^\s*N(\d+)\s*$`);
/** 한 줄 전체가 괄호로만 된 주석 "( T06 - SLEEVE )" */
const LATHE_FULL_COMMENT_LINE_RE = pyRe(String.raw`^\s*\((.*)\)\s*$`);
/** 주석 안의 "T01 - " 같은 공구번호 접두어 */
const LATHE_DESC_PREFIX_RE = pyRe(String.raw`^\s*T\d+\s*-\s*(.*?)\s*$`, RE_I);
/** 블록 안에서 Tnnnn (T0000 제외는 코드에서) */
const LATHE_ANY_T_RE = pyRe(String.raw`T(\d{4})(?!\d)`, RE_I);
/** TOOL NO(T0101)를 공구번호(앞 두 자리)/옵셋(뒤 두 자리)로 쪼갠다 */
const LATHE_TOOL_NO_SPLIT_RE = pyRe(String.raw`^T(\d{2})(\d{2})$`, RE_I);
/** 주석의 "[SO nn]" 표기 */
const LATHE_SO_RE = pyRe(String.raw`\[\s*SO\s*([\d.]+)\s*\]`, RE_I);
/** 옵셋 포함 공구번호만 든 주석 "( T0404 )" — 홀더/인서트가 아니므로 건너뛴다 */
const LATHE_TOOL_NO_COMMENT_RE = pyRe(String.raw`^T\s*\d{2}(?:\d{2})?$`, RE_I);
/** G96/G97(주속 모달), G50/G92(주축 클램프), S<숫자> 토큰 */
const LATHE_SPINDLE_TOKEN_RE = pyRe(String.raw`G9([67])(?!\d)|G(?:50|92)\s*S\s*[\d.]+|S\s*([\d.]+)`, RE_I);
const LATHE_FEED_RE = pyRe(String.raw`F\s*([\d.]+)`, RE_I);
const TRAILING_NUMBER_RE = pyRe(String.raw`([\d.]+)$`);
const NAME_MAP_NO_RE = pyRe(String.raw`T(\d{2})\d{2}`);

/**
 * 선반 행의 값이 어디서 왔는지(NC 주석 태그 / ISO 규격 해석 / 프로그램 / 직접 입력 ...).
 * Python 의 LatheRow(dict).sources 와 같다 — 행 객체 옆에 따로 둬서 열 목록에 섞이지 않게 한다.
 */
const SOURCES = new WeakMap<object, FieldSources>();

export type LatheRow = Record<string, string>;

/** 편집한 행의 값 출처를 붙인다. */
export function setRowSources(row: object, sources: FieldSources): void {
  SOURCES.set(row, sources);
}

/** 이 행의 값 출처. 빈 행(없는 공구번호 자리)이나 복사한 행에는 없다. */
export function rowSources(row: object): FieldSources | undefined {
  return SOURCES.get(row);
}

/** 코드부(주석 제외)에서 SPINDL 표시 문구 목록과 FEED 표시 문구 목록을 등장 순서대로 뽑는다. */
export function latheCollectSpindleFeed(code: string): [spindle: string[], feed: string[]] {
  let mode = '';
  const spindle: string[] = [];
  for (const m of reFinditer(LATHE_SPINDLE_TOKEN_RE, code)) {
    if (m[1]) {
      mode = 'G9' + m[1];
      continue;
    }
    if (m[2]) spindle.push((mode ? mode + 'S' : 'S') + m[2]);
  }
  const feed = [...reFinditer(LATHE_FEED_RE, code)].map((m) => 'F' + m[1]);
  return [spindle, feed];
}

/** SPINDL/FEED 표시 문구에서 정렬용 숫자 크기만 ("G97S800" -> 800, "F.07" -> 0.07) */
export function latheNumericValue(word: string): number {
  const m = reSearch(TRAILING_NUMBER_RE, word);
  if (!m) return 0.0;
  try {
    return pyFloat(m[1]!);
  } catch (error) {
    if (error instanceof PyError) return 0.0;
    throw error;
  }
}

/** 표시 문구 목록을 "최소~최대"로 합친다 (크기가 같으면 하나만, 원문 표기와 모달 접두어 보존) */
export function latheValueRange(words: readonly string[]): string {
  if (!words.length) return '';
  const ordered = [...words].sort((a, b) => latheNumericValue(a) - latheNumericValue(b));
  const lo = ordered[0]!;
  const hi = ordered[ordered.length - 1]!;
  if (latheNumericValue(lo) === latheNumericValue(hi)) return lo;
  return `${lo}~${hi}`;
}

/** 주석 텍스트에서 "T01 - " 식 공구번호 접두어를 걷어낸다. */
export function stripLatheToolPrefix(text: unknown): string {
  const s = pyStrip(text ? pyStr(text) : '');
  const match = reMatch(LATHE_DESC_PREFIX_RE, s);
  return match ? match[1]! : s;
}

interface ToolEntry {
  toolNo: string;
  holder: string;
  insert: string;
  so: string;
  remarks: string[];
  spindle: string[];
  feed: string[];
  tags: Record<string, string>;
  hints: Record<string, unknown>;
}

/** 선반 전용 공구 리스트. store(직접 입력 저장값)가 있으면 [수정] 창에서 넣어 둔 값을 반영한다. */
export function parseLatheProgram(text: string, store?: SpecStore | null): LatheRow[] {
  const lines = pySplitlines(text);
  const nIndices: number[] = [];
  lines.forEach((line, i) => {
    if (reMatch(LATHE_N_RE, line)) nIndices.push(i);
  });
  // REMARK에 붙일 경보정(G41/G42) 표기 — N번호 -> "(G41)" 등.
  const radiusComp = radiusCompByN(lines, LATHE_N_RE);
  const tools = new Map<string, ToolEntry>();
  const order: string[] = [];

  nIndices.forEach((start, pos) => {
    const nLabel = 'N' + reMatch(LATHE_N_RE, lines[start]!)![1];
    const end = pos + 1 < nIndices.length ? nIndices[pos + 1]! : lines.length;
    const block = lines.slice(start + 1, end);

    let comments: string[] = [];
    let commentToolNo = '';
    for (const line of block) {
      if (!pyStrip(line)) continue;
      const commentMatch = reMatch(LATHE_FULL_COMMENT_LINE_RE, line);
      if (commentMatch === null) break;
      const rawComment = pyStrip(commentMatch[1]!);
      if (!comments.length && reMatch(LATHE_TOOL_NO_COMMENT_RE, rawComment)) {
        commentToolNo = rawComment.split(' ').join('').toUpperCase();
        continue;
      }
      comments.push(stripLatheToolPrefix(rawComment));
      if (comments.length >= 2) break;
    }
    let soValue = '';
    const tags: Record<string, string> = {};
    const cleaned: string[] = [];
    for (const commentText of comments) {
      const soMatch = reSearch(LATHE_SO_RE, commentText);
      if (soMatch && !soValue) soValue = soMatch[1]!;
      for (const [tagKey, tagValue] of Object.entries(findTags(commentText))) {
        if (!(tagKey in tags)) tags[tagKey] = tagValue;
      }
      cleaned.push(stripTags(reSub(LATHE_SO_RE, '', commentText)));
    }
    comments = cleaned;
    const holder = comments.length >= 1 ? comments[0]! : '';
    const insert = comments.length >= 2 ? comments[1]! : '';

    let toolNo = '';
    let fallbackToolNo = '';
    for (const line of block) {
      const code = codeWithoutComments(line);
      let found = false;
      for (const match of reFinditer(LATHE_ANY_T_RE, code)) {
        const digits = match[1]!;
        if (digits === '0000') continue;
        if (digits.slice(2) !== '00') {
          toolNo = 'T' + digits;
          found = true;
          break;
        }
        if (!fallbackToolNo) fallbackToolNo = 'T' + digits;
      }
      if (found) break;
    }
    if (!toolNo) toolNo = fallbackToolNo;
    // 블록 코드에 T워드가 전혀 없을 때만, 건너뛴 "( T0404 )" 주석의 4자리 값을 TOOL NO로 쓴다
    // (2자리 "( T04 )"는 옵셋을 알 수 없어 제외).
    if (!toolNo && commentToolNo.length === 5) toolNo = commentToolNo;

    // SPINDL/FEED는 블록 전체 코드(여러 줄에 걸친 G96/G97 모달 추적이 필요)를 한 번에 이어붙여 스캔한다.
    const blockCodeLines = block.map((line) => codeWithoutComments(line));
    const [blockSpindle, blockFeed] = latheCollectSpindleFeed(blockCodeLines.join('\n'));
    const blockHints = programHints(blockCodeLines);

    const key = toolNo || `__N${start}__`;
    let entry = tools.get(key);
    if (!entry) {
      entry = { toolNo, holder: '', insert: '', so: '', remarks: [], spindle: [], feed: [], tags: {}, hints: {} };
      tools.set(key, entry);
    }
    if (!entry.holder) entry.holder = holder;
    if (!entry.insert) entry.insert = insert;
    if (!entry.so) entry.so = soValue;
    for (const [tagKey, tagValue] of Object.entries(tags)) {
      if (!(tagKey in entry.tags)) entry.tags[tagKey] = tagValue;
    }
    entry.hints = mergeHints(entry.hints, blockHints);
    entry.spindle.push(...blockSpindle);
    entry.feed.push(...blockFeed);
    if (!entry.remarks.includes(nLabel)) entry.remarks.push(nLabel);
    if (!order.includes(key)) order.push(key);
  });

  const rowFor = (key: string): LatheRow => {
    const entry = tools.get(key)!;
    const [values, sources] = resolveFields(entry.insert, entry.holder, entry.tags, entry.hints, store);
    const row: LatheRow = {
      NO: entry.toolNo,
      INSERT: entry.insert,
      R: values.R,
      T: values.T,
      PITCH: values.PITCH,
      HOLDER: entry.holder,
      SO: entry.so,
      KIND: values.KIND,
      DIR: values.DIR,
      TIP: values.TIP,
      D: values.D,
      SPINDL: latheValueRange(entry.spindle),
      FEED: latheValueRange(entry.feed),
      REMARK: formatRemark(entry.remarks, radiusComp),
    };
    SOURCES.set(row, sources);
    return row;
  };

  // MCT 툴리스트와 같은 모양으로 정렬한다 — 공구번호 순 + 빠진 번호는 빈 행. TOOL NO 의 앞 두 자리가
  // 공구번호, 뒤 두 자리가 옵셋(같은 공구번호 안에서는 옵셋 오름차순, T0101/T0111처럼 옵셋이 다르면 별도 행).
  // T워드를 못 찾은 항목은 번호를 매길 수 없으므로 정렬된 본문 뒤에 원래 순서 그대로 붙인다.
  const numbered: [number, number, string][] = [];
  const unnumberedKeys: string[] = [];
  for (const key of order) {
    const split = reMatch(LATHE_TOOL_NO_SPLIT_RE, pyStrip(tools.get(key)!.toolNo || '').toUpperCase());
    if (split) numbered.push([pyInt(split[1]!), pyInt(split[2]!), key]);
    else unnumberedKeys.push(key);
  }

  const rows: LatheRow[] = [];
  if (numbered.length) {
    numbered.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const keysByToolNum = new Map<number, string[]>();
    for (const [toolNum, , key] of numbered) {
      const list = keysByToolNum.get(toolNum) ?? [];
      list.push(key);
      keysByToolNum.set(toolNum, list);
    }
    const maxNum = Math.max(...keysByToolNum.keys());
    for (let toolNum = 1; toolNum <= maxNum; toolNum++) {
      const keys = keysByToolNum.get(toolNum);
      if (!keys) {
        rows.push(blankRow(LATHE_COLUMNS));
        continue;
      }
      rows.push(...keys.map(rowFor));
    }
  }
  rows.push(...unnumberedKeys.map(rowFor));
  return rows;
}

/** 3D 뷰어 공정 필터 라벨용 — 선반은 INSERT 를 공구 이름으로 쓴다. 뷰어 키는 T01 (옵셋 없는 2자리). */
export function latheToolNameMapFromRows(
  rows: readonly Readonly<Record<string, unknown>>[] | null | undefined,
): Record<string, string> {
  const mapping: Record<string, string> = {};
  for (const row of rows ?? []) {
    const no = pyStrip(pyStr(Object.prototype.hasOwnProperty.call(row, 'NO') ? row.NO : '')).toUpperCase();
    const insert = pyStrip(pyStr(Object.prototype.hasOwnProperty.call(row, 'INSERT') ? row.INSERT : ''));
    const match = reFullmatch(NAME_MAP_NO_RE, no);
    if (match && insert) {
      const key = 'T' + match[1];
      if (!(key in mapping)) mapping[key] = insert;
    }
  }
  return mapping;
}

/** 장비 이름으로 선반 여부를 판정한다. */
export function isLatheMachine(machineType: unknown): boolean {
  return (machineType ? pyStr(machineType) : '').includes(LATHE_MACHINE_KEYWORD);
}
