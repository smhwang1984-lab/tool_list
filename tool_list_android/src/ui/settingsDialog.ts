// ⚙ 설정 창(비모달) — 원본 SettingsDialog (NC_Tool_List.py 2629~). 값을 바꾸면 바로 반영되고 저장된다.
import {
  CUBE_DEFAULT, CUBE_MAX, CUBE_MIN, FOV_MAX, FOV_MIN, LINE_WIDTH_DEFAULT_PCT, LINE_WIDTH_STEPS, SENSITIVITY_MAX,
  SENSITIVITY_MIN, CUT_LINE_BASE_WIDTH, toolpathLineWidth,
} from '../core/viewerSettings';
import { getViewerSettings, resetViewerSettings, updateViewerSettings } from '../platform/viewerSettings';
import { el } from './dialog';

let open: HTMLDialogElement | null = null;

export interface SettingsExtras {
  /** 선반 스펙 저장소 백업(JSON 파일로 내보내기) / 복원(가져오기) */
  exportStore?: () => void;
  importStore?: () => void;
  /** 상단바 숨김 기능 사용 여부(선택, 기본 꺼짐) */
  hideTopBar?: { get: () => boolean; set: (enabled: boolean) => void };
}

export function showSettings(extras: SettingsExtras = {}): void {
  if (open?.isConnected) return;
  const s = getViewerSettings();
  const dlg = el('dialog', { class: 'settings' });
  const head = el('div', { class: 'dlg-head' });
  head.textContent = '설정';
  const body = el('div', { class: 'dlg-body settings-body' });
  const group = el('fieldset');
  const legend = el('legend');
  legend.textContent = 'Viewer 표시';
  group.append(legend);

  const row = (title: string, control: HTMLElement, value?: HTMLElement): void => {
    const label = el('label', { class: 'settings-row' });
    const name = el('span');
    name.textContent = title;
    label.append(name, control);
    if (value) label.append(value);
    group.append(label);
  };

  // 선 굵기: 굵기별 미리보기 선을 붙인 드롭다운(원본과 같은 선택지)
  const width = el('select', { title: 'Viewer 모드 툴패스 선 굵기 (기본 90% = 이전 버전 굵기)' });
  for (const pct of LINE_WIDTH_STEPS) {
    const px = toolpathLineWidth(CUT_LINE_BASE_WIDTH, pct).toFixed(1);
    width.append(new Option(`${'▬'.repeat(Math.max(1, Math.round(Number(px))))} ${pct}%${pct === LINE_WIDTH_DEFAULT_PCT ? '  (기본)' : ''}`, String(pct)));
  }
  row('툴패스 선 굵기', width);

  const slider = (min: number, max: number): HTMLInputElement => el('input', { type: 'range', min: String(min), max: String(max), step: '1' });
  const sens = slider(SENSITIVITY_MIN, SENSITIVITY_MAX);
  const sensVal = el('output');
  const cube = slider(CUBE_MIN, CUBE_MAX);
  const cubeVal = el('output');
  const fov = slider(FOV_MIN, FOV_MAX);
  const fovVal = el('output');
  row('감도', sens, sensVal);
  row('방향 큐브 크기', cube, cubeVal);
  row('시야각 (FOV)', fov, fovVal);

  const paint = (): void => {
    const v = getViewerSettings();
    width.value = String(v.lineWidthPct);
    sens.value = String(v.sensitivityPct);
    cube.value = String(v.cubeSizePx);
    fov.value = String(v.fovDeg);
    sensVal.textContent = `${v.sensitivityPct}%`;
    cubeVal.textContent = `${v.cubeSizePx}px`;
    fovVal.textContent = `${v.fovDeg}°`;
  };
  paint();
  void s;
  width.addEventListener('change', () => { updateViewerSettings({ lineWidthPct: Number(width.value) }); paint(); });
  sens.addEventListener('input', () => { updateViewerSettings({ sensitivityPct: Number(sens.value) }); paint(); });
  cube.addEventListener('input', () => { updateViewerSettings({ cubeSizePx: Number(cube.value) }); paint(); });
  fov.addEventListener('input', () => { updateViewerSettings({ fovDeg: Number(fov.value) }); paint(); });
  body.append(group);
  if (extras.hideTopBar) {
    const screen = el('fieldset');
    const sl = el('legend');
    sl.textContent = '화면';
    screen.append(sl);
    const row2 = el('label', { class: 'settings-row' });
    const box = el('input', { type: 'checkbox' });
    box.checked = extras.hideTopBar.get();
    box.addEventListener('change', () => extras.hideTopBar?.set(box.checked));
    const text = el('span');
    text.textContent = '상단바 숨김 기능 사용 (숨김 버튼, Ctrl+H)';
    row2.append(box, text);
    screen.append(row2);
    body.append(screen);
  }
  if (extras.exportStore || extras.importStore) {
    const data = el('fieldset');
    const dl = el('legend');
    dl.textContent = '선반 스펙 저장소 (직접 입력한 INSERT/홀더 값)';
    data.append(dl);
    const line = el('div', { class: 'settings-row' });
    const ex = el('button', { type: 'button' });
    ex.textContent = '내보내기';
    ex.addEventListener('click', () => extras.exportStore?.());
    const im = el('button', { type: 'button' });
    im.textContent = '가져오기';
    im.addEventListener('click', () => extras.importStore?.());
    line.append(ex, im);
    data.append(line);
    body.append(data);
  }

  const foot = el('div', { class: 'dlg-foot' });
  const reset = el('button', { type: 'button' });
  reset.textContent = '기본값으로';
  reset.addEventListener('click', () => { resetViewerSettings(); paint(); });
  const close = el('button', { type: 'button', class: 'primary' });
  close.textContent = '닫기';
  close.addEventListener('click', () => dlg.close());
  foot.append(reset, close);
  dlg.append(head, body, foot);
  dlg.addEventListener('close', () => { dlg.remove(); open = null; });
  document.body.append(dlg);
  dlg.showModal(); // 가운데 팝업(뒤 화면은 투명 배경이라 슬라이더 변화를 볼 수 있다)
  open = dlg;
  void CUBE_DEFAULT;
}
