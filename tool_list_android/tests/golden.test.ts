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

import { ncColorLine } from '../src/core/ncColor';
import {
  decodeCp949, decodeProgramBytes, encodeCp949, encodeProgramText, programTextDigest,
} from '../src/core/programText';
import { bytesToHex, createEditPasswordEntry, editPasswordHash, hexToBytes, verifyEditPassword } from '../src/core/password';
import {
  findNextLiteralSpan, findNextRegexSpan, findNextToolChangeSpan, findPrevRegexSpan, findPrevToolChangeSpan,
  lineHasM00Stop, lineHasM01Stop, lineHasProgramStop, lineStopsPlayback,
} from '../src/core/search';
import { pySplitlines } from '../src/core/py';

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
  // programText / password (PG ADD용 compose_program_texts·append_nc_programs 는 Android 버전에서 제외)
  decode_program_bytes: ([raw]) => {
    const d = decodeProgramBytes(raw as Uint8Array);
    return [d.text, d.encoding, d.newline, d.lossy];
  },
  program_text_digest: ([text]) => programTextDigest(text as string),
  _edit_password_hash: async ([password, salt, iterations]) =>
    editPasswordHash(password, salt as Uint8Array, iterations as number),
  // ncColor / search
  nc_color_line: ([line, state, lathe], kw) =>
    ncColorLine(line as string, state as number | null, Boolean(lathe ?? kw.lathe)),
  find_next_regex_span: ([text, pattern, start], kw) =>
    findNextRegexSpan(text as string, pattern as RegExp, start ?? kw.start ?? 0),
  find_prev_regex_span: ([text, pattern, start], kw) =>
    findPrevRegexSpan(text as string, pattern as RegExp, start ?? kw.start ?? 0),
  find_next_tool_change_span: ([text, start, lathe], kw) =>
    findNextToolChangeSpan(text as string, start ?? kw.start ?? 0, Boolean(lathe ?? kw.lathe)),
  find_prev_tool_change_span: ([text, start, lathe], kw) =>
    findPrevToolChangeSpan(text as string, start ?? kw.start ?? 0, Boolean(lathe ?? kw.lathe)),
  line_has_m00_stop: ([line]) => lineHasM00Stop(line),
  line_has_m01_stop: ([line]) => lineHasM01Stop(line),
  line_has_program_stop: ([line]) => lineHasProgramStop(line),
  line_stops_playback: ([line, needle, stopText, stopM00, stopM01], kw) =>
    lineStopsPlayback(line, needle ?? kw.needle ?? '', Boolean(stopText ?? kw.stop_text ?? false),
      (stopM00 ?? kw.stop_m00 ?? true) as boolean, (stopM01 ?? kw.stop_m01 ?? true) as boolean),
  find_next_literal_span: ([text, needle, start], kw) =>
    findNextLiteralSpan(text as string, needle, start ?? kw.start ?? 0),
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
  compose_program_texts: 'PG ADD(파일 이어붙이기)는 Android 버전에서 제외 (2026-11-10 결정)',
  append_nc_programs: 'PG ADD(파일 이어붙이기)는 Android 버전에서 제외 (2026-11-10 결정)',
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
  if (v instanceof Uint8Array) return { bytes: bytesToHex(v) };
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
    it(`${data.func} — ${data.calls.length}건 일치`, async () => {
      const failures: string[] = [];
      for (const call of data.calls) {
        const args = decode(call.args) as unknown[];
        const kwargs = decode(call.kwargs ?? {}) as Record<string, unknown>;
        let got: unknown;
        let threw: unknown = null;
        try {
          got = normalize(await impl(args, kwargs));
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

// ---------------------------------------------------------------- 파일 인코딩·다이제스트·편집 비밀번호
const PROGRAM_TEXT_FILE = new URL('./golden/program_text.json', import.meta.url);

describe('골든: 파일 인코딩·다이제스트·편집 비밀번호', () => {
  const gold = existsSync(PROGRAM_TEXT_FILE)
    ? (JSON.parse(readFileSync(PROGRAM_TEXT_FILE, 'utf8')) as {
        decode: { hex: string; result: [string, string, string, boolean] }[];
        encode: { text: string; encoding: string; newline: string; hex?: string; error?: string; written?: boolean }[];
        digest: { text: string; sha1: string }[];
        cp949: { lines: number; pairs_mapped: number; injective: boolean; sha1: string };
        password: {
          hash: { password: string; salt: string; iterations: number; hash: string }[];
          verify: { entry: unknown; password: string; result: boolean }[];
          create: { password: string; salt: string; entry: unknown }[];
        };
      })
    : null;
  it('골든이 있다', () => {
    expect(gold).not.toBeNull();
  });
  if (!gold) return;

  it(`바이트 읽기 ${gold.decode.length}건 (UTF-8 / BOM / CP949 / 손실)`, () => {
    for (const c of gold.decode) {
      const d = decodeProgramBytes(hexToBytes(c.hex));
      expect([d.text, d.encoding, d.newline, d.lossy], c.hex).toStrictEqual(c.result);
    }
  });
  it(`저장용 인코딩 ${gold.encode.length}건`, () => {
    for (const c of gold.encode) {
      const label = JSON.stringify([c.text, c.encoding, c.newline]);
      if (c.error) {
        expect(() => encodeProgramText(c.text, c.encoding, c.newline), label).toThrow();
      } else {
        expect(bytesToHex(encodeProgramText(c.text, c.encoding, c.newline)), label).toBe(c.hex);
      }
    }
  });
  it('저장했다가 다시 읽으면 같다 (본문·인코딩·줄바꿈)', () => {
    for (const encoding of ['utf-8', 'utf-8-sig', 'cp949'] as const) {
      for (const newline of ['\n', '\r\n'] as const) {
        const text = '%\nO1234 (한글 주석)\nG0 X1.\nM30\n';
        const d = decodeProgramBytes(encodeProgramText(text, encoding, newline));
        expect([d.text, d.encoding, d.newline, d.lossy]).toStrictEqual([text, encoding, newline, false]);
      }
    }
  });
  it(`SHA-1 다이제스트 ${gold.digest.length}건`, async () => {
    for (const c of gold.digest) expect(await programTextDigest(c.text)).toBe(c.sha1);
  });
  it('CP949 표: 1바이트 256개 + 2바이트 조합 전체가 원본 Python cp949 와 같고 글자마다 바이트가 하나다', async () => {
    const lines: string[] = [];
    const seen = new Map<string, string>();
    let injective = true;
    let mapped = 0;
    const raws: number[][] = [];
    for (let b = 0; b < 256; b++) raws.push([b]);
    for (let a = 0x81; a <= 0xfe; a++) for (let b = 0; b < 256; b++) raws.push([a, b]);
    for (const raw of raws) {
      const hex = bytesToHex(Uint8Array.from(raw));
      try {
        const ch = decodeCp949(Uint8Array.from(raw));
        if (ch === null) throw new Error('invalid');
        lines.push(`${hex}:${bytesToHex(new TextEncoder().encode(ch))}`);
        if (raw.length === 2) {
          mapped++;
          if (seen.has(ch)) injective = false;
          seen.set(ch, hex);
        }
      } catch {
        lines.push(`${hex}:ERR`);
      }
    }
    const digest = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(lines.join('\n')));
    expect({ lines: lines.length, mapped, injective, sha1: bytesToHex(new Uint8Array(digest)) }).toStrictEqual({
      lines: gold.cp949.lines, mapped: gold.cp949.pairs_mapped, injective: gold.cp949.injective, sha1: gold.cp949.sha1,
    });
    // 표에 있는 모든 글자를 되돌리면 원래 바이트가 나온다
    for (const [ch, hex] of seen) expect(bytesToHex(encodeCp949(ch))).toBe(hex);
  });
  it(`비밀번호 해시(PBKDF2) ${gold.password.hash.length}건`, async () => {
    for (const c of gold.password.hash) {
      const got = await editPasswordHash(c.password, hexToBytes(c.salt), c.iterations);
      expect(bytesToHex(got)).toBe(c.hash);
    }
  });
  it(`비밀번호 확인 ${gold.password.verify.length}건 (정상·깨진 설정·기본값 1234)`, async () => {
    const failures: string[] = [];
    for (const c of gold.password.verify) {
      const got = await verifyEditPassword(c.password, c.entry === null ? undefined : c.entry);
      if (got !== c.result) failures.push(`${JSON.stringify(c.entry)} / ${c.password}: ${got} != ${c.result}`);
    }
    expect(failures.slice(0, 10).join('\n')).toBe('');
  });
  it('새 비밀번호 설정 항목이 원본과 똑같이 만들어진다 (같은 salt)', async () => {
    for (const c of gold.password.create) {
      expect(await createEditPasswordEntry(c.password, hexToBytes(c.salt))).toStrictEqual(c.entry);
    }
  });
});

// ---------------------------------------------------------------- 샘플 NC 전체 산출
const FIX_DIR = new URL('./golden/fixtures/', import.meta.url);
const fixtureFiles = existsSync(FIX_DIR) ? readdirSync(FIX_DIR).filter((f) => f.endsWith('.json')) : [];

function readFixtureBytes(name: string): Uint8Array {
  return new Uint8Array(readFileSync(new URL(`./fixtures/${name}`, import.meta.url)));
}

function readFixtureText(name: string): string {
  return decodeProgramBytes(readFixtureBytes(name)).text;
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
      it('인코딩·줄바꿈 판별과 글자 수·SHA-1이 같다', async () => {
        const d = decodeProgramBytes(readFixtureBytes(gold.file));
        const want = gold.decode as unknown as { encoding: string; newline: string; lossy: boolean; length: number; lines: number; sha1: string };
        expect([d.encoding, d.newline, d.lossy]).toStrictEqual([want.encoding, want.newline, want.lossy]);
        expect(Array.from(d.text).length).toBe(want.length);
        expect(pySplitlines(d.text).length).toBe(want.lines);
        expect(await programTextDigest(d.text)).toBe(want.sha1);
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
      it('코드 색 (밀링·선반)', () => {
        const lines = pySplitlines(text);
        for (const lathe of [false, true]) {
          let state = 0;
          const got: unknown[] = [];
          for (const line of lines.slice(0, 4000)) {
            const [spans, next] = ncColorLine(line, state, lathe);
            state = next;
            got.push([...spans, state]);
          }
          expect(diff(normalize(got), g(lathe ? 'color_lathe' : 'color_mill'))).toBeNull();
        }
      });
      it('공구 교체 이동 (다음·이전, 밀링·선반)', () => {
        for (const lathe of [false, true]) {
          const chain: unknown[] = [];
          let pos = 0;
          for (let i = 0; i < 400; i++) {
            const span = findNextToolChangeSpan(text, pos, lathe);
            if (span === null) {
              chain.push(null);
              break;
            }
            chain.push([span, findPrevToolChangeSpan(text, span[0], lathe)]);
            if (span[2]) break;
            pos = span[1];
          }
          expect(diff(normalize(chain), g(lathe ? 'tool_search_lathe' : 'tool_search_mill'))).toBeNull();
        }
      });
      it('정지 줄 (M00·M01)과 문자 검색', () => {
        const lines = pySplitlines(text);
        const idx = (fn: (l: string) => boolean) => lines.flatMap((l, i) => (fn(l) ? [i] : []));
        expect(idx(lineHasM00Stop)).toStrictEqual(gold.stop_m00);
        expect(idx(lineHasM01Stop)).toStrictEqual(gold.stop_m01);
        const literal: unknown[] = [];
        for (const needle of ['G43', 'm30', 'T1', '(', 'SPINDL', 'x']) {
          let pos = 0;
          const chain: unknown[] = [];
          for (let i = 0; i < 30; i++) {
            const span = findNextLiteralSpan(text, needle, pos);
            chain.push(span);
            if (span === null || span[2]) break;
            pos = span[1];
          }
          literal.push({ needle, chain });
        }
        expect(diff(normalize(literal), g('literal_search'))).toBeNull();
      });
      it('선반 공정 필터 이름표', () => {
        expect(latheToolNameMapFromRows(parseLatheProgram(text))).toStrictEqual(g('lathe_tool_name_map'));
      });
    });
  }
});
