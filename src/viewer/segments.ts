// 경로 → 그릴 선분 묶음 — 원본 _render_segments / _render_segment_buckets / _compute_scene_radius / 색 표 (nc_viewer_widget.py)
import { formatDuration, type PathPoint, type ToolpathResult } from '../core/toolpath';

export const TOOL_COLOR_MAPS: readonly (readonly [number, number, number])[] = [
  [1.0, 0.45, 0.10], [0.0, 0.70, 1.0], [0.20, 0.90, 0.25], [1.0, 0.25, 0.65], [0.95, 0.85, 0.10], [0.60, 0.35, 1.0],
  [0.00, 0.85, 0.70], [1.0, 0.55, 0.00], [0.65, 0.85, 1.0], [0.90, 0.45, 0.95], [0.45, 1.0, 0.45], [1.0, 0.80, 0.55],
];
export const RAPID_MOVE_COLOR: readonly [number, number, number] = [1.0, 0.0, 0.0];
export const toolColorForIndex = (i: number): readonly [number, number, number] => TOOL_COLOR_MAPS[i % TOOL_COLOR_MAPS.length]!;
export const cssColor = (c: readonly number[]): string =>
  `rgb(${c.map((v) => Math.max(0, Math.min(255, Math.trunc(v * 255)))).join(',')})`;

export interface SegmentBuckets {
  /** 급속(G00) 선분의 끝점쌍(p0,p1,p0,p1…) — 좌표 3개씩 */
  rapid: number[];
  cut: number[];
  /** 각 선분(점 2개)이 속한 seq (rapid/cut 각각 선분 하나당 1개) */
  rapidSeq: number[];
  cutSeq: number[];
}

/** 원본 _render_segments + _render_segment_buckets: 유효하지 않은 점에서 끊고, G00 과 나머지(CUT)로 나눈다. */
export function segmentBuckets(path: readonly PathPoint[]): SegmentBuckets {
  const out: SegmentBuckets = { rapid: [], cut: [], rapidSeq: [], cutSeq: [] };
  let prev: PathPoint | null = null;
  for (const node of path) {
    if (!node.valid) { prev = null; continue; }
    if (!prev) { prev = node; continue; }
    const rapid = node.type === 'G00';
    const target = rapid ? out.rapid : out.cut;
    target.push(prev.pt[0], prev.pt[1], prev.pt[2], node.pt[0], node.pt[1], node.pt[2]);
    (rapid ? out.rapidSeq : out.cutSeq).push(node.seq);
    prev = node;
  }
  return out;
}

/** 모든 유효 점을 감싸는 원점 기준 구의 반지름 */
export function sceneRadius(r: ToolpathResult): number {
  let max = 0;
  for (const path of r.tool_paths.values()) {
    for (const n of path) {
      if (!n.valid) continue;
      const sq = n.pt[0] ** 2 + n.pt[1] ** 2 + n.pt[2] ** 2;
      if (sq > max) max = sq;
    }
  }
  return Math.sqrt(max);
}

/** 모든 유효 점의 경계 상자(없으면 null) */
export function sceneBounds(r: ToolpathResult): { min: [number, number, number]; max: [number, number, number] } | null {
  const min: [number, number, number] = [Infinity, Infinity, Infinity];
  const max: [number, number, number] = [-Infinity, -Infinity, -Infinity];
  let any = false;
  for (const path of r.tool_paths.values()) {
    for (const n of path) {
      if (!n.valid) continue;
      any = true;
      for (let k = 0; k < 3; k++) { min[k] = Math.min(min[k]!, n.pt[k]!); max[k] = Math.max(max[k]!, n.pt[k]!); }
    }
  }
  return any ? { min, max } : null;
}

/** 원본 _tool_display_text */
export function toolDisplayText(r: ToolpathResult, key: string, names: Record<string, string>): string {
  const toolNo = r.process_tool_map.get(key);
  if (!toolNo) return '초기 구간';
  const suffix = r.process_time_sec.size && r.process_time_sec.has(key) ? ` | ${formatDuration(r.process_time_sec.get(key)!)}` : '';
  const m = /T(\d+)/i.exec(toolNo);
  if (!m) return `공정 | ${toolNo} | 이름 없음${suffix}`;
  const n = Number.parseInt(m[1]!, 10);
  const norm = `T${String(n).padStart(2, '0')}`;
  const name = names[norm] || names[`T${n}`] || names[String(n)] || '이름 없음';
  const pm = /^P(\d+)_/.exec(key);
  const label = pm ? `공정 ${String(Number.parseInt(pm[1]!, 10)).padStart(2, '0')}` : '공정';
  return `${label} | ${norm} | ${name}${suffix}`;
}
