// 원본 nc_modal.py (v2.6.4) — 재생 위치의 모달 정보: 주축(S·회전 M), 이송(F·단위), G코드 그룹별 마지막 값, M코드 묶음.
// 실행 순서(seq, M98/M99 확장 결과)대로 읽어 값이 바뀐 seq에서만 스냅샷을 둔다. 표시 전용.
// 골든: tests/golden/toolpath/*.json 의 modal_timeline (원본 viewer.modal_timeline).

export type GroupDef = [id: string, name: string, codes: string[]];

export const MILL_GROUPS: GroupDef[] = [
  ['01', '이동', ['G00', 'G01', 'G02', 'G03']],
  ['02', '평면', ['G17', 'G18', 'G19']],
  ['03', '지령', ['G90', 'G91']],
  ['05', '이송', ['G93', 'G94', 'G95']],
  ['06', '단위', ['G20', 'G21']],
  ['07', '경보정', ['G40', 'G41', 'G42']],
  ['08', '길이보정', ['G43', 'G44', 'G49', 'G43.4', 'G43.5']],
  ['09', '사이클', ['G73', 'G74', 'G76', 'G80', 'G81', 'G82', 'G83', 'G84', 'G85', 'G86', 'G87', 'G88', 'G89']],
  ['10', '복귀', ['G98', 'G99']],
  ['14', '좌표계', ['G54', 'G55', 'G56', 'G57', 'G58', 'G59', 'G54.1']],
  ['15', '경로', ['G61', 'G62', 'G63', 'G64']],
  ['16', '좌표회전', ['G68', 'G69', 'G68.2', 'G68.3']],
];
export const LATHE_GROUPS: GroupDef[] = [
  ['01', '이동', ['G00', 'G01', 'G02', 'G03', 'G32', 'G33', 'G34']],
  ['02', '주속', ['G96', 'G97']],
  ['05', '이송', ['G98', 'G99']],
  ['06', '단위', ['G20', 'G21']],
  ['07', '경보정', ['G40', 'G41', 'G42']],
  ['16', '평면', ['G17', 'G18', 'G19']],
  // G70~G76 복합형 반복 사이클은 그 줄에서만 도는 00 그룹이라 넣지 않는다(모달인 드릴 사이클만)
  ['10', '사이클', ['G80', 'G83', 'G84', 'G85', 'G87', 'G88', 'G89']],
  ['14', '좌표계', ['G54', 'G55', 'G56', 'G57', 'G58', 'G59']],
  ['21', '극좌표', ['G12.1', 'G13.1', 'G112', 'G113']],
];
const M_SPINDLE = ['M03', 'M04', 'M05', 'M19'];
const M_COOLANT = ['M07', 'M08', 'M09'];
const M_STOP = ['M00', 'M01', 'M02', 'M30'];
export const M_CATEGORIES: [key: string, name: string][] = [['spindle', '주축'], ['coolant', '절삭유'], ['stop', '정지'], ['other', '기타']];
const M_SKIP = ['M98', 'M99'];

export interface ModalState {
  S: string | null;
  F: string | null;
  groups: Record<string, string>;
  m: Record<string, string>;
}

export const groupTable = (lathe: boolean): GroupDef[] => (lathe ? LATHE_GROUPS : MILL_GROUPS);
export const emptyState = (): ModalState => ({ S: null, F: null, groups: {}, m: {} });

const codeToGroup = (lathe: boolean): Map<string, string> => {
  const table = new Map<string, string>();
  for (const [gid, , codes] of groupTable(lathe)) for (const c of codes) table.set(c, gid);
  return table;
};

/** 'G1' -> 'G01', 'G43.4' 그대로, 'M3' -> 'M03' */
export function normalizeCode(letter: string, number: string): string {
  const dot = number.indexOf('.');
  const head = dot < 0 ? number : number.slice(0, dot);
  let tail = dot < 0 ? '' : number.slice(dot + 1);
  if (!/^[+-]?\d+$/.test(head)) return letter + number;
  const value = parseInt(head, 10);
  tail = tail.replace(/0+$/, '');
  return `${letter}${String(value).padStart(2, '0')}${tail ? '.' + tail : ''}`; // 파이썬 '%02d'와 같게
}

/** '10000.' -> '10000', '3600.0' -> '3600', '0.15' -> '0.15' (원본 _format_number) */
function formatNumber(number: string): string {
  const value = Number(number);
  if (!Number.isFinite(value)) return number;
  if (value === Math.trunc(value)) return String(Math.trunc(value));
  return value.toFixed(6).replace(/0+$/, '').replace(/\.$/, '');
}

