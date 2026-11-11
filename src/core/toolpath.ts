// NC → 공구 경로 — 원본 NCViewerWidget.process_nc_lines (nc_viewer_widget.py 4639~6172) 순수 로직 이식.
// 그리기·Qt 위젯은 빼고 좌표·seq·줄 대응·가공 시간만 계산한다. 골든(tests/golden/toolpath)과 맞춘다.
import { pySplitlines } from './py';

// ---------------------------------------------------------------- 상수
export const MACHINE_5AXIS_AC = '5축 MCT (A to C)';
export const MACHINE_5AXIS_BC = '5축 MCT (B to C)';
export const isLatheMachine = (machineType: string): boolean => String(machineType ?? '').includes('선반');

const ARC_PLANE_AXES: Record<string, [number, number, number, 'i' | 'j' | 'k', 'i' | 'j' | 'k']> = {
  G17: [0, 1, 2, 'i', 'j'],
  G18: [2, 0, 1, 'k', 'i'],
  G19: [1, 2, 0, 'j', 'k'],
  LATHE: [0, 2, 1, 'k', 'i'],
  LATHE_G17: [2, 1, 0, 'i', 'j'],
  LATHE_G19: [1, 0, 2, 'j', 'k'],
};
const ARC_CHORD_TOLERANCE_MM = 0.05;
const ARC_MIN_SEGMENTS = 6;
const ARC_MAX_SEGMENTS = 720;
const LATHE_C_ARC_STEP_DEG = 5.0;
export const RAPID_FEED_MM_PER_MIN = 7000.0;
const SHORT_SEGMENT_MM = 0.5;
const SLOW_FEED_RATIO = 0.7;
const CLOSED_KEY = '__lathe_closed_gap__';

export type Vec3 = [number, number, number];
export interface PathPoint {
  pt: Vec3;
  type: string;
  valid: boolean;
  src_line: number;
  seq: number;
  c?: number;
}
export type FeedState = [feed: number, perRev: boolean, mode: string, value: number, maxRpm: number];
export type LatheLineInfo = [milling: boolean, plane: string, thread: [number, number] | null];

export interface MachineSpec {
  [key: string]: string | undefined;
}

export interface ToolpathResult {
  tool_paths: Map<string, PathPoint[]>;
  process_tool_map: Map<string, string>;
  process_first_line: Map<string, number>;
  process_first_seq: Map<string, number>;
  line_to_coord_map: Map<number, Vec3>;
  line_to_tool_map: Map<number, string>;
  seq_to_line: number[];
  seq_to_tool_map: Map<number, string>;
  seq_to_coord_map: Map<number, Vec3>;
  seq_to_c_rot: Map<number, number>;
  line_to_c_rot: Map<number, number>;
  line_to_seq: Map<number, number>;
  line_to_seq_all: Map<number, number[]>;
  line_feed_state: Map<number, FeedState>;
  line_axis_map: Map<number, Vec3>;
  line_lathe_map: Map<number, LatheLineInfo>;
  modal_state_map: Map<number, string[]>;
  seq_to_modal_state: Map<number, string[]>;
  seq_to_elapsed_sec: Map<number, number>;
  seq_to_dwell_sec: Map<number, number>;
  process_time_sec: Map<string, number>;
  total_time_sec: number;
}

// ---------------------------------------------------------------- 작은 도우미
type Mat3 = number[][];
const eye = (): Mat3 => [[1, 0, 0], [0, 1, 0], [0, 0, 1]];
const rad = (deg: number): number => (deg * Math.PI) / 180;
const matMul = (a: Mat3, b: Mat3): Mat3 =>
  a.map((row) => [0, 1, 2].map((j) => row[0]! * b[0]![j]! + row[1]! * b[1]![j]! + row[2]! * b[2]![j]!));
const matVec = (m: Mat3, v: number[]): Vec3 =>
  [0, 1, 2].map((i) => m[i]![0]! * v[0]! + m[i]![1]! * v[1]! + m[i]![2]! * v[2]!) as Vec3;
const allcloseEye = (m: Mat3): boolean => {
  const e = eye();
  return m.every((row, i) => row.every((v, j) => Math.abs(v - e[i]![j]!) <= 1e-8 + 1e-5 * Math.abs(e[i]![j]!)));
};

export function codeWithoutCommentsViewer(line: string): string {
  const code = String(line ?? '').split(';', 1)[0]!;
  return code.replace(/\([^()]*\)/g, '');
}

const normalizeToolNo = (value: string): string => {
  const n = Number.parseInt(value, 10);
  return Number.isNaN(n) ? '' : `T${String(n).padStart(2, '0')}`;
};
const makeProcessKey = (processNo: number, toolNo: string): string =>
  `P${String(processNo).padStart(3, '0')}_${toolNo || 'T00'}`;

// ---------------------------------------------------------------- 선반 좌표계
export function latheLocalPoint(z: number, xDia: number, y = 0): Vec3 {
  return [Number(z), Number(y || 0), Number(xDia) / 2.0];
}
export function latheRotateC(point: number[], cDeg: number): Vec3 {
  const c = Number(cDeg || 0);
  if (!c) return [point[0]!, point[1]!, point[2]!];
  const r = rad(c);
  const y = point[1]!;
  const z = point[2]!;
  return [point[0]!, y * Math.cos(r) + z * Math.sin(r), -y * Math.sin(r) + z * Math.cos(r)];
}
export function latheWorldPoint(z: number, xDia: number, cDeg = 0, y = 0): Vec3 {
  return latheRotateC(latheLocalPoint(z, xDia, y), cDeg);
}
export function latheCArcAngles(startC: number, endC: number, step = LATHE_C_ARC_STEP_DEG): number[] {
  const delta = Number(endC) - Number(startC);
  const steps = Math.max(1, Math.ceil(Math.abs(delta) / step));
  return Array.from({ length: steps }, (_, k) => Number(startC) + (delta * (k + 1)) / steps);
}
export function latheCArcPoints(startLocal: number[], endLocal: number[], startC: number, endC: number, step = LATHE_C_ARC_STEP_DEG): Vec3[] {
  const delta = Number(endC) - Number(startC);
  const steps = Math.max(1, Math.ceil(Math.abs(delta) / step));
  const pts: Vec3[] = [];
  for (let k = 1; k <= steps; k++) {
    const t = k / steps;
    const p = [0, 1, 2].map((i) => startLocal[i]! + (endLocal[i]! - startLocal[i]!) * t);
    pts.push(latheRotateC(p, Number(startC) + delta * t));
  }
  return pts;
}
export function latheCRolloverEnd(startC: number, endC: number): number {
  const x = Number(endC) - Number(startC) + 180.0;
  const delta = (((x % 360) + 360) % 360) - 180.0; // Python % (부호는 나누는 수를 따른다)
  return Number(startC) + delta;
}

