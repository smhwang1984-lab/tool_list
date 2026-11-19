// REMARK 경보정(G41/G42) 표기 — 원본 _subprogram_bodies ~ _format_remark (v1.7.8)
// 밀링/선반 REMARK 조립에 같이 쓴다. M98 P<n>로 부르는 서브프로그램 안의 G41/G42도 호출한 N에 포함한다.
import { codeWithoutComments } from './text';
import { RE_I, pyInt, pyRe, reFinditer, reMatch, reSearch } from './py';
import { M6_RE } from './patterns';

export const RADIUS_COMP_RE = pyRe(String.raw`G0*4([12])(?![\d.])`, RE_I);
/** 화면/PDF에서 굵게 그릴 "(G41)" "(G41/G42)" 부분 */
export const RADIUS_COMP_DISPLAY_RE = pyRe(
  String.raw`\(G4[12](?:/G4[12])*\)|\(M[23]00(?:H\d+(?:≠H\d+)?)?\)|(?<![A-Za-z\d])M[23]00(?:H\d+(?:≠H\d+)?)?(?!\d)`,
);
/** v2.3.7: M300/M200(H번호) 표기 "(M300H1)" — 공정의 G43 H(없으면 M6 T)와 다르면 "(M300H2≠H1)" 로 적고 빨간 글씨로 그린다 */
const M_PROBE_RE = pyRe(String.raw`(?<![A-Z])M0*([23]00)(?![\d.])\s*(?:H\s*0*(\d+)(?![\d.]))?`, RE_I);
export const RADIUS_COMP_MISMATCH_RE = pyRe(String.raw`\(?M[23]00H\d+≠H\d+\)?`);
const G43_RE = pyRe(String.raw`(?<![A-Z])G43(?:\.[0-9])?(?![0-9])`, RE_I);
const H_WORD_RE = pyRe(String.raw`(?<![A-Z])H\s*(\d+)(?![\d.])`, RE_I);
const SUBPROGRAM_O_HEADER_RE = pyRe(String.raw`^\s*O\s*0*(\d+)\b`, RE_I);
const SUBPROGRAM_CALL_RE = pyRe(String.raw`M98\s*P\s*0*(\d+)`, RE_I);
const SUBPROGRAM_RETURN_RE = pyRe(String.raw`M0?99\b`, RE_I);

/** O<번호> -> [본문 시작 줄, 끝 줄). 본문은 O헤더 다음 줄부터 첫 M99 줄까지(없으면 다음 O헤더 전까지). */
export function subprogramBodies(lines: readonly string[]): Map<number, [number, number]> {
  const headers: [number, number][] = [];
  lines.forEach((line, i) => {
    const m = reMatch(SUBPROGRAM_O_HEADER_RE, line);
    if (m) headers.push([i, pyInt(m[1]!)]);
  });
  const bodies = new Map<number, [number, number]>();
  headers.forEach(([start, num], index) => {
    const nextStart = index + 1 < headers.length ? headers[index + 1]![0] : lines.length;
    let end = nextStart;
    for (let j = start + 1; j < nextStart; j++) {
      if (reSearch(SUBPROGRAM_RETURN_RE, codeWithoutComments(lines[j]))) {
        end = j + 1;
        break;
      }
    }
    if (!bodies.has(num)) bodies.set(num, [start + 1, end]);
  });
  return bodies;
}

/** 코드부(주석 제외) 문자열에서 G41/G42를 등장 순서대로 */
export function collectRadiusCompCodes(codeText: string): string[] {
  return [...reFinditer(RADIUS_COMP_RE, codeText)].map((m) => 'G4' + m[1]);
}

function radiusCompCodesForBlock(
  blockLines: readonly string[], bodies: Map<number, [number, number]>,
  lines: readonly string[], visited: Set<number>,
): string[] {
  const codeText = blockLines.map((line) => codeWithoutComments(line)).join('\n');
  const codes = collectRadiusCompCodes(codeText);
  for (const m of reFinditer(SUBPROGRAM_CALL_RE, codeText)) {
    const num = pyInt(m[1]!);
    if (visited.has(num)) continue;
    visited.add(num);
    const range = bodies.get(num);
    if (!range) continue;
    codes.push(...radiusCompCodesForBlock(lines.slice(range[0], range[1]), bodies, lines, visited));
  }
  return codes;
}

