// 선반 인서트·홀더 규격표와 툴리스트 자동 입력 — 원본 lathe_insert_spec.py (v2.1.0 ~ v2.2.3)
//
// - ISO 1832 선삭 인서트 코드(CNMG 120408 ...)를 형상/여유각/내접원/두께/노즈 R로 푼다.
// - 나사 인서트(16ER 1.5 ISO ...), 잘 알려진 홈 인서트 표기, ISO 5608 홀더 코드를 읽는다.
// - 값의 출처와 우선순위(앞이 이긴다):
//     R, T   : NC 주석 태그 > 직접 입력 저장값 > 인서트 문구의 R > ISO 규격 해석
//     PITCH  : NC 주석 태그 > 인서트 표기(16ER 1.5 ISO) > 프로그램 G76/G32의 F > 직접 입력 저장값
//     종류/방향: 직접 입력 저장값(홀더+인서트별) > 자동 추천
//   저장값이 BLANK('-')이면 "일부러 비운 칸"으로 보고 자동 추천도 채우지 않는다.
// 읽지 못한 값은 절대 지어내지 않고 빈 문자열로 둔다.
//
// 결과 객체의 키 이름은 원본 dict 키(snake_case)를 그대로 쓴다 — 골든 비교와 P6(형상 시뮬레이션)에서
// 같은 이름으로 쓰기 위해서다. 저장소 파일 입출력은 platform/에서 한다(여기는 메모리 안의 저장소만).
import {
  PyError, RE_I, pyFloat, pyFormatFixed, pyInt, pyRe, pyRoundDigits, pyStr, pyStrip,
  pyTruthy, reFinditer, reFullmatch, reSearch, reSub,
} from './py';

// --------------------------------------------------------------------------
// 표 (ISO 1832 / ISO 5608)
// --------------------------------------------------------------------------

/** 인서트 형상 문자 -> [이름, 날끝각°]. R(원형)은 각이 없다. */
export const INSERT_SHAPES: Readonly<Record<string, readonly [string, number | null]>> = {
  C: ['80° 마름모', 80.0],
  D: ['55° 마름모', 55.0],
  E: ['75° 마름모', 75.0],
  M: ['86° 마름모', 86.0],
  V: ['35° 마름모', 35.0],
  S: ['정사각형', 90.0],
  T: ['정삼각형', 60.0],
  W: ['80° 트라이곤', 80.0],
  R: ['원형', null],
};
/** 여유각 문자 -> ° */
export const CLEARANCE_ANGLES: Readonly<Record<string, number>> = {
  A: 3.0, B: 5.0, C: 7.0, D: 15.0, E: 20.0, F: 25.0, G: 30.0, N: 0.0, P: 11.0,
};
/** 두께 코드 -> mm */
export const THICKNESS_MM: Readonly<Record<string, number>> = {
  '01': 1.59, T1: 1.98, '02': 2.38, '03': 3.18, T3: 3.97, '04': 4.76,
  '05': 5.56, '06': 6.35, '07': 7.94, '09': 9.52,
};
/** 표준 내접원(mm) — 인치계열(6.35 = 1/4")와 미터계열 */
export const IC_INCH: readonly number[] = [3.97, 4.76, 5.56, 6.35, 7.94, 9.525, 12.7, 15.875, 19.05, 25.4, 31.75];
export const IC_METRIC: readonly number[] = [6.0, 8.0, 10.0, 12.0, 16.0, 20.0, 25.0];
const IC_ALL: readonly number[] = [...new Set([...IC_INCH, ...IC_METRIC])].sort((a, b) => a - b);

/** 홀더(ISO 5608) 접근각(공구 주절인각) — 형태 문자 -> ° */
export const HOLDER_APPROACH_ANGLES: Readonly<Record<string, number>> = {
  A: 90.0, B: 75.0, C: 90.0, D: 45.0, E: 60.0, F: 90.0, G: 90.0,
  H: 107.5, J: 93.0, K: 75.0, L: 95.0, M: 50.0, N: 63.0, P: 117.5,
  R: 75.0, S: 45.0, T: 60.0, U: 93.0, V: 72.5, W: 60.0, Y: 85.0,
};
/** 홀더 전체 길이 문자 -> mm */
export const HOLDER_LENGTHS: Readonly<Record<string, number>> = {
  A: 32, B: 40, C: 50, D: 60, E: 70, F: 80, G: 90, H: 100,
  J: 110, K: 125, L: 140, M: 150, N: 160, P: 170, Q: 180,
  R: 200, S: 250, T: 300, U: 350, V: 400, W: 450, Y: 500,
};

/** 툴리스트 열 값 */
export const KINDS = [
  '외경', '내경', '외경홈', '내경홈', '정면홈', '외경나사', '내경나사', '절단',
  '드릴', '엔드밀', '페이스커터', '비절삭',
] as const;
/** 턴밀(M35 구동공구)·중심 드릴 — 지름(D)이 필요하다 */
export const MILLING_KINDS: readonly string[] = ['드릴', '엔드밀', '페이스커터'];
export const NON_CUTTING_KIND = '비절삭';
/**
 * 인선(가상 인선 번호) — 노즈 중심에서 가상 인선(프로그램 좌표점)이 있는 방향.
 * 화면에서 X(반경)가 위, Z가 오른쪽(+Z = 심압대 쪽) 기준:
 *   1 = 우상(+X +Z), 2 = 우하(-X +Z), 3 = 좌하(-X -Z), 4 = 좌상(+X -Z), 9 = 노즈 중심.
 */
export const TIPS = ['1', '2', '3', '4', '9'] as const;
export const TIP_LABELS: Readonly<Record<string, string>> = {
  1: '1 (우상)', 2: '2 (우하)', 3: '3 (좌하)', 4: '4 (좌상)', 9: '9 (중심)',
};
export const DIRECTIONS = ['R', 'L', 'N'] as const;
export const DIRECTION_LABELS: Readonly<Record<string, string>> = {
  R: 'R (우수)', L: 'L (좌수)', N: 'N (중립)',
};

