// 선반 공구 단면 다각형 — 원본 nc_lathe_sim.py (insert_polygon / groove_polygon / thread_polygon / center_tool_polygon)
import type { ToolGeometry } from '../core/latheInsertSpec';
import { toolShapeFromValues } from './toolShape';

export class ToolShapeError extends Error {}

/** 단면 다각형: 반시계 볼록, 좌표 [z, r] 쌍의 평탄 배열. 프로그램 좌표점이 원점 */
export interface LatheTool {
  poly: Float64Array; // [z0, r0, z1, r1, ...]
  kind: string;
  name: string;
}

type Pt = [number, number];
const GROOVE_REACH = 60.0;
const UNLIMITED_LENGTH = 1000.0;
const DEFAULT_KAPPA: Record<string, number> = { C: 95, D: 93, E: 93, M: 93, V: 93, S: 90, T: 91, W: 95 };
const TIP_FLIPS: Record<string, [number, number]> = { '3': [1, 1], '2': [-1, 1], '4': [1, -1], '1': [-1, -1], '9': [1, 1] };
const SHAPE_INTERIORS: Record<string, (a: number) => number[]> = {
  C: (a) => [a, 180 - a, a, 180 - a], D: (a) => [a, 180 - a, a, 180 - a], E: (a) => [a, 180 - a, a, 180 - a],
  M: (a) => [a, 180 - a, a, 180 - a], V: (a) => [a, 180 - a, a, 180 - a], S: () => [90, 90, 90, 90],
  T: () => [60, 60, 60], W: () => [80, 160, 80, 160, 80, 160],
};
const rad = (d: number): number => (d * Math.PI) / 180;

function signedArea(p: Pt[]): number {
  let s = 0;
  for (let i = 0; i < p.length; i++) { const a = p[i]!, b = p[(i + 1) % p.length]!; s += a[0] * b[1] - b[0] * a[1]; }
  return s / 2;
}
function applyFlips(poly: Pt[], sz: number, sr: number): Pt[] {
  let out = poly.map(([z, r]): Pt => [z * sz, r * sr]);
  if (signedArea(out) < 0) out = out.reverse();
  return out;
}
function walkPolygon(heading: number, side: number, interiors: number[]): Pt[] {
  const pts: Pt[] = [[0, 0]];
  let h = heading;
  for (let k = 1; k < interiors.length; k++) {
    const [z, r] = pts[pts.length - 1]!;
    pts.push([z + side * Math.cos(rad(h)), r + side * Math.sin(rad(h))]);
    h += 180 - interiors[k]!;
  }
  return pts;
}
function linspace(a: number, b: number, n: number): number[] {
  return Array.from({ length: n }, (_, i) => (n === 1 ? a : a + ((b - a) * i) / (n - 1)));
}

/** 볼록 껍질(반시계) */
export function convexHull(points: Pt[]): Pt[] {
  const pts = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const uniq: Pt[] = [];
  for (const p of pts) { const q = uniq[uniq.length - 1]; if (!q || Math.abs(q[0] - p[0]) > 1e-9 || Math.abs(q[1] - p[1]) > 1e-9) uniq.push(p); }
  if (uniq.length < 3) return uniq;
  const cross = (o: Pt, a: Pt, b: Pt): number => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: Pt[] = [];
  for (const p of uniq) { while (lower.length >= 2 && cross(lower[lower.length - 2]!, lower[lower.length - 1]!, p) <= 0) lower.pop(); lower.push(p); }
  const upper: Pt[] = [];
  for (let i = uniq.length - 1; i >= 0; i--) { const p = uniq[i]!; while (upper.length >= 2 && cross(upper[upper.length - 2]!, upper[upper.length - 1]!, p) <= 0) upper.pop(); upper.push(p); }
  return [...lower.slice(0, -1), ...upper.slice(0, -1)];
}