// ---------------------------------------------------------------- 시간 계산 도우미
export function effectiveFeedMmPerMin(motion: string, feed: number, distance: number): number {
  if (motion === 'G00') return RAPID_FEED_MM_PER_MIN;
  const f = Number.isFinite(Number(feed)) ? Number(feed || 0) : 0;
  if (f <= 0) return 0;
  if (motion === 'G02' || motion === 'G03' || Number(distance) <= SHORT_SEGMENT_MM) return f * SLOW_FEED_RATIO;
  return f;
}

const DWELL_RE = /G0?4(?![\d.])/;
const DWELL_WORD_RE = /([XUPF])([+-]?(?:\d+\.?\d*|\.\d+))/;
export function parseDwell(code: string): [number | null, string] {
  const m = DWELL_RE.exec(code ?? '');
  if (!m) return [null, code];
  let rest = code.slice(0, m.index) + code.slice(m.index + m[0].length);
  let seconds = 0;
  const w = DWELL_WORD_RE.exec(rest);
  if (w) {
    const letter = w[1]!;
    const text = w[2]!;
    const value = Math.abs(Number.parseFloat(text)) || 0;
    seconds = letter === 'P' || (letter !== 'F' && !text.includes('.')) ? value / 1000.0 : value;
    rest = rest.slice(0, w.index) + rest.slice(w.index + w[0].length);
  }
  return [seconds, rest];
}

export function latheSpindleRpm(mode: string, value: number, diameter: number, maxRpm: number): number {
  const v = Number(value || 0) || 0;
  let max = Number(maxRpm || 0) || 0;
  if (v <= 0) return 0;
  let rpm: number;
  if (String(mode).toUpperCase() === 'G96') {
    const d = Math.abs(Number(diameter || 0));
    rpm = d <= 1e-6 ? max : (v * 1000.0) / (Math.PI * d);
  } else {
    rpm = v;
  }
  if (max > 0) rpm = Math.min(rpm, max);
  max = 0;
  return rpm;
}

export function formatDuration(seconds: number): string {
  let total = Math.round(Number(seconds || 0));
  if (!Number.isFinite(total)) total = 0;
  total = Math.max(0, total);
  const h = Math.floor(total / 3600);
  const rem = total % 3600;
  const m = Math.floor(rem / 60);
  const s = rem % 60;
  const p2 = (n: number) => String(n).padStart(2, '0');
  return h ? `${h}:${p2(m)}:${p2(s)}` : `${p2(m)}:${p2(s)}`;
}

// ---------------------------------------------------------------- 5축 회전
function rotationMatrix(i: number, j: number, k: number): Mat3 {
  const ri = rad(i), rj = rad(j), rk = rad(k);
  const mi: Mat3 = [[1, 0, 0], [0, Math.cos(ri), -Math.sin(ri)], [0, Math.sin(ri), Math.cos(ri)]];
  const mj: Mat3 = [[Math.cos(rj), 0, Math.sin(rj)], [0, 1, 0], [-Math.sin(rj), 0, Math.cos(rj)]];
  const mk: Mat3 = [[Math.cos(rk), -Math.sin(rk), 0], [Math.sin(rk), Math.cos(rk), 0], [0, 0, 1]];
  return matMul(matMul(mk, mj), mi);
}
function fiveAxisRotationMatrix(machineType: string, i: number, j: number, k: number): Mat3 {
  if (machineType.includes(MACHINE_5AXIS_AC)) {
    const ra = rad(j), rc = rad(i), rk = rad(k);
    const a: Mat3 = [[1, 0, 0], [0, Math.cos(ra), -Math.sin(ra)], [0, Math.sin(ra), Math.cos(ra)]];
    const c: Mat3 = [[Math.cos(rc), -Math.sin(rc), 0], [Math.sin(rc), Math.cos(rc), 0], [0, 0, 1]];
    const kk: Mat3 = [[Math.cos(rk), -Math.sin(rk), 0], [Math.sin(rk), Math.cos(rk), 0], [0, 0, 1]];
    return matMul(matMul(kk, c), a);
  }
  return rotationMatrix(i, j, k);
}
export function toolAxisFromRotary(isAc: boolean, a: number, b: number, c: number): Vec3 {
  const rc = rad(c);
  if (isAc) {
    const ra = rad(a);
    return [Math.sin(ra) * Math.sin(rc), -Math.sin(ra) * Math.cos(rc), Math.cos(ra)];
  }
  const rb = rad(b);
  return [Math.sin(rb) * Math.cos(rc), Math.sin(rb) * Math.sin(rc), Math.cos(rb)];
}

// ---------------------------------------------------------------- 원호
const numOr0 = (m: RegExpExecArray | null): number => (m ? Number.parseFloat(m[1]!) : 0.0);

