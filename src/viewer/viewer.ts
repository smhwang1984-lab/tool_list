// 3D 뷰어 — Three.js. 공정별 경로(급속 빨강 / 절삭 공구색), 카메라(궤도·이동·줌), 투영 버튼, 좌표·시간 표시, 재생.
// 계산은 core/toolpath.ts 의 결과를 그대로 쓴다. 원본: NCViewerWidget(경로 그리기·카메라·재생).
import * as THREE from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { elapsedSecondsAtSeq, formatElapsedOverTotal, lineAtSeq, resolveSeqForLine, sequenceLength } from '../core/playback';
import { isLatheMachine, type ToolpathResult } from '../core/toolpath';
import { createSimLayer, type SimLayer, type SimSource, type SimStatus } from './simLayer';
import type { SimProgram } from '../sim/segments';
import type { Bounds } from '../sim/stock';
import type { LatheProgram } from '../sim/latheSegments';
import type { LatheBounds } from '../sim/latheStock';
import { CUT_LINE_BASE_WIDTH, FOV_MAX, FOV_MIN, toolpathLineWidth } from '../core/viewerSettings';
import { getPref, setPref } from '../platform/prefs';
import { getViewerSettings, onViewerSettings } from '../platform/viewerSettings';
import { el } from '../ui/dialog';
import { icon } from '../icons';
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
  /** 가공 형상 상태가 바뀜(진행·적용) */
  onSimChange?: () => void;
}
export interface Viewer {
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

  const group = new THREE.Group();
  scene.add(group);
  const sim: SimLayer = createSimLayer(scene, () => { dirty = true; instantBtn.disabled = !sim.hasStock(); hooks.onSimChange?.(); }, (busy, pct) => {
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
  let processes: ProcessObjects[] = [];
  const materials: { m: LineMaterial; base: number }[] = [];

  // ---------------------------------------------------------------- 화면 겹침(오버레이)
  const projBar = el('div', { class: 'v-proj' });
  const coordBox = el('div', { class: 'v-coord' });
  const playBar = el('div', { class: 'v-play' });
  host.append(projBar, coordBox, playBar, progressBox);
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
    projBar.append(instantBtn, sectionBtn);
    sectionBtn.hidden = !lathe;
  };

  const bPrevTool = mkIconBtn(playBar, 'prev', '이전 공정');
  const bRewind = mkIconBtn(playBar, 'rewind', '처음으로');
  const bPlay = mkIconBtn(playBar, 'play', '재생 / 정지');
  const bNextTool = mkIconBtn(playBar, 'next', '다음 공정');
  const speedSel = el('select', { title: '재생 속도' });
  for (const s of PLAY_SPEEDS) speedSel.append(new Option(`${s}x`, String(s)));
  speedSel.value = '50';
  const slider = el('input', { type: 'range', min: '0', max: '0', value: '0', title: '재생 위치' });
  const timeText = el('span', { class: 'v-time' });
  timeText.textContent = '00:00 / 00:00';
  playBar.append(speedSel, slider, timeText);

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
        t.obj.visible = traceOn && count > 0;
        if (count > 0) (t.obj.geometry as LineSegmentsGeometry & { instanceCount: number }).instanceCount = count;
      }
    }
    // 현재 위치 표시와 좌표
    let c = result.seq_to_coord_map.get(seqNow);
    if (!c) {
      for (let k = seqNow - 1; k >= 0 && !c; k--) c = result.seq_to_coord_map.get(k);
    }
    // 선반 C축: 공구는 +X 센터에 고정되고 경로가 도는 것처럼 — 마커는 C 역회전, 진행 선은 C 만큼 회전(원본 v1.6.6)
    const cRot = lathe ? (result.seq_to_c_rot.get(seqNow) ?? 0) : 0;
    if (c) {
      let [mx, my, mz] = c;
      if (cRot) {
        const r = (cRot * Math.PI) / 180;
        const sn = Math.sin(r), cs = Math.cos(r);
        [my, mz] = [my * cs - mz * sn, my * sn + mz * cs];
      }
      marker.position.set(mx, my, mz); marker.visible = true;
    } else marker.visible = false;
    for (const p of processes) for (const t of p.trace) t.obj.rotation.x = (cRot * Math.PI) / 180;
    // 진입 방향 화살표
    entryArrow.visible = false;
    if (!lathe) {
      const key = result.seq_to_tool_map.get(seqNow);
      const g = key ? groupAt(entryGroups.get(key) ?? [], seqNow) : null;
      if (g && (!keysVisible || keysVisible.has(key!))) {
        entryArrow.position.set(g.entry[0], g.entry[1], g.entry[2]);
        entryArrow.quaternion.setFromUnitVectors(Z_UP, axisVec.set(g.direction[0], g.direction[1], g.direction[2]));
        entryArrow.scale.setScalar(axes.scale.x * 0.35);
        entryArrow.visible = true;
      }
    }
    const ax = result.line_axis_map.get(result.seq_to_line[seqNow] ?? -1);
    if (ax && Math.hypot(ax[0], ax[1], ax[2]) > 1e-9) axisVec.set(ax[0], ax[1], ax[2]).normalize(); else axisVec.copy(Z_UP);
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
    coordBox.textContent = modal ? `X ${modal[0]}  Y ${modal[1]}  Z ${modal[2]}${lathe ? `  C ${modal[5]}` : `  A ${modal[3]}  B ${modal[4]}  C ${modal[5]}`}` : '';
    timeText.textContent = formatElapsedOverTotal(elapsedSecondsAtSeq(result, seqNow, sortedKeys), result.total_time_sec);
    dirty = true;
    if (emit) hooks.onLine?.(lineAtSeq(result, seqNow));
  }

  const stopPlaying = (): void => { playing = false; bPlay.innerHTML = icon('play'); };
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
    const starts = [...result.process_first_seq.entries()].filter(([k]) => result!.tool_paths.has(k)).map(([, s]) => s).sort((a, b) => a - b);
    const target = dir > 0 ? starts.find((s) => s > seqNow) : [...starts].reverse().find((s) => s < seqNow);
    if (target !== undefined) { stopPlaying(); showSeq(target, true); }
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
  const tick = (now: number): void => {
    raf = requestAnimationFrame(tick);
    // 실시간 형상: 계산이 재생 위치를 못 따라오면 잠깐 기다린다(최대 3초 — 계산이 멈춘 경우 재생이 영영 서지 않게)
    let hold = false;
    if (playing && simLive && sim.lagging()) {
      holdSince ??= now;
      hold = now - holdSince < 3000;
    } else holdSince = null;
    if (playing && result && hold) lastFrame = now;
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
        if (next - startSeq > 20000) break;
      }
      if (next >= 0 && next !== seqNow) showSeq(next, true);
      if (seqNow >= n - 1) stopPlaying();
    }
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
      sim.setLive(on);
      sim.setTarget(on ? seqNow : selectionEndSeq());
    },
    simStatus: () => sim.status(),
    exportStl: () => sim.exportStl(),
    setSection: (m) => { applySection(m); },
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
