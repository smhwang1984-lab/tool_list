// 밀링 공구 형상 — 원본 nc_sim.py ToolShape / tool_shape_from_values (공구 축 = +Z, 원점 = 공구 팁)
export interface ToolValues {
  type: string;
  D: number | null;
  FL: number | null;
  R: number | null;
  SIG: number | null;
  PL: number | null;
  SO: number | null;
}

const TYPE_FLAT = new Set(['FLAT E/M', 'DYNAMIC E/M']);
const TYPE_FILLET = new Set(['FILLET E/M', 'CUTTER', 'FACE MILL']);
const TYPE_BALL = new Set(['BALL E/M']);
const TYPE_DRILL = new Set(['DRILL']);
export const DEFAULT_DRILL_ANGLE_DEG = 118;

// v2.8.0: GPU 엔진(sim_shaders/cut.frag)이 같은 형상을 쓰도록 프로파일마다 셰이더용 매개변수
// [종류, a, b, c]를 붙인다(원본 nc_sim.py PROFILE_* 와 같은 번호·식).
//   0 평바닥 h=0 / 1 코너 R(a=평평한 반경, b=코너 R) / 2 원뿔(a=기울기) / 3 챔퍼(a=평평한 반경)
export const PROFILE_FLAT = 0;
export const PROFILE_CORNER = 1;
export const PROFILE_CONE = 2;
export const PROFILE_CHAMFER = 3;
export type ProfileParams = readonly [number, number, number, number];
type Profile = ((r: number) => number) & { params?: ProfileParams };

export interface RadialLut {
  lut: Float64Array;
  invStep: number;
}

export class ToolShape {
  readonly radius: number;
  readonly length: number;
  readonly cutLength: number;
  readonly typeName: string;
  private readonly profile: Profile;
  private readonly luts = new Map<number, RadialLut>();

  constructor(radius: number, profile: Profile, length: number, typeName = '', cutLength: number | null = null) {
    this.radius = radius;
    this.length = length;
    this.cutLength = cutLength ? cutLength : length;
    this.typeName = typeName;
    this.profile = profile;
  }

  /** 격자 간격 res 에 맞춘 반경 방향 높이표 (원본 radial_lut) */
  radialLut(res: number): RadialLut {
    const key = Math.round(res * 1e6) / 1e6;
    let entry = this.luts.get(key);
    if (!entry) {
      const n = Math.max(1, Math.ceil(this.radius / (res / 32)));
      const step = this.radius / n;
      const lut = new Float64Array(n + 2);
      for (let k = 0; k < n + 2; k++) lut[k] = this.profile(Math.min(k * step, this.radius));
      entry = { lut, invStep: 1 / step };
      this.luts.set(key, entry);
    }
    return entry;
  }

  /** GPU 셰이더에 넘기는 형상 매개변수. 형상 함수를 직접 만든 공구처럼 모르면 null(CPU 엔진으로 깎아야 한다). */
  profileParams(): ProfileParams | null {
    return this.profile.params ?? null;
  }
}

function withParams(fn: (r: number) => number, params: ProfileParams): Profile {
  const profile = fn as Profile;
  profile.params = params;
  return profile;
}

const flatProfile = (): Profile => withParams(() => 0, [PROFILE_FLAT, 0, 0, 0]);
function cornerRProfile(radius: number, cornerR: number): Profile {
  const c = Math.min(Math.max(cornerR, 0), radius);
  const flatR = radius - c;
  return withParams((r) => {
    if (c > 1e-9 && r > flatR) {
      const dr = Math.min(Math.max(r - flatR, 0), c);
      return c - Math.sqrt(Math.max(c * c - dr * dr, 0));
    }
    return 0;
  }, c > 1e-9 ? [PROFILE_CORNER, flatR, c, 0] : [PROFILE_FLAT, 0, 0, 0]);
}
function coneProfile(halfAngleRad: number): Profile {
  const slope = 1 / Math.max(Math.tan(Math.max(halfAngleRad, 1e-4)), 1e-6);
  return withParams((r) => r * slope, [PROFILE_CONE, slope, 0, 0]);
}
function chamferProfile(radius: number, chamferHeight: number): Profile {
  const h = Math.min(Math.max(chamferHeight, 0), radius);
  const flatR = radius - h;
  return withParams((r) => Math.max(r - flatR, 0), [PROFILE_CHAMFER, flatR, 0, 0]);
}

/** 툴리스트 한 공구의 값으로 형상을 만든다. 지름이 없거나 0 이하면 null. */
export function toolShapeFromValues(v: ToolValues): ToolShape | null {
  const d = v.D;
  if (!d || d <= 0) return null;
  const radius = d / 2;
  const length = v.SO ? v.SO : v.FL ? v.FL : d * 3;
  const cutLength = v.FL ? v.FL : length;
  const name = (v.type || '').trim().toUpperCase();
  if (TYPE_BALL.has(name)) return new ToolShape(radius, cornerRProfile(radius, radius), length, name, cutLength);
  if (TYPE_DRILL.has(name)) {
    const angle = v.SIG ? v.SIG : DEFAULT_DRILL_ANGLE_DEG;
    return new ToolShape(radius, coneProfile((Math.max(angle, 1) / 2) * (Math.PI / 180)), length, name, cutLength);
  }
  if (TYPE_FILLET.has(name)) return new ToolShape(radius, cornerRProfile(radius, v.R ? v.R : 0), length, name, cutLength);
  if (TYPE_FLAT.has(name)) return new ToolShape(radius, flatProfile(), length, name, cutLength);
  if (v.PL) return new ToolShape(radius, chamferProfile(radius, v.PL), length, name, cutLength);
  return new ToolShape(radius, flatProfile(), length, name, cutLength);
}

/** 3D 뷰어 필터 키(T01/T1/1) → 공구 값 (원본 tool_shape_map_from_rows) */
export function toolShapeMapFromRows(rows: readonly Record<string, unknown>[]): Map<string, ToolValues> {
  const num = (x: unknown): number | null => {
    const s = String(x ?? '').trim();
    if (!s) return null;
    const n = Number(s);
    return Number.isFinite(n) ? n : null;
  };
  const map = new Map<string, ToolValues>();
  for (const row of rows) {
    const m = /^T?(\d+)$/.exec(String(row.NO ?? '').trim().toUpperCase());
    if (!m) continue;
    const n = parseInt(m[1]!, 10);
    const values: ToolValues = {
      type: String(row.TYPE ?? '').trim(),
      D: num(row.D), FL: num(row.FL), R: num(row.R), SIG: num(row.SIG), PL: num(row.PL), SO: num(row.SO),
    };
    for (const key of [`T${String(n).padStart(2, '0')}`, `T${n}`, String(n)]) map.set(key, values);
  }
  return map;
}
