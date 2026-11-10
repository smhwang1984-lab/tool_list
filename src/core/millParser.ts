// 밀링 공구 리스트 산출 — 원본 parse_program / _collect_mill_block_checks /
// tool_name_map_from_rows / tool_shape_map_from_rows
import {
  type SpindleCheck, hNumberAlertText, soAlertText, spindleAlertText,
} from './alerts';
import { COLUMNS, blankRow } from './columns';
import { deriveD, deriveType, type NameType } from './nameTypes';
import {
  COMMENT_SO_RE, KV_RE, LATHE_T_RE, M6_RE, N_RE, TOOL_RE,
} from './patterns';
import { formatRemark, radiusCompByN } from './radiusComp';
import { codeWithoutComments, fmtNum } from './text';
import {
  PyError, RE_I, pad2, pyFloat, pyInt, pyRe, pySplitlines, pyStr, pyStrip,
  reFinditer, reFullmatch, reMatch, reSearch,
} from './py';

// 밀링 공구 블록(M6 Tn ~ 다음 M6)의 `S… M3/M4` 회전수와 SPINDL 주석, G43 H번호와 T번호 비교
const MILL_SPINDLE_M_RE = pyRe(String.raw`(?<![A-Z])M0?[34](?!\d)`, RE_I);
const MILL_S_WORD_RE = pyRe(String.raw`(?<![A-Z])S\s*(\d+(?:\.\d*)?)`, RE_I);
const MILL_G43_RE = pyRe(String.raw`(?<![A-Z])G43(?:\.[0-9])?(?![0-9])`, RE_I);
const MILL_H_WORD_RE = pyRe(String.raw`(?<![A-Z])H\s*(\d+)(?![\d.])`, RE_I);
const BLOCK_SPINDL_RE = pyRe(String.raw`\bSPINDL\s+(-?\d+(?:\.\d+)?)`, RE_I);
const TOOL_KEY_RE = pyRe(String.raw`T?(\d+)`);

/** 표 한 행. 열 값은 문자열이고 SPINDL_CHECKS만 목록이다. */
export type MillRow = Record<string, string | SpindleCheck[]>;

interface ToolEntry {
  f: Map<string, string>;
  remarks: string[];
  sChecks: SpindleCheck[];
  hChecks: [number, number][];
  alert?: string;
}

/** 공구 블록 상태: [공구번호, 이 블록 SPINDL 주석(표 값과 같으면 null)] */
type CurBlock = [number | null, string | null];

function setdefault(map: Map<string, string>, key: string, value: string): void {
  if (!map.has(key)) map.set(key, value);
}

function collectMillBlockChecks(tool: ToolEntry, curBlock: CurBlock, lineNo: number, line: string): void {
  const code = codeWithoutComments(line);
  if (code.toUpperCase().includes('S') && reSearch(MILL_SPINDLE_M_RE, code)) {
    const sm = reSearch(MILL_S_WORD_RE, code);
    if (sm) tool.sChecks.push([lineNo, fmtNum(sm[1]!), curBlock[1]]);
  }
  if (reSearch(MILL_G43_RE, code)) {
    const hm = reSearch(MILL_H_WORD_RE, code);
    if (hm) tool.hChecks.push([lineNo, pyInt(hm[1]!)]);
  }
}

/**
 * N번호 ~ 공구 교체 사이의 괄호 주석을 읽어 공구별로 정리한 행 목록.
 * 공구 교체 지점: 밀링 `M6 Tnn`, 선반 `Tnn00` (lathe=true).
 */
