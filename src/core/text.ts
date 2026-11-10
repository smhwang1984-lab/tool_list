// 공통 문자열 처리 — 원본 NC_Tool_List.py code_without_comments / fmt_num / normalize_metadata_key
import { PyError, pyFloat, pyFloatRepr, pyIntStr, pyRe, pyStr, pyStrip, reSub } from './py';

const NC_COMMENT_RE = pyRe(String.raw`\([^)]*\)`);

/** 괄호 주석을 걷어낸 코드 부분만 돌려준다. */
export function codeWithoutComments(line: string | null | undefined): string {
  return reSub(NC_COMMENT_RE, ' ', line || '');
}

/** '38.500000' -> '38.5', '10.000000' -> '10' */
export function fmtNum(s: unknown): string {
  let f: number;
  try {
    f = pyFloat(s);
  } catch (error) {
    if (error instanceof PyError) return pyStrip(pyStr(s));
    throw error;
  }
  if (Number.isNaN(f)) return pyStrip(pyStr(s)); // int(nan) → ValueError
  if (!Number.isFinite(f)) throw new PyError('OverflowError', 'cannot convert float infinity to integer');
  return f === Math.trunc(f) ? pyIntStr(f) : pyFloatRepr(f);
}

export function normalizeMetadataKey(value: string): string {
  return value.toUpperCase().replace(/[^A-Z0-9]/g, '');
}
