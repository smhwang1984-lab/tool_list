// 경고 문구 — 원본 spindle_alert_text / h_number_alert_text / so_alert_text (v2.2.6, v2.3.2)
import { fmtNum } from './text';
import { PyError, pad2, pyFloat, pyStr, pyStrip } from './py';
import { deriveD } from './nameTypes';

export const SPINDLE_TOLERANCE_RPM = 1.0; // 1rpm 미만 차이는 같은 값
export const ALERT_MAX_LINES = 4;

const isNoneOrEmpty = (v: unknown) => v === null || v === undefined || v === '';

export function sameNumber(a: unknown, b: unknown): boolean {
  try {
    return Math.abs(pyFloat(a) - pyFloat(b)) < 1e-9;
  } catch (error) {
    if (!(error instanceof PyError)) throw error;
    return pyStrip(pyStr(a)) === pyStrip(pyStr(b));
  }
}

export function lineListText(lineNumbers: readonly number[]): string {
  const shown = lineNumbers.slice(0, ALERT_MAX_LINES).map((n) => pyStr(n)).join(', ');
  const extra = lineNumbers.length - ALERT_MAX_LINES;
  return shown + (extra > 0 ? `행 외 ${extra}곳` : '행');
}

/** 밀링 S 검사 한 건: [줄번호, 프로그램 S, 블록 SPINDL 주석 또는 null(표 값과 비교)] */
export type SpindleCheck = [lineNo: number, programS: string, blockRef: string | null];

/** 공구 하나의 S 검사 목록 → 불일치 안내 문구(일치하면 '') */
export function spindleAlertText(checks: readonly SpindleCheck[] | null | undefined, tableSpindle: unknown): string {
  const groups = new Map<string, { s: string; ref: string; nums: number[] }>();
  for (const [lineNo, programS, blockRef] of checks ?? []) {
    const ref = isNoneOrEmpty(blockRef) ? tableSpindle : blockRef;
    try {
      if (Math.abs(pyFloat(programS) - pyFloat(ref)) < SPINDLE_TOLERANCE_RPM) continue;
    } catch (error) {
      if (error instanceof PyError) continue; // 비교할 SPINDL 값이 없음
      throw error;
    }
    const s = fmtNum(programS);
    const r = fmtNum(ref);
    const key = JSON.stringify([s, r]);
    let group = groups.get(key);
    if (!group) groups.set(key, (group = { s, ref: r, nums: [] }));
    group.nums.push(lineNo);
  }
  const lines = [...groups.values()].map((g) => `프로그램 S${g.s} (${lineListText(g.nums)}) / SPINDL ${g.ref}`);
  if (lines.length && !isNoneOrEmpty(tableSpindle)
    && [...groups.values()].some((g) => g.ref !== fmtNum(tableSpindle))) {
    lines.push(`(툴리스트 SPINDL ${fmtNum(tableSpindle)})`);
  }
  return lines.join('\n');
}

/** T번호와 다른 G43 H번호가 있으면 안내 문구. hChecks: [줄번호, H번호] */
export function hNumberAlertText(toolNumber: number, hChecks: readonly (readonly [number, number])[] | null | undefined): string {
  const groups = new Map<number, number[]>();
  for (const [lineNo, h] of hChecks ?? []) {
    if (h !== toolNumber) {
      const nums = groups.get(h) ?? [];
      nums.push(lineNo);
      groups.set(h, nums);
    }
  }
  return [...groups].map(([h, nums]) => `T${pad2(toolNumber)} 블록에서 H${pad2(h)} 사용 (${lineListText(nums)})`).join('\n');
}

/** 원본 v2.6.9 d_alert_text: 공구명 지름(D10)과 주석 DC가 둘 다 있고 값이 다르면 안내 문구 */
export function dAlertText(nameD: unknown, commentDc: unknown): string {
  if (isNoneOrEmpty(nameD) || isNoneOrEmpty(commentDc)) return '';
  if (sameNumber(nameD, commentDc)) return '';
  return `공구명 D${pyStr(nameD)} / 주석 DC ${pyStr(commentDc)}`;
}

/** 표 한 행의 D 경고: 파서가 만든 D_ALERT가 있으면 그것, [수정]으로 D_ALERT가 지워졌으면 공구명 D와 표 D를 다시 비교 */
export function dRowAlert(row: Readonly<Record<string, unknown>>): string {
  const text = (k: string) => (row[k] === undefined || row[k] === null ? '' : String(row[k]));
  if ('D_ALERT' in row) return text('D_ALERT');
  const nameD = deriveD(text('NAME'));
  const shown = text('D').trim();
  return nameD && shown && !sameNumber(nameD, shown) ? `공구명 D${nameD} / 표 D${shown}` : '';
}

/** 공구명 SO와 주석 SO가 둘 다 있고 값이 다르면 안내 문구 */
export function soAlertText(nameSo: unknown, commentSo: unknown): string {
  if (isNoneOrEmpty(nameSo) || isNoneOrEmpty(commentSo)) return '';
  if (sameNumber(nameSo, commentSo)) return '';
  return `공구명 SO ${pyStr(nameSo)} / 주석 SO ${pyStr(commentSo)}`;
}