function insertPolygon(g: ToolGeometry): Pt[] {
  const shape = g.shape;
  if (!shape) throw new ToolShapeError('인서트 형상을 해석하지 못함(INSERT 문구 확인)');
  let tip = String(g.tip ?? '');
  if (!(tip in TIP_FLIPS)) tip = g.kind === '내경' || g.kind === '내경나사' ? '4' : '3';
  let nose = g.nose_r ?? 0;
  if (shape === 'R') {
    const radius = (g.ic ?? 0) / 2;
    if (radius <= 0) throw new ToolShapeError('원형 인서트의 지름을 모름');
    const circle: Pt[] = Array.from({ length: 40 }, (_, i): Pt => { const a = (i / 40) * 2 * Math.PI; return [radius * Math.cos(a), radius * Math.sin(a)]; });
    const ref: Pt = tip === '9' ? [0, 0] : [-radius, -radius];
    const [sz, sr] = TIP_FLIPS[tip]!;
    return applyFlips(circle.map(([z, r]): Pt => [z - ref[0], r - ref[1]]), sz, sr);
  }
  const alpha = g.tip_angle;
  const side = g.edge_length;
  if (!alpha || !side) throw new ToolShapeError('인서트 크기를 해석하지 못함(내접원·날 길이)');
  const kappa = g.approach_angle || DEFAULT_KAPPA[shape] || 95;
  const theta1 = 180 - kappa;
  const theta2 = theta1 - alpha;
  const mk = SHAPE_INTERIORS[shape];
  if (!mk) throw new ToolShapeError('지원하지 않는 인서트 형상');
  const verts = walkPolygon(theta2, side, mk(alpha));
  const half = rad(alpha / 2);
  nose = nose > 0 ? Math.min(nose, 0.9 * side * Math.tan(half)) : 0;
  let poly: Pt[];
  let origin: Pt;
  if (nose > 0) {
    const bis = rad(theta1 - alpha / 2);
    const dist = nose / Math.sin(half);
    const cz = dist * Math.cos(bis), cr = dist * Math.sin(bis);
    const nArc = Math.max(2, Math.ceil((180 - alpha) / 10));
    const arc = linspace(theta1 + 90, theta2 + 270, nArc + 1).map((p): Pt => [cz + nose * Math.cos(rad(p)), cr + nose * Math.sin(rad(p))]);
    poly = [...arc, ...verts.slice(1)];
    origin = tip === '9' ? [cz, cr] : [cz - nose, cr - nose];
  } else {
    poly = verts;
    origin = [0, 0];
  }
  const [sz, sr] = TIP_FLIPS[tip]!;
  return applyFlips(poly.map(([z, r]): Pt => [z - origin[0], r - origin[1]]), sz, sr);
}

function rectPolygon(zLo: number, zHi: number, rLo: number, rHi: number, corner: number, rl: boolean, rh: boolean, zl: boolean, zh: boolean): Pt[] {
  const R = Math.max(0, Math.min(corner, (zHi - zLo) / 2, (rHi - rLo) / 2));
  const arc = (cz: number, cr: number, a0: number, a1: number): Pt[] => linspace(a0, a1, 5).map((a): Pt => [cz + R * Math.cos(rad(a)), cr + R * Math.sin(rad(a))]);
  return [
    ...(R && rl && zl ? arc(zLo + R, rLo + R, 180, 270) : [[zLo, rLo] as Pt]),
    ...(R && rl && zh ? arc(zHi - R, rLo + R, 270, 360) : [[zHi, rLo] as Pt]),
    ...(R && rh && zh ? arc(zHi - R, rHi - R, 0, 90) : [[zHi, rHi] as Pt]),
    ...(R && rh && zl ? arc(zLo + R, rHi - R, 90, 180) : [[zLo, rHi] as Pt]),
  ];
}