export const SOURCE_TAG = 'NC 주석 태그';
export const SOURCE_INSERT = '인서트 표기';
export const SOURCE_PROGRAM = '프로그램(G76/G32)';
export const SOURCE_SAVED = '직접 입력(저장)';
export const SOURCE_TEXT = '인서트 문구';
export const SOURCE_ISO = 'ISO 규격 해석';
export const SOURCE_AUTO = '자동 추천';
export const SOURCE_MANUAL = '직접 입력(이번 표만)';
/** 저장소에 넣는 "일부러 비움" 표식 */
export const BLANK = '-';
/** 프로그램에서 온 값 — 인서트 이름별 저장값보다 우선하므로 [수정]에서 고쳐도 저장값으로 적용되지 않는다 */
export const PROGRAM_SPECIFIC_SOURCES: readonly string[] = [SOURCE_TAG, SOURCE_INSERT, SOURCE_PROGRAM];

// --------------------------------------------------------------------------
// 정규식
// --------------------------------------------------------------------------

/** ISO 1832 선삭 인서트: 형상 여유각 공차 고정 + 크기(2) 두께(2, 또는 T#) [노즈 R(2)] */
const INSERT_RE = pyRe(
  String.raw`(?<![A-Z0-9])([CDEMVSTWR])([ABCDEFGNP])([AFCHEGJKLMNU])([ABFGHJMNQRTUWX])`
  + String.raw`\s*(\d{2})\s*(T\d|\d{2})\s*(\d{2})?(?!\d)`, RE_I);
/** 나사 인서트: 길이 [E|I][R|L] 피치 [규격]  (16ER 1.5 ISO, 16IR 14W, 22ER 3.0 ISO) */
const THREAD_INSERT_RE = pyRe(
  String.raw`(?<![A-Z0-9.])(\d{2})\s*([EI])\s*([RL])\s*(\d+(?:[.,]\d+)?)\s*(ISO|UNJ|UNC|UNF|UNEF|UNS|UN|W|NPTF|NPT|BSPT|BSPP|G|ACME)?`
  + String.raw`(?![A-Z0-9])`, RE_I);
/** 부분 프로파일 나사 인서트: 16ER AG60, 16IR A60 (피치 없음) */
const THREAD_PARTIAL_RE = pyRe(
  String.raw`(?<![A-Z0-9])(\d{2})\s*([EI])\s*([RL])\s*(?:A|AG|N|NG|G)\s*(55|60)(?![0-9])`, RE_I);
// 잘 알려진 홈 인서트 표기
const GROOVE_N123_RE = pyRe(String.raw`(?<![A-Z0-9])N123[A-Z]\d?\s*-\s*(\d{4})(?:\s*-\s*(\d{4}))?`, RE_I);
const GROOVE_MGXN_RE = pyRe(String.raw`(?<![A-Z0-9])M[GR][GM]N\s*(\d{3,4})(?![0-9])`, RE_I);
const GROOVE_GTN_RE = pyRe(String.raw`(?<![A-Z0-9])GTN\s*-?\s*(\d+(?:\.\d+)?)(?![0-9.])`, RE_I);
const GROOVE_GIP_RE = pyRe(String.raw`(?<![A-Z0-9])GIP\s*(\d+\.\d+)\s*-\s*(\d+\.\d+)`, RE_I);
/** ISO 5608 홀더: 클램프 인서트형상 접근각 여유각 좌우 [섕크 폭x높이 길이] [인서트 크기] */
const HOLDER_RE = pyRe(
  String.raw`(?<![A-Z])([A-Z])([CDEMVSTWRKLABHOP])([A-Z])([A-Z])([RLN])`
  + String.raw`(?:\s*(\d{2})(\d{2})\s*([A-Z])?)?\s*(\d{2})?(?![0-9])`, RE_I);
/** ISO 5608 형식이 아닌 홀더(홈/나사/절단용: MGEHR 2525-3, SER 2525M16)의 좌우 */
const HOLDER_HAND_RE = pyRe(String.raw`(?<![A-Z])[A-Z]{2,5}([RL])\s*\d{4}(?![0-9])`, RE_I);
/** 내경 바(boring bar) 접두어: S25T-PCLNR, A32S-MCLNR */
const BAR_PREFIX_RE = pyRe(String.raw`(?<![A-Z0-9])[A-Z]\d{2}[A-Z]\s*-?\s*[A-Z]{4,5}[RLN]`, RE_I);
/** 문구 안 노즈 R 표기: "| R-0.8", "R0.4" */
const TEXT_R_RE = pyRe(String.raw`(?<![A-Za-z0-9])R\s*[-=]?\s*(\d+(?:\.\d+)?)(?![0-9.]*[A-Za-z])`);

/** NC 주석 태그: [R 0.8] [T 3.0] [P 1.5] / [PITCH 1.5] / [D 10](턴밀 공구 지름) */
const TAG_RES: readonly (readonly [string, RegExp])[] = [
  ['D', pyRe(String.raw`\[\s*D\s*=?\s*([\d.]+)\s*\]`, RE_I)],
  ['R', pyRe(String.raw`\[\s*R\s*=?\s*([\d.]+)\s*\]`, RE_I)],
  ['T', pyRe(String.raw`\[\s*T\s*=?\s*([\d.]+)\s*\]`, RE_I)],
  ['PITCH', pyRe(String.raw`\[\s*P(?:ITCH)?\s*=?\s*([\d.]+)\s*\]`, RE_I)],
];

