// 골든 비교 — 원본 Python 결과(tests/golden/calls/*.json)와 TS 이식본 결과가 같은지 본다.
// 골든은 tools/golden/export_golden.py 로 만든다(WORK_PLAN P1 §1.1).
import { existsSync, readdirSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { PyError, pyRe } from '../src/core/py';
import { codeWithoutComments, fmtNum, normalizeMetadataKey } from '../src/core/text';
import { defaultPdfFilename, parseProgramMetadata, programHeaderText } from '../src/core/metadata';
import { cleanNameTypes, deriveD, deriveType } from '../src/core/nameTypes';
import { collectRadiusCompCodes, formatCompSuffix, formatRemark, subprogramBodies } from '../src/core/radiusComp';
import { hNumberAlertText, lineListText, sameNumber, soAlertText, spindleAlertText } from '../src/core/alerts';

type Fn = (args: unknown[], kwargs: Record<string, unknown>) => unknown;

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
        try {
          expect(got).toStrictEqual(want);
        } catch {
          failures.push(`${label}\n  기대: ${JSON.stringify(want).slice(0, 300)}\n  실제: ${JSON.stringify(got).slice(0, 300)}`);
        }
      }
      expect(failures.slice(0, 15).join('\n')).toBe('');
    });
  }
});
