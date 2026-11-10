// 골든 비교 — 원본 Python 결과(tests/golden/**)와 TS 이식본 결과가 같은지 본다.
// 골든은 tools/golden/export_golden.py 로 만든다(WORK_PLAN P1 §1.1).
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PyError, pyRe } from '../src/core/py';
import { codeWithoutComments, fmtNum, normalizeMetadataKey } from '../src/core/text';
import { defaultPdfFilename, parseProgramMetadata, programHeaderText } from '../src/core/metadata';
import { cleanNameTypes, deriveD, deriveType } from '../src/core/nameTypes';
import { collectRadiusCompCodes, formatCompSuffix, formatRemark, subprogramBodies } from '../src/core/radiusComp';
import { parseProgram, toolNameMapFromRows, toolShapeMapFromRows } from '../src/core/millParser';
import { hNumberAlertText, lineListText, sameNumber, soAlertText, spindleAlertText } from '../src/core/alerts';
import * as lis from '../src/core/latheInsertSpec';
import { LatheSpecStore } from '../src/core/latheSpecStore';
import {
  type LatheRow, isLatheMachine, latheCollectSpindleFeed, latheNumericValue, parseLatheProgram,
  latheToolNameMapFromRows, latheValueRange, rowSources, stripLatheToolPrefix,
} from '../src/core/latheParser';

/** 선반 행 -> 골든과 같은 모양: 출처가 있는 행은 {row, sources}, 빈 행은 그대로 */
function wrapLatheRows(rows: LatheRow[]): unknown[] {
  return rows.map((row) => {
    const sources = rowSources(row);
    return sources ? { row: { ...row }, sources: { ...sources } } : { ...row };
  });
}

type Fn = (args: unknown[], kwargs: Record<string, unknown>) => unknown;

/** LatheRow 는 {row, sources} 로 풀려 온다 — 행만 꺼낸다 */
const rowOf = (x: unknown): Record<string, unknown> =>
  (x && typeof x === 'object' && 'row' in (x as object) ? (x as { row: Record<string, unknown> }).row : x) as Record<string, unknown>;

/** 원본 함수 이름 → TS 구현 (인자는 Python 위치 인자 그대로) */
const IMPL: Record<string, Fn> = {
  code_without_comments: ([line]) => codeWithoutComments(line as string),
  fmt_num: ([s]) => fmtNum(s),
  normalize_metadata_key: ([v]) => normalizeMetadataKey(v as string),
  parse_program_metadata: ([t]) => parseProgramMetadata(t as string),
  program_header_text: ([t]) => programHeaderText(t as string),
  clean_name_types: ([items]) => cleanNameTypes(items),
  derive_type: ([name, types], kw) =>
    deriveType(name as string, (types ?? kw.name_types ?? null) as [string, string][] | null),
  derive_d: ([name]) => deriveD(name as string),
  default_pdf_filename: ([m]) => defaultPdfFilename(m as Record<string, unknown>),
  // radiusComp
  _subprogram_bodies: ([lines]) => subprogramBodies(lines as string[]),
  _collect_radius_comp_codes: ([code]) => collectRadiusCompCodes(code as string),
  _format_comp_suffix: ([codes]) => formatCompSuffix(codes as string[]),
  _format_remark: ([labels, comp]) => formatRemark(labels as string[], comp as Record<string, string>),
  // alerts
  _same_number: ([a, b]) => sameNumber(a, b),
  _line_list_text: ([nums]) => lineListText(nums as number[]),
  spindle_alert_text: ([checks, table]) => spindleAlertText(checks as never, table),
  h_number_alert_text: ([n, checks]) => hNumberAlertText(n as number, checks as never),
  so_alert_text: ([a, b]) => soAlertText(a, b),
  // millParser
  parse_program: ([text, types], kw) =>
    parseProgram(text as string, (types ?? kw.name_types ?? null) as never, Boolean(kw.lathe)),
  tool_name_map_from_rows: ([rows]) => toolNameMapFromRows(rows as never),
  tool_shape_map_from_rows: ([rows]) => toolShapeMapFromRows(rows as never),
  // latheParser
  _lathe_collect_spindle_feed: ([code]) => latheCollectSpindleFeed(code as string),
  _lathe_numeric_value: ([w]) => latheNumericValue(w as string),
  _lathe_value_range: ([words]) => latheValueRange(words as string[]),
  _strip_lathe_tool_prefix: ([t]) => stripLatheToolPrefix(t),
  parse_lathe_program: ([text]) => wrapLatheRows(parseLatheProgram(text as string)),
  lathe_tool_name_map_from_rows: ([rows]) => latheToolNameMapFromRows((rows as unknown[]).map(rowOf) as never),
  is_lathe_machine: ([m]) => isLatheMachine(m),
  // latheInsertSpec (원본 lathe_insert_spec.py)
  'lis.fmt_number': ([v]) => lis.fmtNumber(v),
  'lis.normalize_key': ([v]) => lis.normalizeKey(v),
  'lis.strip_tags': ([v]) => lis.stripTags(v),
  'lis.find_tags': ([v]) => lis.findTags(v),
  'lis._clean_number': ([v]) => lis.cleanNumber(v),
  'lis._float': ([v]) => lis.floatOrNull(v),
  'lis.edge_length_from_ic': ([shape, ic]) => lis.edgeLengthFromIc(shape as string, ic as number),
  'lis.size_code_for_ic': ([shape, ic]) => lis.sizeCodeForIc(shape as string, ic as number),
  'lis.ic_for_size_code': ([shape, code, clearance]) =>
    lis.icForSizeCode(shape as string, code as number, (clearance ?? 'N') as string),
  'lis.parse_insert': ([t]) => lis.parseInsert(t),
  'lis.parse_thread_insert': ([t]) => lis.parseThreadInsert(t),
  'lis.parse_groove_insert': ([t]) => lis.parseGrooveInsert(t),
  'lis.parse_tool_diameter': ([t]) => lis.parseToolDiameter(t),
  'lis.parse_holder': ([t]) => lis.parseHolder(t),
  'lis.program_hints': ([lines]) => lis.programHints(lines as string[]),
  'lis.merge_hints': ([a, b]) => lis.mergeHints(a as never, b as never),
  'lis.infer_kind': ([i, h, hints]) => lis.inferKind(i, h, hints as never),
  'lis.infer_direction': ([kind, i, h]) => lis.inferDirection(kind as string, i, h),
  'lis.infer_tip': ([kind, hand]) => lis.inferTip(kind as string, hand),
  'lis.iso_values': ([i, h]) => lis.isoValues(i, h ?? ''),
  'lis.resolve_fields': ([i, h, tags, hints], kw) =>
    lis.resolveFields(i, h, (tags ?? kw.tags ?? null) as never, (hints ?? kw.hints ?? null) as never, null),
  'lis.recommend_fields': ([i, h]) => lis.recommendFields(i, h),
  'lis.describe_insert': ([t]) => lis.describeInsert(t),
  'lis.describe_holder': ([t]) => lis.describeHolder(t),
  'lis.chamfer_angle': ([t]) => lis.chamferAngle(t),
  'lis.mill_type_for': ([kind, i]) => lis.millTypeFor(kind as string, i ?? ''),
  'lis.geometry_from_row': ([row]) => lis.geometryFromRow(rowOf(row)),
  'lis.geometry_map_from_rows': ([rows]) => lis.geometryMapFromRows((rows as unknown[]).map(rowOf)),
};