const KW_NONCUT = pyRe(String.raw`SETTING[\s.-]*PIN|NULLING|KNURL|ROLLE|널링|세팅`, RE_I);
const KW_DRILL = pyRe(String.raw`드릴|DRILL|CENTER|CENTRE|센터|(?<![A-Z])TAP(?![A-Z])|탭`, RE_I);
const KW_FACECUT = pyRe(String.raw`FACE[\s-]*(?:CUTTER|MILL)|페이스`, RE_I);
const KW_ENDMILL = pyRe(
  String.raw`END?[\s-]*MILL|엔드밀|E/M|(?<![A-Z])(?:FLAT|FILLET|BALL|CHAMF\w*|EN)(?![A-Z])|볼`, RE_I);
/** 공구 블록이 턴밀(구동공구) 구간 — M35 또는 극좌표 G12.1/G112 */
const MILLING_MODE_RE = pyRe(String.raw`M35(?!\d)|G12\.1|G112(?!\d)`, RE_I);
/** 공구 지름 표기: "D10 X 90 NC DRILL", "D5.5 CARBIDE DRILL", "MTI 0808 D30 A60" */
const TOOL_D_RE = pyRe(String.raw`(?<![A-Z0-9.])D\s*(\d+(?:\.\d+)?)(?![0-9])(?![A-WYZa-wyz])`, RE_I);
/** 명시 지름 "| DIA-6.35" — D 표기보다 우선 */
const TOOL_DIA_RE = pyRe(String.raw`(?<![A-Z])DIA\s*[-=:]?\s*(\d+(?:\.\d+)?)`, RE_I);
/** 홀더 문구의 구동공구 표식("MILL TOOL CHECK") */
const KW_LIVE_TOOL = pyRe(String.raw`MILL[\s_-]*TOOL`, RE_I);
/** 인치 나사 호칭 ".2500-28 UNJF" — 나사밀 지름을 모를 때의 대체값(호칭 지름 inch × 25.4) */
const THREAD_SIZE_INCH_RE = pyRe(String.raw`(?<![\d.])(\d*\.\d+)\s*-\s*\d+\s*UN`, RE_I);
/** 챔퍼밀 각도 "D2X90X6"의 90, "90DEG"/"90°" */
const CHAMFER_ANGLE_RE = pyRe(String.raw`X\s*(\d+(?:\.\d+)?)\s*X|(\d+(?:\.\d+)?)\s*(?:DEG|°)`, RE_I);
const KW_CUTOFF = pyRe(String.raw`절단|CUT[\s-]?OFF|PARTING`, RE_I);
const KW_THREAD = pyRe(String.raw`나사|THREAD|THRD`, RE_I);
const KW_GROOVE = pyRe(String.raw`홈|GROOV|GRV`, RE_I);
const KW_FACE = pyRe(String.raw`정면|\bFACE\b`, RE_I);
const KW_INTERNAL = pyRe(String.raw`내경|BORING|\bBORE\b|(?<![A-Z])ID(?![A-Z])|INTERNAL`, RE_I);
const KW_EXTERNAL = pyRe(String.raw`외경|(?<![A-Z])OD(?![A-Z])|EXTERNAL|TURNING`, RE_I);

const GCODE_THREAD_RE = pyRe(String.raw`G(?:76|32)(?!\d)`, RE_I);
const GCODE_GROOVE_RE = pyRe(String.raw`G75(?!\d)`, RE_I);
const GCODE_FACE_GROOVE_RE = pyRe(String.raw`G74(?!\d)`, RE_I);
const GCODE_TURN_CYCLE_RE = pyRe(String.raw`G7[0-3](?!\d)`, RE_I);
const F_WORD_RE = pyRe(String.raw`F\s*([\d.]+)`, RE_I);
const WS_RUN_RE = pyRe(String.raw`\s+`);
const TOOL_NO_RE = pyRe(String.raw`T(\d{2})\d{2}`);

// --------------------------------------------------------------------------
// 유틸
// --------------------------------------------------------------------------

/** 값이 거짓이면 '' 아니면 str(값) — Python의 `'%s' % (x or '')` */
function orEmpty(value: unknown): string {
  return pyTruthy(value) ? pyStr(value) : '';
}

function has<T extends object>(table: T, key: string): boolean {
  return Object.prototype.hasOwnProperty.call(table, key);
}

function lookup<V>(table: Readonly<Record<string, V>>, key: string): V | null {
  return has(table, key) ? table[key]! : null;
}

/** 3.0 -> '3', 0.8 -> '0.8', None -> ''. ('%.3f' 뒤 끝의 0과 . 을 걷어낸다) */
export function fmtNumber(value: unknown): string {
  if (value === null || value === undefined) return '';
  const text = pyFormatFixed(pyFloat(value), 3).replace(/0+$/, '').replace(/\.$/, '');
  return text || '0';
}

/** 저장소 키 — 태그·대소문자·공백 차이를 없앤다. */
export function normalizeKey(text: unknown): string {
  let s = orEmpty(text);
  for (const [, pattern] of TAG_RES) s = reSub(pattern, '', s);
  return pyStrip(reSub(WS_RUN_RE, ' ', s)).toUpperCase();
}

/** 표시 문구에서 [R ..]/[T ..]/[P ..] 태그를 걷어낸다. */
export function stripTags(text: unknown): string {
  let s = orEmpty(text);
  for (const [, pattern] of TAG_RES) s = reSub(pattern, '', s);
  return pyStrip(s);
}

/** text 안의 태그 값을 {R: '0.8', ...}로 돌려준다(없는 것은 생략). */
export function findTags(text: unknown): Record<string, string> {
  const found: Record<string, string> = {};
  const s = orEmpty(text);
  for (const [key, pattern] of TAG_RES) {
    const match = reSearch(pattern, s);
    if (match) {
      const value = cleanNumber(match[1]);
      if (value) found[key] = value;
    }
  }
  return found;
}

/** float(str(text).replace(',', '.')) 를 fmt_number 로. 못 읽으면 '' */
export function cleanNumber(text: unknown): string {
  try {
    return fmtNumber(pyFloat(pyStr(text).replace(/,/g, '.')));
  } catch (error) {
    if (error instanceof PyError) return '';
    throw error;
  }
}

