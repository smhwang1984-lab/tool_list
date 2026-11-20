// 공정(공구 교체)의 "시작 표시 줄" — 그 공정의 첫 N 시퀀스와 주석. 원본 nc_process_marker.py(v2.6.6)와 같은 결과를 낸다.
// 재생 바 [이전 공구]/[다음 공구]가 M6 줄이 아니라 이 줄로 이동해 공정 머리말 주석이 함께 보인다.

const N_RE = /^\s*\/?\s*N\s*\d+/i;
const MOTION_RE = /G0?[0-3](?!\d)/;
const AXIS_RE = /[XYZABCUVW]\s*[-+]?[\d.]/;
const STOP_RE = /M0?[01](?!\d)|M30(?!\d)/;

const codeOf = (line: string): string => (line || '').replace(/\([^)]*\)/g, ' ').split(';')[0]!.toUpperCase().replace(/ /g, '');

export const isMotionLine = (line: string): boolean => {
  const code = codeOf(line);
  return MOTION_RE.test(code) && AXIS_RE.test(code);
};

export const isNLine = (line: string): boolean => N_RE.test(line || '');

export function lineComments(line: string): string[] {
  const text = line || '';
  const found: string[] = [];
  for (const m of text.matchAll(/\(([^)]*)\)/g)) found.push(m[1]!.trim());
  const rest = text.replace(/\([^)]*\)/g, ' ');
  const semi = rest.indexOf(';');
  if (semi >= 0) found.push(rest.slice(semi + 1).trim());
  return found.filter((c) => c);
}

/** 공구 교체 줄(changeSeq)에서 위로 올라가며 공정의 첫 N 줄을 찾는다. floorSeq = 앞 공정의 공구 교체 seq(없으면 -1). */
export function findProcessMarker(lines: readonly string[], changeSeq: number, floorSeq = -1, maxComments = 2): { seq: number; comments: string[] } {
  const total = lines.length;
  const change = total ? Math.max(0, Math.min(Math.trunc(changeSeq), total - 1)) : 0;
  let best: number | null = null;
  for (let seq = change; seq > floorSeq && seq >= 0; seq--) {
    const text = lines[seq]!;
    if (seq !== change) {
      if (isMotionLine(text)) break;
      if (best !== null && STOP_RE.test(codeOf(text))) break;
    }
    if (isNLine(text)) best = seq;
  }
  const start = best ?? change;
  const comments: string[] = [];
  for (let s = start; s <= change; s++) {
    comments.push(...lineComments(lines[s]!));
    if (comments.length >= maxComments) break;
  }
  return { seq: start, comments: comments.slice(0, maxComments) };
}

/** 시작 N 줄 seq 목록에서 이전/다음 이동 목표. 시작 줄에 서 있으면 다음 = 다음 공정, 공정 중간의 이전 = 그 공정 시작 줄. */
export function pickRelativeMarker(orderedSeqs: readonly number[], currentSeq: number, direction: -1 | 1): number {
  const ordered = [...orderedSeqs].sort((a, b) => a - b);
  let index = -1;
  ordered.forEach((s, i) => { if (s <= currentSeq) index = i; });
  if (direction > 0) return ordered[Math.min(index + 1, ordered.length - 1)]!;
  if (index < 0) return ordered[0]!;
  if (ordered[index]! < currentSeq) return ordered[index]!;
  return ordered[Math.max(index - 1, 0)]!;
}