/** 일부러 TS로 옮기지 않는 함수 (이유) */
const NOT_PORTED: Record<string, string> = {
  'lis.specs_path': '저장 파일 경로 조립은 platform/ 에서(Android는 Preferences/앱 폴더)',
};

interface CallRecord {
  args: unknown[];
  kwargs?: Record<string, unknown>;
  result?: unknown;
  raises?: string;
}

/** JSON 특수 표기를 JS 값으로 */
function decode(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(decode);
  if (v && typeof v === 'object') {
    const o = v as Record<string, unknown>;
    if ('__bytes__' in o) return Uint8Array.from(Buffer.from(o.__bytes__ as string, 'hex'));
    if ('__float__' in o) {
      const s = o.__float__ as string;
      return s === 'nan' ? NaN : s.startsWith('-') ? -Infinity : Infinity;
    }
    if ('__re__' in o) return pyRe(o.__re__ as string, o.flags as number);
    if ('__pairs__' in o) return new Map((o.__pairs__ as unknown[][]).map(([k, x]) => [decode(k), decode(x)]));
    if ('__lathe_row__' in o) return { row: decode(o.__lathe_row__), sources: decode(o.sources) };
    return Object.fromEntries(Object.entries(o).map(([k, x]) => [k, decode(x)]));
  }
  return v;
}

/** TS 결과를 비교 가능한 모양으로 (Map → 객체, 튜플/배열 그대로) */
function normalize(v: unknown): unknown {
  if (v instanceof Map) return Object.fromEntries([...v].map(([k, x]) => [String(k), normalize(x)]));
  if (Array.isArray(v)) return v.map(normalize);
  if (v && typeof v === 'object') {
    return Object.fromEntries(Object.entries(v as object).map(([k, x]) => [k, normalize(x)]));
  }
  return v;
}

/**
 * 깊은 비교. 문자열·정수·구조는 엄격하고, 소수는 마지막 자리 차이(상대 1e-12)까지 같게 본다 —
 * sin/tan 같은 삼각함수는 JS와 C 라이브러리의 마지막 자리가 다를 수 있다.
 */