/** float(...) 로 못 읽으면 null */
export function floatOrNull(text: unknown): number | null {
  try {
    return pyFloat(pyStrip(pyStr(text)).replace(/,/g, '.'));
  } catch (error) {
    if (error instanceof PyError) return null;
    throw error;
  }
}

const radians = (deg: number): number => deg * (Math.PI / 180); // Python math.radians 와 같은 식

// --------------------------------------------------------------------------
// ISO 1832 인서트
// --------------------------------------------------------------------------

/** 내접원 지름 ic(mm)에서 절삭날 길이(mm). 원형은 null. */
export function edgeLengthFromIc(shape: string, ic: number): number | null {
  if (shape === 'R') return null;
  if (shape === 'S') return ic;
  if (shape === 'T') return ic * Math.sqrt(3.0);
  if (shape === 'W') { // 80°/160° 교대 육각 — 이웃 두 꼭짓점의 접선 길이 합
    const r = ic / 2.0;
    return r * (1.0 / Math.tan(radians(40.0)) + 1.0 / Math.tan(radians(80.0)));
  }
  if (!has(INSERT_SHAPES, shape)) throw new PyError('KeyError', shape);
  return ic / Math.sin(radians(INSERT_SHAPES[shape]![1]!));
}

/** ISO 1832 크기 코드(정수) — 절삭날 길이(원형은 지름)를 내림한 값. */
export function sizeCodeForIc(shape: string, ic: number): number {
  const length = shape === 'R' ? ic : edgeLengthFromIc(shape, ic)!;
  return Math.floor(length + 0.05);
}

/**
 * 크기 코드에서 내접원 지름을 찾는다. [ic, 대안 목록] — 못 찾으면 [null, []].
 * 후보가 둘 이상(12.0/12.7)이면 인치계열을 우선하고, 원형 + 여유각이 N이 아니면 미터계열을 우선한다.
 */
export function icForSizeCode(shape: string, code: number, clearance = 'N'): [number | null, number[]] {
  const candidates = IC_ALL.filter((ic) => sizeCodeForIc(shape, ic) === code);
  if (!candidates.length) return [null, []];
  if (candidates.length === 1) return [candidates[0]!, []];
  const preferMetric = shape === 'R' && clearance !== 'N';
  const preferred = preferMetric ? IC_METRIC : IC_INCH;
  const picked = candidates.filter((ic) => preferred.includes(ic));
  const ic = picked.length ? picked[0]! : candidates[0]!;
  return [ic, candidates.filter((c) => c !== ic)];
}

export interface InsertInfo {
  code: string;
  shape: string;
  shape_name: string;
  angle: number | null;
  clearance: string;
  clearance_angle: number | null;
  tolerance: string;
  mounting: string;
  size_code: number;
  ic: number | null;
  ic_alt: number[];
  edge_length: number | null;
  thickness: number;
  nose_r: number | null;
}

/** 텍스트에서 ISO 1832 선삭 인서트 코드를 찾아 푼다. 없으면 null. */
export function parseInsert(text: unknown): InsertInfo | null {
  const match = reSearch(INSERT_RE, orEmpty(text));
  if (!match) return null;
  const [shape, clear, tol, mount, size, thick, nose] = [1, 2, 3, 4, 5, 6, 7]
    .map((i) => (match[i] ? match[i]!.toUpperCase() : null)) as [string, string, string, string, string, string, string | null];
  if (!has(THICKNESS_MM, thick)) return null;
  const [ic, alt] = icForSizeCode(shape, pyInt(size), clear);
  const info: InsertInfo = {
    code: `${shape}${clear}${tol}${mount} ${size}${thick}${nose || ''}`,
    shape,
    shape_name: INSERT_SHAPES[shape]![0],
    angle: INSERT_SHAPES[shape]![1],
    clearance: clear,
    clearance_angle: lookup(CLEARANCE_ANGLES, clear),
    tolerance: tol,
    mounting: mount,
    size_code: pyInt(size),
    ic,
    ic_alt: alt,
    edge_length: ic === null ? null : edgeLengthFromIc(shape, ic),
    thickness: THICKNESS_MM[thick]!,
    nose_r: null,
  };
  if (shape === 'R') {
    info.nose_r = ic === null ? null : ic / 2.0;
  } else if (nose && pyInt(nose) > 0) { // '00'은 날끝이 날카롭거나 미지정 — R 값을 지어내지 않는다
    info.nose_r = pyInt(nose) / 10.0;
  }
  return info;
}

const TPI_FORMS: readonly string[] = ['UN', 'UNJ', 'UNC', 'UNF', 'UNEF', 'UNS', 'W', 'NPT', 'NPTF', 'BSPT', 'BSPP', 'G'];

export interface ThreadInfo {
  side: string;
  hand: string;
  pitch: number | null;
  form: string;
  length: number;
  angle: number;
}

/** 나사 인서트(16ER 1.5 ISO / 16IR AG60 ...). 없으면 null. */
export function parseThreadInsert(text: unknown): ThreadInfo | null {
  const s = orEmpty(text);
  let match = reSearch(THREAD_INSERT_RE, s);
  if (match) {
    const length = match[1]!;
    const side = match[2]!;
    const hand = match[3]!;
    const number = match[4]!;
    const form = (match[5] ?? '').toUpperCase();
    const value = floatOrNull(number);
    if (value === null || value <= 0) return null;
    const pitch = TPI_FORMS.includes(form) ? 25.4 / value : value; // 산/inch
    return {
      side: side.toUpperCase() === 'E' ? '외경' : '내경', hand: hand.toUpperCase(),
      pitch, form: form || 'ISO', length: pyInt(length),
      angle: ['W', 'BSPT', 'BSPP', 'G'].includes(form) ? 55.0 : 60.0,
    };
  }
  match = reSearch(THREAD_PARTIAL_RE, s);
  if (match) {
    return {
      side: match[2]!.toUpperCase() === 'E' ? '외경' : '내경', hand: match[3]!.toUpperCase(),
      pitch: null, form: 'PARTIAL', length: pyInt(match[1]!), angle: pyFloat(match[4]!),
    };
  }
  return null;
}