interface ArcPatterns { i: RegExp; j: RegExp; k: RegExp; r: RegExp }
function arcPoints(
  line: string, start: number[], target: number[], motion: string, plane: string, pats: ArcPatterns,
): Vec3[] {
  const [ui, vi, wi, uLetter, vLetter] = ARC_PLANE_AXES[plane] ?? ARC_PLANE_AXES.G17!;
  const offs = { i: pats.i, j: pats.j, k: pats.k };
  const uOff = numOr0(offs[uLetter].exec(line));
  const vOff = numOr0(offs[vLetter].exec(line));
  const su = start[ui]!, sv = start[vi]!, sw = start[wi]!;
  const tu = target[ui]!, tv = target[vi]!, tw = target[wi]!;
  let cu = su + uOff;
  let cv = sv + vOff;
  const rm = pats.r.exec(line);
  if (rm) {
    const spec = Number.parseFloat(rm[1]!);
    const du = tu - su;
    const dv = tv - sv;
    const dist = Math.hypot(du, dv);
    if (dist > 0) {
      const h = Math.sqrt(Math.max(0.0, spec ** 2 - (dist / 2) ** 2));
      const sign = (spec > 0 ? motion === 'G03' : motion === 'G02') ? 1 : -1;
      cu = su + du / 2 - sign * h * (dv / dist);
      cv = sv + dv / 2 + sign * h * (du / dist);
    }
  }
  const r0 = Math.hypot(su - cu, sv - cv);
  const r1 = Math.hypot(tu - cu, tv - cv);
  const radius = (r0 + r1) / 2.0;
  if (radius <= 1e-9) {
    const p: Vec3 = [0, 0, 0];
    p[ui] = tu; p[vi] = tv; p[wi] = tw;
    return [p];
  }
  const aStart = Math.atan2(sv - cv, su - cu);
  let aEnd = Math.atan2(tv - cv, tu - cu);
  if (motion === 'G02' && aEnd >= aStart) aEnd -= 2 * Math.PI;
  else if (motion === 'G03' && aEnd <= aStart) aEnd += 2 * Math.PI;
  const delta = aEnd - aStart;
  const maxStep = radius > ARC_CHORD_TOLERANCE_MM
    ? 2 * Math.acos(Math.max(-1.0, 1.0 - ARC_CHORD_TOLERANCE_MM / radius)) : Math.PI / 6;
  let segments = maxStep > 0 ? Math.ceil(Math.abs(delta) / maxStep) + 1 : ARC_MIN_SEGMENTS;
  segments = Math.max(ARC_MIN_SEGMENTS, Math.min(ARC_MAX_SEGMENTS, segments));
  const last = segments - 1;
  const step = (aEnd - aStart) / last;
  const out: Vec3[] = [];
  for (let s = 1; s <= last; s++) {
    const ang = s === last ? aEnd : aStart + s * step; // numpy linspace: 끝점은 정확히 stop
    const ratio = s / last;
    const p: Vec3 = [0, 0, 0];
    if (s === last) {
      p[ui] = tu; p[vi] = tv;
    } else {
      p[ui] = cu + Math.cos(ang) * radius;
      p[vi] = cv + Math.sin(ang) * radius;
    }
    p[wi] = sw + (tw - sw) * ratio;
    out.push(p);
  }
  return out;
}

// ---------------------------------------------------------------- 서브프로그램 펼치기 (M98/M99)
const M30_RE = /M30(?!\d)/;
const M98_RE = /M98(?!\d)/;
const M99_RE = /M99(?!\d)/;
const M98_P_RE = /P0*(\d+)(?!\d)/;
const M98_L_RE = /L0*(\d+)(?!\d)/;
const SUB_HEADER_RE = /^\s*O0*(\d+)\b/;
const N_LABEL_RE = /^\s*N0*(\d+)/;
const SUB_MAX_DEPTH = 10;
const SUB_MAX_STEPS = 200_000;
const LATHE_N_LINE_RE = /^\s*N(\d+)\s*$/;
const LATHE_ANY_T_LINE_RE = /T(\d{4})(?!\d)/gi;

type SeqLine = [idx: number, line: string];

export function expandSubprograms(lines: readonly string[]): SeqLine[] {
  const codeCache = lines.map((raw) => codeWithoutCommentsViewer(raw).toUpperCase());
  if (!codeCache.some((c) => M98_RE.test(c))) return lines.map((l, i) => [i, l]);

  let m30: number | null = null;
  for (let i = 0; i < codeCache.length; i++) {
    if (M30_RE.test(codeCache[i]!)) { m30 = i; break; }
  }
  const subs = new Map<number, [number, number]>();
  if (m30 !== null) {
    const headers: [number, number][] = [];
    for (let i = m30 + 1; i < lines.length; i++) {
      const hm = SUB_HEADER_RE.exec(codeWithoutCommentsViewer(lines[i]!));
      if (hm) headers.push([Number.parseInt(hm[1]!, 10), i]);
    }
    headers.forEach(([no, start], pos) => {
      const end = pos + 1 < headers.length ? headers[pos + 1]![1] : lines.length;
      if (!subs.has(no)) subs.set(no, [start + 1, end]);
    });
  }
  const mainEnd = m30 !== null ? m30 + 1 : lines.length;
  const labelCache = new Map<string, Map<number, number>>();
  const labels = (start: number, end: number): Map<number, number> => {
    const key = `${start},${end}`;
    let t = labelCache.get(key);
    if (t) return t;
    t = new Map();
    for (let i = start; i < end; i++) {
      const m = N_LABEL_RE.exec(lines[i]!);
      if (m) {
        const n = Number.parseInt(m[1]!, 10);
        if (!t.has(n)) t.set(n, i);
      }
    }
    labelCache.set(key, t);
    return t;
  };
  interface Frame { start: number; end: number; pc: number; repeat: number }
  const frames: Frame[] = [{ start: 0, end: mainEnd, pc: 0, repeat: 1 }];
  const result: SeqLine[] = [];
  let steps = 0;
  while (frames.length && steps < SUB_MAX_STEPS) {
    const frame = frames[frames.length - 1]!;
    if (frame.pc >= frame.end) {
      steps++;
      frame.repeat--;
      if (frame.repeat > 0) frame.pc = frame.start;
      else frames.pop();
      continue;
    }
    const idx = frame.pc;
    const code = codeCache[idx]!;
    result.push([idx, lines[idx]!]);
    frame.pc++;
    steps++;
    if (M99_RE.test(code)) {
      const pm = M98_P_RE.exec(code);
      const isMain = frames.length === 1;
      if (pm) {
        const n = Number.parseInt(pm[1]!, 10);
        if (isMain) {
          const target = labels(frame.start, frame.end).get(n);
          if (target !== undefined) frame.pc = target;
          else frames.pop();
        } else {
          frames.pop();
          if (frames.length) {
            const caller = frames[frames.length - 1]!;
            const target = labels(caller.start, caller.end).get(n);
            if (target !== undefined) caller.pc = target;
          }
        }
      } else if (!isMain) {
        frame.repeat--;
        if (frame.repeat > 0) frame.pc = frame.start;
        else frames.pop();
      }
      continue;
    }
    if (frames.length < SUB_MAX_DEPTH && M98_RE.test(code)) {
      const pm = M98_P_RE.exec(code);
      if (pm) {
        const body = subs.get(Number.parseInt(pm[1]!, 10));
        if (body) {
          const lm = M98_L_RE.exec(code);
          const repeat = lm ? Math.max(1, Number.parseInt(lm[1]!, 10)) : 1;
          frames.push({ start: body[0], end: body[1], pc: body[0], repeat });
        }
      }
    }
  }
  return result;
}

