// 공구 이름 → TYPE / D — 원본 DEFAULT_NAME_TYPES / clean_name_types / derive_type / derive_d
import { RE_I, pyLen, pyRe, pyStr, pyStrip, reSearch } from './py';

export type NameType = [abbr: string, type: string];

/** 사용자용 기본 목록 (이름 약어 -> TYPE). "이름 경우의 수" 버튼에서 보여 준다. */
export const DEFAULT_NAME_TYPES: readonly NameType[] = [
  ['F.EM', 'FLAT E/M'],
  ['FLAT E/M', 'FLAT E/M'],
  ['FLAT END MILL', 'FLAT E/M'],
  ['R.EM', 'FILLET E/M'],
  ['FILLET E/M', 'FILLET E/M'],
  ['RADIUS E/M', 'FILLET E/M'],
  ['B.EM', 'BALL E/M'],
  ['BALL E/M', 'BALL E/M'],
  ['BALL END MILL', 'BALL E/M'],
  ['DR', 'DRILL'],
  ['DRILL', 'DRILL'],
  ['F.MIL', 'FACE MILL'],
  ['FACE MILL', 'FACE MILL'],
  ['CUT', 'CUTTER'],
  ['CUTTER', 'CUTTER'],
  ['RM', 'REAMER'],
  ['REAMER', 'REAMER'],
  ['C.D', 'CENTER'],
  ['CENTER DRILL', 'CENTER'],
  ['T.CUT', 'T-CUTTER'],
  ['T-CUTTER', 'T-CUTTER'],
  ['DY.EM', 'DYNAMIC E/M'],
  ['DYNAMIC E/M', 'DYNAMIC E/M'],
  ['C.MIL', 'CHAMF MILL'],
  ['CHAMF MILL', 'CHAMF MILL'],
  ['TAP', 'TAP'], // 원본 v2.6.9: 탭은 TYPE이 빈칸이었다
];

function isDict(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === 'object' && !Array.isArray(v);
}

/** `abbr, typ = item` 풀기 — 두 개짜리 리스트/문자열만 된다. 안 되면 null. */
function unpack2(item: unknown): [unknown, unknown] | null {
  if (Array.isArray(item)) return item.length === 2 ? [item[0], item[1]] : null;
  if (typeof item === 'string') {
    const cps = Array.from(item);
    return cps.length === 2 ? [cps[0], cps[1]] : null;
  }
  return null;
}

/** 올바르고 중복 없는 행만 남긴다(표시 순서 유지, 약어는 대소문자 무시로 중복 판정). */
export function cleanNameTypes(items: unknown): NameType[] {
  if (!Array.isArray(items)) return [];
  const clean: NameType[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    let pair: [unknown, unknown] | null;
    if (isDict(item)) pair = ['name' in item ? item.name : '', 'type' in item ? item.type : ''];
    else pair = unpack2(item);
    if (!pair) continue;
    const abbr = pyStrip(pyStr(pair[0]));
    const typ = pyStrip(pyStr(pair[1]));
    if (abbr && typ && !seen.has(abbr.toUpperCase())) {
      clean.push([abbr, typ]);
      seen.add(abbr.toUpperCase());
    }
  }
  return clean;
}

/** 가장 긴 약어부터 맞춰 TYPE을 고른다. name_types를 안 주면 기본 목록. */
export function deriveType(
  name: string | null | undefined,
  nameTypes?: readonly (readonly [string, string])[] | null,
): string {
  const u = (name || '').toUpperCase();
  const mappings = nameTypes ?? DEFAULT_NAME_TYPES;
  const sorted = [...mappings].sort((a, b) => pyLen(b[0]) - pyLen(a[0]));
  for (const [abbr, typ] of sorted) {
    if (u.includes(abbr.toUpperCase())) return typ;
  }
  return '';
}

const DERIVE_D_RE = pyRe(String.raw`D\s*([\d.]+)`, RE_I);

/** 이름에서 지름 "D10" → "10" */
export function deriveD(name: string | null | undefined): string {
  const m = reSearch(DERIVE_D_RE, name || '');
  return m ? m[1]! : '';
}