export interface GrooveInfo {
  width: number;
  corner_r: number | null;
  series: string;
}

/** 잘 알려진 홈 인서트 표기에서 폭(mm)·코너 R을 읽는다. 없으면 null. */
export function parseGrooveInsert(text: unknown): GrooveInfo | null {
  const s = orEmpty(text);
  let match = reSearch(GROOVE_N123_RE, s);
  if (match) {
    return {
      width: pyInt(match[1]!) / 100.0,
      corner_r: match[2] === undefined ? null : pyInt(match[2]) / 10.0,
      series: 'N123',
    };
  }
  match = reSearch(GROOVE_MGXN_RE, s);
  if (match) return { width: pyInt(match[1]!) / 100.0, corner_r: null, series: 'MGMN' };
  match = reSearch(GROOVE_GIP_RE, s);
  if (match) return { width: pyFloat(match[1]!), corner_r: pyFloat(match[2]!), series: 'GIP' };
  match = reSearch(GROOVE_GTN_RE, s);
  if (match) return { width: pyFloat(match[1]!), corner_r: null, series: 'GTN' };
  return null;
}

// --------------------------------------------------------------------------
// ISO 5608 홀더
// --------------------------------------------------------------------------

/** 문구의 지름(턴밀·중심 드릴 공구, mm) — "DIA-6.35"가 있으면 그것, 없으면 D<숫자>. 없으면 null. */
export function parseToolDiameter(text: unknown): number | null {
  const s = orEmpty(text);
  const match = reSearch(TOOL_DIA_RE, s) ?? reSearch(TOOL_D_RE, s);
  if (!match) {
    const inch = reSearch(THREAD_SIZE_INCH_RE, s);
    const value = inch ? floatOrNull(inch[1]) : null;
    return value && value > 0 ? pyRoundDigits(value * 25.4, 4) : null;
  }
  const value = floatOrNull(match[1]);
  return value && value > 0 ? value : null;
}

export interface HolderInfo {
  code: string;
  clamp: string;
  insert_shape: string;
  style: string;
  approach_angle: number | null;
  clearance: string;
  hand: string;
  shank_w: number | null;
  shank_h: number | null;
  length: number | null;
  insert_size: number | null;
  is_bar: boolean;
}

/** ISO 5608 홀더 코드를 푼다. 없으면 null. 앞에 다른 단어가 있어도 유효한 코드를 찾는다. */
export function parseHolder(text: unknown): HolderInfo | null {
  const s = orEmpty(text);
  for (const match of reFinditer(HOLDER_RE, s)) {
    const [clamp, shape, style, clear, hand] = [1, 2, 3, 4, 5].map((i) => match[i]!.toUpperCase()) as
      [string, string, string, string, string];
    const [sw, sh, lengthLetter, size] = [match[6], match[7], match[8], match[9]];
    if (!has(CLEARANCE_ANGLES, clear) && clear !== 'O') continue;
    return {
      code: pyStrip(match[0]),
      clamp,
      insert_shape: shape,
      style,
      approach_angle: lookup(HOLDER_APPROACH_ANGLES, style),
      clearance: clear,
      hand,
      shank_w: sw ? pyInt(sw) : null,
      shank_h: sh ? pyInt(sh) : null,
      length: lookup(HOLDER_LENGTHS, (lengthLetter || '').toUpperCase()),
      insert_size: size ? pyInt(size) : null,
      is_bar: reSearch(BAR_PREFIX_RE, s) !== null,
    };
  }
  return null;
}

// --------------------------------------------------------------------------
// 종류·방향 자동 추천
// --------------------------------------------------------------------------

export interface Hints {
  thread: boolean;
  groove: boolean;
  face_groove: boolean;
  turning: boolean;
  milling: boolean;
  pitch: string;
}
export type PartialHints = Partial<Hints> | Readonly<Record<string, unknown>>;

/** 공구 블록 코드(주석 제외, 줄 목록)에서 종류/피치 힌트를 뽑는다. */
export function programHints(codeLines: Iterable<string>): Hints {
  const hints: Hints = { thread: false, groove: false, face_groove: false, turning: false, milling: false, pitch: '' };
  for (const line of [...codeLines]) {
    if (reSearch(GCODE_THREAD_RE, line)) {
      hints.thread = true;
      if (!hints.pitch) {
        // G76 두 줄 형식은 둘째 줄에도 G76이 있어 그 줄의 F가 잡힌다. 같은 줄의 F만 쓴다.
        const f = reSearch(F_WORD_RE, line);
        const value = f ? floatOrNull(f[1]) : null;
        if (value !== null && value >= 0.05 && value <= 12.0) hints.pitch = fmtNumber(value);
      }
    }
    if (reSearch(GCODE_GROOVE_RE, line)) hints.groove = true;
    if (reSearch(GCODE_FACE_GROOVE_RE, line)) hints.face_groove = true;
    if (reSearch(GCODE_TURN_CYCLE_RE, line)) hints.turning = true;
    if (reSearch(MILLING_MODE_RE, line)) hints.milling = true;
  }
  return hints;
}

/** 같은 공구가 여러 N 블록에서 쓰일 때 힌트를 합친다(피치는 처음 값 유지). */
export function mergeHints(base: PartialHints, extra: PartialHints): Record<string, unknown> {
  const b = base as Record<string, unknown>;
  const e = extra as Record<string, unknown>;
  const merged: Record<string, unknown> = { ...b };
  for (const key of ['thread', 'groove', 'face_groove', 'turning', 'milling']) {
    merged[key] = pyTruthy(b[key]) || pyTruthy(e[key]);
  }
  merged.pitch = (pyTruthy(b.pitch) ? b.pitch : pyTruthy(e.pitch) ? e.pitch : '') as unknown;
  return merged;
}