function latheNBlocks(seq: SeqLine[]): [Set<number>, Map<number, string>] {
  const nPos: number[] = [];
  seq.forEach(([, raw], pos) => { if (LATHE_N_LINE_RE.test(raw)) nPos.push(pos); });
  const toolAt = new Map<number, string>();
  nPos.forEach((start, order) => {
    const end = order + 1 < nPos.length ? nPos[order + 1]! : seq.length;
    let toolDigits = '';
    let fallback = '';
    for (let pos = start + 1; pos < end; pos++) {
      const code = codeWithoutCommentsViewer(seq[pos]![1]).toUpperCase();
      let found = false;
      for (const m of code.matchAll(LATHE_ANY_T_LINE_RE)) {
        const digits = m[1]!;
        if (digits === '0000') continue;
        if (digits.slice(2) !== '00') { toolDigits = digits; found = true; break; }
        if (!fallback) fallback = digits;
      }
      if (found) break;
    }
    const digits = toolDigits || fallback;
    toolAt.set(start, digits ? normalizeToolNo(digits.slice(0, 2)) : '');
  });
  return [new Set(nPos), toolAt];
}

// ---------------------------------------------------------------- 정규식 (원본과 같은 것)
const T_PAT = /T0*(\d+)/;
const M6_PAT = /M0?6(?!\d)/;
const LATHE_TOOL_CHANGE = /T(?!0000)(\d{2})00(?!\d)/;
const M35 = /M35(?!\d)/;
const M34 = /M34(?!\d)/;
const LATHE_PROCESS_END = /M(?:0?[01]|30)(?!\d)/;
const X_PAT = /X\s*([+-]?\d*\.?\d+)/;
const Y_PAT = /Y\s*([+-]?\d*\.?\d+)/;
const Z_PAT = /Z\s*([+-]?\d*\.?\d+)/;
const A_PAT = /A\s*([+-]?\d*\.?\d+)/;
const B_PAT = /B\s*([+-]?\d*\.?\d+)/;
const C_PAT = /C\s*([+-]?\d*\.?\d+)/;
const G28 = /G28(?!\d)/;
const G91 = /G91/;
const G68 = /G68\.2/;
const G69 = /G69/;
const G53_1 = /G53\.1/;
const G12_1 = /G12\.1(?!\d)|G112(?!\d)/;
const G13_1 = /G13\.1(?!\d)|G113(?!\d)/;
const H_PAT = /H\s*([+-]?\d*\.?\d+)/;
const MOTION = /(G0[0-3]|G[0-3])(?![.\d])/;
const G17 = /G17(?!\d)/;
const G18 = /G18(?!\d)/;
const G19 = /G19(?!\d)/;
const I_PAT = /I\s*([+-]?\d*\.?\d+)/;
const J_PAT = /J\s*([+-]?\d*\.?\d+)/;
const K_PAT = /K\s*([+-]?\d*\.?\d+)/;
const R_PAT = /R\s*([+-]?\d*\.?\d+)/;
const G43 = /G43/;
const G43_4 = /G43\.4(?!\d)/;
const G49 = /G49/;
const G98 = /G98/;
const G99 = /G99/;
/** 선반 G80 줄의 좌표 이동을 급속(G00)으로 본다. 원본은 G80 모션 그대로(F 없으면 시간 0·절삭 취급)라 골든 시험은 끈 채로 비교한다. */
let latheG80Rapid = false;
export function setLatheG80Rapid(on: boolean): void { latheG80Rapid = on; }
const CYCLE = /(G73|G74|G76|G81|G82|G83|G84|G85|G86|G87|G88|G89|G80)/;
const LATHE_CYCLE = /(G81|G82|G83|G84|G85|G86|G87|G88|G89|G80)/;
const LATHE_CYCLE_FULL = /^(?:G81|G82|G83|G84|G85|G86|G87|G88|G89|G80)$/;
const F_PAT = /F\s*([+-]?\d*\.?\d+)/;
const S_PAT = /S\s*(\d*\.?\d+)/;
const G50_S = /G50\s*S\s*(\d*\.?\d+)/;
const G96 = /G96(?!\d)/;
const G97 = /G97(?!\d)/;
const ARC_PATS: ArcPatterns = { i: I_PAT, j: J_PAT, k: K_PAT, r: R_PAT };

const f = (m: RegExpExecArray): number => Number.parseFloat(m[1]!);

