// 턴밀 공구 축 정하기 — 원본 nc_lathe_sim.py plane_normal / rotate_about_spindle / entry_axes
type V3 = [number, number, number];
const AXIS_PLANE_TOLERANCE_DEG = 30;

/** 평면 코드의 공구 축 후보(팁→홀더). G17 = +월드 X, G19 = C 각도에서의 기계 +X 방향 */
export function planeNormal(plane: string | null | undefined, point: V3, cDeg: number | null | undefined): V3 | null {
  if (plane === 'G17') return [1, 0, 0];
  if (plane === 'G19') {
    if (cDeg !== null && cDeg !== undefined) { const c = (cDeg * Math.PI) / 180; return [0, Math.sin(c), Math.cos(c)]; }
    const n = Math.hypot(point[1], point[2]);
    return n > 1e-6 ? [0, point[1] / n, point[2] / n] : [0, 0, 1];
  }
  return null;
}

/** 월드 벡터를 주축(월드 X) 둘레로 C도 돌린다(lathe_rotate_c 규약) */
export function rotateAboutSpindle(v: V3, cDeg: number): V3 {
  const c = (cDeg * Math.PI) / 180;
  const s = Math.sin(c), k = Math.cos(c);
  return [v[0], v[1] * k + v[2] * s, -v[1] * s + v[2] * k];
}

export interface EntryInput {
  p0: V3[]; p1: V3[]; rapid: boolean[]; breaks: boolean[];
  planes: (string | null)[]; cAngles: (number | null)[]; cStart: number[]; cEnd: number[];
}

export function entryAxes(inp: EntryInput): { axes0: V3[]; axes1: V3[]; corrected: number } {
  const { p0, p1, rapid, breaks, planes, cAngles, cStart, cEnd } = inp;
  const count = p0.length;
  const axes: V3[] = Array.from({ length: count }, () => [1, 0, 0] as V3);
  const assigned = new Array<boolean>(count).fill(false);
  const source = Array.from({ length: count }, (_, i) => i);
  let corrected = 0;
  const cosTol = Math.cos((AXIS_PLANE_TOLERANCE_DEG * Math.PI) / 180);
  const dot = (a: V3, b: V3): number => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
  let m = 0;
  while (m < count) {
    if (rapid[m]) { m++; continue; }
    const start = m;
    let end = m + 1;
    while (end < count && !rapid[end] && !breaks[end]) end++;
    let axis: V3 | null = null;
    let entry = start;
    for (let k = start; k < end; k++) {
      const e: V3 = [p1[k]![0] - p0[k]![0], p1[k]![1] - p0[k]![1], p1[k]![2] - p0[k]![2]];
      const len = Math.hypot(e[0], e[1], e[2]);
      if (len > 1e-6) {
        entry = k;
        axis = [-e[0] / len, -e[1] / len, -e[2] / len];
        const normal = planeNormal(planes[k], p0[k]!, cAngles[k]);
        if (normal && Math.abs(dot(axis, normal)) < cosTol) { axis = normal; corrected++; } else if (normal && dot(axis, normal) < 0) axis = normal;
        break;
      }
    }
    if (!axis) axis = planeNormal(planes[start], p0[start]!, cAngles[start]) ?? [1, 0, 0];
    for (let k = start; k < end; k++) { axes[k] = axis; source[k] = entry; assigned[k] = true; }
    m = end;
  }
  let k = 0;
  while (k < count) {
    if (assigned[k]) { k++; continue; }
    const runStart = k;
    while (k < count && !assigned[k]) k++;
    const runEnd = k;
    let cut = -1;
    for (let j = runStart; j < runEnd; j++) if (breaks[j]) { cut = j; break; }
    const prevI = runStart > 0 ? runStart - 1 : null;
    const nextI = runEnd < count ? runEnd : null;
    const fill = (a: number, b: number, i: number | null): void => {
      if (i === null || a >= b) return;
      for (let j = a; j < b; j++) { axes[j] = axes[i]!; source[j] = source[i]!; }
    };
    if (cut >= 0) { fill(runStart, cut, prevI); fill(cut, runEnd, nextI ?? prevI); continue; }
    if (prevI === null && nextI === null) continue;
    if (prevI === null) fill(runStart, runEnd, nextI);
    else if (nextI === null || runEnd - runStart === 1) fill(runStart, runEnd, prevI);
    else { fill(runStart, runEnd - 1, prevI); fill(runEnd - 1, runEnd, nextI); }
  }
  const axes0: V3[] = [], axes1: V3[] = [];
  for (let i = 0; i < count; i++) {
    const ref = cStart[source[i]!]!;
    axes0.push(rotateAboutSpindle(axes[i]!, cStart[i]! - ref));
    axes1.push(rotateAboutSpindle(axes[i]!, cEnd[i]! - ref));
  }
  return { axes0, axes1, corrected };
}