function groovePolygon(g: ToolGeometry): Pt[] {
  const width = g.width;
  if (!width || width <= 0) throw new ToolShapeError('홈 폭(T)을 모름 — 툴리스트 T 칸에 입력하세요');
  const corner = g.nose_r ?? 0;
  let tip = String(g.tip ?? '');
  const reach = GROOVE_REACH;
  if (g.kind === '정면홈') {
    if (!['3', '4', '9'].includes(tip)) tip = '4';
    const [rLo, rHi] = ({ '4': [-width, 0], '3': [0, width], '9': [-width / 2, width / 2] } as Record<string, [number, number]>)[tip]!;
    return rectPolygon(0, reach, rLo, rHi, corner, true, true, true, false);
  }
  const internal = g.kind === '내경홈';
  const allowed = internal ? ['4', '1', '9'] : ['3', '2', '9'];
  if (!allowed.includes(tip)) tip = allowed[0]!;
  const zr: Record<string, [number, number]> = { [allowed[0]!]: [0, width], [allowed[1]!]: [-width, 0], '9': [-width / 2, width / 2] };
  const [zLo, zHi] = zr[tip]!;
  return internal
    ? rectPolygon(zLo, zHi, -reach, 0, corner, false, true, true, true)
    : rectPolygon(zLo, zHi, 0, reach, corner, true, false, true, true);
}

function threadPolygon(g: ToolGeometry): Pt[] {
  const angle = g.thread_angle || 60;
  const height = 4;
  const half = height * Math.tan(rad(angle / 2));
  return applyFlips([[0, 0], [half, height], [-half, height]], 1, g.kind === '내경나사' ? -1 : 1);
}

function centerPolygon(g: ToolGeometry): Pt[] {
  if (!g.diameter || !g.mill_type) throw new ToolShapeError('공구 지름(D) 또는 종류를 모름 — 툴리스트 D·종류 칸을 확인하세요');
  const so = g.so || UNLIMITED_LENGTH;
  let shape;
  if (g.mill_type === 'CHAMF') shape = toolShapeFromValues({ type: 'DRILL', D: g.diameter, FL: null, R: null, SIG: g.chamfer_angle || 90, PL: null, SO: so });
  else shape = toolShapeFromValues({ type: g.mill_type, D: g.diameter, FL: null, R: g.nose_r, SIG: null, PL: null, SO: so });
  if (!shape) throw new ToolShapeError('공구 형상을 만들 수 없음');
  const { lut, invStep } = shape.radialLut(0.05);
  const pts: Pt[] = linspace(0, shape.radius, 25).map((r): Pt => [lut[Math.min(Math.round(r * invStep), lut.length - 1)] ?? 0, r]);
  pts.push([shape.cutLength, shape.radius], [shape.cutLength, 0]);
  return convexHull(pts);
}

/** 툴리스트 형상 한 항목 → 선반 공구. 선삭·홈·나사·중심 드릴/엔드밀을 지원한다(페이스커터·턴밀 3D 는 제외). */
export function latheToolFromGeometry(g: ToolGeometry, name = ''): LatheTool {
  const kind = g.kind || '';
  let poly: Pt[];
  if (kind === '외경' || kind === '내경') poly = insertPolygon(g);
  else if (['외경홈', '내경홈', '정면홈', '절단'].includes(kind)) poly = groovePolygon(g);
  else if (kind === '외경나사' || kind === '내경나사') poly = threadPolygon(g);
  else if (kind === '드릴' || kind === '엔드밀') poly = centerPolygon(g);
  else if (kind === '페이스커터') throw new ToolShapeError('페이스커터는 턴밀(3D)에서만 지원');
  else if (kind === '비절삭') throw new ToolShapeError('비절삭 공구');
  else throw new ToolShapeError('공구 종류를 모름 — 툴리스트 종류 칸을 확인하세요');
  const flat = new Float64Array(poly.length * 2);
  poly.forEach(([z, r], i) => { flat[i * 2] = z; flat[i * 2 + 1] = r; });
  return { poly: flat, kind, name };
}