/** G41/G42 목록 → "(G41)" / "(G41/G42)" (등장 순서, 중복 제거). 없으면 '' */
export function formatCompSuffix(codes: readonly string[]): string {
  if (!codes.length) return '';
  const ordered: string[] = [];
  for (const code of codes) if (!ordered.includes(code)) ordered.push(code);
  return '(' + ordered.join('/') + ')';
}

/** 공정(N 블록) 안 M300/M200 → "(M300H1)(M200)" 표기. H가 있고 같은 공정의 G43 H(없으면 M6 T 번호)와 다르면 "(M300H2≠H1)" */
export function probeSuffix(blockLines: readonly string[]): string {
  let g43Ref: number | null = null, tRef: number | null = null;
  const found: [string, number | null][] = [];
  for (const line of blockLines) {
    const code = codeWithoutComments(line);
    const hm = reSearch(G43_RE, code) ? reSearch(H_WORD_RE, code) : null;
    if (hm && g43Ref === null) g43Ref = pyInt(hm[1]!);
    const tm = reMatch(M6_RE, line);
    if (tm && tRef === null) tRef = pyInt(tm[1]!);
    for (const m of reFinditer(M_PROBE_RE, code)) found.push([m[1]!, m[2] ? pyInt(m[2]) : null]);
  }
  const ref = g43Ref !== null ? g43Ref : tRef;
  const out: string[] = [];
  for (const [codeNo, h] of found) {
    const text = h === null ? `(M${codeNo})` : ref !== null && h !== ref ? `(M${codeNo}H${h}≠H${ref})` : `(M${codeNo}H${h})`;
    if (!out.includes(text)) out.push(text);
  }
  return out.join('');
}

/** N번호(예 "N8") → 경보정 표시 문구. 블록은 nRe가 맞는 줄부터 다음 맞는 줄 전까지. */
export function radiusCompByN(lines: readonly string[], nRe: RegExp): Record<string, string> {
  const bodies = subprogramBodies(lines);
  const positions: [number, string][] = [];
  lines.forEach((line, i) => {
    const m = reMatch(nRe, line);
    if (m) positions.push([i, 'N' + m[1]]);
  });
  const result: Record<string, string> = {};
  positions.forEach(([start, label], index) => {
    const end = index + 1 < positions.length ? positions[index + 1]![0] : lines.length;
    result[label] = formatCompSuffix(radiusCompCodesForBlock(lines.slice(start + 1, end), bodies, lines, new Set())) + probeSuffix(lines.slice(start + 1, end));
  });
  return result;
}

/** 전역(g·u) 정규식의 .test() 는 lastIndex 가 남아 번갈아 틀리므로 매번 0으로 되돌려 검사한다 */
export function isProbeMismatch(text: string): boolean {
  RADIUS_COMP_MISMATCH_RE.lastIndex = 0;
  const hit = RADIUS_COMP_MISMATCH_RE.test(text);
  RADIUS_COMP_MISMATCH_RE.lastIndex = 0;
  return hit;
}

export function hasCompDisplay(text: string): boolean {
  RADIUS_COMP_DISPLAY_RE.lastIndex = 0;
  const hit = RADIUS_COMP_DISPLAY_RE.test(text);
  RADIUS_COMP_DISPLAY_RE.lastIndex = 0;
  return hit;
}

const PROBE_TOKEN_RE = /\(M[23]00(?:H\d+(?:≠H\d+)?)?\)/g;

/** REMARK 표시 문구 "N8(G41), N9, N10" — v2.5.5: M300/M200 은 2줄로 내린다("N3(G41), N7\nM300H3 · M200", 같은 코드는 합침) */
export function formatRemark(labels: readonly string[], compMap: Readonly<Record<string, string>>): string {
  const heads: string[] = [];
  const probes = new Map<string, string[]>();
  for (const label of labels) {
    const suffix = Object.prototype.hasOwnProperty.call(compMap, label) ? compMap[label]! : '';
    for (const token of suffix.match(PROBE_TOKEN_RE) ?? []) {
      const code = token.slice(1, -1);
      const owners = probes.get(code) ?? [];
      if (!owners.includes(label)) owners.push(label);
      probes.set(code, owners);
    }
    heads.push(label + suffix.replace(PROBE_TOKEN_RE, ''));
  }
  let text = heads.join(', ');
  // v2.5.8: 어느 N에서 측정하는지 "M300H3: N3, N7 · M200: N3"
  if (probes.size) text += '\n' + [...probes].map(([c, o]) => `${c}: ${o.join(', ')}`).join(' · ');
  return text;
}