export function feedUnit(state: ModalState, lathe: boolean): string {
  const length = state.groups['06'] === 'G20' ? 'in' : 'mm';
  const code = state.groups['05'];
  let perRev: boolean;
  if (lathe) perRev = code !== 'G98';
  else {
    if (code === 'G93') return '1/min';
    perRev = code === 'G95';
  }
  return `${length}/${perRev ? 'rev' : 'min'}`;
}

const WORD_RE = /([GMSFH])\s*([+-]?\d+(?:\.\d*)?)/g;
const MAX_RPM_RE = /G(?:50|92)(?![\d.])/;

export function applyLine(state: ModalState, line: string, lathe: boolean, table = codeToGroup(lathe)): Set<string> {
  const code = line.replace(/\([^)]*\)/g, ' ').split(';', 1)[0]!.toUpperCase();
  const changed = new Set<string>();
  if (!code.trim()) return changed; // '/' 블록 스킵 줄도 경로 계산처럼 실행한 것으로 본다
  const words = [...code.matchAll(WORD_RE)].map((m) => [m[1]!, m[2]!] as const);
  if (!words.length) return changed;
  const maxRpmLine = MAX_RPM_RE.test(code.replace(/ /g, ''));
  let hWord: string | null = null;
  for (const [letter, number] of words) if (letter === 'H') hWord = formatNumber(number);
  for (const [letter, number] of words) {
    if (letter === 'G') {
      const g = normalizeCode('G', number);
      const gid = table.get(g);
      if (gid === undefined) continue;
      let text = g;
      if (gid === '08' && ['G43', 'G44', 'G43.4', 'G43.5'].includes(g) && hWord !== null) {
        const h = Number(hWord);
        text = Number.isFinite(h) ? `${g} H${String(Math.trunc(h)).padStart(2, '0')}` : `${g} H${hWord}`;
      }
      if (state.groups[gid] !== text) { state.groups[gid] = text; changed.add(gid); }
    } else if (letter === 'M') {
      const m = normalizeCode('M', number);
      if (M_SKIP.includes(m)) continue;
      const category = M_SPINDLE.includes(m) ? 'spindle' : M_COOLANT.includes(m) ? 'coolant' : M_STOP.includes(m) ? 'stop' : 'other';
      if (state.m[category] !== m) { state.m[category] = m; changed.add('m:' + category); }
    } else if (letter === 'S') {
      if (maxRpmLine) continue; // G50/G92 S는 최고 회전수 제한
      const s = formatNumber(number);
      if (state.S !== s) { state.S = s; changed.add('S'); }
    } else if (letter === 'F') {
      const f = formatNumber(number);
      if (state.F !== f) { state.F = f; changed.add('F'); }
    }
  }
  return changed;
}

const snapshot = (s: ModalState): ModalState => ({ S: s.S, F: s.F, groups: { ...s.groups }, m: { ...s.m } });

export class ModalTimeline {
  readonly lathe: boolean;
  readonly keys: number[] = [];
  readonly states: ModalState[] = [];
  readonly changes: Set<string>[] = [];

  constructor(lineSequence: Iterable<readonly [number, string]>, lathe: boolean) {
    this.lathe = lathe;
    const state = emptyState();
    const table = codeToGroup(lathe);
    let seq = 0;
    for (const [, line] of lineSequence) {
      const changed = applyLine(state, line, lathe, table);
      if (changed.size) { this.keys.push(seq); this.states.push(snapshot(state)); this.changes.push(changed); }
      seq++;
    }
  }

  at(seq: number): { state: ModalState; changed: Set<string> } {
    let lo = 0, hi = this.keys.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (this.keys[mid]! <= seq) lo = mid + 1; else hi = mid; }
    const pos = lo - 1;
    if (pos < 0) return { state: emptyState(), changed: new Set() };
    return { state: this.states[pos]!, changed: this.keys[pos] === seq ? this.changes[pos]! : new Set() };
  }
}

/** 접혀 있을 때 한 줄 요약 — 'S10000 M03 · F3600 · G01 G68.2' */
export function summaryText(state: ModalState, lathe: boolean): string {
  const parts: string[] = [];
  const spindle = [state.S ? 'S' + state.S : '', state.m.spindle ?? ''].filter(Boolean).join(' ');
  if (spindle) parts.push(spindle);
  if (state.F) parts.push('F' + state.F);
  const g = state.groups;
  const codes = [g['01']];
  const cycle = g[lathe ? '10' : '09'];
  if (cycle && cycle !== 'G80') codes.push(cycle);
  const rotate = g[lathe ? '21' : '16'];
  if (rotate && !['G69', 'G13.1', 'G113'].includes(rotate)) codes.push(rotate);
  const shown = codes.filter((c): c is string => !!c);
  if (shown.length) parts.push(shown.join(' '));
  return parts.length ? parts.join(' · ') : '지령 전';
}