function diff(a: unknown, b: unknown, path = '$'): string | null {
  if (typeof a === 'number' && typeof b === 'number') {
    if (a === b || (Number.isNaN(a) && Number.isNaN(b))) return null;
    const tolerance = 1e-12 * Math.max(1, Math.abs(a), Math.abs(b));
    return Math.abs(a - b) <= tolerance ? null : `${path}: ${a} != ${b}`;
  }
  if (Array.isArray(a) && Array.isArray(b)) {
    if (a.length !== b.length) return `${path}: 길이 ${a.length} != ${b.length}`;
    for (let i = 0; i < a.length; i++) {
      const d = diff(a[i], b[i], `${path}[${i}]`);
      if (d) return d;
    }
    return null;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object' && !Array.isArray(a) && !Array.isArray(b)) {
    const ka = Object.keys(a).sort();
    const kb = Object.keys(b).sort();
    if (ka.join('\u0000') !== kb.join('\u0000')) return `${path}: 키 ${JSON.stringify(ka)} != ${JSON.stringify(kb)}`;
    for (const k of ka) {
      const d = diff((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k], `${path}.${k}`);
      if (d) return d;
    }
    return null;
  }
  return a === b ? null : `${path}: ${JSON.stringify(a)} != ${JSON.stringify(b)}`;
}

const CALLS_DIR = new URL('./golden/calls/', import.meta.url);
const files = existsSync(CALLS_DIR) ? readdirSync(CALLS_DIR).filter((f) => f.endsWith('.json')) : [];

describe('골든: 원본 함수 호출 기록', () => {
  it('골든 파일이 있다', () => {
    expect(files.length).toBeGreaterThan(0);
  });
  for (const file of files) {
    const data = JSON.parse(readFileSync(new URL(file, CALLS_DIR), 'utf8')) as { func: string; calls: CallRecord[] };
    const impl = IMPL[data.func];
    if (!impl) {
      if (data.func in NOT_PORTED) continue;
      it.todo(`${data.func} (${data.calls.length}건)`);
      continue;
    }
    it(`${data.func} — ${data.calls.length}건 일치`, () => {
      const failures: string[] = [];
      for (const call of data.calls) {
        const args = decode(call.args) as unknown[];
        const kwargs = decode(call.kwargs ?? {}) as Record<string, unknown>;
        let got: unknown;
        let threw: unknown = null;
        try {
          got = normalize(impl(args, kwargs));
        } catch (error) {
          threw = error;
        }
        const label = JSON.stringify(call.args).slice(0, 200);
        if (call.raises) {
          if (!threw) failures.push(`${label}\n  기대: ${call.raises} 예외 / 실제: ${JSON.stringify(got)}`);
          else if (threw instanceof PyError && threw.pyType !== call.raises) {
            failures.push(`${label}\n  기대: ${call.raises} / 실제: ${threw.pyType}`);
          }
          continue;
        }
        if (threw) {
          failures.push(`${label}\n  예외: ${String(threw)}`);
          continue;
        }
        const want = normalize(decode(call.result));
        const d = diff(got, want);
        if (d) failures.push(`${label}\n  ${d}\n  기대: ${JSON.stringify(want).slice(0, 300)}\n  실제: ${JSON.stringify(got).slice(0, 300)}`);
      }
      expect(failures.slice(0, 15).join('\n')).toBe('');
    });
  }
});

// ---------------------------------------------------------------- 선반 스펙 저장소
interface StoreCase {
  raw: string;
  insert: unknown;
  tool: unknown;
  queries: {
    insert_text: string; holder_text: string; insert_key: string; tool_key: string;
    get_insert: unknown; get_tool: unknown;
  }[];
  resolves: { args: [string, string, Record<string, string>, Record<string, unknown> | null]; values: unknown; sources: unknown }[];
  parses: { file: string; rows: unknown }[];
}

const STORE_FILE = new URL('./golden/lathe_store.json', import.meta.url);