export function parseProgram(
  text: string, nameTypes?: readonly (readonly [string, string])[] | null, lathe = false,
): MillRow[] {
  const tools = new Map<number, ToolEntry>();
  let curN: string | null = null;
  let buf: string[] = [];
  const curBlock: CurBlock = [null, null];

  const ensure = (n: number): ToolEntry => {
    let t = tools.get(n);
    if (!t) tools.set(n, (t = { f: new Map(), remarks: [], sChecks: [], hChecks: [] }));
    return t;
  };

  const flush = (num: number): void => {
    const t = ensure(num);
    const block = buf.join('\n');
    if (!lathe) {
      const spm = reSearch(BLOCK_SPINDL_RE, block);
      let blockSpindle: string | null = spm ? fmtNum(spm[1]!) : null;
      // 표 SPINDL은 처음 SPINDL이 나온 블록 값이다 — 그 블록은 표 값과 비교(null)해야
      // [수정]으로 표 SPINDL을 고쳤을 때 다시 비교된다.
      if (!t.f.has('SPINDL')) blockSpindle = null;
      curBlock[0] = num;
      curBlock[1] = blockSpindle;
    }
    const tm = reSearch(TOOL_RE, block);
    if (tm) {
      setdefault(t.f, 'NAME', pyStrip(tm[2]!));
      if (tm[3]) setdefault(t.f, 'SO_NAME', pyStrip(tm[3]));
      setdefault(t.f, 'HOLDER', pyStrip(tm[4]!));
    }
    const sm = reSearch(COMMENT_SO_RE, block);
    if (sm) setdefault(t.f, 'SO_CMT', fmtNum(sm[1]!));
    // 같은 공구가 여러 번 나올 때 어느 블록에서든 어긋나면 강조한다.
    if (tm && tm[3] && sm && !t.alert) t.alert = soAlertText(pyStrip(tm[3]), fmtNum(sm[1]!));
    for (const m of reFinditer(KV_RE, block)) {
      setdefault(t.f, m[1]!.toUpperCase(), fmtNum(m[2]!));
    }
    if (curN && !t.remarks.includes(curN)) t.remarks.push(curN);
  };

  const lines = pySplitlines(text);
  lines.forEach((line, index) => {
    const lineNo = index + 1;
    if (!lathe && curBlock[0] !== null && !reMatch(M6_RE, line)) {
      collectMillBlockChecks(tools.get(curBlock[0])!, curBlock, lineNo, line);
    }
    let m = reMatch(N_RE, line);
    if (m) {
      curN = 'N' + m[1];
      buf = [];
      return;
    }
    if (lathe) {
      // 선반은 T 워드가 블록 어디에 있어도 되므로(예: "N1 G50 S2500 T0100 M08") 주석 뺀 코드에서 찾는다.
      m = reSearch(LATHE_T_RE, codeWithoutComments(line));
      if (m) {
        flush(pyInt(m[1]!));
        buf = [];
        return;
      }
    } else {
      m = reMatch(M6_RE, line);
      if (m) {
        flush(pyInt(m[1]!));
        buf = [];
        // 같은 줄에 S/M3·G43 H가 함께 있어도 새 블록 기준으로 본다.
        collectMillBlockChecks(tools.get(curBlock[0]!)!, curBlock, lineNo, line.slice(m[0].length));
        return;
      }
    }
    if (line.includes('(')) buf.push(line);
  });

  const rows: MillRow[] = [];
  if (!tools.size) return rows;
  // v1.7.8: REMARK에 붙일 경보정(G41/G42) 표기 — N번호 -> "(G41)" 등.
  const radiusComp = radiusCompByN(lines, N_RE);
  // 번호 = 행 위치. 없는 공구번호는 그 행을 빈칸으로 비운다(T1 없으면 1행이 빔).
  const maxN = Math.max(...tools.keys());
  for (let n = 1; n <= maxN; n++) {
    const tool = tools.get(n);
    if (!tool) {
      rows.push(blankRow(COLUMNS));
      continue;
    }
    const f = tool.f;
    const get = (key: string): string => f.get(key) ?? '';
    // R(코너R): RE 값이 있고 0이 아니면 표시, 아니면 빈칸
    const reVal = get('RE');
    let r = '';
    if (reVal !== '') {
      try {
        if (pyFloat(reVal) !== 0) r = reVal;
      } catch (error) {
        if (!(error instanceof PyError)) throw error;
        r = reVal;
      }
    }
    const d = get('DC') || deriveD(get('NAME'));
    rows.push({
      NO: 'T' + pad2(n),
      TYPE: deriveType(get('NAME'), nameTypes as NameType[] | null | undefined),
      NAME: get('NAME'),
      D: d,
      FL: get('FL'),
      LCF: get('LCF'),
      F: get('F'),
      R: r,
      SIG: get('SIG'),
      PL: get('PL'),
      // 주석 SO가 있으면 그 값이 기준, 없으면 공구명 뒤 [SO]
      SO: get('SO_CMT') || get('SO_NAME'),
      GL: get('GL'),
      HOLDER: get('HOLDER'),
      SPINDL: get('SPINDL'),
      FEED: get('FEED'),
      REMARK: formatRemark(tool.remarks, radiusComp),
      SO_NAME: get('SO_NAME'),
      SO_CMT: get('SO_CMT'),
      SO_ALERT: tool.alert ?? '',
      // S값·H번호 일치성. 검사 목록은 [수정] 후 다시 비교할 때 쓴다.
      SPINDL_CHECKS: tool.sChecks.map((c) => [...c] as SpindleCheck),
      SPINDL_ALERT: spindleAlertText(tool.sChecks, get('SPINDL')),
      NO_ALERT: hNumberAlertText(n, tool.hChecks),
    });
  }
  return rows;
}

