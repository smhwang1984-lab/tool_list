// Sum Path Android — P0 앱 뼈대.
// 원본 v2.2.8 화면 배치(제목 줄 / 툴바 / 프로그램 입력 │ 툴리스트·Viewer)를 그대로 잡아 두고,
// 기능은 P1~P5에서 채운다. 아직 동작하지 않는 버튼은 비활성으로 둔다.
import './styles.css';
import { APP_NAME, APP_VERSION } from './version';
import { applyTheme, type ThemeName } from './theme';
import { icon } from './icons';
import { EXAMPLE } from './example';
import { getPref, getPrefNumber, loadPrefs, setPref } from './platform/prefs';
import { confirmDialog, el, installLongPressHints, showDialog, toast } from './ui/dialog';
import { createEditor } from './ui/editor';
import { createSearchBar } from './ui/searchBar';

type Mode = 'tool' | 'viewer';
type Tab = 'program' | Mode;

function toolButton(label: string, iconName: string, title: string, opts: { accent?: boolean; disabled?: boolean } = {}) {
  const b = el('button', { class: 'tool-btn' + (opts.accent ? ' accent' : ''), title, type: 'button' },
    icon(iconName) + `<span>${label}</span>`);
  if (opts.disabled) b.disabled = true;
  return b;
}

function group(...buttons: HTMLElement[]): HTMLElement {
  const g = el('div', { class: 'tb-group' });
  g.append(...buttons);
  return g;
}

const HELP_TEXT = [
  '■ 이 버전은 P0(앱 뼈대)입니다.',
  '  화면 배치와 다크모드, 화면 모드 전환만 동작합니다.',
  '  공구 리스트 산출(P1·P2), 파일·PDF(P3), 3D 뷰어(P4), 제스처(P5)를 차례로 채웁니다.',
  '',
  '■ 화면 배치',
  '  가로 화면: 원본과 같은 2단(프로그램 입력 │ 툴리스트·Viewer). 가운데 손잡이를 끌어 폭 조절.',
  '  폰 세로 화면: 프로그램 / 툴리스트 / Viewer 탭.',
].join('\n');

