// 3D 뷰어 — Three.js. 공정별 경로(급속 빨강 / 절삭 공구색), 카메라(궤도·이동·줌), 투영 버튼, 좌표·시간 표시, 재생.
// 계산은 core/toolpath.ts 의 결과를 그대로 쓴다. 원본: NCViewerWidget(경로 그리기·카메라·재생).
import * as THREE from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { elapsedSecondsAtSeq, formatElapsedOverTotal, lineAtSeq, resolveSeqForLine, sequenceLength } from '../core/playback';
import { findProcessMarker, pickRelativeMarker } from '../core/processMarker';
import { isLatheMachine, type TableRot, type ToolpathResult } from '../core/toolpath';
import { createSimLayer, type SimLayer, type SimSource, type SimStatus } from './simLayer';
import type { SimProgram } from '../sim/segments';
import type { Bounds } from '../sim/stock';
import type { LatheProgram } from '../sim/latheSegments';
import type { LatheBounds } from '../sim/latheStock';
import {
  CUT_LINE_BASE_WIDTH, FOV_MAX, FOV_MIN, ROTARY_SPEED_MAX, ROTARY_SPEED_MIN, ROTARY_SPEED_STEP, TRAIL_BLOCKS_MAX, TRAIL_BLOCKS_MIN,
  TRAIL_BLOCKS_STEP, toolpathLineWidth,
} from '../core/viewerSettings';
import { getPref, setPref } from '../platform/prefs';
import { getViewerSettings, onViewerSettings, updateViewerSettings } from '../platform/viewerSettings';
import { el } from '../ui/dialog';
import { icon } from '../icons';
import { emptyState, feedUnit, groupTable, M_CATEGORIES, summaryText, type ModalState } from '../core/modal';
import { cutGroups, groupAt, type CutGroup } from './entryArrow';
import { buildToolGeometry } from './toolMesh';
import { toolShapeFromValues, type ToolValues } from '../sim/toolShape';
import { RAPID_MOVE_COLOR, sceneBounds, segmentBuckets, toolColorForIndex } from './segments';

const RAPID_LINE_BASE_WIDTH = 1.5;
const TRACE_CUT_LINE_BASE_WIDTH = 3.5;
const ZOOM_TO_FIT_MARGIN = 1.25;
const FALLBACK_DISTANCE = 200;
const PROJECTIONS: Record<string, [elevation: number, azimuth: number]> = {
  ISO: [30, -45], XY: [90, -90], XZ: [0, -90], YZ: [0, 0], LATHE: [0, -90],
};
export const PLAY_SPEEDS = [1, 5, 10, 50, 100, 500, 1000, 5000];

export interface StopRule {
  text: boolean; textValue: string; m00: boolean; m01: boolean;
}
export interface ViewerHooks {
  /** WebGL 을 시작하지 못함 → 호출 쪽이 2D 대체 화면을 쓴다 */
  onWebglFailed?: (message: string) => void;
  /** 재생·찍기로 위치가 바뀜 → 입력창이 그 줄로 이동 (PG 매칭) */
  onLine?: (line: number) => void;
  /** 위치 찍기로 고른 줄 → 입력창 이동(항상) */
  onPick?: (line: number) => void;
  stopRule?: () => StopRule;
  lineText?: (line: number) => string;
  /** "실시간 형상" 버튼을 누름 → 호출 쪽이 켜고 끈 뒤 setSimLive 로 알려 준다 */
  onLiveToggle?: () => void;
  /** 가공 형상 상태가 바뀜(진행·적용) */
  onSimChange?: () => void;
}
export interface Viewer {
  /** 원본 v2.6.2: 정지 옵션(텍스트 정지·정지·옵션정지)을 큐브 아래 옵션 창에 풀어서 넣는다 */
  setStopOptions(content: HTMLElement): void;
  setProgram(result: ToolpathResult | null, machineType: string): void;
  /** 표시할 공정(null = 전부) */
  setVisible(keys: string[] | null): void;
  /** 입력창 커서 줄 → 경로 위치 */
  setLine(line: number): void;
  seq(): number;
  resize(): void;
  reset(): void;
  togglePlay(): void;
  jumpTool(dir: -1 | 1): void;
  /** 위치 찍기 모드가 켜져 있으면 끄고 true */
  cancelPick(): boolean;
  /** 가공 형상: 절삭 선분·공구 형상(프로그램이 바뀔 때마다) */
  setSimProgram(p: SimProgram | LatheProgram | null, source: SimSource | null): void;
  /** 밀링 공구 모양을 그리기 위한 툴리스트 공구값(키: T01/T1/1) */
  setToolValues(v: ReadonlyMap<string, ToolValues> | null): void;
  /** 원본 v2.6.4: 재생 바 옆 지금 공구 이름(키: T01/T1/1, 선반이면 null) */
  setToolNames(names: Readonly<Record<string, string>> | null): void;
  /** 소재 적용(bounds 가 null 이면 소재 제거) */
  applyStock(bounds: Bounds | LatheBounds | null, resolution: number | null, enabled: boolean): void;
  /** PG 매칭: 전체 경로를 지우고 커서가 있는 공정만 커서 위치까지 그린다 */
  setPgMatch(on: boolean): void;
  /** 툴패스 선 표시/숨김(가공 형상을 가리지 않게) */
  setToolpathVisible(on: boolean): void;
  setSimEnabled(on: boolean): void;
  setSimLive(on: boolean): void;
  simStatus(): SimStatus;
  exportStl(): Uint8Array | null;
  setSection(m: '3q' | 'half' | 'full'): void;
  dispose(): void;
}

interface ProcessObjects { key: string; index: number; objs: LineSegments2[]; trace: { obj: LineSegments2; seqs: number[] }[]; buckets: { pos: number[]; seqs: number[] }[] }

const rgb = (c: readonly number[]): number => ((Math.round(c[0]! * 255) << 16) | (Math.round(c[1]! * 255) << 8) | Math.round(c[2]! * 255));