/** 공구 종류 자동 추천. 알 수 없으면 ''. */
export function inferKind(insertText: unknown, holderText: unknown, hints?: PartialHints | null): string {
  const h = (hints ?? {}) as Record<string, unknown>;
  const text = `${orEmpty(insertText)} ${orEmpty(holderText)}`;
  const thread = parseThreadInsert(text);
  const holder = parseHolder(holderText) ?? parseHolder(insertText);
  const internal = Boolean(
    reSearch(KW_INTERNAL, text) || reSearch(BAR_PREFIX_RE, text) || (thread && thread.side === '내경'));
  if (reSearch(KW_NONCUT, text)) return NON_CUTTING_KIND;
  if (reSearch(KW_DRILL, text)) return '드릴';
  if (reSearch(KW_FACECUT, text)) return '페이스커터';
  if (reSearch(KW_ENDMILL, text)) return '엔드밀';
  if (reSearch(KW_CUTOFF, text)) return '절단';
  if (reSearch(KW_THREAD, text) || thread) return internal ? '내경나사' : '외경나사';
  if (reSearch(KW_GROOVE, text) || parseGrooveInsert(text)) {
    if (reSearch(KW_FACE, text)) return '정면홈';
    return internal ? '내경홈' : '외경홈';
  }
  if (parseInsert(text)) return internal ? '내경' : '외경';
  if (reSearch(KW_INTERNAL, text)) return '내경';
  if (reSearch(KW_EXTERNAL, text)) return '외경';
  const millingHint = pyTruthy(h.milling) || reSearch(KW_LIVE_TOOL, text) !== null;
  if (millingHint && reSearch(THREAD_SIZE_INCH_RE, orEmpty(insertText))) {
    // 구동공구의 인치 나사 호칭(".2500-28 UNJF_3B")은 측면 리지드 탭(M29 + G88) — 드릴 형상으로 근사
    return '드릴';
  }
  if (millingHint && parseToolDiameter(insertText)) {
    // 문구로 종류를 못 정해도 턴밀(M35/G12.1) 구간에서 지름이 있는 공구는 엔드밀로 추천한다
    return '엔드밀';
  }
  if (pyTruthy(h.thread)) return internal ? '내경나사' : '외경나사';
  if (pyTruthy(h.groove)) return internal ? '내경홈' : '외경홈';
  if (pyTruthy(h.face_groove)) return '정면홈';
  if (pyTruthy(h.turning)) return internal ? '내경' : '외경';
  if (holder) return internal || holder.is_bar ? '내경' : '외경';
  return '';
}

/** 공구 방향(R 우수 / L 좌수 / N 중립) 자동 추천. 알 수 없으면 ''. */
export function inferDirection(kind: string, insertText: unknown, holderText: unknown): string {
  const text = `${orEmpty(insertText)} ${orEmpty(holderText)}`;
  const thread = parseThreadInsert(text);
  if (thread) return thread.hand;
  const holder = parseHolder(holderText) ?? parseHolder(insertText);
  if (holder) return holder.hand;
  const handMatch = reSearch(HOLDER_HAND_RE, orEmpty(holderText));
  if (handMatch) return handMatch[1]!.toUpperCase();
  if (['절단', '드릴', '외경홈', '내경홈', '정면홈'].includes(kind)) return 'N';
  return '';
}

/**
 * 가상 인선 번호 자동 추천 — 외경 R 3 / L 2, 내경 R 4 / L 1, 정면홈 4. 그 밖은 ''.
 * (외경·내경 홈은 프로그램 기준 모서리를 알 수 없어 추천하지 않는다.)
 */
export function inferTip(kind: string, hand: unknown): string {
  const h = orEmpty(hand).toUpperCase();
  if (kind === '외경' || kind === '외경나사') return h === 'R' ? '3' : h === 'L' ? '2' : '';
  if (kind === '내경' || kind === '내경나사') return h === 'R' ? '4' : h === 'L' ? '1' : '';
  if (kind === '정면홈') return '4'; // 실측(O2222/O4811 정면홈 가공 경로): 프로그램 기준점 = 바깥(+r) 모서리
  return '';
}

// --------------------------------------------------------------------------
// 값 결정 (출처 우선순위)
// --------------------------------------------------------------------------

export type ValueSource = [value: string, source: string];

/** 텍스트만으로 알 수 있는(ISO 해석/문구) R·T·PITCH 값과 출처. 모르면 키 없음. */
export function isoValues(insertText: unknown, _holderText: unknown = ''): Record<string, ValueSource> {
  const text = orEmpty(insertText);
  const found: Record<string, ValueSource> = {};
  const textR = reSearch(TEXT_R_RE, text);
  if (textR && (floatOrNull(textR[1]) || 0.0) > 0) { // "R-0." 같은 0은 값이 아니다
    found.R = [cleanNumber(textR[1]), SOURCE_TEXT];
  }
  const insert = parseInsert(text);
  const groove = parseGrooveInsert(text);
  const thread = parseThreadInsert(text);
  if (!('R' in found)) {
    if (insert && insert.nose_r !== null) found.R = [fmtNumber(insert.nose_r), SOURCE_ISO];
    else if (groove && groove.corner_r !== null) found.R = [fmtNumber(groove.corner_r), SOURCE_ISO];
  }
  if (groove) found.T = [fmtNumber(groove.width), SOURCE_ISO];
  if (thread && thread.pitch !== null) found.PITCH = [fmtNumber(thread.pitch), SOURCE_INSERT];
  return found;
}

/** 직접 입력 저장소가 줘야 하는 것 */
export interface SpecStore {
  getInsert(insertText: unknown, holderText?: unknown): Record<string, string>;
  getTool(holderText: unknown, insertText: unknown): Record<string, string>;
}

export interface FieldValues {
  R: string; T: string; PITCH: string; KIND: string; DIR: string; TIP: string; D: string;
}
export type FieldSources = FieldValues;

