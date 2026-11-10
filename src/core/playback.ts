// 재생 위치 계산 — 원본 NCViewerWidget.sequence_length / line_at_seq / resolve_seq_for_line / elapsed_seconds_at_seq (6371~6520)
import { formatDuration, type ToolpathResult } from './toolpath';

export const sequenceLength = (r: ToolpathResult): number => r.seq_to_line.length;

/** seq → 원본 줄번호. 범위 밖은 끝으로 자른다. 시퀀스가 비었으면 seq 그대로. */
export function lineAtSeq(r: ToolpathResult, seq: number): number {
  if (!r.seq_to_line.length) return Math.max(0, Math.trunc(seq));
  const s = Math.max(0, Math.min(Math.trunc(seq), r.seq_to_line.length - 1));
  return r.seq_to_line[s]!;
}

/** 원본 줄번호가 실행된 seq 중 하나(near 가 있으면 가장 가까운 것, 동률이면 앞). 한 번도 실행 안 됐으면 null. */
export function resolveSeqForLine(r: ToolpathResult, line: number, near?: number | null): number | null {
  const seqs = r.line_to_seq_all.get(line);
  if (!seqs || !seqs.length) return null;
  if (near === undefined || near === null) return seqs[seqs.length - 1]!;
  let best = seqs[0]!;
  let bestDist = Math.abs(best - near);
  for (const c of seqs.slice(1)) {
    const d = Math.abs(c - near);
    if (d < bestDist) { best = c; bestDist = d; }
  }
  return best;
}

/** seq 까지의 누적 가공 시간(초). 점이 없는 seq 는 앞선 가장 가까운 값. */
export function elapsedSecondsAtSeq(r: ToolpathResult, seq: number, sortedKeys?: number[]): number {
  if (!r.seq_to_elapsed_sec.size) return 0;
  const v = r.seq_to_elapsed_sec.get(seq);
  if (v !== undefined) return v;
  const keys = sortedKeys ?? [...r.seq_to_elapsed_sec.keys()].sort((a, b) => a - b);
  let lo = 0, hi = keys.length;
  while (lo < hi) { const mid = (lo + hi) >> 1; if (seq < keys[mid]!) hi = mid; else lo = mid + 1; }
  return lo === 0 ? 0 : r.seq_to_elapsed_sec.get(keys[lo - 1]!)!;
}

export const dwellSecondsAtSeq = (r: ToolpathResult, seq: number): number => r.seq_to_dwell_sec.get(seq) ?? 0;

export const formatElapsedOverTotal = (elapsed: number, total: number): string =>
  `${formatDuration(elapsed)} / ${formatDuration(total)}`;

/** 줄 번호까지의 누적 시간 */
export function elapsedSecondsAtLine(r: ToolpathResult, line: number, sortedKeys?: number[]): number {
  return elapsedSecondsAtSeq(r, r.line_to_seq.get(line) ?? line, sortedKeys);
}
