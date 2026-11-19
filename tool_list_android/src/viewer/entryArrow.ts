// 진입 방향 화살표 — 원본 nc_tool_marker.py cut_groups / group_at (v2.4.5). 밀링 전용.
// 공정 경로를 "같은 공구 축으로 가공하는 구간"으로 나누고, 구간의 첫 절삭 이동 시작점에 그 이동 방향의 화살표를 그린다.
// 공구 축이 바뀌면(축 회전) 구간이 끝나고 다음 절삭에서 새 화살표가 생긴다.
import type { PathPoint, Vec3 } from '../core/toolpath';

export interface CutGroup {
  entry: Vec3;
  /** 첫 절삭 이동의 단위 방향 */
  direction: Vec3;
  axis: Vec3;
  startSeq: number;
  /** null = 공정 끝까지 */
  endSeq: number | null;
}

const Z_AXIS: Vec3 = [0, 0, 1];
const sameAxis = (a: Vec3, b: Vec3, tol = 1e-6): boolean => Math.abs(a[0] - b[0]) <= tol && Math.abs(a[1] - b[1]) <= tol && Math.abs(a[2] - b[2]) <= tol;

export function cutGroups(path: readonly PathPoint[], axisOfLine?: ReadonlyMap<number, Vec3>): CutGroup[] {
  const axisOf = (n: PathPoint): Vec3 => axisOfLine?.get(n.src_line) ?? Z_AXIS;
  const groups: CutGroup[] = [];
  let current: CutGroup | null = null;
  let prev: PathPoint | null = null;
  for (const node of path) {
    if (!node.valid) { prev = null; continue; }
    const axis = axisOf(node);
    if (current && !sameAxis(axis, current.axis)) { current.endSeq = node.seq ?? 0; current = null; }
    if (prev && !current && node.type !== 'G00') {
      const d: Vec3 = [node.pt[0] - prev.pt[0], node.pt[1] - prev.pt[1], node.pt[2] - prev.pt[2]];
      const len = Math.hypot(d[0], d[1], d[2]);
      if (len > 1e-9) {
        current = { entry: [prev.pt[0], prev.pt[1], prev.pt[2]], direction: [d[0] / len, d[1] / len, d[2] / len], axis, startSeq: node.seq ?? 0, endSeq: null };
        groups.push(current);
      }
    }
    prev = node;
  }
  return groups;
}

/** seq(재생 위치)에 해당하는 가공 구간. 없으면 null(= 화살표를 지운다) */
export function groupAt(groups: readonly CutGroup[], seq: number): CutGroup | null {
  let found: CutGroup | null = null;
  for (const g of groups) if (g.startSeq <= seq && (g.endSeq === null || seq < g.endSeq)) found = g;
  return found;
}