describe('골든: 선반 스펙 저장소 (직접 입력 저장값)', () => {
  const gold = existsSync(STORE_FILE)
    ? (JSON.parse(readFileSync(STORE_FILE, 'utf8')) as {
        cases: StoreCase[];
        updates: { raw: string; ops: unknown[][]; insert: unknown; tool: unknown }[];
      })
    : null;
  it('골든이 있다', () => {
    expect(gold).not.toBeNull();
  });
  gold?.cases.forEach((c, index) => {
    describe(`사례 ${index + 1}`, () => {
      const store = new LatheSpecStore(c.raw);
      it('파일 내용을 원본과 똑같이 읽는다', () => {
        expect(diff(store.insert, c.insert)).toBeNull();
        expect(diff(store.tool, c.tool)).toBeNull();
      });
      it('키와 저장값 조회', () => {
        for (const q of c.queries) {
          expect(LatheSpecStore.insertKey(q.insert_text, q.holder_text)).toBe(q.insert_key);
          expect(LatheSpecStore.toolKey(q.holder_text, q.insert_text)).toBe(q.tool_key);
          expect(store.getInsert(q.insert_text, q.holder_text)).toStrictEqual(q.get_insert);
          expect(store.getTool(q.holder_text, q.insert_text)).toStrictEqual(q.get_tool);
        }
      });
      it(`선반 공구 리스트 전체 산출(저장소 포함) ${c.parses.length}개 파일`, () => {
        const failures: string[] = [];
        for (const p of c.parses) {
          const got = normalize(wrapLatheRows(parseLatheProgram(readFixtureText(p.file), store)));
          const d = diff(got, normalize(decode(p.rows)));
          if (d) failures.push(`${p.file}\n  ${d}`);
        }
        expect(failures.join('\n')).toBe('');
      });
      it(`resolve_fields(저장소 포함) ${c.resolves.length}건`, () => {
        const failures: string[] = [];
        for (const r of c.resolves) {
          const [i, h, tags, hints] = r.args;
          const [values, sources] = lis.resolveFields(i, h, tags, hints as never, store);
          const d = diff(values, r.values) ?? diff(sources, r.sources);
          if (d) failures.push(`${JSON.stringify(r.args)}\n  ${d}`);
        }
        expect(failures.slice(0, 10).join('\n')).toBe('');
      });
    });
  });
  gold?.updates.forEach((u, index) => {
    it(`저장값 갱신 ${index + 1}`, () => {
      const store = new LatheSpecStore(u.raw);
      for (const op of u.ops) {
        if (op[0] === 'update_insert') store.updateInsert(op[1], op[2] as never, op[3]);
        else store.updateTool(op[1], op[2], op[3] as never);
      }
      expect(diff(store.insert, u.insert)).toBeNull();
      expect(diff(store.tool, u.tool)).toBeNull();
    });
  });
});

// ---------------------------------------------------------------- 샘플 NC 전체 산출
const FIX_DIR = new URL('./golden/fixtures/', import.meta.url);
const fixtureFiles = existsSync(FIX_DIR) ? readdirSync(FIX_DIR).filter((f) => f.endsWith('.json')) : [];

/** 임시 디코더 — 인코딩 판별·저장은 P1-T7(programText)에서 원본과 똑같이 이식한다. */
function readFixtureText(name: string): string {
  const raw = readFileSync(new URL(`./fixtures/${name}`, import.meta.url));
  let text: string;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(raw);
  } catch {
    text = new TextDecoder('euc-kr').decode(raw);
  }
  return text.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
}

describe('골든: 샘플 NC 전체 산출', () => {
  it('샘플이 있다', () => {
    expect(fixtureFiles.length).toBeGreaterThan(0);
  });
  for (const file of fixtureFiles) {
    const gold = JSON.parse(readFileSync(new URL(file, FIX_DIR), 'utf8')) as Record<string, unknown> & {
      file: string; decode: { length: number; lines: number };
    };
    describe(gold.file, () => {
      const text = readFixtureText(gold.file);
      const g = (key: string) => normalize(decode(gold[key]));
      it('글자 수가 같다', () => {
        expect(Array.from(text).length).toBe(gold.decode.length);
      });
      it('출력 정보·좌상단 문구·PDF 파일명', () => {
        const metadata = parseProgramMetadata(text);
        expect(metadata).toStrictEqual(g('metadata'));
        expect(programHeaderText(text)).toBe(gold.header);
        expect(defaultPdfFilename(metadata)).toBe(gold.pdf_filename);
      });
      it('밀링 공구 리스트', () => {
        expect(normalize(parseProgram(text))).toStrictEqual(g('mill_rows'));
      });
      it('밀링 공구 리스트 (lathe 표시)', () => {
        expect(normalize(parseProgram(text, null, true))).toStrictEqual(g('mill_rows_lathe_flag'));
      });
      it('밀링 공구 리스트 (이름표 직접 지정)', () => {
        const types: [string, string][] = [['EM', 'END MILL'], ['DR', 'DRILL X']];
        expect(normalize(parseProgram(text, types))).toStrictEqual(g('mill_rows_custom_types'));
      });
      it('공정 필터 이름표', () => {
        expect(toolNameMapFromRows(parseProgram(text))).toStrictEqual(g('tool_name_map'));
      });
      it('선반 공구 리스트 (행 + 값 출처)', () => {
        const d = diff(normalize(wrapLatheRows(parseLatheProgram(text))), g('lathe_rows'));
        expect(d).toBeNull();
      });
      it('선반 공정 필터 이름표', () => {
        expect(latheToolNameMapFromRows(parseLatheProgram(text))).toStrictEqual(g('lathe_tool_name_map'));
      });
    });
  }
});
