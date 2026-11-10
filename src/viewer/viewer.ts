// 3D 뷰어 — Three.js. 공정별 경로(급속 빨강 / 절삭 공구색), 카메라(궤도·이동·줌), 투영 버튼, 좌표·시간 표시, 재생.
// 계산은 core/toolpath.ts 의 결과를 그대로 쓴다. 원본: NCViewerWidget(경로 그리기·카메라·재생).
import * as THREE from 'three';
import { LineMaterial } from 'three/examples/jsm/lines/LineMaterial.js';
import { LineSegments2 } from 'three/examples/jsm/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/examples/jsm/lines/LineSegmentsGeometry.js';
import { elapsedSecondsAtSeq, formatElapsedOverTotal, lineAtSeq, resolveSeqForLine, sequenceLength } from '../core/playback';
import { isLatheMachine, type ToolpathResult } from '../core/toolpath';
import { CUT_LINE_BASE_WIDTH, FOV_MAX, FOV_MIN, toolpathLineWidth } from '../core/viewerSettings';
import { getViewerSettings, onViewerSettings } from '../platform/viewerSettings';
import { el } from '../ui/dialog';
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
  /** 재생·찍기로 위치가 바뀜 → 입력창이 그 줄로 이동 (PG 매칭) */
  onLine?: (line: number) => void;
  /** 위치 찍기로 고른 줄 → 입력창 이동(항상) */
  onPick?: (line: number) => void;
  stopRule?: () => StopRule;
  lineText?: (line: number) => string;
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
  dispose(): void;
}

interface ProcessObjects { key: string; index: number; objs: LineSegments2[]; trace: { obj: LineSegments2; seqs: number[] }[]; buckets: { pos: number[]; seqs: number[] }[] }

const rgb = (c: readonly number[]): number => ((Math.round(c[0]! * 255) << 16) | (Math.round(c[1]! * 255) << 8) | Math.round(c[2]! * 255));