type AnyRow = Readonly<Record<string, unknown>>;

/** Python dict.get(key, default) — 키가 있으면 값이 null이어도 그 값 */
function rget(row: AnyRow, key: string, fallback: unknown = ''): unknown {
  return Object.prototype.hasOwnProperty.call(row, key) ? row[key] : fallback;
}

/** 뷰어 공정 필터 라벨용: T01 / T1 / 1 → 공구 이름 */
export function toolNameMapFromRows(rows: readonly AnyRow[] | null | undefined): Record<string, string> {
  const mapping: Record<string, string> = {};
  for (const row of rows ?? []) {
    const no = pyStrip(pyStr(rget(row, 'NO'))).toUpperCase();
    const name = pyStrip(pyStr(rget(row, 'NAME')));
    const match = reFullmatch(TOOL_KEY_RE, no);
    if (match) {
      const number = pyInt(match[1]!);
      mapping['T' + pad2(number)] = name;
      mapping['T' + number] = name;
      mapping[String(number)] = name;
    }
  }
  return mapping;
}

/** 숫자로 못 읽으면(빈 칸 포함) null — 공구 형상 값이 없다는 뜻 */
function safeFloat(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null;
  try {
    return pyFloat(value);
  } catch (error) {
    if (error instanceof PyError) return null;
    throw error;
  }
}

export interface ToolShapeValues {
  type: string;
  D: number | null;
  FL: number | null;
  R: number | null;
  SIG: number | null;
  PL: number | null;
  SO: number | null;
}

/** 형상 시뮬레이션용: 뷰어 필터 키(T01/T1/1)마다 TYPE/D/FL/R/SIG/PL/SO를 묶는다(밀링 전용). */
export function toolShapeMapFromRows(rows: readonly AnyRow[] | null | undefined): Record<string, ToolShapeValues> {
  const mapping: Record<string, ToolShapeValues> = {};
  for (const row of rows ?? []) {
    const no = pyStrip(pyStr(rget(row, 'NO'))).toUpperCase();
    const match = reFullmatch(TOOL_KEY_RE, no);
    if (!match) continue;
    const number = pyInt(match[1]!);
    const values: ToolShapeValues = {
      type: pyStrip(pyStr(rget(row, 'TYPE'))),
      D: safeFloat(rget(row, 'D')),
      FL: safeFloat(rget(row, 'FL')),
      R: safeFloat(rget(row, 'R')),
      SIG: safeFloat(rget(row, 'SIG')),
      PL: safeFloat(rget(row, 'PL')),
      SO: safeFloat(rget(row, 'SO')),
    };
    for (const key of ['T' + pad2(number), 'T' + number, String(number)]) mapping[key] = values;
  }
  return mapping;
}