export function createViewer(host: HTMLElement, hooks: ViewerHooks = {}): Viewer | null {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch (error) {
    hooks.onWebglFailed?.(String(error));
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x11151c);
  host.append(renderer.domElement);

  const scene = new THREE.Scene();
  const settings = getViewerSettings();
  // 원본(OrthographicGLViewWidget)처럼 직교 투영 — FOV는 화면에 보이는 높이(2·거리·tan(fov/2))만 정한다
  let fovDeg = settings.fovDeg;
  let aspect = 1;
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -1000, 1000);
  camera.up.set(0, 0, 1);

  // 카메라 상태 — pyqtgraph 와 같은 (중심, 거리, 고도, 방위)
  const center = new THREE.Vector3();
  let distance = FALLBACK_DISTANCE;
  let elevation = 30;
  let azimuth = -45;
  let radius = 0;
  let orbitLocked = false;
  let lathe = false;
  let result: ToolpathResult | null = null;
  let machine = '';

  // 공구 위치 표시: 구(날끝) + 구에서 공구 축 방향(날끝 반대쪽, 홀더 쪽)으로 뻗은 막대
  const marker = new THREE.Group();
  const markerMat = new THREE.MeshBasicMaterial({ color: 0xffe14a, depthTest: false });
  const markerBall = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), markerMat);
  const markerStick = new THREE.Mesh(new THREE.CylinderGeometry(0.22, 0.22, 6, 8), markerMat);
  markerStick.rotation.x = Math.PI / 2; // 원기둥(Y 축)을 +Z 로 눕힌다
  markerStick.position.z = 3.5;
  markerBall.renderOrder = 10;
  markerStick.renderOrder = 10;
  marker.add(markerBall, markerStick);
  marker.visible = false;
  scene.add(marker);
  /** 구 크기: 기본 선굵기(90%)일 때 이전 기준 크기의 50%, 선굵기에 비례해 줄고 늘어난다 */
  let markerBase = 1;
  const applyMarkerScale = (): void => {
    marker.scale.setScalar(markerBase * 0.5 * (getViewerSettings().lineWidthPct / 90));
  };
  // 진입 방향 화살표(밀링): 같은 공구 축으로 가공하는 구간의 첫 절삭 위치에, 그 이동 방향으로. 축이 바뀌면 지우고 다음 절삭에서 다시 그린다.
  const arrowMat = new THREE.MeshBasicMaterial({ color: 0xffd91a, depthTest: false });
  const entryArrow = new THREE.Group();
  const arrowShaft = new THREE.Mesh(new THREE.CylinderGeometry(0.035, 0.035, 0.75, 8), arrowMat);
  arrowShaft.rotation.x = Math.PI / 2;
  arrowShaft.position.z = 0.375;
  const arrowHead = new THREE.Mesh(new THREE.ConeGeometry(0.1, 0.25, 12), arrowMat);
  arrowHead.rotation.x = Math.PI / 2;
  arrowHead.position.z = 0.875;
  arrowShaft.renderOrder = 11;
  arrowHead.renderOrder = 11;
  entryArrow.add(arrowShaft, arrowHead);
  entryArrow.visible = false;
  scene.add(entryArrow);
  let entryGroups = new Map<string, CutGroup[]>();
  // 공구 모양(밀링): 재생 위치에 팁을 놓고 공구 축 방향으로 몸통을 세운다. 공구 정보가 없으면 구+막대 표시를 쓴다.
  scene.add(new THREE.AmbientLight(0xffffff, 1.0));
  const keyLight = new THREE.DirectionalLight(0xffffff, 1.6);
  keyLight.position.set(1, 2, 3);
  scene.add(keyLight);
  const toolMat = new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.95, depthTest: false, side: THREE.DoubleSide }); // 음영 없이 평평하게(원본 v2.4.7)
  const toolMesh = new THREE.Mesh(new THREE.BufferGeometry(), toolMat);
  toolMesh.visible = false;
  toolMesh.renderOrder = 12; // 소재 형상 안에 들어가도 보이게 깊이 검사를 끄고 맨 위에 그린다
  scene.add(toolMesh);
  let toolValues: ReadonlyMap<string, ToolValues> | null = null;
  const toolGeoCache = new Map<string, THREE.BufferGeometry | null>();
  const toolGeometry = (toolNo: string): THREE.BufferGeometry | null => {
    if (toolGeoCache.has(toolNo)) return toolGeoCache.get(toolNo)!;
    const v = toolValues?.get(toolNo);
    const shape = v ? toolShapeFromValues(v) : null;
    const g = shape ? buildToolGeometry(shape) : null;
    if (g && shape) g.userData.radius = shape.radius;
    toolGeoCache.set(toolNo, g);
    return g;
  };
  const Z_UP = new THREE.Vector3(0, 0, 1);
  const axisVec = new THREE.Vector3();
  const axes = new THREE.AxesHelper(1);
  scene.add(axes);

  // v2.5.9: 테이블 회전 — 경로(group)와 가공 형상(sim)을 한 부모(workGroup)에 두고 통째로 돌린다
  const workGroup = new THREE.Group();
  scene.add(workGroup);
  const group = new THREE.Group();
  workGroup.add(group);
  const sim: SimLayer = createSimLayer(workGroup, () => { dirty = true; instantBtn.disabled = !sim.hasStock(); hooks.onSimChange?.(); }, (busy, pct) => {
    progressBox.hidden = !busy;
    if (busy) progressBox.textContent = `가공 형상 ${Math.round(pct * 100)}%`;
  });
  // 화면 가운데 진행률(가공 형상 계산 중)
  const progressBox = el('div', { class: 'v-progress' });
  progressBox.hidden = true;
  const instantBtn = el('button', { type: 'button', class: 'v-instant', title: '소재를 끝까지 깎은 가공 형상을 바로 보여 줍니다' });
  instantBtn.textContent = '가공형상 즉시 보기';
  instantBtn.disabled = true;
  let simLive = false;
  const liveBtn = el('button', { type: 'button', class: 'v-live', 'aria-pressed': 'false',
    title: '실시간 형상: 켜면 재생·커서 위치까지 소재를 깎아 보여 주고, 끄면 선택한 공정의 끝까지 깎은 모양을 보여 줍니다.' });
  liveBtn.textContent = '실시간 형상';
  liveBtn.addEventListener('click', () => hooks.onLiveToggle?.());
  let paintMoreRef: (() => void) | null = null;
  const paintLive = (): void => {
    liveBtn.classList.toggle('on', simLive);
    liveBtn.setAttribute('aria-pressed', String(simLive));
    paintMoreRef?.();
  };
  // v2.5.9: 5축 재생 중 공구는 고정하고 테이블·소재가 A/B/C 값만큼 도는 표시(기본 켜짐, 설정 창과 같은 값)
  let tableOn = getViewerSettings().tableRotation;
  const tableBtn = el('button', { type: 'button', class: 'v-live', 'aria-pressed': String(tableOn),
    title: '5축 재생 중 공구는 고정하고 테이블·소재가 A/B/C 회전축 값만큼 돌게 봅니다.' });
  tableBtn.textContent = '테이블 회전';
  const paintTable = (): void => {
    tableBtn.classList.toggle('on', tableOn);
    tableBtn.setAttribute('aria-pressed', String(tableOn));
  };
  paintTable();
  tableBtn.addEventListener('click', () => { updateViewerSettings({ tableRotation: !tableOn }); });
  // 원본 v2.6.0: 지난 경로 숨김 — 재생(PG 매칭) 중 지금 줄 기준 앞쪽 N블록만 그린다
  let trailOn = getViewerSettings().trailHide;
  let trailBlocks = getViewerSettings().trailBlocks;
  let rotarySpeed = getViewerSettings().rotarySpeed;
  const trailBtn = el('button', { type: 'button', class: 'v-live', title: '켜면 재생 중 지금 줄 기준 앞쪽 N블록만 보입니다 (블록 수는 − + 또는 설정 창)' });
  trailBtn.textContent = '지난 경로 숨김';
  const trailMinus = el('button', { type: 'button', class: 'v-step', title: `표시 블록 수 -${TRAIL_BLOCKS_STEP}` });
  trailMinus.textContent = '−';
  const trailPlus = el('button', { type: 'button', class: 'v-step', title: `표시 블록 수 +${TRAIL_BLOCKS_STEP}` });
  trailPlus.textContent = '+';
  const trailLabel = el('span', { class: 'v-step-label' });
  const paintTrail = (): void => {
    trailBtn.classList.toggle('on', trailOn);
    trailBtn.setAttribute('aria-pressed', String(trailOn));
    trailLabel.textContent = `${trailBlocks} 블록`;
    trailMinus.disabled = !trailOn;
    trailPlus.disabled = !trailOn;
    trailLabel.classList.toggle('off', !trailOn);
  };
  paintTrail();
  trailBtn.addEventListener('click', () => { updateViewerSettings({ trailHide: !trailOn }); });
  const stepTrail = (d: number): void => {
    updateViewerSettings({ trailBlocks: Math.max(TRAIL_BLOCKS_MIN, Math.min(TRAIL_BLOCKS_MAX, trailBlocks + d)) });
  };
  trailMinus.addEventListener('click', () => stepTrail(-TRAIL_BLOCKS_STEP));
  trailPlus.addEventListener('click', () => stepTrail(TRAIL_BLOCKS_STEP));
  /** 지난 경로 숨김이 켜져 있으면 그릴 첫 seq(원본 _trail_seq_from). 아니면 0 */
  const trailSeqFrom = (seq: number): number => (trailOn && pgMatch ? Math.max(0, seq - trailBlocks + 1) : 0);
  /** 이미 만든 선 묶음에서 [from, count) 구간만 그리게 한다(인스턴스 시작 위치를 옮긴다) */
  const setTraceWindow = (g: LineSegmentsGeometry, from: number, count: number): void => {
    const ud = g.userData as { from?: number };
    if ((ud.from ?? 0) !== from) {
      const start = g.getAttribute('instanceStart') as THREE.InterleavedBufferAttribute;
      const data = start.data;
      g.setAttribute('instanceStart', new THREE.InterleavedBufferAttribute(data, 3, from * 6));
      g.setAttribute('instanceEnd', new THREE.InterleavedBufferAttribute(data, 3, from * 6 + 3));
      ud.from = from;
    }
    (g as LineSegmentsGeometry & { instanceCount: number }).instanceCount = Math.max(0, count - from);
  };
  let tableKeys: number[] = [];
  let tableKeysFor: Map<number, unknown> | null = null;
  const rotX = (d: number): THREE.Matrix4 => new THREE.Matrix4().makeRotationX((d * Math.PI) / 180);
  const rotY = (d: number): THREE.Matrix4 => new THREE.Matrix4().makeRotationY((d * Math.PI) / 180);
  const rotZ = (d: number): THREE.Matrix4 => new THREE.Matrix4().makeRotationZ((d * Math.PI) / 180);
  /** 원본 _table_target_info: seq 시점 회전축 상태(종류, A, B, C 도). 테이블 회전을 보이지 않으면 null */
  const tableInfo = (seq: number): TableRot | null => {
    if (lathe || !pgMatch || !tableOn) return null;
    const map = result?.seq_to_table_rot;
    if (!map || !map.size) return null;
    if (tableKeysFor !== map) { tableKeys = [...map.keys()].sort((a, b) => a - b); tableKeysFor = map; }
    let lo = 0, hi = tableKeys.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (tableKeys[mid]! <= seq) lo = mid + 1; else hi = mid; }
    if (lo === 0) return null;
    return map.get(tableKeys[lo - 1]!) ?? null;
  };
  /** 원본 _table_rotation_matrices: 소재 회전(part)과 공구 방향(tool). 공구 축 Rᵀ·z 관계를 지켜 공구 모양·진입 방향·가공면이 같다.
   * A→C: (Rz(C)·Rx(A))ᵀ, B→C(원본 v2.6.2): (Rz(C)·Ry(B))ᵀ — 둘 다 공구는 수직, 4축 B: Ry(B)ᵀ */
  const tableMatsOf = (info: TableRot): { part: THREE.Matrix4; tool: THREE.Matrix4 } => {
    const [kind, a, b, c] = info;
    if (kind === 'ac') return { part: rotZ(c).multiply(rotX(a)).transpose(), tool: new THREE.Matrix4() };
    if (kind === 'bc') return { part: rotZ(c).multiply(rotY(b)).transpose(), tool: new THREE.Matrix4() };
    return { part: rotY(b).transpose(), tool: new THREE.Matrix4() };
  };
  // 원본 v2.6.7: 재생 중 회전축 인덱스는 rotarySpeed(°/초) 일정 속도로 돌고, 모든 축이 동시에 끝난다. 손으로 옮길 때는 바로 맞춘다.
  let tableGoal: TableRot | null = null;
  let tableDisp: TableRot | null = null;
  let tableStart: TableRot | null = null;
  let tableDelta: [number, number, number] = [0, 0, 0];
  let tableDur = 0;
  let tableElapsed = 0;
  const rotInfo = el('div', { class: 'v-hud' });
  rotInfo.style.cssText = 'position:absolute;left:8px;top:48px;padding:4px 8px;border-radius:4px;background:rgba(20,24,30,.8);color:#ffe082;font-size:12px;pointer-events:none';
  rotInfo.hidden = true;
  host.append(rotInfo);
  const sameRot = (x: TableRot | null, y: TableRot | null): boolean =>
    x === y || (!!x && !!y && x[0] === y[0] && x[1] === y[1] && x[2] === y[2] && x[3] === y[3]);
  const paintRotInfo = (): void => {
    if (!tableGoal || !tableDisp || !tableStart || sameRot(tableGoal, tableDisp)) { rotInfo.hidden = true; return; }
    const parts: string[] = [];
    (['A', 'B', 'C'] as const).forEach((name, k) => {
      if (Math.abs(tableDelta[k]!) >= 0.05) parts.push(`${name} ${(tableDisp![k + 1] as number).toFixed(1)}° → ${(tableGoal![k + 1] as number).toFixed(1)}°`);
    });
    rotInfo.textContent = parts.length ? `회전 중… ${parts.join('   ')}` : '';
    rotInfo.hidden = !parts.length;
  };
  const tableSync = (seq: number): void => {
    const target = tableInfo(seq);
    if (!target) { tableGoal = null; tableDisp = null; paintRotInfo(); return; }
    if (sameRot(target, tableGoal)) return;
    tableGoal = target;
    // 원본 v2.6.5: 동시 5축은 재생(이송 · 배속)을 그대로 따른다 — 바로 맞춘다
    const follow = result?.seq_table_follow?.has(seq) ?? false;
    if (!playing || follow || !tableDisp || tableDisp[0] !== target[0]) { tableDisp = target; paintRotInfo(); return; }
    const d: [number, number, number] = [0, 0, 0];
    for (const i of [1, 2, 3] as const) {
      let delta = target[i] - tableDisp[i];
      if (i === 3) delta = ((((delta + 180) % 360) + 360) % 360) - 180; // C는 가까운 쪽으로
      d[i - 1] = delta;
    }
    const biggest = Math.max(Math.abs(d[0]), Math.abs(d[1]), Math.abs(d[2]));
    if (biggest < 0.05) { tableDisp = target; paintRotInfo(); return; }
    tableStart = tableDisp;
    tableDelta = d;
    tableDur = biggest / Math.max(1, rotarySpeed);
    tableElapsed = 0;
    paintRotInfo();
  };
  /** 회전축이 아직 목표 각도로 도는 중인가 — 재생은 회전이 끝날 때까지 다음 줄로 넘어가지 않는다 */
  const tableAnimating = (): boolean => !!tableGoal && !!tableDisp && !!tableStart && !sameRot(tableGoal, tableDisp);
  /** 도는 회전을 바로 목표 각도로 맞춘다(재생 정지·일시정지) */
  const tableFinish = (): void => {
    if (!tableAnimating()) return;
    tableDisp = tableGoal;
    tableStart = null;
    paintRotInfo();
    showSeq(seqNow, false);
  };
  /** 원본 table_rotation_changes_at: 이 seq 에서 A·B·C 인덱스 회전(G43.4 동시 5축 제외)이 새로 일어나는가 */
  const tableRotationChangesAt = (seq: number): boolean => {
    if (seq <= 0 || (result?.seq_table_follow?.has(seq) ?? false)) return false;
    const now = tableInfo(seq), before = tableInfo(seq - 1);
    if (!now || !before || now[0] !== before[0]) return false;
    return [1, 2, 3].some((i) => Math.abs((now[i] as number) - (before[i] as number)) >= 0.05);
  };
  /** 한 프레임만큼 표시 각도를 목표 쪽으로 옮긴다. 옮겼으면 true */
  const tableStep = (dt: number): boolean => {
    if (!tableAnimating() || !tableGoal || !tableStart) return false;
    tableElapsed += Math.max(0, Math.min(0.2, dt));
    const f = Math.min(1, tableElapsed / Math.max(tableDur, 1e-9));
    if (f >= 1) { tableDisp = tableGoal; tableStart = null; }
    else tableDisp = [tableGoal[0], tableStart[1] + tableDelta[0] * f, tableStart[2] + tableDelta[1] * f, tableStart[3] + tableDelta[2] * f] as TableRot;
    paintRotInfo();
    return true;
  };
  const SECTION_LABEL = { '3q': '단면 3/4', half: '단면 1/2', full: '원통' } as const;
  const SECTION_ORDER = ['3q', 'half', 'full'] as const;
  let sectionMode: (typeof SECTION_ORDER)[number] = ((): (typeof SECTION_ORDER)[number] => {
    const v = getPref('sim_section');
    return v === 'half' || v === 'full' ? v : '3q';
  })();
  const sectionBtn = el('button', { type: 'button', class: 'v-instant v-section', title: '선반 가공 형상 단면: 3/4 → 1/2 → 원통(전체)' });
  sectionBtn.textContent = SECTION_LABEL[sectionMode];
  const applySection = (m: (typeof SECTION_ORDER)[number]): void => {
    sectionMode = m;
    sectionBtn.textContent = SECTION_LABEL[m];
    setPref('sim_section', m);
    sim.setSection(m);
  };
  sectionBtn.addEventListener('click', () => applySection(SECTION_ORDER[(SECTION_ORDER.indexOf(sectionMode) + 1) % 3]!));
  sim.setSection(sectionMode);
  let pgMatch = false;
  let toolpathOn = true;
  /** seqNow 가 속한 공정 키(공정 첫 seq 가 seqNow 이하인 마지막 공정) */
  const currentProcessKey = (): string | null => {
    if (!result) return null;
    let best: string | null = null;
    let bestSeq = -1;
    for (const [key, s] of result.process_first_seq) if (s <= seqNow && s >= bestSeq) { best = key; bestSeq = s; }
    return best;
  };
  /** 원본 v2.6.6: 공정별 시작 N 줄 seq와 머리말 주석(최대 2개) — 결과가 바뀔 때 다시 만든다 */
  let markerCache: { res: ToolpathResult; list: { seq: number; key: string; comments: string[] }[] } | null = null;
  const processMarkers = (): { seq: number; key: string; comments: string[] }[] => {
    if (!result) return [];
    if (markerCache?.res === result) return markerCache.list;
    const ordered = [...result.process_first_seq.entries()].filter(([k]) => result!.tool_paths.has(k)).sort((a, b) => a[1] - b[1]);
    let floor = -1;
    const list = ordered.map(([key, changeSeq]) => {
      const m = key === 'Initial' ? { seq: 0, comments: [] as string[] } : findProcessMarker(result!.seq_texts, changeSeq, floor);
      floor = changeSeq;
      return { seq: m.seq, key, comments: m.comments };
    }).sort((a, b) => a.seq - b.seq);
    markerCache = { res: result, list };
    return list;
  };
  /** seqNow 가 속한 공정 = 시작 N 줄이 seq 이하인 마지막 공정 */
  const markerAt = (seq: number): { seq: number; key: string; comments: string[] } | null => {
    let found: { seq: number; key: string; comments: string[] } | null = null;
    for (const m of processMarkers()) { if (m.seq <= seq) found = m; else break; }
    return found;
  };
  let processes: ProcessObjects[] = [];
  const materials: { m: LineMaterial; base: number }[] = [];

  // ---------------------------------------------------------------- 화면 겹침(오버레이)
  const projBar = el('div', { class: 'v-proj' });
  // 원본 v2.6.4: 재생 정보 묶음 — 좌표 · [모달 정보](기본 접힘) · 진행 · 재생 버튼을 한 판에
  const hud = el('div', { class: 'v-hud' });
  const coordRow = el('div', { class: 'v-coordrow' });
  const coordBox = el('div', { class: 'v-coord' });
  const modalRow = el('div', { class: 'v-modalrow' });
  const modalToggle = el('button', { type: 'button', class: 'v-mtoggle', 'aria-expanded': 'false',
    title: '주축 · 이송 · 마지막으로 적용된 G코드(그룹별)와 M코드 보기 / 숨기기' });
  const modalPeek = el('span', { class: 'v-peek' });
  modalRow.append(modalToggle, modalPeek);
  const modalPanel = el('div', { class: 'v-modal' });
  const kvBox = el('div', { class: 'v-kv' });
  const groupBox = el('div', { class: 'v-groups' });
  const mRow = el('div', { class: 'v-mrow' });
  modalPanel.append(kvBox, groupBox, mRow);
  const playBar = el('div', { class: 'v-play' });
  const buttonRow = el('div', { class: 'v-btnrow' });
  hud.append(coordRow, modalRow, modalPanel, playBar, buttonRow);
  host.append(projBar, hud, progressBox);
  let modalOpen = getPref('modal_info_open') === 'true';
  let toolNames: Readonly<Record<string, string>> | null = null;
  const kvCells = new Map<string, HTMLElement>();
  for (const [key, name] of [['S', '주축'], ['spindle', '회전'], ['F', '이송'], ['unit', '단위']] as const) {
    const n = el('span'); n.textContent = name;
    const v = el('b'); v.textContent = '—';
    const row = el('div'); row.append(n, v);
    kvBox.append(row);
    kvCells.set(key, v);
  }
  let groupCells = new Map<string, HTMLElement>();
  let groupsLathe: boolean | null = null;
  const buildGroups = (isLathe: boolean): void => {
    if (groupsLathe === isLathe) return;
    groupsLathe = isLathe;
    groupBox.replaceChildren();
    groupCells = new Map();
    for (const [gid, name] of groupTable(isLathe)) {
      const cell = el('div', { class: 'v-gg' });
      const t = el('span'); t.textContent = `${gid} ${name}`;
      const v = el('code'); v.textContent = '—';
      cell.append(t, v);
      groupBox.append(cell);
      groupCells.set(gid, v);
    }
  };
  const paintCell = (cell: HTMLElement, text: string | null | undefined, changed: boolean): void => {
    cell.textContent = text || '—';
    cell.classList.toggle('chg', changed);
    cell.classList.toggle('none', !text);
  };
  const paintModalToggle = (): void => {
    modalPanel.hidden = !modalOpen;
    modalPeek.hidden = modalOpen;
    modalToggle.setAttribute('aria-expanded', String(modalOpen));
    modalToggle.textContent = `${modalOpen ? '▾' : '▸'} 모달 정보`;
  };
  paintModalToggle();
  modalToggle.addEventListener('click', () => {
    modalOpen = !modalOpen;
    setPref('modal_info_open', String(modalOpen));
    paintModalToggle();
    showModal();
  });
  /** 원본 _tool_number_and_name — 'T03' + 이름 (선반은 번호만) */
  const toolNumberAndName = (toolNo: string | undefined): [string, string] => {
    if (!toolNo) return ['', ''];
    const m = /T(\d+)/i.exec(toolNo);
    if (!m) return [toolNo, ''];
    const n = parseInt(m[1]!, 10);
    if (lathe) return [n >= 100 ? `T${String(n).padStart(4, '0')}` : `T${String(n).padStart(2, '0')}`, ''];
    const key = `T${String(n).padStart(2, '0')}`;
    return [key, (toolNames && (toolNames[key] || toolNames[`T${n}`] || toolNames[String(n)])) || ''];
  };
  instantBtn.addEventListener('click', () => {
    if (!result) return;
    let end: number | null = null;
    for (const path of result.tool_paths.values()) for (let i = path.length - 1; i >= 0; i--) { const n = path[i]!; if (n.valid) { if (end === null || n.seq > end) end = n.seq; break; } }
    sim.setEnabled(true);
    sim.setTarget(end, true);
  });
  const mkBtn = (parent: HTMLElement, label: string, title: string): HTMLButtonElement => {
    const b = el('button', { type: 'button', title });
    b.textContent = label;
    parent.append(b);
    return b;
  };
  const mkIconBtn = (parent: HTMLElement, name: string, title: string): HTMLButtonElement => {
    const b = el('button', { type: 'button', title, 'aria-label': title, class: 'v-icon' });
    b.innerHTML = icon(name);
    parent.append(b);
    return b;
  };
  const projButtons: HTMLButtonElement[] = [];
  let pickMode = false;
  const cube = el('div', { class: 'v-cube' });
  const cubeBody = el('div', { class: 'v-cube-body' });
  cube.append(cubeBody);
  host.append(cube);
  // 원본 v2.6.2: 큐브 아래 [« 옵션] — 왼쪽으로 열리는 별도 창에 테이블 회전 · 가공형상 즉시 보기 · 정지 옵션 · 지난 경로 숨김을 나열
  const dock = el('div', { class: 'v-dock' });
  const moreBtn = el('button', { type: 'button', class: 'v-more', 'aria-expanded': 'false',
    title: '옵션 창 열기 / 닫기 — 테이블 회전 · 가공형상 즉시 보기 · 정지 옵션 · 지난 경로 숨김' });
  const panel = el('div', { class: 'v-panel' });
  panel.hidden = true;
  const section = (title: string): HTMLElement => { const h = el('div', { class: 'v-sec' }); h.textContent = title; return h; };
  const stopSlot = el('div', { class: 'v-stop' });
  const stepRow = el('div', { class: 'v-steprow' });
  stepRow.append(trailMinus, trailLabel, trailPlus);
  // 원본 v2.6.7: 회전축(A·B·C) 속도 °/초 — 설정 창과 같은 값
  const rotMinus = el('button', { type: 'button', class: 'v-step', title: `회전축 속도 -${ROTARY_SPEED_STEP} °/초` });
  rotMinus.textContent = '−';
  const rotPlus = el('button', { type: 'button', class: 'v-step', title: `회전축 속도 +${ROTARY_SPEED_STEP} °/초` });
  rotPlus.textContent = '+';
  const rotLabel = el('span', { class: 'v-step-label' });
  const rotRow = el('div', { class: 'v-steprow' });
  rotRow.append(rotMinus, rotLabel, rotPlus);
  const paintRot = (): void => { rotLabel.textContent = `${rotarySpeed} °/초`; };
  paintRot();
  const stepRot = (d: number): void => {
    updateViewerSettings({ rotarySpeed: Math.max(ROTARY_SPEED_MIN, Math.min(ROTARY_SPEED_MAX, rotarySpeed + d)) });
  };
  rotMinus.addEventListener('click', () => stepRot(-ROTARY_SPEED_STEP));
  rotPlus.addEventListener('click', () => stepRot(ROTARY_SPEED_STEP));
  panel.append(section('뷰'), tableBtn, instantBtn, section('재생 정지'), stopSlot, liveBtn, section('회전축 속도 (A·B·C, G0)'), rotRow, section('지난 경로'), trailBtn, stepRow);
  dock.append(moreBtn, panel);
  host.append(dock);
  let moreOpen = getPref('overlay_more_open') === 'true';
  const activeCount = (): number => {
    let n = (tableOn && !lathe ? 1 : 0) + (trailOn ? 1 : 0) + (simLive ? 1 : 0);
    for (const box of stopSlot.querySelectorAll<HTMLInputElement>('input[type=checkbox]')) if (box.checked) n++;
    return n;
  };
  function paintMore(): void {
    panel.hidden = !moreOpen;
    moreBtn.setAttribute('aria-expanded', String(moreOpen));
    const n = activeCount();
    moreBtn.textContent = `${moreOpen ? '옵션 닫기' : '옵션 열기'}${n && !moreOpen ? `  ${n}` : ''}`;
  }
  paintMoreRef = paintMore;
  moreBtn.addEventListener('click', () => { moreOpen = !moreOpen; setPref('overlay_more_open', String(moreOpen)); paintMore(); });
  stopSlot.addEventListener('change', paintMore);
  const CUBE_FACES: [label: string, transform: string, view: [number, number]][] = [
    ['+Z', 'translateZ(var(--h))', [90, -90]],
    ['-Z', 'rotateX(180deg) translateZ(var(--h))', [-90, -90]],
    ['+X', 'rotateY(90deg) translateZ(var(--h))', [0, 0]],
    ['-X', 'rotateY(-90deg) translateZ(var(--h))', [0, 180]],
    ['+Y', 'rotateX(-90deg) translateZ(var(--h))', [0, 90]],
    ['-Y', 'rotateX(90deg) translateZ(var(--h))', [0, -90]],
  ];
  for (const [label, transform, view] of CUBE_FACES) {
    const face = el('div', { class: 'v-face' });
    face.textContent = label;
    face.style.transform = transform;
    face.addEventListener('click', () => {
      if (orbitLocked) return;
      [elevation, azimuth] = view;
      apply();
    });
    cubeBody.append(face);
  }
  const updateCube = (): void => {
    const size = Math.round(getViewerSettings().cubeSizePx * 0.4);
    cube.style.setProperty('--s', `${size}px`);
    cube.style.setProperty('--h', `${size / 2}px`);
    host.style.setProperty('--cube-s', `${size}px`);
    dock.hidden = false;
    cube.hidden = lathe;
    const e = (elevation * Math.PI) / 180;
    const a = (azimuth * Math.PI) / 180;
    const d = [Math.cos(e) * Math.cos(a), Math.cos(e) * Math.sin(a), Math.sin(e)];
    const r = [-Math.sin(a), Math.cos(a), 0];
    const u = [-Math.sin(e) * Math.cos(a), -Math.sin(e) * Math.sin(a), Math.cos(e)];
    // 월드 X/Y/Z 단위벡터가 화면(오른쪽, 아래, 보는 사람 쪽)에서 놓이는 곳
    const m = [
      r[0]!, -u[0]!, d[0]!, 0, r[1]!, -u[1]!, d[1]!, 0, r[2]!, -u[2]!, d[2]!, 0, 0, 0, 0, 1,
    ];
    cubeBody.style.transform = `matrix3d(${m.join(',')})`;
  };
  const buildProjButtons = (): void => {
    projBar.replaceChildren();
    projButtons.length = 0;
    const names = lathe ? ['ISO', 'LATHE'] : ['ISO', 'XY', 'XZ', 'YZ'];
    const pick = mkIconBtn(projBar, 'pin', '위치 찍기: 경로를 탭하면 그 줄로 이동');
    pick.classList.toggle('on', pickMode);
    pick.addEventListener('click', () => { pickMode = !pickMode; pick.classList.toggle('on', pickMode); });
    for (const name of names) {
      const b = mkBtn(projBar, name === 'LATHE' ? '선반' : name, `${name} 보기`);
      b.addEventListener('click', () => { setProjection(name); }); // v2.4.2: 뷰를 바꿔도 위치 찍기는 유지
      projButtons.push(b);
    }
    projBar.append(sectionBtn);
    sectionBtn.hidden = !lathe;
    tableBtn.hidden = lathe;
    paintMore();
  };

  // [이전 공구]  (처음으로) (재생) 지금 공구  [다음 공구]
  const labelBtn = (name: string, text: string, title: string, iconAfter: boolean): HTMLButtonElement => {
    const b = el('button', { type: 'button', title, class: 'v-tool' });
    b.innerHTML = iconAfter ? `<span>${text}</span>${icon(name)}` : `${icon(name)}<span>${text}</span>`;
    return b;
  };
  const bPrevTool = labelBtn('prev', '이전 공구', '이전 공구 (F6)', false);
  const bNextTool = labelBtn('next', '다음 공구', '다음 공구 (F8)', true);
  const centerBox = el('div', { class: 'v-center' });
  const bRewind = mkIconBtn(centerBox, 'rewind', '처음으로');
  const bPlay = mkIconBtn(centerBox, 'play', '재생 / 정지 (F7)');
  bPlay.classList.add('v-playbtn');
  const toolNow = el('span', { class: 'v-toolnow' });
  centerBox.append(toolNow);
  buttonRow.append(bPrevTool, centerBox, bNextTool);
  const speedSel = el('select', { title: '재생 속도' });
  for (const s of PLAY_SPEEDS) speedSel.append(new Option(`${s}x`, String(s)));
  speedSel.value = '50';
  const slider = el('input', { type: 'range', min: '0', max: '0', value: '0', title: '재생 위치' });
  const pctText = el('span', { class: 'v-pct' });
  pctText.textContent = '0%';
  playBar.append(speedSel, slider, pctText);
  const timeText = el('span', { class: 'v-time' });
  timeText.textContent = '00:00 / 00:00';
  coordRow.append(coordBox, timeText);
  /** 원본 PlaybackBarWidget.set_modal_state / set_tool_text */
  function showModal(): void {
    paintModalToggle();
    const tl = result?.modal_timeline;
    const isLathe = tl ? tl.lathe : lathe;
    const { state, changed } = tl ? tl.at(seqNow) : { state: emptyState() as ModalState, changed: new Set<string>() };
    modalPeek.textContent = summaryText(state, isLathe);
    const mk = markerAt(seqNow);
    const [num, name] = toolNumberAndName(mk?.key ?? result?.seq_to_tool_map.get(seqNow));
    toolNow.innerHTML = '';
    if (num) {
      toolNow.append(num + ' '); const b = el('b'); b.textContent = name; toolNow.append(b);
      // 원본 v2.6.6: 공정 머리말 주석 최대 2줄
      for (const c of (mk?.comments ?? []).slice(0, 2)) { toolNow.append(el('br')); const t = el('span', { class: 'v-toolcm' }); t.textContent = c; toolNow.append(t); }
    }
    if (!modalOpen) return;
    buildGroups(isLathe);
    let s = state.S ? 'S' + state.S : '';
    if (isLathe && state.groups['02'] === 'G96' && s) s += ' (주속)';
    paintCell(kvCells.get('S')!, s, changed.has('S'));
    paintCell(kvCells.get('spindle')!, state.m.spindle, changed.has('m:spindle'));
    paintCell(kvCells.get('F')!, state.F ? 'F' + state.F : '', changed.has('F'));
    paintCell(kvCells.get('unit')!, feedUnit(state, isLathe), false);
    for (const [gid, cell] of groupCells) paintCell(cell, state.groups[gid], changed.has(gid));
    mRow.replaceChildren();
    for (const [key, name] of M_CATEGORIES) {
      const item = el('span');
      const code = el('code');
      paintCell(code, state.m[key], changed.has('m:' + key));
      item.append(name + ' ', code);
      mRow.append(item);
    }
  }

  // ---------------------------------------------------------------- 카메라
  const cameraPosition = (): THREE.Vector3 => {
    const e = (elevation * Math.PI) / 180;
    const a = (azimuth * Math.PI) / 180;
    return new THREE.Vector3(
      center.x + distance * Math.cos(e) * Math.cos(a),
      center.y + distance * Math.cos(e) * Math.sin(a),
      center.z + distance * Math.sin(e),
    );
  };
  const clampRange = (): void => {
    const far = Math.max(1000, (radius + distance) * 4);
    void far;
    const halfH = distance * Math.tan((fovDeg * Math.PI) / 360);
    const depth = Math.max(distance, radius) * 20 + 1000;
    camera.left = -halfH * aspect; camera.right = halfH * aspect;
    camera.top = halfH; camera.bottom = -halfH;
    camera.near = -depth; camera.far = depth;
  };
  let dirty = true;
  const apply = (): void => {
    elevation = Math.max(-90, Math.min(90, elevation));
    // 정확히 ±90°면 up 벡터와 평행이라 방향이 뒤집힌다 — 아주 조금 비킨다
    const safeElev = Math.abs(elevation) > 89.999 ? Math.sign(elevation) * 89.999 : elevation;
    const keep = elevation;
    elevation = safeElev;
    camera.position.copy(cameraPosition());
    elevation = keep;
    camera.lookAt(center);
    clampRange();
    camera.updateProjectionMatrix();
    updateCube();
    dirty = true;
  };
  const distanceForRadius = (r: number, w: number, h: number): number => {
    if (!r || r <= 0) return FALLBACK_DISTANCE;
    const aspect = Math.max(w, 1) / Math.max(h, 1);
    const halfTan = Math.tan((Math.max(fovDeg, 1) * Math.PI) / 360);
    return Math.max((r / (halfTan * Math.min(1, aspect))) * ZOOM_TO_FIT_MARGIN, 10);
  };
  const boundsCenterRadius = (): { c: THREE.Vector3; r: number } => {
    const b = result ? sceneBounds(result) : null;
    if (!b) return { c: new THREE.Vector3(), r: 0 };
    const c = new THREE.Vector3((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2);
    const r = Math.hypot(b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]) / 2;
    return { c, r };
  };
  /** 화면 크기가 아직 0 일 때 맞춘 뷰는 크기가 정해지면 다시 맞춘다 */
  let needFit = false;
  function setProjection(name: string): void {
    const preset = PROJECTIONS[name];
    if (!preset) return;
    needFit = host.clientWidth < 50 || host.clientHeight < 50;
    [elevation, azimuth] = preset;
    const w = host.clientWidth;
    const h = host.clientHeight;
    const { c, r } = boundsCenterRadius();
    if (r > 0) {
      center.copy(c);
      distance = distanceForRadius(r, w, h);
    } else {
      center.set(0, 0, 0);
      distance = distanceForRadius(radius, w, h);
    }
    orbitLocked = lathe && name === 'LATHE';
    projButtons.forEach((b, i) => b.classList.toggle('on', (lathe ? ['ISO', 'LATHE'] : ['ISO', 'XY', 'XZ', 'YZ'])[i] === name));
    apply();
  }

  // ---------------------------------------------------------------- 입력 (한 손가락 궤도·두 손가락 이동/확대·휠·오른쪽 끌기 이동)
  const pointers = new Map<number, { x: number; y: number }>();
  let lastPinch = 0;
  const panBy = (dx: number, dy: number): void => {
    const h = Math.max(host.clientHeight, 1);
    const worldPerPx = (2 * distance * Math.tan((fovDeg * Math.PI) / 360)) / h;
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
    center.addScaledVector(right, -dx * worldPerPx).addScaledVector(up, dy * worldPerPx);
    apply();
  };
  // 제스처 위치 기준 계산: 화면 점 → 보는 방향에 수직이고 중심을 지나는 평면 위의 월드 좌표
  const frame = (): { r: THREE.Vector3; u: THREE.Vector3 } => {
    const e = (elevation * Math.PI) / 180;
    const a = (azimuth * Math.PI) / 180;
    return {
      r: new THREE.Vector3(-Math.sin(a), Math.cos(a), 0),
      u: new THREE.Vector3(-Math.sin(e) * Math.cos(a), -Math.sin(e) * Math.sin(a), Math.cos(e)),
    };
  };
  const screenOffset = (cx: number, cy: number): { sx: number; sy: number } => {
    const box = renderer.domElement.getBoundingClientRect();
    const wpp = (2 * distance * Math.tan((fovDeg * Math.PI) / 360)) / Math.max(box.height, 1);
    return { sx: (cx - box.left - box.width / 2) * wpp, sy: -(cy - box.top - box.height / 2) * wpp };
  };
  /** 손가락 위치를 고정한 채 확대·축소 */
  const zoomAt = (factor: number, cx: number, cy: number): void => {
    const { r, u } = frame();
    const { sx, sy } = screenOffset(cx, cy);
    const next = Math.max(1, Math.min(distance * factor, 1e6));
    const f = next / distance;
    center.addScaledVector(r, sx * (1 - f)).addScaledVector(u, sy * (1 - f));
    distance = next;
    apply();
  };
  /** 손가락을 댄 지점을 중심으로 회전 */
  const orbitAbout = (cx: number, cy: number, dAz: number, dEl: number): void => {
    const f0 = frame();
    const { sx, sy } = screenOffset(cx, cy);
    const pivot = center.clone().addScaledVector(f0.r, sx).addScaledVector(f0.u, sy);
    azimuth += dAz;
    elevation = Math.max(-90, Math.min(90, elevation + dEl));
    const f1 = frame();
    center.copy(pivot).addScaledVector(f1.r, -sx).addScaledVector(f1.u, -sy);
    apply();
  };
  const dom = renderer.domElement;
  dom.style.touchAction = 'none';
  // 제스처 상태 — 탭/드래그 구분은 8dp
  const TAP_SLOP = 8;
  const DOUBLE_TAP_MS = 320;
  let lastTapEnd = 0;
  let lastTapPos = { x: 0, y: 0 };
  let zoomDrag = false;
  let moved = false;
  let downTime = 0;
  let longTimer = 0;
  let region: { x0: number; y0: number; x1: number; y1: number } | null = null;
  const regionBox = el('div', { class: 'v-region' });
  regionBox.hidden = true;
  host.append(regionBox);
  const drawRegion = (): void => {
    if (!region) { regionBox.hidden = true; return; }
    const r = dom.getBoundingClientRect();
    regionBox.hidden = false;
    regionBox.style.left = `${Math.min(region.x0, region.x1) - r.left}px`;
    regionBox.style.top = `${Math.min(region.y0, region.y1) - r.top}px`;
    regionBox.style.width = `${Math.abs(region.x1 - region.x0)}px`;
    regionBox.style.height = `${Math.abs(region.y1 - region.y0)}px`;
  };
  const zoomToRegion = (r: { x0: number; y0: number; x1: number; y1: number }): void => {
    const box = dom.getBoundingClientRect();
    const w = box.width, h = box.height;
    const rw = Math.abs(r.x1 - r.x0), rh = Math.abs(r.y1 - r.y0);
    if (rw < 12 || rh < 12) return;
    const cxp = (r.x0 + r.x1) / 2 - box.left - w / 2;
    const cyp = (r.y0 + r.y1) / 2 - box.top - h / 2;
    const worldPerPx = (2 * distance * Math.tan((fovDeg * Math.PI) / 360)) / Math.max(h, 1);
    const right = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 0);
    const up = new THREE.Vector3().setFromMatrixColumn(camera.matrixWorld, 1);
    center.addScaledVector(right, cxp * worldPerPx).addScaledVector(up, -cyp * worldPerPx);
    distance = Math.max(1, distance * Math.max(rw / w, rh / h));
    apply();
  };
  const fitView = (): void => {
    const w = host.clientWidth, h = host.clientHeight;
    const { c, r } = boundsCenterRadius();
    if (r > 0) {
      center.copy(c);
      distance = distanceForRadius(r, w, h);
    } else {
      center.set(0, 0, 0);
      distance = distanceForRadius(radius, w, h);
    }

    apply();
  };
  dom.addEventListener('pointerdown', (e) => {
    dom.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    window.clearTimeout(longTimer);
    if (pointers.size === 1) {
      moved = false;
      downPos = { x: e.clientX, y: e.clientY };
      downTime = performance.now();
      zoomDrag = downTime - lastTapEnd < DOUBLE_TAP_MS && Math.hypot(e.clientX - lastTapPos.x, e.clientY - lastTapPos.y) < 24;
      if (!zoomDrag) {
        longTimer = window.setTimeout(() => {
          if (pointers.size === 1 && !moved) {
            region = { x0: e.clientX, y0: e.clientY, x1: e.clientX, y1: e.clientY };
            navigator.vibrate?.(15);
            drawRegion();
          }
        }, 400);
      }
    } else {
      zoomDrag = false;
      region = null;
      drawRegion();
    }
    if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      lastPinch = Math.hypot(a!.x - b!.x, a!.y - b!.y);
    }
  });
  dom.addEventListener('pointermove', (e) => {
    const p = pointers.get(e.pointerId);
    if (!p) return;
    const dx = e.clientX - p.x;
    const dy = e.clientY - p.y;
    p.x = e.clientX;
    p.y = e.clientY;
    const sens = getViewerSettings().sensitivityPct / 100;
    if (pointers.size === 1 && !moved && Math.hypot(e.clientX - lastTapPos.x, e.clientY - lastTapPos.y) < 0) moved = true;
    if (pointers.size === 1 && !region) {
      // 눌린 자리에서 8dp 넘게 움직이면 탭이 아니라 드래그
      if (Math.abs(dx) + Math.abs(dy) > 0) {
        const first = tapOrigin ?? (tapOrigin = { x: e.clientX - dx, y: e.clientY - dy });
        if (Math.hypot(e.clientX - first.x, e.clientY - first.y) > TAP_SLOP) { moved = true; window.clearTimeout(longTimer); }
      }
    }
    if (region) {
      region.x1 = e.clientX; region.y1 = e.clientY; drawRegion();
    } else if (pointers.size >= 3) {
      const s = updateViewerSettingsFov(-dy * 0.15);
      void s;
    } else if (pointers.size === 2) {
      const [a, b] = [...pointers.values()];
      const d = Math.hypot(a!.x - b!.x, a!.y - b!.y);
      if (lastPinch > 0 && d > 0) zoomAt(lastPinch / d, (a!.x + b!.x) / 2, (a!.y + b!.y) / 2);
      lastPinch = d;
      panBy(dx / 2, dy / 2);
    } else if (!moved) {
      /* 아직 탭인지 드래그인지 정해지지 않았다 */
    } else if (zoomDrag) {
      zoomAt(1.01 ** (dy * sens * 2.5), e.clientX, e.clientY);
    } else if (e.buttons & 6 || orbitLocked) {
      panBy(dx, dy);
    } else {
      orbitAbout(downPos.x, downPos.y, -dx * sens, dy * sens);
    }
  });
  let tapOrigin: { x: number; y: number } | null = null;
  let downPos = { x: 0, y: 0 };
  const updateViewerSettingsFov = (delta: number): number => {
    const fov = Math.max(FOV_MIN, Math.min(FOV_MAX, fovDeg + delta));
    fovDeg = fov;
    apply();
    return fov;
  };
  let downAt: { x: number; y: number } | null = null;
  dom.addEventListener('pointerdown', (e) => { downAt = pointers.size === 0 ? { x: e.clientX, y: e.clientY } : null; }, true);
  const pickAt = (cx: number, cy: number): void => {
    if (!result) return;
    const rect = dom.getBoundingClientRect();
    const w = rect.width, h = rect.height;
    const px = cx - rect.left, py = cy - rect.top;
    const v = new THREE.Vector3();
    const toScreen = (x: number, y: number, z: number): [number, number, boolean] => {
      v.set(x, y, z).project(camera);
      return [(v.x * 0.5 + 0.5) * w, (-v.y * 0.5 + 0.5) * h, v.z < 1];
    };
    let best = 24; // px
    let bestSeq = -1;
    for (const p of processes) {
      if (visible && !visible.has(p.key)) continue;
      for (const b of p.buckets) {
        for (let i = 0; i < b.seqs.length; i++) {
          const o = i * 6;
          const [ax, ay, aok] = toScreen(b.pos[o]!, b.pos[o + 1]!, b.pos[o + 2]!);
          const [bx, by, bok] = toScreen(b.pos[o + 3]!, b.pos[o + 4]!, b.pos[o + 5]!);
          if (!aok || !bok) continue;
          const dx = bx - ax, dy = by - ay;
          const len2 = dx * dx + dy * dy;
          const tt = len2 ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
          const dist = Math.hypot(px - (ax + dx * tt), py - (ay + dy * tt));
          if (dist < best) { best = dist; bestSeq = b.seqs[i]!; }
        }
      }
    }
    if (bestSeq >= 0) { stopPlaying(); showSeq(bestSeq, false); hooks.onPick?.(lineAtSeq(result, bestSeq)); }
  };
  const endPointer = (e: PointerEvent): void => {
    window.clearTimeout(longTimer);
    const single = pointers.size === 1;
    const wasTap = single && !moved && !region && performance.now() - downTime < 350;
    if (region) {
      zoomToRegion(region);
      region = null;
      drawRegion();
      pickMode = true; // 영역 확대 뒤에는 위치 찍기 모드가 켜진다
      projBar.firstElementChild?.classList.add('on');
    } else if (pickMode && downAt && single && Math.hypot(e.clientX - downAt.x, e.clientY - downAt.y) < TAP_SLOP) {
      pickAt(e.clientX, e.clientY);
    } else if (wasTap && !zoomDrag) {
      const now = performance.now();
      if (now - lastTapEnd < DOUBLE_TAP_MS && Math.hypot(e.clientX - lastTapPos.x, e.clientY - lastTapPos.y) < 24) { fitView(); lastTapEnd = 0; }
      else { lastTapEnd = now; lastTapPos = { x: e.clientX, y: e.clientY }; }
    } else if (wasTap && zoomDrag) {
      fitView(); // 두 번째 탭을 누른 채 끌지 않고 뗐다 = 두 번 탭
      lastTapEnd = 0;
    }
    if (zoomDrag && moved) lastTapEnd = 0;
    zoomDrag = false;
    tapOrigin = null;
    downAt = null;
    pointers.delete(e.pointerId);
    lastPinch = 0;
  };
  dom.addEventListener('pointerup', endPointer);
  dom.addEventListener('pointercancel', endPointer);
  dom.addEventListener('contextmenu', (e) => e.preventDefault());
  dom.addEventListener('wheel', (e) => { e.preventDefault(); zoomAt(Math.exp(e.deltaY * 0.0015), e.clientX, e.clientY); }, { passive: false });

  // ---------------------------------------------------------------- 경로 그리기
  const lineWidth = (base: number): number => toolpathLineWidth(base, getViewerSettings().lineWidthPct);
  const clearScene = (): void => {
    for (const p of processes) for (const o of [...p.objs, ...p.trace.map((t) => t.obj)]) { group.remove(o); o.geometry.dispose(); (o.material as LineMaterial).dispose(); }
    processes = [];
    entryGroups = new Map();
    materials.length = 0;
  };
  const makeLines = (pos: number[], color: readonly number[], base: number): LineSegments2 => {
    const geom = new LineSegmentsGeometry();
    geom.setPositions(new Float32Array(pos));
    const mat = new LineMaterial({ color: rgb(color), linewidth: lineWidth(base), worldUnits: false, depthTest: false, transparent: true });
    mat.resolution.set(Math.max(1, host.clientWidth), Math.max(1, host.clientHeight));
    materials.push({ m: mat, base });
    const obj = new LineSegments2(geom, mat);
    obj.frustumCulled = false;
    return obj;
  };

  function setProgram(r: ToolpathResult | null, machineType: string): void {
    clearScene();
    result = r;
    machine = machineType;
    lathe = isLatheMachine(machineType);
    buildProjButtons();
    marker.visible = false;
    if (!r) { radius = 0; updateSlider(); apply(); return; }
    let idx = 0;
    for (const [key, path] of r.tool_paths) {
      const buckets = segmentBuckets(path);
      const color = toolColorForIndex(idx);
      const entry: ProcessObjects = { key, index: idx, objs: [], trace: [], buckets: [] };
      entry.buckets.push({ pos: buckets.rapid, seqs: buckets.rapidSeq }, { pos: buckets.cut, seqs: buckets.cutSeq });
      if (buckets.rapid.length) {
        const o = makeLines(buckets.rapid, RAPID_MOVE_COLOR, RAPID_LINE_BASE_WIDTH);
        entry.objs.push(o); group.add(o);
        const t = makeLines(buckets.rapid, RAPID_MOVE_COLOR, RAPID_LINE_BASE_WIDTH + 1);
        t.visible = false; entry.trace.push({ obj: t, seqs: buckets.rapidSeq }); group.add(t);
      }
      if (buckets.cut.length) {
        const o = makeLines(buckets.cut, color, CUT_LINE_BASE_WIDTH);
        entry.objs.push(o); group.add(o);
        const t = makeLines(buckets.cut, color, TRACE_CUT_LINE_BASE_WIDTH);
        t.visible = false; entry.trace.push({ obj: t, seqs: buckets.cutSeq }); group.add(t);
      }
      if (!lathe) entryGroups.set(key, cutGroups(path, r.line_axis_map));
      processes.push(entry);
      idx++;
    }
    const b = sceneBounds(r);
    radius = b ? Math.sqrt(Math.max(...b.min.map(Math.abs), ...b.max.map(Math.abs)) ** 2 * 3) : 0;
    const markerSize = Math.max(0.5, Math.min(6, (b ? Math.hypot(b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]) : 100) / 120));
    markerBase = markerSize;
    applyMarkerScale();
    axes.scale.setScalar(Math.max(10, radius / 6));
    updateSlider();
    setProjection(lathe ? 'LATHE' : 'XY');
    seqNow = 0;
    showSeq(0, false);
  }

  const visibleKeys = (): Set<string> | null => visible;
  let visible: Set<string> | null = null;
  function setVisible(keys: string[] | null): void {
    visible = keys ? new Set(keys) : null;
    showSeq(seqNow, false);
    if (!simLive) sim.setTarget(selectionEndSeq());
  }

  /** 지금 보이는 공정들 중 가장 뒤 공정의 끝 seq (실시간 형상이 아닐 때 소재를 어디까지 깎을지) */
  function selectionEndSeq(): number | null {
    if (!result) return null;
    let best: number | null = null;
    for (const [key, path] of result.tool_paths) {
      if (visible && !visible.has(key)) continue;
      for (let i = path.length - 1; i >= 0; i--) {
        const n = path[i]!;
        if (n.valid) { if (best === null || n.seq > best) best = n.seq; break; }
      }
    }
    return best;
  }

  // ---------------------------------------------------------------- 재생
  let seqNow = 0;
  let playing = false;
  let virtualTime = 0;
  let lastFrame = 0;
  let sortedKeys: number[] = [];
  const updateSlider = (): void => {
    const n = result ? sequenceLength(result) : 0;
    slider.max = String(Math.max(0, n - 1));
    sortedKeys = result ? [...result.seq_to_elapsed_sec.keys()].sort((a, b) => a - b) : [];
  };

  function showSeq(seq: number, emit: boolean): void {
    if (!result) return;
    const n = sequenceLength(result);
    seqNow = Math.max(0, Math.min(seq, Math.max(0, n - 1)));
    slider.value = String(seqNow);
    if (simLive) sim.setTarget(seqNow);
    const keysVisible = visibleKeys();
    const curKey = pgMatch ? currentProcessKey() : null;
    const fromSeq = trailSeqFrom(seqNow);
    for (const p of processes) {
      const on = !keysVisible || keysVisible.has(p.key);
      for (const o of p.objs) o.visible = on && !pgMatch && toolpathOn; // PG 매칭 중에는 전체 경로를 숨긴다
      const traceOn = on && toolpathOn && (!pgMatch || p.key === curKey);
      for (const t of p.trace) {
        let count = 0;
        const s = t.seqs;
        let lo = 0, hi = s.length;
        while (lo < hi) { const mid = (lo + hi) >> 1; if (s[mid]! <= seqNow) lo = mid + 1; else hi = mid; }
        count = lo;
        let from = 0;
        if (fromSeq > 0) {
          let a = 0, z = count;
          while (a < z) { const mid = (a + z) >> 1; if (s[mid]! < fromSeq) a = mid + 1; else z = mid; }
          from = a;
        }
        t.obj.visible = traceOn && count > from;
        if (count > from) setTraceWindow(t.obj.geometry as LineSegmentsGeometry, from, count);
      }
    }
    // 현재 위치 표시와 좌표
    let c = result.seq_to_coord_map.get(seqNow);
    if (!c) {
      for (let k = seqNow - 1; k >= 0 && !c; k--) c = result.seq_to_coord_map.get(k);
    }
    // 선반 C축: 공구는 +X 센터에 고정되고 경로가 도는 것처럼 — 마커는 C 역회전, 진행 선은 C 만큼 회전(원본 v1.6.6)
    const cRot = lathe ? (result.seq_to_c_rot.get(seqNow) ?? 0) : 0;
    tableSync(seqNow);
    const tm = tableDisp ? tableMatsOf(tableDisp) : null;
    if (tm) workGroup.quaternion.setFromRotationMatrix(tm.part); else workGroup.quaternion.identity();
    axes.quaternion.copy(workGroup.quaternion); // 원본 v2.6.0: 축 원점 표시도 소재와 함께 돈다
    if (c) {
      let [mx, my, mz] = c;
      if (cRot) {
        const r = (cRot * Math.PI) / 180;
        const sn = Math.sin(r), cs = Math.cos(r);
        [my, mz] = [my * cs - mz * sn, my * sn + mz * cs];
      }
      marker.position.set(mx, my, mz);
      if (tm) marker.position.applyMatrix4(tm.part);
      marker.visible = true;
    } else marker.visible = false;
    for (const p of processes) for (const t of p.trace) t.obj.rotation.x = (cRot * Math.PI) / 180;
    // 진입 방향 화살표
    entryArrow.visible = false;
    if (!lathe) {
      const key = result.seq_to_tool_map.get(seqNow);
      const g = key ? groupAt(entryGroups.get(key) ?? [], seqNow) : null;
      if (g && (!keysVisible || keysVisible.has(key!))) {
        entryArrow.position.set(g.entry[0], g.entry[1], g.entry[2]);
        axisVec.set(g.direction[0], g.direction[1], g.direction[2]);
        if (tm) { entryArrow.position.applyMatrix4(tm.part); axisVec.transformDirection(tm.part); }
        entryArrow.quaternion.setFromUnitVectors(Z_UP, axisVec);
        entryArrow.scale.setScalar(axes.scale.x * 0.35);
        entryArrow.visible = true;
      }
    }
    const ax = result.line_axis_map.get(result.seq_to_line[seqNow] ?? -1);
    if (ax && Math.hypot(ax[0], ax[1], ax[2]) > 1e-9) axisVec.set(ax[0], ax[1], ax[2]).normalize(); else axisVec.copy(Z_UP);
    if (tm) axisVec.copy(Z_UP).transformDirection(tm.tool);
    marker.quaternion.setFromUnitVectors(Z_UP, axisVec);
    toolMesh.visible = false;
    if (!lathe && marker.visible) {
      const pk = result.seq_to_tool_map.get(seqNow);
      const toolNo = pk ? result.process_tool_map.get(pk) : undefined;
      const geo = toolNo ? toolGeometry(toolNo) : null;
      if (geo && pk && (!keysVisible || keysVisible.has(pk))) {
        const base = toolColorForIndex(processes.find((p) => p.key === pk)?.index ?? 0);
        toolMat.color.setRGB(0.6 + 0.4 * base[0], 0.6 + 0.4 * base[1], 0.6 + 0.4 * base[2]);
        toolMesh.geometry = geo;
        // 전체가 한눈에 보이는 배율에서도 보이도록, 너무 작은 공구는 구 표시(markerBase) 기준 최소 지름까지만 키운다
        const minDia = markerBase * 1.5 * (getViewerSettings().lineWidthPct / 90);
        toolMesh.scale.setScalar(Math.max(1, minDia / (2 * ((geo.userData.radius as number) || 1))));
        toolMesh.position.copy(marker.position);
        toolMesh.quaternion.copy(marker.quaternion);
        toolMesh.visible = true;
        marker.visible = false;
      }
    }
    const modal = result.seq_to_modal_state.get(seqNow);
    // 원본 v2.6.4: 축 이름은 흐리게, 값은 한 가지 색 · 고정폭
    coordBox.replaceChildren();
    if (modal) {
      const axes = lathe ? [['X', 0], ['Y', 1], ['Z', 2], ['C', 5]] as const : [['X', 0], ['Y', 1], ['Z', 2], ['A', 3], ['B', 4], ['C', 5]] as const;
      for (const [name, i] of axes) { const s = el('span'); s.textContent = name; const b = el('b'); b.textContent = String(modal[i]); s.append(b); coordBox.append(s); }
    }
    if (result.machine_auto_note) { const note = el('em'); note.textContent = result.machine_auto_note; coordBox.append(note); }
    timeText.textContent = formatElapsedOverTotal(elapsedSecondsAtSeq(result, seqNow, sortedKeys), result.total_time_sec);
    const total = sequenceLength(result);
    pctText.textContent = `${total > 1 ? Math.round((Math.max(0, Math.min(1, seqNow / (total - 1)))) * 100) : 0}%`;
    showModal();
    dirty = true;
    if (emit) hooks.onLine?.(lineAtSeq(result, seqNow));
  }

  const stopPlaying = (): void => { playing = false; bPlay.innerHTML = icon('play'); tableFinish(); };
  const startPlaying = (): void => {
    if (!result) return;
    if (seqNow >= sequenceLength(result) - 1) { seqNow = 0; showSeq(0, true); }
    virtualTime = elapsedSecondsAtSeq(result, seqNow, sortedKeys);
    lastFrame = performance.now();
    playing = true;
    bPlay.innerHTML = icon('pause');
  };
  bPlay.addEventListener('click', () => (playing ? stopPlaying() : startPlaying()));
  bRewind.addEventListener('click', () => { stopPlaying(); showSeq(0, true); });
  slider.addEventListener('input', () => { stopPlaying(); showSeq(Number(slider.value), true); });
  const jumpTool = (dir: -1 | 1): void => {
    if (!result) return;
    // 원본 v2.6.6: 공구 교체(M6) 줄이 아니라 공정의 첫 N 시퀀스 줄로 간다(주석이 함께 보인다)
    const seqs = processMarkers().map((m) => m.seq);
    if (!seqs.length) return;
    stopPlaying();
    showSeq(pickRelativeMarker(seqs, seqNow, dir), true);
  };
  bPrevTool.addEventListener('click', () => jumpTool(-1));
  bNextTool.addEventListener('click', () => jumpTool(1));

  const shouldStop = (seq: number): boolean => {
    const rule = hooks.stopRule?.();
    if (!rule || !result) return false;
    const line = lineAtSeq(result, seq);
    const text = hooks.lineText?.(line) ?? '';
    const code = text.split(';')[0]!.replace(/\([^()]*\)/g, '').toUpperCase().replace(/ /g, '');
    if (rule.m00 && /M0?0(?!\d)/.test(code)) return true;
    if (rule.m01 && /M0?1(?!\d)/.test(code)) return true;
    if (rule.text && rule.textValue && text.toUpperCase().includes(rule.textValue.toUpperCase())) return true;
    return false;
  };

  let holdSince: number | null = null;
  let animClock: number | null = null;
  const tick = (now: number): void => {
    raf = requestAnimationFrame(tick);
    // 실시간 형상: 계산이 재생 위치를 못 따라오면 잠깐 기다린다(최대 3초 — 계산이 멈춘 경우 재생이 영영 서지 않게)
    let hold = false;
    if (playing && simLive && sim.lagging()) {
      holdSince ??= now;
      hold = now - holdSince < 3000;
    } else holdSince = null;
    const rotating = playing && tableAnimating();
    if (playing && result && (hold || rotating)) { lastFrame = now; virtualTime = elapsedSecondsAtSeq(result, seqNow, sortedKeys); }
    else if (playing && result) {
      const dt = (now - lastFrame) / 1000;
      lastFrame = now;
      virtualTime += dt * Number(speedSel.value);
      const n = sequenceLength(result);
      let next = seqNow;
      const startSeq = seqNow;
      while (next < n - 1 && elapsedSecondsAtSeq(result, next + 1, sortedKeys) <= virtualTime) {
        next++;
        // 같은 줄이 여러 seq 로 이어질 때(G80·사이클 줄 등) 줄에 들어설 때 한 번만 멈춘다 — 재생을 다시 눌렀을 때 같은 줄에서 또 멈춰 진행이 안 되던 문제
        if (lineAtSeq(result, next) !== lineAtSeq(result, next - 1) && shouldStop(next)) { showSeq(next, true); stopPlaying(); next = -1; break; }
        // 원본 v2.6.7: 회전축 인덱스 줄에서 한 번 멈춰 회전을 보인다(다 돌 때까지 아래에서 기다린다)
        if (tableRotationChangesAt(next)) break;
        if (next - startSeq > 20000) break;
      }
      if (next >= 0 && next !== seqNow) showSeq(next, true);
      if (seqNow >= n - 1) stopPlaying();
    }
    if (tableStep((now - (animClock ?? now)) / 1000)) showSeq(seqNow, false);
    animClock = now;
    if (dirty) {
      dirty = false;
      // 선 굵기 계산용 해상도가 0이면 선이 사라진다 — 매 그리기 전에 실제 크기와 맞춘다
      const rw = Math.max(1, host.clientWidth), rh = Math.max(1, host.clientHeight);
      for (const { m } of materials) if (m.resolution.x !== rw || m.resolution.y !== rh) m.resolution.set(rw, rh);
      renderer.render(scene, camera);
    }
  };
  let raf = requestAnimationFrame(tick);

  // ---------------------------------------------------------------- 설정 반영·크기
  const offSettings = onViewerSettings((s) => {
    fovDeg = s.fovDeg;
    const changed = s.tableRotation !== tableOn || s.trailHide !== trailOn || s.trailBlocks !== trailBlocks;
    rotarySpeed = s.rotarySpeed;
    paintRot();
    tableOn = s.tableRotation;
    trailOn = s.trailHide;
    trailBlocks = s.trailBlocks;
    paintTable();
    paintTrail();
    paintMore();
    if (changed) { tableGoal = null; tableDisp = null; showSeq(seqNow, false); }
    for (const { m, base } of materials) m.linewidth = toolpathLineWidth(base, s.lineWidthPct);
    applyMarkerScale();
    apply();
  });
  const resize = (): void => {
    const w = Math.max(1, host.clientWidth);
    const h = Math.max(1, host.clientHeight);
    renderer.setSize(w, h, false);
    aspect = w / h;
    if (needFit && host.clientWidth >= 50 && host.clientHeight >= 50 && result) { setProjection(lathe ? 'LATHE' : 'XY'); return; }
    for (const { m } of materials) m.resolution.set(w, h);
    apply();
  };
  const ro = new ResizeObserver(resize);
  ro.observe(host);
  resize();
  buildProjButtons();

  return {
    setProgram,
    setVisible,
    setLine(line: number) {
      if (!result) return;
      const s = resolveSeqForLine(result, line, seqNow);
      if (s !== null && s !== seqNow) { stopPlaying(); showSeq(s, false); }
    },
    seq: () => seqNow,
    resize,
    reset() { stopPlaying(); showSeq(0, true); setProjection(lathe ? 'LATHE' : 'XY'); },
    togglePlay() { if (playing) stopPlaying(); else startPlaying(); },
    jumpTool,
    cancelPick() {
      if (!pickMode) return false;
      pickMode = false;
      projBar.firstElementChild?.classList.remove('on');
      return true;
    },
    setToolValues(v) { toolValues = v; toolGeoCache.clear(); },
    setToolNames(names) { toolNames = names; },
    setSimProgram(p, source) { sim.setProgram(p, source); if (!simLive) sim.setTarget(selectionEndSeq()); },
    applyStock(bounds, resolution, on) {
      if (bounds && 'X' in bounds) {
        // 소재가 화면 가운데에 꽉 차게 맞춘다
        center.set((bounds.X[0] + bounds.X[1]) / 2, (bounds.Y[0] + bounds.Y[1]) / 2, (bounds.Z[0] + bounds.Z[1]) / 2);
        const r = Math.hypot(bounds.X[1] - bounds.X[0], bounds.Y[1] - bounds.Y[0], bounds.Z[1] - bounds.Z[0]) / 2;
        distance = distanceForRadius(r, host.clientWidth, host.clientHeight);
        apply();
      }
      sim.setStock(bounds, resolution, on); sim.setTarget(simLive ? seqNow : selectionEndSeq(), true); },
    setToolpathVisible(on) { toolpathOn = on; showSeq(seqNow, false); },
    setPgMatch(on) { pgMatch = on; showSeq(seqNow, false); },
    setSimEnabled(on) { sim.setEnabled(on); },
    setSimLive(on) {
      simLive = on;
      paintLive();
      sim.setLive(on);
      sim.setTarget(on ? seqNow : selectionEndSeq());
    },
    simStatus: () => sim.status(),
    exportStl: () => sim.exportStl(),
    setSection: (m) => { applySection(m); },
    setStopOptions(content) { stopSlot.replaceChildren(content); paintMore(); },
    dispose() {
      sim.dispose();
      cancelAnimationFrame(raf);
      ro.disconnect();
      offSettings();
      clearScene();
      renderer.dispose();
      void machine;
    },
  };
}