export function createViewer(host: HTMLElement, hooks: ViewerHooks = {}): Viewer | null {
  let renderer: THREE.WebGLRenderer;
  try {
    renderer = new THREE.WebGLRenderer({ antialias: true });
  } catch (error) {
    host.innerHTML = `<div class="placeholder" style="color:#c7d0e0">WebGL을 시작할 수 없습니다.<br>${String(error)}</div>`;
    return null;
  }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  renderer.setClearColor(0x11151c);
  host.append(renderer.domElement);

  const scene = new THREE.Scene();
  const settings = getViewerSettings();
  const camera = new THREE.PerspectiveCamera(settings.fovDeg, 1, 1, 100000);
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

  const marker = new THREE.Mesh(new THREE.SphereGeometry(1, 16, 12), new THREE.MeshBasicMaterial({ color: 0xffe14a, depthTest: false }));
  marker.renderOrder = 10;
  marker.visible = false;
  scene.add(marker);
  const axes = new THREE.AxesHelper(1);
  scene.add(axes);

  const group = new THREE.Group();
  scene.add(group);
  let processes: ProcessObjects[] = [];
  const materials: { m: LineMaterial; base: number }[] = [];

  // ---------------------------------------------------------------- 화면 겹침(오버레이)
  const projBar = el('div', { class: 'v-proj' });
  const coordBox = el('div', { class: 'v-coord' });
  const playBar = el('div', { class: 'v-play' });
  host.append(projBar, coordBox, playBar);
  const mkBtn = (parent: HTMLElement, label: string, title: string): HTMLButtonElement => {
    const b = el('button', { type: 'button', title });
    b.textContent = label;
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
    const pick = mkBtn(projBar, '📍', '위치 찍기: 경로를 탭하면 그 줄로 이동');
    pick.classList.toggle('on', pickMode);
    pick.addEventListener('click', () => { pickMode = !pickMode; pick.classList.toggle('on', pickMode); });
    for (const name of names) {
      const b = mkBtn(projBar, name === 'LATHE' ? '선반' : name, `${name} 보기`);
      b.addEventListener('click', () => { pickMode = false; projBar.firstElementChild?.classList.remove('on'); setProjection(name); });
      projButtons.push(b);
    }
  };

  const bPrevTool = mkBtn(playBar, '⏮', '이전 공정');
  const bRewind = mkBtn(playBar, '↺', '처음으로');
  const bPlay = mkBtn(playBar, '▶', '재생 / 정지');
  const bNextTool = mkBtn(playBar, '⏭', '다음 공정');
  const speedSel = el('select', { title: '재생 속도' });
  for (const s of PLAY_SPEEDS) speedSel.append(new Option(`${s}x`, String(s)));
  speedSel.value = '100';
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
    camera.near = Math.max(0.05, distance / 500);
    camera.far = far;
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
    const halfTan = Math.tan((Math.max(camera.fov, 1) * Math.PI) / 360);
    return Math.max((r / (halfTan * Math.min(1, aspect))) * ZOOM_TO_FIT_MARGIN, 10);
  };
  const boundsCenterRadius = (): { c: THREE.Vector3; r: number } => {
    const b = result ? sceneBounds(result) : null;
    if (!b) return { c: new THREE.Vector3(), r: 0 };
    const c = new THREE.Vector3((b.min[0] + b.max[0]) / 2, (b.min[1] + b.max[1]) / 2, (b.min[2] + b.max[2]) / 2);
    const r = Math.hypot(b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]) / 2;
    return { c, r };
  };
  function setProjection(name: string): void {
    const preset = PROJECTIONS[name];
    if (!preset) return;
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
    const worldPerPx = (2 * distance * Math.tan((camera.fov * Math.PI) / 360)) / h;
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
    const wpp = (2 * distance * Math.tan((camera.fov * Math.PI) / 360)) / Math.max(box.height, 1);
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
    const worldPerPx = (2 * distance * Math.tan((camera.fov * Math.PI) / 360)) / Math.max(h, 1);
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
    const fov = Math.max(FOV_MIN, Math.min(FOV_MAX, camera.fov + delta));
    camera.fov = fov;
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
      processes.push(entry);
      idx++;
    }
    const b = sceneBounds(r);
    radius = b ? Math.sqrt(Math.max(...b.min.map(Math.abs), ...b.max.map(Math.abs)) ** 2 * 3) : 0;
    const markerSize = Math.max(0.5, Math.min(6, (b ? Math.hypot(b.max[0] - b.min[0], b.max[1] - b.min[1], b.max[2] - b.min[2]) : 100) / 120));
    marker.scale.setScalar(markerSize);
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
    for (const p of processes) {
      const on = !visible || visible.has(p.key);
      for (const o of p.objs) o.visible = on;
    }
    showSeq(seqNow, false);
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
    const keysVisible = visibleKeys();
    for (const p of processes) {
      const on = !keysVisible || keysVisible.has(p.key);
      for (const t of p.trace) {
        let count = 0;
        const s = t.seqs;
        let lo = 0, hi = s.length;
        while (lo < hi) { const mid = (lo + hi) >> 1; if (s[mid]! <= seqNow) lo = mid + 1; else hi = mid; }
        count = lo;
        t.obj.visible = on && count > 0;
        if (count > 0) (t.obj.geometry as LineSegmentsGeometry & { instanceCount: number }).instanceCount = count;
      }
    }
    // 현재 위치 표시와 좌표
    let c = result.seq_to_coord_map.get(seqNow);
    if (!c) {
      for (let k = seqNow - 1; k >= 0 && !c; k--) c = result.seq_to_coord_map.get(k);
    }
    if (c) { marker.position.set(c[0], c[1], c[2]); marker.visible = true; } else marker.visible = false;
    const modal = result.seq_to_modal_state.get(seqNow);
    coordBox.textContent = modal ? `X ${modal[0]}  Y ${modal[1]}  Z ${modal[2]}${lathe ? '' : `  A ${modal[3]}  B ${modal[4]}  C ${modal[5]}`}` : '';
    timeText.textContent = formatElapsedOverTotal(elapsedSecondsAtSeq(result, seqNow, sortedKeys), result.total_time_sec);
    dirty = true;
    if (emit) hooks.onLine?.(lineAtSeq(result, seqNow));
  }

  const stopPlaying = (): void => { playing = false; bPlay.textContent = '▶'; };
  const startPlaying = (): void => {
    if (!result) return;
    if (seqNow >= sequenceLength(result) - 1) { seqNow = 0; showSeq(0, true); }
    virtualTime = elapsedSecondsAtSeq(result, seqNow, sortedKeys);
    lastFrame = performance.now();
    playing = true;
    bPlay.textContent = '⏸';
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

  const tick = (now: number): void => {
    raf = requestAnimationFrame(tick);
    if (playing && result) {
      const dt = (now - lastFrame) / 1000;
      lastFrame = now;
      virtualTime += dt * Number(speedSel.value);
      const n = sequenceLength(result);
      let next = seqNow;
      const startSeq = seqNow;
      while (next < n - 1 && elapsedSecondsAtSeq(result, next + 1, sortedKeys) <= virtualTime) {
        next++;
        if (shouldStop(next)) { showSeq(next, true); stopPlaying(); next = -1; break; }
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
    camera.fov = s.fovDeg;
    for (const { m, base } of materials) m.linewidth = toolpathLineWidth(base, s.lineWidthPct);
    apply();
  });
  const resize = (): void => {
    const w = Math.max(1, host.clientWidth);
    const h = Math.max(1, host.clientHeight);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
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
    dispose() {
      cancelAnimationFrame(raf);
      ro.disconnect();
      offSettings();
      clearScene();
      renderer.dispose();
      void machine;
    },
  };
}