/**
 * 툴리스트 한 행의 R/T/PITCH/KIND/DIR/TIP/D 값을 출처 우선순위대로 정한다.
 * tags: NC 주석 태그, hints: programHints() 결과, store: 직접 입력 저장값(없으면 null)
 */
export function resolveFields(
  insertText: unknown, holderText: unknown,
  tags?: Readonly<Record<string, string>> | null, hints?: PartialHints | null, store?: SpecStore | null,
): [FieldValues, FieldSources] {
  const tg = tags ?? {};
  const hn = (hints ?? {}) as Record<string, unknown>;
  const saved = store ? store.getInsert(insertText, holderText) : {};
  const savedTool = store ? store.getTool(holderText, insertText) : {};
  const iso = isoValues(insertText, holderText);
  const values: FieldValues = { R: '', T: '', PITCH: '', KIND: '', DIR: '', TIP: '', D: '' };
  const sources: FieldSources = { R: '', T: '', PITCH: '', KIND: '', DIR: '', TIP: '', D: '' };
  const none: ValueSource = ['', ''];
  const str = (v: unknown): string => (v === undefined || v === null ? '' : (v as string));

  const take = (key: keyof FieldValues, candidates: readonly (readonly [string, string])[]): void => {
    for (const [value, source] of candidates) {
      if (value === BLANK) { // 사용자가 일부러 비운 칸 — 낮은 우선순위 값도 쓰지 않는다
        values[key] = '';
        sources[key] = source;
        return;
      }
      if (value) {
        values[key] = value;
        sources[key] = source;
        return;
      }
    }
  };

  take('R', [[str(tg.R), SOURCE_TAG], [str(saved.R), SOURCE_SAVED], iso.R ?? none]);
  take('T', [[str(tg.T), SOURCE_TAG], [str(saved.T), SOURCE_SAVED], iso.T ?? none]);
  take('PITCH', [[str(tg.PITCH), SOURCE_TAG], iso.PITCH ?? none,
    [str(hn.pitch), SOURCE_PROGRAM], [str(saved.PITCH), SOURCE_SAVED]]);
  const autoKind = inferKind(insertText, holderText, hints);
  take('KIND', [[str(savedTool.KIND), SOURCE_SAVED], [autoKind, SOURCE_AUTO]]);
  const autoDir = inferDirection(values.KIND || autoKind, insertText, holderText);
  take('DIR', [[str(savedTool.DIR), SOURCE_SAVED], [autoDir, SOURCE_AUTO]]);
  const autoTip = inferTip(values.KIND || autoKind, values.DIR || autoDir);
  take('TIP', [[str(savedTool.TIP), SOURCE_SAVED], [autoTip, SOURCE_AUTO]]);
  // 턴밀·중심 드릴 공구 지름 — 인서트 문구의 D<숫자>(홀더 문구는 밀링 공구일 때만 뒤져 본다)
  let diameter = parseToolDiameter(insertText);
  if (diameter === null && MILLING_KINDS.includes(values.KIND || autoKind)) {
    diameter = parseToolDiameter(holderText);
  }
  take('D', [[str(tg.D), SOURCE_TAG], [str(saved.D), SOURCE_SAVED], [diameter ? fmtNumber(diameter) : '', SOURCE_TEXT]]);
  return [values, sources];
}

/** [자동 추천] 버튼용 — 문구만으로 추천할 수 있는 값(저장값·태그 제외) */
export function recommendFields(insertText: unknown, holderText: unknown): FieldValues {
  return resolveFields(insertText, holderText)[0];
}

// --------------------------------------------------------------------------
// 표시용 설명 (길게 누르면 나오는 설명)
// --------------------------------------------------------------------------

/** 인서트 문구의 규격 해석 요약. 해석할 게 없으면 ''. */
export function describeInsert(text: unknown): string {
  const insert = parseInsert(text);
  if (insert) {
    const parts: string[] = [insert.shape_name];
    if (insert.clearance_angle !== null) parts.push(`여유각 ${fmtNumber(insert.clearance_angle)}°`);
    if (insert.ic !== null) parts.push(`내접원 ${fmtNumber(insert.ic)}`);
    if (insert.edge_length !== null) parts.push(`날 길이 ${fmtNumber(pyRoundDigits(insert.edge_length, 1))}`);
    parts.push(`두께 ${fmtNumber(insert.thickness)}`);
    if (insert.nose_r !== null) parts.push(`노즈R ${fmtNumber(insert.nose_r)}`);
    const note = insert.ic_alt.length ? ` (내접원 후보: ${insert.ic_alt.map((v) => fmtNumber(v)).join(', ')})` : '';
    return `ISO 1832 ${insert.code}: ${parts.join(' / ')}${note}`;
  }
  const thread = parseThreadInsert(text);
  if (thread) {
    const parts: string[] = [`${thread.side} 나사`, `${thread.hand} (${thread.hand === 'R' ? '우수' : '좌수'})`];
    if (thread.pitch !== null) parts.push(`피치 ${fmtNumber(thread.pitch)}`);
    parts.push(`${fmtNumber(thread.angle)}°`);
    return '나사 인서트: ' + parts.join(' / ');
  }
  const groove = parseGrooveInsert(text);
  if (groove) {
    const parts: string[] = [`폭 ${fmtNumber(groove.width)}`];
    if (groove.corner_r !== null) parts.push(`코너R ${fmtNumber(groove.corner_r)}`);
    return `홈 인서트(${groove.series}): ${parts.join(' / ')}`;
  }
  return '';
}

/** 홀더 문구의 규격 해석 요약. 해석할 게 없으면 ''. */
export function describeHolder(text: unknown): string {
  const holder = parseHolder(text);
  if (!holder) return '';
  const parts: string[] = [];
  if (holder.approach_angle !== null) parts.push(`접근각 ${fmtNumber(holder.approach_angle)}°`);
  const handName: Record<string, string> = { R: '우수(R)', L: '좌수(L)', N: '중립(N)' };
  parts.push(handName[holder.hand]!);
  if (holder.shank_w) parts.push(`섕크 ${holder.shank_w}×${holder.shank_h}`);
  if (holder.length) parts.push(`길이 ${holder.length}`);
  if (holder.is_bar) parts.push('내경 바');
  return `ISO 5608 ${holder.code}: ${parts.join(' / ')}`;
}