function mount(root: HTMLElement): void {
  let theme: ThemeName = getPref('theme') === 'dark' ? 'dark' : 'light';
  applyTheme(theme);

  // ---------- 제목 줄 ----------
  const topBar = el('header', { class: 'top-bar' });
  topBar.innerHTML = `<span class="title">${APP_NAME} v${APP_VERSION}</span>` +
    `<span class="caption">Android</span><span class="spacer"></span>`;
  const btnSettings = el('button', { class: 'icon-btn', title: '설정', type: 'button' }, icon('gear'));
  btnSettings.disabled = true;
  const btnHelp = el('button', { class: 'icon-btn', title: '도움말', type: 'button' }, icon('help'));
  const btnAbout = el('button', { class: 'icon-btn', title: 'About', type: 'button' }, icon('info'));
  const btnDark = el('button', { class: 'icon-btn', title: '다크모드', type: 'button' });
  const paintDark = () => { btnDark.innerHTML = icon(theme === 'dark' ? 'sun' : 'moon'); };
  paintDark();
  topBar.append(btnSettings, btnHelp, btnAbout, btnDark);

  // ---------- 툴바 (원본 순서) ----------
  const toolbar = el('nav', { class: 'main-toolbar' });
  const btnExample = toolButton('예제', 'document', '예제 프로그램 불러오기');
  const btnClear = toolButton('지우기', 'eraser', '프로그램과 공구 리스트 지우기');
  const btnTool = toolButton('툴리스트 산출', 'table', '툴리스트 산출 모드');
  const btnViewer = toolButton('Viewer', 'toolpath', 'Viewer 모드 (3D 공구 경로)');
  toolbar.append(
    group(
      toolButton('파일 열기', 'folder_open', 'NC 파일 열기', { disabled: true }),
      btnExample,
      btnClear,
    ),
    group(toolButton('편집 모드', 'pencil', '편집 모드 (비밀번호)', { disabled: true })),
    group(toolButton('Tool List', 'run', '공구 리스트 산출', { accent: true, disabled: true })),
    group(btnTool, btnViewer),
  );

  // ---------- 폰 세로 탭 ----------
  const tabs = el('div', { class: 'tabs' });
  const tabButtons: Record<Tab, HTMLButtonElement> = {
    program: el('button', { type: 'button' }, '프로그램'),
    tool: el('button', { type: 'button' }, '툴리스트'),
    viewer: el('button', { type: 'button' }, 'Viewer'),
  };
  tabs.append(tabButtons.program, tabButtons.tool, tabButtons.viewer);

  // ---------- 본문 ----------
  const body = el('main', { class: 'body' });
  const programPane = el('section', { class: 'pane program-pane' });
  programPane.innerHTML = '<div class="pane-head">① 프로그램 입력</div>';
  // 장비 타입(밀링/선반)은 T4의 장비 패널에서 정한다. 그 전까지는 밀링.
  const lathe = false;
  const editorHost = el('div', { class: 'editor-host' });
  const editor = createEditor(editorHost, {
    fontSize: getPrefNumber('editor_font_px', 14, 9, 32),
    onFontSize: (px) => setPref('editor_font_px', String(px)),
  });
  editor.setLathe(lathe);
  const searchBar = createSearchBar(editor, () => lathe);
  programPane.append(searchBar.root, editorHost);

  const splitter = el('div', { class: 'splitter', role: 'separator', 'aria-orientation': 'vertical' });

  const rightPane = el('section', { class: 'pane right-pane' });
  const toolView = el('div', { class: 'placeholder' },
    '공구 리스트<br>밀링 16열 / 선반 14열 표는 P1·P2에서 원본과 같게 산출합니다.');
  const viewerView = el('div', { class: 'viewer-host' });
  viewerView.hidden = true;
  rightPane.append(toolView, viewerView);
  body.append(programPane, splitter, rightPane);

  root.append(topBar, toolbar, tabs, body);

  // ---------- 동작 ----------
  let mode: Mode = 'tool';
  let viewerStarted = false;
  const setTab = (tab: Tab) => {
    body.dataset.tab = tab;
    for (const [k, b] of Object.entries(tabButtons)) b.classList.toggle('active', k === tab);
    if (tab !== 'program') setMode(tab);
  };
  const setMode = (next: Mode) => {
    mode = next;
    btnTool.classList.toggle('checked', mode === 'tool');
    btnViewer.classList.toggle('checked', mode === 'viewer');
    toolView.hidden = mode !== 'tool';
    viewerView.hidden = mode !== 'viewer';
    if (mode === 'viewer' && !viewerStarted) {
      viewerStarted = true;
      void import('./viewer/placeholder').then((m) => m.startPlaceholderViewer(viewerView));
    }
  };
  // 툴바의 모드 버튼은 폰 세로 화면에서 탭 전환도 겸한다(가로 화면에서는 탭이 숨어 있어 영향 없음).
  btnTool.addEventListener('click', () => setTab('tool'));
  btnViewer.addEventListener('click', () => setTab('viewer'));
  for (const [k, b] of Object.entries(tabButtons)) b.addEventListener('click', () => setTab(k as Tab));
  setMode('tool');
  setTab('program');

  btnDark.addEventListener('click', () => {
    theme = theme === 'dark' ? 'light' : 'dark';
    applyTheme(theme);
    setPref('theme', theme);
    paintDark();
  });
  btnExample.addEventListener('click', () => {
    editor.setText(EXAMPLE);
    toast('예제 프로그램을 불러왔습니다');
  });
  btnClear.addEventListener('click', async () => {
    if (editor.getText() && !(await confirmDialog('지우기', '프로그램과 공구 리스트를 지울까요?', '지우기'))) return;
    editor.setText('');
  });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'F6') { e.preventDefault(); searchBar.prevTool(); }
    if (e.key === 'F8') { e.preventDefault(); searchBar.nextTool(); }
  });
  installLongPressHints(root);
  btnHelp.addEventListener('click', () => showDialog('도움말', HELP_TEXT));
  btnAbout.addEventListener('click', () => showDialog('About', [
    `${APP_NAME} v${APP_VERSION} (Android)`,
    '만든 사람: Hwang.seonmun',
    '용도: NC 프로그램에서 공구 리스트를 산출하고 NC 경로를 Viewer로 확인하는 도구',
    '',
    '오픈소스: Capacitor, Vite, TypeScript, Three.js',
  ].join('\n')));

  // 가운데 손잡이 끌어서 폭 조절 (원본 QSplitter, 최소 폭 300px)
  splitter.addEventListener('pointerdown', (ev) => {
    splitter.setPointerCapture(ev.pointerId);
    const startX = ev.clientX;
    const startW = programPane.getBoundingClientRect().width;
    const move = (e: PointerEvent) => {
      const max = body.getBoundingClientRect().width - 320;
      const w = Math.max(300, Math.min(max, startW + e.clientX - startX));
      programPane.style.flex = `0 0 ${w}px`;
    };
    const up = () => {
      splitter.removeEventListener('pointermove', move);
      splitter.removeEventListener('pointerup', up);
      splitter.removeEventListener('pointercancel', up);
    };
    splitter.addEventListener('pointermove', move);
    splitter.addEventListener('pointerup', up);
    splitter.addEventListener('pointercancel', up);
  });
}

void loadPrefs().then(() => mount(document.getElementById('app')!));
