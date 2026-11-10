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
import { createMachinePanel } from './ui/machinePanel';
import { createToolTable } from './ui/toolTable';
import { createFilterPanel } from './ui/filterPanel';
import { showSettings } from './ui/settingsDialog';
import { showRowEditor } from './ui/rowEditor';
import { showTypeList } from './ui/typeListDialog';
import { COLUMNS, LATHE_COLUMNS, LATHE_SPEC_KEYS } from './core/columns';
import { resolveFields } from './core/latheInsertSpec';
import { type LatheRow, rowSources, setRowSources } from './core/latheParser';
import { propagateLatheSpecs, saveLatheSpecEdits } from './core/latheEdit';
import { deriveD, deriveType, type NameType } from './core/nameTypes';
import { parseProgram } from './core/millParser';
import { parseLatheProgram } from './core/latheParser';
import { parseProgramMetadata } from './core/metadata';
import { LatheSpecStore } from './core/latheSpecStore';
import { cleanNameTypes, DEFAULT_NAME_TYPES } from './core/nameTypes';
import { MACHINE_LATHE } from './core/machines';

type Mode = 'tool' | 'viewer';

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
  const btnHelp = el('button', { class: 'icon-btn', title: '도움말', type: 'button' }, icon('help'));
  const btnAbout = el('button', { class: 'icon-btn', title: 'About', type: 'button' }, icon('info'));
  const btnDark = el('button', { class: 'icon-btn', title: '다크모드', type: 'button' });
  const paintDark = () => { btnDark.innerHTML = icon(theme === 'dark' ? 'sun' : 'moon'); };
  paintDark();
  topBar.append(btnSettings, btnHelp, btnAbout, btnDark);

  // ---------- 툴바 (원본 순서) ----------
  const toolbar = el('nav', { class: 'main-toolbar' });
  const btnRun = toolButton('Tool List', 'run', '공구 리스트 산출', { accent: true });
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
    group(btnRun),
    group(btnTool, btnViewer),
  );

  // ---------- 본문 ----------
  const body = el('main', { class: 'body' });
  const programPane = el('section', { class: 'pane program-pane' });
  programPane.innerHTML = '<div class="pane-head">① 프로그램 입력</div>';
  const editorHost = el('div', { class: 'editor-host' });
  const editor = createEditor(editorHost, {
    fontSize: getPrefNumber('editor_font_px', 14, 9, 32),
    onFontSize: (px) => setPref('editor_font_px', String(px)),
  });
  // 장비 타입(밀링/선반)이 공구 교체 기준·표 양식·색칠 기준을 정한다(원본 is_lathe_program).
  const machinePanel = createMachinePanel(() => {
    editor.setLathe(isLathe());
    syncTableModeToMachine();
  });
  const isLathe = (): boolean => machinePanel.isLathe();
  editor.setLathe(isLathe());
  const searchBar = createSearchBar(editor, isLathe);
  const filterPanel = createFilterPanel();
  const vSplitter = el('div', { class: 'vsplitter', role: 'separator', 'aria-orientation': 'horizontal' });
  programPane.append(machinePanel.root, searchBar.root, editorHost, vSplitter, filterPanel.root);
  const setFilterHeight = (h: number): void => {
    filterPanel.root.style.flex = `0 0 ${h}px`;
  };
  setFilterHeight(getPrefNumber('filter_height_px', window.innerHeight <= 520 ? 110 : 190, 70, 2000));
  vSplitter.addEventListener('pointerdown', (ev) => {
    vSplitter.setPointerCapture(ev.pointerId);
    const startY = ev.clientY;
    const startH = filterPanel.root.getBoundingClientRect().height;
    const move = (e: PointerEvent): void => {
      const room = programPane.getBoundingClientRect().height - 160;
      setFilterHeight(Math.max(70, Math.min(room, startH - (e.clientY - startY))));
    };
    const up = (): void => {
      vSplitter.removeEventListener('pointermove', move);
      vSplitter.removeEventListener('pointerup', up);
      vSplitter.removeEventListener('pointercancel', up);
      setPref('filter_height_px', String(Math.round(filterPanel.root.getBoundingClientRect().height)));
    };
    vSplitter.addEventListener('pointermove', move);
    vSplitter.addEventListener('pointerup', up);
    vSplitter.addEventListener('pointercancel', up);
  });

  const splitter = el('div', { class: 'splitter', role: 'separator', 'aria-orientation': 'vertical' });

  const rightPane = el('section', { class: 'pane right-pane' });
  const toolTable = createToolTable();
  const toolView = toolTable.root;
  const viewerView = el('div', { class: 'viewer-host' });
  viewerView.hidden = true;
  rightPane.append(toolView, viewerView);
  body.append(programPane, splitter, rightPane);

  root.append(topBar, toolbar, body);

  // ---------- 산출 ----------
  const storeJson = getPref('lathe_store');
  const lathe_store = storeJson ? new LatheSpecStore(storeJson) : new LatheSpecStore();
  const saveStore = (): void => setPref('lathe_store', JSON.stringify(lathe_store.toJson()));
  const loadNameTypes = (): NameType[] => {
    try {
      const saved = JSON.parse(getPref('name_types')) as unknown;
      if (Array.isArray(saved)) return cleanNameTypes(saved);
    } catch {
      /* 기본값 */
    }
    return DEFAULT_NAME_TYPES.map(([a, b]) => [a, b] as NameType);
  };
  const nameTypes: NameType[] = loadNameTypes();
  const saveNameTypes = (): void => setPref('name_types', JSON.stringify(nameTypes.map(([name, type]) => ({ name, type }))));
  let lastMct = getPref('last_mct_machine_type');
  const run = (): void => {
    const text = editor.getText();
    const lathe = isLathe();
    const rows = lathe ? parseLatheProgram(text, lathe_store) : parseProgram(text, nameTypes, false);
    toolTable.setRows(rows, lathe, parseProgramMetadata(text));
  };
  /** 장비가 바뀌면 표 양식이 달라지므로 비우고(원본과 같다), 이미 산출한 적이 있으면 다시 산출한다. */
  let hasRun = false;
  const syncTableModeToMachine = (): void => {
    if (!isLathe()) {
      lastMct = machinePanel.machineType();
      setPref('last_mct_machine_type', lastMct);
    }
    toolTable.setMode(isLathe());
    if (hasRun) run();
    else toolTable.clear();
  };
  toolTable.onModeChange = (wantLathe) => {
    if (wantLathe === isLathe()) return;
    const types = machinePanel.machineTypes();
    const target = wantLathe
      ? types.find((n) => n === MACHINE_LATHE) ?? types.find((n) => n.includes('선반'))
      : (lastMct && types.includes(lastMct) && !lastMct.includes('선반') ? lastMct : types.find((n) => !n.includes('선반')));
    if (target) machinePanel.setMachineType(target);
    hasRun = true;
    run();
  };
  // ---------- 행 편집 (삭제 / 수정 / 행 추가 / 이름 경우의 수) ----------
  const activeColumns = () => (isLathe() ? LATHE_COLUMNS : COLUMNS);
  const textOf = (row: Record<string, unknown>): Record<string, string> =>
    Object.fromEntries(activeColumns().map(([key]) => [key, row[key] === undefined || Array.isArray(row[key]) ? '' : String(row[key])]));
  const nextToolNo = (): string => {
    if (isLathe()) return '';
    let max = 0;
    for (const row of toolTable.rows()) {
      const m = /^T?(\d+)$/i.exec(String(row.NO ?? '').trim());
      if (m) max = Math.max(max, Number(m[1]));
    }
    return 'T' + String(max + 1).padStart(2, '0');
  };
  const openEditor = (index: number | null): void => {
    const lathe = isLathe();
    const old = index === null ? null : toolTable.rows()[index]!;
    const values = old ? textOf(old) : { ...Object.fromEntries(activeColumns().map(([k]) => [k, ''])), NO: nextToolNo() };
    const sources = old && lathe ? { ...(rowSources(old) ?? {}) } as Record<string, string> : undefined;
    showRowEditor({
      lathe, editing: index !== null, values, sources,
      onSave: (edited) => {
        if ('TYPE' in edited && !edited.TYPE && edited.NAME) edited.TYPE = deriveType(edited.NAME, nameTypes);
        if ('D' in edited && !edited.D && edited.NAME) edited.D = deriveD(edited.NAME);
        if (!lathe) {
          const next: Record<string, unknown> = { ...(old ?? {}), ...edited };
          delete next.SO_ALERT; // 표 SO와 주석 SO를 다시 비교한다
          if (old && String(old.NO ?? '') !== edited.NO) delete next.NO_ALERT;
          toolTable.putRow(index, next);
          return;
        }
        const row = { ...edited } as LatheRow;
        const baseline: Record<string, string> = { ...values };
        const rowSrc: Record<string, string> = index === null ? {} : { ...(sources ?? {}) };
        if (index === null) {
          const [resolved, resolvedSources] = resolveFields(row.INSERT ?? '', row.HOLDER ?? '', null, null, lathe_store);
          for (const key of LATHE_SPEC_KEYS) {
            const r = (resolved as unknown as Record<string, string>)[key];
            if (!row[key] && r) {
              row[key] = r;
              rowSrc[key] = (resolvedSources as unknown as Record<string, string>)[key] ?? '';
              baseline[key] = r;
            }
          }
        }
        const result = saveLatheSpecEdits(baseline, row, rowSrc, lathe_store);
        setRowSources(row, rowSrc as never);
        const at = toolTable.putRow(index, row);
        const touched = propagateLatheSpecs(toolTable.rows() as LatheRow[], at, values, row, rowSrc, result.changed);
        if (result.storeChanged) saveStore();
        if (touched.length) toolTable.refresh();
        if (result.notice) toolTable.flash(result.notice, 6000);
      },
    });
  };
  toolTable.onEdit = (i) => openEditor(i);
  toolTable.onAdd = () => openEditor(null);
  toolTable.onEditButton = () => {
    const sel = toolTable.selected();
    if (!sel.length) toast('수정할 행을 먼저 선택하세요.');
    else openEditor(sel[0]!);
  };
  toolTable.onDelete = async () => {
    const sel = toolTable.selected();
    if (!sel.length) return toast('삭제할 행을 먼저 선택하세요.');
    if (await confirmDialog('행 삭제', `${sel.length}개 행을 삭제할까요?`, '삭제')) toolTable.removeRows(sel);
  };
  toolTable.onTypes = () => showTypeList(nameTypes, saveNameTypes);

  toolTable.setMode(isLathe());
  btnRun.addEventListener('click', () => {
    hasRun = true;
    run();
    setMode('tool');
    toast(`공구 ${toolTable.rows().length}개`);
  });

  // ---------- 동작 ----------
  let mode: Mode = 'tool';
  let viewerStarted = false;
  const setMode = (next: Mode) => {
    mode = next;
    btnTool.classList.toggle('checked', mode === 'tool');
    btnViewer.classList.toggle('checked', mode === 'viewer');
    toolView.hidden = mode !== 'tool';
    viewerView.hidden = mode !== 'viewer';
    vSplitter.hidden = mode !== 'viewer';
    filterPanel.root.hidden = mode !== 'viewer'; // 필터 영역은 Viewer 모드에서만 (원본과 같다)
    machinePanel.root.hidden = mode !== 'viewer'; // 원본: 산출 모드에서는 장비 패널을 숨기고 표 위 콤보를 쓴다
    if (mode === 'viewer' && !viewerStarted) {
      viewerStarted = true;
      void import('./viewer/placeholder').then((m) => m.startPlaceholderViewer(viewerView));
    }
  };
  btnTool.addEventListener('click', () => setMode('tool'));
  btnViewer.addEventListener('click', () => setMode('viewer'));
  setMode('tool');

  btnDark.addEventListener('click', () => {
    theme = theme === 'dark' ? 'light' : 'dark';
    applyTheme(theme);
    setPref('theme', theme);
    paintDark();
  });
  btnExample.addEventListener('click', () => {
    editor.setText(EXAMPLE);
    hasRun = true;
    run();
    toast('예제 프로그램을 불러왔습니다');
  });
  btnClear.addEventListener('click', async () => {
    if (editor.getText() && !(await confirmDialog('지우기', '프로그램과 공구 리스트를 지울까요?', '지우기'))) return;
    editor.setText('');
    toolTable.clear();
  });
  window.addEventListener('keydown', (e) => {
    if (e.key === 'F6') { e.preventDefault(); searchBar.prevTool(); }
    if (e.key === 'F8') { e.preventDefault(); searchBar.nextTool(); }
  });
  installLongPressHints(root);
  btnSettings.addEventListener('click', showSettings);
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