// ---------------------------------------------------------------- 본체
export function processNcLines(lines: readonly string[], machineType: string, specs: MachineSpec | undefined): ToolpathResult {
  const res: ToolpathResult = {
    tool_paths: new Map(), process_tool_map: new Map(), process_first_line: new Map(), process_first_seq: new Map(),
    line_to_coord_map: new Map(), line_to_tool_map: new Map(), seq_to_line: [], seq_to_tool_map: new Map(),
    seq_to_coord_map: new Map(), seq_to_c_rot: new Map(), line_to_c_rot: new Map(), line_to_seq: new Map(),
    line_to_seq_all: new Map(), line_feed_state: new Map(), line_axis_map: new Map(), line_lathe_map: new Map(),
    modal_state_map: new Map(), seq_to_modal_state: new Map(), seq_to_elapsed_sec: new Map(),
    seq_to_dwell_sec: new Map(), process_time_sec: new Map(), total_time_sec: 0,
  };
  const isLathe = isLatheMachine(machineType);
  const is4 = machineType.includes('4축');
  const is5ac = machineType.includes(MACHINE_5AXIS_AC);
  const is5bc = machineType.includes(MACHINE_5AXIS_BC);
  const is5 = is5ac || is5bc;

  let mX: number, mY: number, mZ: number;
  {
    const a = Number(specs?.['X 행정'] ?? '500') / 2.0;
    const b = Number(specs?.['Y 행정'] ?? '500') / 2.0;
    const c = Number(specs?.['Z 행정'] ?? '500');
    if (Number.isNaN(a) || Number.isNaN(b) || Number.isNaN(c)) { mX = 250; mY = 250; mZ = 300; } else { mX = a; mY = b; mZ = c; }
  }
  let specMaxRpm = Number(specs?.['최대 RPM'] || 0);
  if (Number.isNaN(specMaxRpm)) specMaxRpm = 0;

  const paths = res.tool_paths;
  let currentTool = 'Initial';
  paths.set(currentTool, []);
  res.process_tool_map.set(currentTool, '');
  res.process_first_line.set(currentTool, 0);
  res.process_first_seq.set(currentTool, 0);
  const push = (p: PathPoint): void => { paths.get(currentTool)!.push(p); };

  let cx = 0, cy = 0, cz = 0, ccDeg = 0, cyLathe = 0, polarTheta = 0;
  const modal = ['0.000', '0.000', '0.000', '0.000', '0.000', '0.000'];
  let g43Active = false;
  let currentMotion = 'G00';
  let currentPlane = 'G17';
  let polar = false;
  let latheMilling = false;
  let g68Pending = false;
  let pendI = 0, pendJ = 0, pendK = 0;
  let activeMatrix = eye();
  let pendingOrigin: number[] = [0, 0, 0];
  let activeOrigin: number[] = [0, 0, 0];
  let tcp = false;
  let g98Active = true;
  let cycleActive = false;
  let detectedT = '';
  let processNo = 0;
  let millCycleInitialZ = 0, millCycleR = 0, millCycleDepth = 0;
  let latheCycleAxis: 'X' | 'Z' | null = null;
  let latheCycleRef: number | null = null;
  let latheCycleR = 0;
  let latheCycleDepth = 0;
  let planeExplicit = false;
  let currentFeed = 0;
  let feedPerRev = true;
  let activeLatheTool: string | null = null;
  let processOpen = true;
  let spindleMode = 'G97';
  let spindleValue = 0;
  let maxRpm = specMaxRpm;

  const seqLines = expandSubprograms(lines);
  res.seq_to_line = seqLines.map(([idx]) => idx);
  const [nStarts, nToolAt] = isLathe ? latheNBlocks(seqLines) : [new Set<number>(), new Map<number, string>()];

  for (let seqPos = 0; seqPos < seqLines.length; seqPos++) {
    const [idx, line] = seqLines[seqPos]!;
    const lineWithComments = line.toUpperCase().replace(/ /g, '');
    let lineUpper = codeWithoutCommentsViewer(line).toUpperCase().replace(/ /g, '');
    const [dwell, rest] = parseDwell(lineUpper);
    lineUpper = rest;
    if (dwell !== null) res.seq_to_dwell_sec.set(seqPos, dwell);

    [X_PAT, Y_PAT, Z_PAT, A_PAT, B_PAT, C_PAT].forEach((pat, pos) => {
      const m = pat.exec(lineUpper);
      if (m) modal[pos] = m[1]!;
    });
    res.modal_state_map.set(idx, [...modal]);
    res.seq_to_modal_state.set(seqPos, [...modal]);
    res.line_to_seq.set(idx, seqPos);
    const all = res.line_to_seq_all.get(idx);
    if (all) all.push(seqPos); else res.line_to_seq_all.set(idx, [seqPos]);
    res.line_to_c_rot.set(idx, ccDeg);
    res.seq_to_c_rot.set(seqPos, ccDeg);

    const tComment = T_PAT.exec(lineWithComments);
    if (tComment) detectedT = normalizeToolNo(tComment[1]!);

    res.line_to_tool_map.set(idx, currentTool);
    res.seq_to_tool_map.set(seqPos, currentTool);
    if (!lineUpper) continue;

    const fMatch = F_PAT.exec(lineUpper);
    if (fMatch) {
      const fv = f(fMatch);
      if (fv > 0) currentFeed = fv;
    }
    if (isLathe) {
      const prevPerRev: boolean = feedPerRev;
      if (G99.test(lineUpper)) feedPerRev = true;
      else if (G98.test(lineUpper)) feedPerRev = false;
      if (feedPerRev !== prevPerRev && !fMatch) currentFeed = 0;
      let scan = lineUpper;
      const g50 = G50_S.exec(scan);
      if (g50) {
        maxRpm = f(g50);
        scan = scan.slice(0, g50.index) + scan.slice(g50.index + g50[0].length);
      }
      if (G96.test(scan)) spindleMode = 'G96';
      else if (G97.test(scan)) spindleMode = 'G97';
      const sm = S_PAT.exec(scan);
      if (sm) spindleValue = f(sm);
      res.line_feed_state.set(idx, [currentFeed, feedPerRev, spindleMode, spindleValue, maxRpm]);
    } else {
      res.line_feed_state.set(idx, [currentFeed, false, '', 0.0, 0.0]);
    }

    let planeSeen = true;
    if (G17.test(lineUpper)) currentPlane = 'G17';
    else if (G18.test(lineUpper)) currentPlane = 'G18';
    else if (G19.test(lineUpper)) currentPlane = 'G19';
    else planeSeen = false;
    if (isLathe && planeSeen) planeExplicit = true;

    if (isLathe) {
      const resetCycle = (): void => {
        cycleActive = false; latheCycleAxis = null; latheCycleRef = null; latheCycleR = 0; latheCycleDepth = 0;
        planeExplicit = false;
        if (LATHE_CYCLE_FULL.test(currentMotion || '')) currentMotion = 'G00';
      };
      if (M35.test(lineUpper)) {
        latheMilling = true;
        resetCycle();
      } else if (M34.test(lineUpper)) {
        latheMilling = false;
        resetCycle();
        if (!polar) cyLathe = 0;
      }
    }

    if (G12_1.test(lineUpper)) {
      polar = true;
      if (!isLathe) continue;
    }
    if (G13_1.test(lineUpper)) {
      polar = false;
      if (isLathe) { cyLathe = 0; polarTheta = 0; } else continue;
    }

    if (G43.test(lineUpper)) {
      g43Active = true;
      tcp = G43_4.test(lineUpper);
    }
    if (G49.test(lineUpper)) {
      g43Active = false;
      tcp = false;
      continue;
    }

    if (isLathe) {
      let thread: [number, number] | null = null;
      if (/G76(?!\d)/.test(lineUpper) && /[XZ][+-]?[\d.]/.test(lineUpper)) {
        const tf = F_PAT.exec(lineUpper);
        const tp = /P(\d+)/.exec(lineUpper);
        if (tf) thread = [f(tf), tp ? Number.parseFloat(tp[1]!) / 1000.0 : 0.0];
      }
      res.line_lathe_map.set(idx, [Boolean(latheMilling || polar), currentPlane, thread]);
    }

    if (!isLathe) {
      let axis: Vec3 | null = null;
      if (is4) {
        const rb = rad(Number.parseFloat(modal[4]!));
        axis = [Math.sin(rb), 0.0, Math.cos(rb)];
      } else if (is5) {
        if (!allcloseEye(activeMatrix)) {
          axis = [activeMatrix[0]![2]!, activeMatrix[1]![2]!, activeMatrix[2]![2]!];
        } else if (tcp) {
          axis = toolAxisFromRotary(is5ac, Number.parseFloat(modal[3]!), Number.parseFloat(modal[4]!), Number.parseFloat(modal[5]!));
        }
      }
      if (axis && (Math.abs(axis[0]) > 1e-9 || Math.abs(axis[1]) > 1e-9)) res.line_axis_map.set(idx, axis);
    }

    if (!isLathe) {
      if (G98.test(lineUpper)) { g98Active = true; currentMotion = 'G98'; }
      else if (G99.test(lineUpper)) g98Active = false;
    }

    const cycleMatch = (isLathe ? LATHE_CYCLE : CYCLE).exec(lineUpper);
    if (cycleMatch) {
      const code = cycleMatch[1]!;
      const was = cycleActive;
      cycleActive = code !== 'G80';
      currentMotion = code;
      if (!isLathe) {
        if (cycleActive && !was) millCycleInitialZ = cz;
        else if (!cycleActive) { millCycleR = 0; millCycleDepth = 0; currentMotion = 'G00'; }
      }
      if (isLathe && code === 'G80') {
        if (latheG80Rapid) currentMotion = 'G00'; // G80 은 이동 지령이 아니다 — 같은 줄의 좌표 이동은 급속(F 없음)
        latheCycleAxis = null; latheCycleRef = null; latheCycleR = 0; latheCycleDepth = 0;
      }
    }

    let toolChanged: boolean;
    if (isLathe) {
      if (nStarts.size) {
        toolChanged = nStarts.has(seqPos);
        if (toolChanged) {
          detectedT = nToolAt.get(seqPos) ?? '';
          processOpen = true;
        } else if (!processOpen) {
          currentTool = CLOSED_KEY;
          if (!paths.has(currentTool)) paths.set(currentTool, []);
        }
        if (LATHE_PROCESS_END.test(lineUpper)) processOpen = false;
      } else {
        const ltc = LATHE_TOOL_CHANGE.exec(lineUpper);
        toolChanged = ltc !== null;
        if (ltc) {
          detectedT = normalizeToolNo(ltc[1]!);
          if (detectedT === activeLatheTool) toolChanged = false;
          else activeLatheTool = detectedT;
        }
        if (LATHE_PROCESS_END.test(lineUpper)) activeLatheTool = null;
      }
    } else {
      const tm = T_PAT.exec(lineUpper);
      if (tm) detectedT = normalizeToolNo(tm[1]!);
      toolChanged = M6_PAT.test(lineUpper);
    }

    if (toolChanged) {
      processNo++;
      currentTool = makeProcessKey(processNo, detectedT);
      paths.set(currentTool, []);
      res.process_tool_map.set(currentTool, detectedT);
      res.process_first_line.set(currentTool, idx);
      res.process_first_seq.set(currentTool, seqPos);
      const startPoint: Vec3 = isLathe ? latheWorldPoint(cz, cx, ccDeg) : [cx, cy, cz];
      push({ pt: startPoint, type: currentMotion, valid: isLathe ? true : g43Active, src_line: idx, seq: seqPos });
      res.line_to_tool_map.set(idx, currentTool);
      res.seq_to_tool_map.set(seqPos, currentTool);
    }

    const mm = MOTION.exec(lineUpper);
    if (mm && !cycleActive) {
      const mot = mm[1]!;
      if (mot === 'G0' || mot === 'G00') currentMotion = 'G00';
      else if (mot === 'G1' || mot === 'G01') currentMotion = 'G01';
      else if (mot === 'G2' || mot === 'G02') currentMotion = 'G02';
      else if (mot === 'G3' || mot === 'G03') currentMotion = 'G03';
    }

    if (is5) {
      if (G69.test(lineUpper)) {
        activeMatrix = eye(); activeOrigin = [0, 0, 0]; g68Pending = false;
      } else if (G68.test(lineUpper)) {
        g68Pending = true;
        pendI = numOr0(I_PAT.exec(lineUpper));
        pendJ = numOr0(J_PAT.exec(lineUpper));
        pendK = numOr0(K_PAT.exec(lineUpper));
        pendingOrigin = [numOr0(X_PAT.exec(lineUpper)), numOr0(Y_PAT.exec(lineUpper)), numOr0(Z_PAT.exec(lineUpper))];
      }
      if (G53_1.test(lineUpper) && g68Pending) {
        activeMatrix = fiveAxisRotationMatrix(machineType, pendI, pendJ, pendK);
        activeOrigin = [...pendingOrigin];
        g68Pending = false;
      }
    }
    if (is4) {
      const bm = B_PAT.exec(lineUpper);
      if (bm) {
        const rb = rad(f(bm));
        activeMatrix = [[Math.cos(rb), 0, Math.sin(rb)], [0, 1, 0], [-Math.sin(rb), 0, Math.cos(rb)]];
      }
    }

    const g28Here = G28.test(lineUpper);
    const g28CHome = isLathe && g28Here && H_PAT.test(lineUpper);
    if (g28Here && (G91.test(lineUpper) || g28CHome)) {
      if (isLathe) {
        if (/X\s*0/.test(lineUpper)) cx = mX * 2.0;
        if (/Z\s*0/.test(lineUpper)) cz = mZ;
        if (H_PAT.test(lineUpper)) {
          ccDeg = 0;
          res.line_to_c_rot.set(idx, 0); res.seq_to_c_rot.set(seqPos, 0);
        }
        const fin = latheWorldPoint(cz, cx, ccDeg);
        push({ pt: fin, type: 'G00', valid: true, src_line: idx, seq: seqPos });
        res.line_to_coord_map.set(idx, fin); res.seq_to_coord_map.set(seqPos, fin);
        continue;
      }
      if (/X\s*0/.test(lineUpper)) cx = mX;
      if (/Y\s*0/.test(lineUpper)) cy = mY;
      if (/Z\s*0/.test(lineUpper)) cz = mZ;
      if (g43Active) {
        const fin: Vec3 = [cx, cy, cz];
        push({ pt: fin, type: 'G00', valid: true, src_line: idx, seq: seqPos });
        res.line_to_coord_map.set(idx, fin); res.seq_to_coord_map.set(seqPos, fin);
      }
      continue;
    }

    const xM = X_PAT.exec(lineUpper);
    const yM = Y_PAT.exec(lineUpper);
    const zM = Z_PAT.exec(lineUpper);
    const cM = C_PAT.exec(lineUpper);
    const rCycle = R_PAT.exec(lineUpper);
    const hM = isLathe ? H_PAT.exec(lineUpper) : null;
    const hIncr = hM && !polar && !g28Here && !G43.test(lineUpper) ? hM : null;
    const isArc = currentMotion === 'G02' || currentMotion === 'G03';
    const arcCenter = isArc && !(G68.test(lineUpper) || G53_1.test(lineUpper))
      && (I_PAT.test(lineUpper) || J_PAT.test(lineUpper) || K_PAT.test(lineUpper));

    if (!(xM || yM || zM || cM || hIncr || (cycleActive && rCycle) || arcCenter)) continue;

    let startPt: Vec3 = [cx, cy, cz];
    let startLocal: Vec3 = [0, 0, 0];
    let startCc = 0;
    let cAbsolute = false;
    let targetLocal: Vec3 = [0, 0, 0];
    let targetPt: Vec3;
    let localTargetPt: Vec3;
    if (isLathe) {
      startLocal = latheLocalPoint(cz, cx, cyLathe);
      startPt = latheRotateC(startLocal, ccDeg);
      startCc = ccDeg;
      cAbsolute = cM !== null;
      if (xM) cx = f(xM);
      if (zM) cz = f(zM);
      if (polar) {
        if (cM) {
          cyLathe = f(cM);
          const radiusNow = cx / 2.0;
          polarTheta = cyLathe || radiusNow ? (Math.atan2(cyLathe, radiusNow) * 180) / Math.PI : 0.0;
        }
      } else {
        if (cM) {
          ccDeg = f(cM);
          res.line_to_c_rot.set(idx, ccDeg); res.seq_to_c_rot.set(seqPos, ccDeg);
        } else if (hIncr) {
          ccDeg += f(hIncr);
          res.line_to_c_rot.set(idx, ccDeg); res.seq_to_c_rot.set(seqPos, ccDeg);
        }
        if (latheMilling && yM) cyLathe = f(yM);
      }
      targetLocal = latheLocalPoint(cz, cx, cyLathe);
      targetPt = latheRotateC(targetLocal, ccDeg);
      localTargetPt = targetLocal;
      if (polar) {
        const v = ccDeg + polarTheta;
        res.line_to_c_rot.set(idx, v); res.seq_to_c_rot.set(seqPos, v);
      }
    } else {
      if (xM) cx = f(xM);
      if (yM) cy = f(yM);
      if (zM) cz = f(zM);
      localTargetPt = [cx, cy, cz];
      targetPt = is5 || is4 ? addVec(matVec(activeMatrix, localTargetPt), activeOrigin) : [...localTargetPt] as Vec3;
    }

    if (cycleActive && isLathe) {
      const isDef = cycleMatch !== null;
      let axis: 'X' | 'Z';
      if (planeExplicit) axis = currentPlane === 'G19' ? 'X' : 'Z';
      else if (isDef) axis = zM ? 'Z' : 'X';
      else axis = latheCycleAxis ?? 'Z';
      if (isDef || latheCycleAxis !== axis || latheCycleRef === null) {
        latheCycleAxis = axis;
        latheCycleRef = axis === 'Z' ? startLocal[0] : startLocal[2];
      }
      if (rCycle) latheCycleR = f(rCycle);
      if (axis === 'Z' && zM) latheCycleDepth = f(zM);
      else if (axis === 'X' && xM) latheCycleDepth = f(xM) / 2.0;
      const rTarget = latheCycleRef + latheCycleR;
      const depthTarget = latheCycleDepth;
      let approach: Vec3, rPoint: Vec3, fin: Vec3;
      if (axis === 'Z') {
        approach = latheWorldPoint(startLocal[0], cx, ccDeg);
        rPoint = latheWorldPoint(rTarget, cx, ccDeg);
        fin = latheWorldPoint(depthTarget, cx, ccDeg);
        cz = startLocal[0];
      } else {
        approach = latheWorldPoint(cz, startLocal[2] * 2.0, ccDeg);
        rPoint = latheWorldPoint(cz, rTarget * 2.0, ccDeg);
        fin = latheWorldPoint(cz, depthTarget * 2.0, ccDeg);
        cx = startLocal[2] * 2.0;
      }
      if (!polar && startCc !== ccDeg) {
        const approachLocal = axis === 'Z' ? latheLocalPoint(startLocal[0], cx) : latheLocalPoint(cz, startLocal[2] * 2.0);
        const arcEnd = cAbsolute ? latheCRolloverEnd(startCc, ccDeg) : ccDeg;
        const pts = latheCArcPoints(startLocal, approachLocal, startCc, arcEnd);
        const angs = latheCArcAngles(startCc, arcEnd);
        for (let k = 0; k < pts.length - 1; k++) {
          push({ pt: pts[k]!, type: 'G00', valid: true, src_line: idx, seq: seqPos, c: angs[k]! });
        }
      }
      push({ pt: approach, type: 'G00', valid: true, src_line: idx, seq: seqPos });
      push({ pt: rPoint, type: 'G00', valid: true, src_line: idx, seq: seqPos });
      push({ pt: fin, type: 'G01', valid: true, src_line: idx, seq: seqPos });
      push({ pt: approach, type: 'G00', valid: true, src_line: idx, seq: seqPos });
      res.line_to_coord_map.set(idx, fin); res.seq_to_coord_map.set(seqPos, fin);
      continue;
    }

    if (cycleActive && g43Active) {
      const tx = cx;
      const ty = cy;
      if (zM) millCycleDepth = f(zM);
      if (rCycle) millCycleR = f(rCycle);
      const tz = millCycleDepth;
      const rVal = millCycleR;
      const returnZ = g98Active ? millCycleInitialZ : rVal;
      const raw: number[][] = [[tx, ty, startPt[2]], [tx, ty, rVal], [tx, ty, tz], [tx, ty, returnZ]];
      const [xyApproach, rPoint, finalZ, returnPt] = is5
        ? raw.map((r) => addVec(matVec(activeMatrix, r), activeOrigin))
        : raw.map((r) => [r[0]!, r[1]!, r[2]!] as Vec3);
      push({ pt: xyApproach!, type: 'G00', valid: true, src_line: idx, seq: seqPos });
      push({ pt: rPoint!, type: 'G00', valid: true, src_line: idx, seq: seqPos });
      push({ pt: finalZ!, type: 'G01', valid: true, src_line: idx, seq: seqPos });
      push({ pt: returnPt!, type: 'G00', valid: true, src_line: idx, seq: seqPos });
      cz = returnZ;
      res.line_to_coord_map.set(idx, finalZ!); res.seq_to_coord_map.set(seqPos, finalZ!);
      continue;
    }

    const setCoord = (p: Vec3): void => { res.line_to_coord_map.set(idx, p); res.seq_to_coord_map.set(seqPos, p); };
    if (isArc && isLathe) {
      const addArc = (pts: Vec3[], rotate: boolean): void => {
        for (const p of pts) {
          push({ pt: rotate ? latheRotateC(p, ccDeg) : p, type: currentMotion, valid: true, src_line: idx, seq: seqPos });
        }
      };
      if (polar) addArc(arcPoints(lineUpper, startLocal, targetLocal, currentMotion, 'LATHE_G17', ARC_PATS), true);
      else if (latheMilling && (currentPlane === 'G17' || currentPlane === 'G19')) {
        addArc(arcPoints(lineUpper, startLocal, targetLocal, currentMotion, currentPlane === 'G17' ? 'LATHE_G17' : 'LATHE_G19', ARC_PATS), true);
      } else addArc(arcPoints(lineUpper, startPt, targetPt, currentMotion, 'LATHE', ARC_PATS), false);
      setCoord(targetPt);
    } else if (isArc) {
      const arcPts = arcPoints(lineUpper, startPt, localTargetPt, currentMotion, currentPlane, ARC_PATS);
      let last: Vec3 | null = null;
      for (const lp of arcPts) {
        const rp: Vec3 = is5 || is4 ? addVec(matVec(activeMatrix, lp), activeOrigin) : lp;
        push({ pt: rp, type: currentMotion, valid: g43Active, src_line: idx, seq: seqPos });
        last = rp;
      }
      if (g43Active) setCoord(last ?? targetPt);
    } else if (isLathe && !polar && startCc !== ccDeg) {
      const arcEnd = cAbsolute ? latheCRolloverEnd(startCc, ccDeg) : ccDeg;
      const pts = latheCArcPoints(startLocal, targetLocal, startCc, arcEnd);
      const angs = latheCArcAngles(startCc, arcEnd);
      pts.forEach((p, k) => push({ pt: p, type: currentMotion, valid: true, src_line: idx, seq: seqPos, c: angs[k]! }));
      setCoord(targetPt);
    } else {
      push({ pt: targetPt, type: currentMotion, valid: isLathe ? true : g43Active, src_line: idx, seq: seqPos });
      if (g43Active || isLathe) setCoord(targetPt);
    }
  }

  paths.delete(CLOSED_KEY);
  for (const [key, pts] of [...paths]) if (!pts.length) paths.delete(key);
  for (const key of [...res.process_tool_map.keys()]) if (!paths.has(key)) res.process_tool_map.delete(key);
  computeMachiningTimes(res, isLathe);
  return res;
}