// --------------------------------------------------------------------------
// 시뮬레이션용 형상 맵
// --------------------------------------------------------------------------

/** 챔퍼밀 끝 각도(도) — "D2X90X6"의 90. 없으면 null. */
export function chamferAngle(text: unknown): number | null {
  const match = reSearch(CHAMFER_ANGLE_RE, orEmpty(text));
  if (!match) return null;
  const value = floatOrNull(match[1] ?? match[2]);
  return value && value > 0 && value < 180 ? value : null;
}

/** 턴밀·중심 드릴 종류 -> 밀링 공구 형상 type 문자열. 해당 없으면 null. */
export function millTypeFor(kind: string, insertText: unknown = ''): string | null {
  const text = orEmpty(insertText).toUpperCase();
  if (kind === '드릴') return 'DRILL';
  if (kind === '페이스커터') return 'FACE MILL';
  if (kind === '엔드밀') {
    if (text.includes('CHAMF')) return 'CHAMF';
    if (text.includes('BALL') || text.includes('볼')) return 'BALL E/M';
    if (text.includes('FILLET')) return 'FILLET E/M';
    return 'FLAT E/M';
  }
  return null;
}

export interface ToolGeometry {
  kind: string;
  hand: string;
  tip: number | null;
  diameter: number | null;
  so: number | null;
  mill_type: string | null;
  chamfer_angle: number | null;
  nose_r: number | null;
  width: number | null;
  pitch: number | null;
  shape: string | null;
  tip_angle: number | null;
  clearance_angle: number | null;
  ic: number | null;
  edge_length: number | null;
  thickness: number | null;
  thread_angle: number | null;
  approach_angle: number | null;
  shank: [number, number | null] | null;
}

const DIGITS_ONLY_RE = pyRe(String.raw`^\d+$`);

/** Python dict.get(key, default) */
function rget(row: Readonly<Record<string, unknown>>, key: string, fallback: unknown = ''): unknown {
  return has(row, key) ? row[key] : fallback;
}

/** 툴리스트 행 하나 -> 선반 시뮬레이션이 쓸 공구 형상. 값이 없거나 해석 못한 항목은 null. */
export function geometryFromRow(row: Readonly<Record<string, unknown>>): ToolGeometry {
  const insertText = pyStr(rget(row, 'INSERT'));
  const holderText = pyStr(rget(row, 'HOLDER'));
  const insert = parseInsert(insertText);
  const holder = parseHolder(holderText) ?? parseHolder(insertText);
  const thread = parseThreadInsert(insertText);
  const groove = parseGrooveInsert(insertText);
  const tipText = pyStrip(pyStr(rget(row, 'TIP')));
  const geometry: ToolGeometry = {
    kind: pyStrip(pyStr(rget(row, 'KIND'))),
    hand: pyStrip(pyStr(rget(row, 'DIR'))).toUpperCase(),
    tip: reSearch(DIGITS_ONLY_RE, tipText) ? pyInt(tipText) : null,
    diameter: floatOrNull(rget(row, 'D', null)),
    so: floatOrNull(rget(row, 'SO', null)), // 날장 최대(날 길이가 없을 때)
    mill_type: null,
    chamfer_angle: chamferAngle(insertText),
    nose_r: floatOrNull(rget(row, 'R', null)),
    width: floatOrNull(rget(row, 'T', null)),
    pitch: floatOrNull(rget(row, 'PITCH', null)),
    shape: null, tip_angle: null, clearance_angle: null, ic: null,
    edge_length: null, thickness: null,
    thread_angle: null,
    approach_angle: null, shank: null,
  };
  if (geometry.nose_r === null && insert && insert.nose_r !== null) geometry.nose_r = insert.nose_r;
  if (geometry.nose_r === null && groove && groove.corner_r !== null) {
    geometry.nose_r = groove.corner_r; // 홈 인서트는 코너 R을 노즈 R 자리에 둔다
  }
  if (insert) {
    geometry.shape = insert.shape;
    geometry.tip_angle = insert.angle;
    geometry.clearance_angle = insert.clearance_angle;
    geometry.ic = insert.ic;
    geometry.edge_length = insert.edge_length;
    geometry.thickness = insert.thickness;
  }
  if (thread) {
    geometry.thread_angle = thread.angle;
    if (geometry.pitch === null) geometry.pitch = thread.pitch;
  }
  if (groove && geometry.width === null) geometry.width = groove.width;
  geometry.mill_type = millTypeFor(geometry.kind, insertText);
  if (holder) {
    geometry.approach_angle = holder.approach_angle;
    if (holder.shank_w) geometry.shank = [holder.shank_w, holder.shank_h];
    if (!geometry.hand) geometry.hand = holder.hand;
  }
  return geometry;
}

/** 툴리스트 행들 -> {T01/T1/1: 공구 형상}. 같은 공구번호가 옵셋 다르게 여러 행이면 먼저 나온 행. */
export function geometryMapFromRows(
  rows: readonly Readonly<Record<string, unknown>>[] | null | undefined,
): Record<string, ToolGeometry> {
  const mapping: Record<string, ToolGeometry> = {};
  for (const row of rows ?? []) {
    const match = reFullmatch(TOOL_NO_RE, pyStrip(pyStr(rget(row, 'NO'))).toUpperCase());
    if (!match) continue;
    const number = pyInt(match[1]!);
    const geometry = geometryFromRow(row);
    for (const key of [`T${String(number).padStart(2, '0')}`, `T${number}`, String(number)]) {
      if (!has(mapping, key)) mapping[key] = geometry;
    }
  }
  return mapping;
}