const addVec = (a: number[], o: number[]): Vec3 => [a[0]! + o[0]!, a[1]! + o[1]!, a[2]! + o[2]!];

// ---------------------------------------------------------------- 가공 시간
function bisectRight(arr: number[], x: number): number {
  let lo = 0;
  let hi = arr.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (x < arr[mid]!) hi = mid; else lo = mid + 1;
  }
  return lo;
}

function computeMachiningTimes(res: ToolpathResult, isLathe: boolean): void {
  res.seq_to_elapsed_sec.clear();
  res.process_time_sec.clear();
  res.total_time_sec = 0;

  const starts: [number, string][] = [];
  for (const [key, pts] of res.tool_paths) {
    const seqs = pts.map((p) => p.seq).filter((s) => s !== undefined && s !== null);
    if (seqs.length) starts.push([Math.min(...seqs), key]);
  }
  starts.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
  const startSeqs = starts.map(([s]) => s);
  const dwellsBy = new Map<string | undefined, number[]>();
  for (const dwellSeq of [...res.seq_to_dwell_sec.keys()].sort((a, b) => a - b)) {
    let owner = res.seq_to_tool_map.get(dwellSeq);
    if ((owner === undefined || !res.tool_paths.has(owner)) && starts.length) {
      const position = bisectRight(startSeqs, dwellSeq);
      owner = starts[Math.min(position, starts.length - 1)]![1];
    }
    const list = dwellsBy.get(owner);
    if (list) list.push(dwellSeq); else dwellsBy.set(owner, [dwellSeq]);
  }

  let elapsed = 0;
  for (const [key, points] of res.tool_paths) {
    const processStart = elapsed;
    let prev: Vec3 | null = null;
    const dwellSeqs = dwellsBy.get(key) ?? [];
    dwellsBy.delete(key);
    let dwellPos = 0;
    for (const point of points) {
      const pt = point.pt;
      if (!pt || pt.length < 3) continue;
      const srcLine = point.src_line;
      const seq = point.seq;
      while (seq !== undefined && seq !== null && dwellPos < dwellSeqs.length && dwellSeqs[dwellPos]! < seq) {
        elapsed += res.seq_to_dwell_sec.get(dwellSeqs[dwellPos]!)!;
        res.seq_to_elapsed_sec.set(dwellSeqs[dwellPos]!, elapsed);
        dwellPos++;
      }
      if (prev) {
        const dx = pt[0] - prev[0], dy = pt[1] - prev[1], dz = pt[2] - prev[2];
        const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (distance > 0) {
          const fs = res.line_feed_state.get(srcLine);
          let feed: number;
          if (!fs) feed = 0;
          else if (isLathe) {
            const [fv, perRev, mode, sv, mr] = fs;
            feed = fv;
            if (perRev) {
              const meanDia = Math.hypot(prev[1], prev[2]) + Math.hypot(pt[1], pt[2]);
              feed = fv * latheSpindleRpm(mode, sv, meanDia, mr);
            }
          } else feed = fs[0];
          const speed = effectiveFeedMmPerMin(point.type, feed, distance);
          if (speed > 0) elapsed += (distance / speed) * 60.0;
        }
      }
      if (seq !== undefined && seq !== null) res.seq_to_elapsed_sec.set(seq, elapsed);
      else if (srcLine !== undefined && srcLine !== null) res.seq_to_elapsed_sec.set(srcLine, elapsed);
      prev = pt;
    }
    for (const ds of dwellSeqs.slice(dwellPos)) {
      elapsed += res.seq_to_dwell_sec.get(ds)!;
      res.seq_to_elapsed_sec.set(ds, elapsed);
    }
    res.process_time_sec.set(key, elapsed - processStart);
  }
  for (const list of dwellsBy.values()) for (const ds of list) elapsed += res.seq_to_dwell_sec.get(ds)!;
  res.total_time_sec = elapsed;
}

/** 편의: 텍스트 전체(Python splitlines 규칙) */
export const toolpathFromText = (text: string, machineType: string, specs?: MachineSpec, maxLines?: number): ToolpathResult => {
  const lines = pySplitlines(text);
  return processNcLines(maxLines ? lines.slice(0, maxLines) : lines, machineType, specs);
};
