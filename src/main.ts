// Sum Path Android — P0 앱 뼈대.
// 원본 v2.2.8 화면 배치(제목 줄 / 툴바 / 프로그램 입력 │ 툴리스트·Viewer)를 그대로 잡아 두고,
// 기능은 P1~P5에서 채운다. 아직 동작하지 않는 버튼은 비활성으로 둔다.
import './styles.css';
import { APP_NAME, APP_VERSION } from './version';
import { applyTheme, type ThemeName } from './theme';
import { icon } from './icons';
import { EXAMPLE } from './example';
import { getPref, getPrefNumber, loadPrefs, setPref } from './platform/prefs';
import { alertDialog, confirmDialog, el, installLongPressHints, showDialog, toast } from './ui/dialog';
import { createEditor } from './ui/editor';
import { createSearchBar } from './ui/searchBar';
import { createMachinePanel } from './ui/machinePanel';
import { showStockDialog } from './ui/stockDialog';
import { buildSimProgram, toolpathBounds } from './sim/segments';
import { toolShapeMapFromRows } from './sim/toolShape';
import { createFallback2D } from './viewer/canvas2d';
import { buildLatheProgram, latheToolpathExtent, type LatheProgram } from './sim/latheSegments';
import { geometryMapFromRows } from './core/latheInsertSpec';
import { showLatheStockDialog } from './ui/latheStockDialog';
import { createToolTable } from './ui/toolTable';
import { createFilterPanel } from './ui/filterPanel';
import { createDocumentController } from './app/documentController';
import { onIncoming } from './platform/files';
import { setLatheG80Rapid, toolpathFromText } from './core/toolpath';
setLatheG80Rapid(true);
import { latheToolNameMapFromRows } from './core/latheParser';
import { toolNameMapFromRows } from './core/millParser';
import { cssColor, toolColorForIndex, toolDisplayText } from './viewer/segments';
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
  '■ 화면 (가로 전용)',
  '  제목 줄 오른쪽: 설정 / 도움말 / About / 다크모드.',
  '  툴바: [파일 열기 · 예제 · 지우기] [편집 모드] [Tool List] [툴리스트 산출 · Viewer].',
  '  버튼을 길게 누르면 설명이 나옵니다. 가운데 손잡이를 끌어 폭을 조절합니다.',
  '',
  '■ 파일',
  '  파일 열기: 저장소에서 NC 파일을 고릅니다(UTF-8·CP949 자동 판별).',
  '  다른 앱(파일 앱·메일·메신저)에서 NC 파일을 "Sum Path로 열기"/공유해도 열립니다.',
  '  앱으로 돌아왔을 때 파일이 바뀌었으면 새로고침할지 묻습니다.',
  '',
  '■ 편집 모드',
  '  앱은 항상 읽기 모드로 시작합니다. 편집 모드 → 비밀번호(기본 1234) → 프로그램을 직접 고칠 수 있고',
  '  고친 내용은 잠시 뒤 공구 리스트와 경로에 반영됩니다. 저장은 원래 인코딩·줄바꿈을 유지하며',
  '  기존 내용을 앱 폴더(Android/data/com.sumpath.nctoollist/files/backup)에 .bak로 남깁니다.',
  '',
  '■ 공구 리스트',
  '  Tool List 버튼으로 산출합니다. 행을 두 번 탭하거나 길게 누르면 수정합니다.',
  '  삭제 / 수정 / 행 추가 / 이름 경우의 수 / 복사(엑셀 붙여넣기) / PDF(저장 위치 선택).',
  '',
  '■ 3D Viewer 손동작',
  '  한 손가락 드래그: 회전   두 손가락 드래그: 이동   핀치: 확대·축소',
  '  두 번 탭: 전체 맞춤   두 번 탭 후 누른 채 위아래로 끌기: 연속 확대·축소',
  '  세 손가락 위아래: 원근감(FOV)',
  '  길게 누른 뒤(0.4초) 끌기: 사각형 영역 확대 → 위치 찍기 모드가 켜집니다.',
  '  위치 찍기(과녁 모양) 버튼(또는 영역 확대 뒤)에서 경로를 탭하면 가장 가까운 선의 프로그램 줄로 이동합니다.',
  '  방향 큐브의 면을 탭하면 해당 방향으로 바뀝니다. 뒤로 버튼으로 위치 찍기를 끝냅니다.',
  '',
  '■ 재생 (PG 매칭)',
  '  ▶ 재생/정지, ↺ 처음으로, ⏮⏭ 이전/다음 공정, 속도 1x~5000x, 막대를 끌어 위치 이동.',
  '  텍스트 정지 / 정지(M00) / 옵션정지(M01)에서 자동으로 멈춥니다.',
  '  "PG 매칭"을 켜면 전체 경로를 지우고, 입력창 커서가 있는 공정만 커서 위치까지 그립니다(재생·방향키 연동).',
  '',
  '■ 소재와 가공 형상 (밀링)',
  '  툴바 "소재" 단추 → 치수(T/W/L)·축·기준 위치·해상도를 정하고 적용하면 깎인 모양이 보입니다.',
  '  프로그램 위쪽 주석 (STOCK SIZE : T50 W95 L385) 이 있으면 치수를 자동으로 읽습니다.',
  '  "실시간 형상"을 켜면 재생·커서 위치까지, 끄면 선택한 공정의 끝까지 깎습니다.',
  '  경사면·5축처럼 공구 축이 기운 이동이 있으면 3D 복셀로 깎습니다(자동 해상도는 거칠 수 있음). 선반 소재는 다음 단계입니다.',
  '',
  '■ 공정 필터',
  '  목록에서 공정을 여러 개 골라 표시합니다. 전체 / 해제 / Reset.',
  '',
  '■ 입력창',
  '  두 손가락 핀치로 글자 크기를 바꿉니다(저장됨). 읽기 모드에서 입력창을 탭하면 장비 설정 패널이 접힙니다.',
  '',
  '■ 키보드(블루투스)',
  '  F5 처음으로(Viewer)  F6 이전 공구/공정  F7 재생·정지  F8 다음 공구/공정  Ctrl+S 저장(편집 모드)',
  '',
  '■ 설정',
  '  툴패스 선 굵기·감도·방향 큐브 크기·FOV, 선반 스펙 저장소 내보내기/가져오기.',
  '',
  '■ 안드로이드 뒤로 버튼',
  '  위치 찍기 종료 → 열린 창 닫기 → Tool List 화면으로 → 종료 확인 순서입니다.',
].join('\n');

function mount(root: HTMLElement): void {
  let theme: ThemeName = getPref('theme') === 'dark' ? 'dark' : 'light';
  applyTheme(theme);

  // ---------- 제목 줄 ----------
  const topBar = el('header', { class: 'top-bar' });
  topBar.innerHTML = `<span class="title">${APP_NAME}</span><span class="ver">v${APP_VERSION}</span>` +
    `<span class="caption" id="file-caption">Android</span><span class="spacer"></span>`;
  const btnSettings = el('button', { class: 'icon-btn', title: '설정', type: 'button' }, icon('gear'));
  const btnHelp = el('button', { class: 'icon-btn', title: '도움말', type: 'button' }, icon('help'));
  const btnAbout = el('button', { class: 'icon-btn', title: 'About', type: 'button' }, icon('info'));
  const btnDark = el('button', { class: 'icon-btn', title: '다크모드', type: 'button' });
  const paintDark = () => { btnDark.innerHTML = icon(theme === 'dark' ? 'sun' : 'moon'); };
  paintDark();
  topBar.append(btnSettings, btnHelp, btnAbout, btnDark);

  // ---------- 툴바 (원본 순서) ----------
  const toolbar = el('nav', { class: 'main-toolbar' });
  const btnOpen = toolButton('파일 열기', 'folder_open', 'NC 파일 열기');
  const btnEdit = toolButton('편집 모드', 'pencil', '편집 모드 (비밀번호)');
  const btnEditSave = toolButton('저장', 'save', '편집 내용을 파일에 저장 (원래 인코딩·줄바꿈 유지)');
  const btnEditPw = toolButton('비밀번호', 'key', '편집 모드 비밀번호 변경');
  const editLabel = el('span', { class: 'edit-label' });
  editLabel.innerHTML = `${icon('pencil')}<span>편집 중</span>`;
  btnEditSave.hidden = true;
  btnEditPw.hidden = true;
  editLabel.hidden = true;
  const btnMachine = toolButton('장비', 'gear', '장비 타입 및 스펙 설정');
  const btnStop = toolButton('정지 옵션', 'run', '텍스트 정지 · 정지 · 옵션정지 · 실시간 형상');
  const btnStockTb = toolButton('소재', 'document', '소재(STOCK) 설정과 가공 형상 시뮬레이션');
  const btnStockClear = toolButton('소재 지우기', 'eraser', '소재와 가공 형상을 지우고 툴패스 선을 다시 보이게 합니다');
  btnStockClear.disabled = true;
  const btnStl = toolButton('STL', 'save', '지금 보이는 가공 형상을 STL 파일로 내보내기');
  btnStl.disabled = true;
  const btnRun = toolButton('Tool List', 'run', '공구 리스트 산출', { accent: true });
  const btnExample = toolButton('예제', 'document', '예제 프로그램 불러오기');
  const btnClear = toolButton('지우기', 'eraser', '프로그램과 공구 리스트 지우기');
  const btnTool = toolButton('툴리스트 산출', 'table', '툴리스트 산출 모드');
  const btnViewer = toolButton('Viewer', 'toolpath', 'Viewer 모드 (3D 공구 경로)');
  toolbar.append(
    group(
      btnOpen,
      btnExample,
      btnClear,
    ),
    group(btnMachine, btnStop, btnStockTb, btnStockClear, btnStl),
    group(btnEdit, btnEditSave, btnEditPw, editLabel),
    group(btnRun),
    group(btnTool, btnViewer),
  );

  // ---------- 3D 뷰어 상태 (본문보다 먼저 선언) ----------
  let viewer: import('./viewer/viewer').Viewer | null = null;
  let fallback2d: import('./viewer/canvas2d').Fallback2D | null = null;
  let viewerLoading: Promise<void> | null = null;
  let viewerStale = true;
  let pgMatchOn = false;
  let viewerTimer = 0;
  let lastResult: import('./core/toolpath').ToolpathResult | null = null;
  const scheduleViewerRefresh = (): void => {
    window.clearTimeout(viewerTimer);
    viewerTimer = window.setTimeout(() => { if (mode === 'viewer') refreshViewer(); }, 350);
  };

  // ---------- 본문 ----------
  const body = el('main', { class: 'body' });
  const programPane = el('section', { class: 'pane program-pane' });
  programPane.innerHTML = '<div class="pane-head">프로그램 입력</div>';
  const editorHost = el('div', { class: 'editor-host' });
  const editor = createEditor(editorHost, {
    fontSize: getPrefNumber('editor_font_px', 9, 9, 32),
    onFontSize: (px) => setPref('editor_font_px', String(px)),
    onChange: () => { viewerStale = true; scheduleViewerRefresh(); },
  });
  // 장비 타입(밀링/선반)이 공구 교체 기준·표 양식·색칠 기준을 정한다(원본 is_lathe_program).
  const machinePanel = createMachinePanel(() => {
    editor.setLathe(isLathe());
    syncTableModeToMachine();
    viewerStale = true;
    scheduleViewerRefresh();
  });
  const isLathe = (): boolean => machinePanel.isLathe();
  editor.setLathe(isLathe());
  const searchBar = createSearchBar(editor, isLathe);
  const filterPanel = createFilterPanel();
  const vSplitter = el('div', { class: 'vsplitter', role: 'separator', 'aria-orientation': 'horizontal' });
  programPane.append(searchBar.root, editorHost, vSplitter, filterPanel.root);
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

  toolTable.onPdf = async () => {
    if (!toolTable.rows().length) return toast('먼저 공구 리스트를 생성하세요.');
    toast('PDF를 만드는 중...');
    try {
      const { makeToolListPdf } = await import('./platform/pdf');
      const { openPdf, saveAs } = await import('./platform/files');
      const { bytes, filename } = await makeToolListPdf(toolTable.rows(), toolTable.metadata(), toolTable.isLathe());
      // PDF 를 먼저 띄운다 — 저장·공유는 사용자가 PDF 앱에서 정한다. PDF 앱이 없으면 저장 위치를 묻는다.
      if (!(await openPdf(filename, bytes))) {
        const saved = await saveAs(filename, bytes);
        if (saved) toast(`PDF를 저장했습니다: ${saved.name}`);
      }
    } catch (error) {
      await alertDialog('PDF 실패', String((error as Error).message ?? error));
    }
  };
  toolTable.setMode(isLathe());
  btnRun.addEventListener('click', () => {
    hasRun = true;
    run();
    setMode('tool');
    toast(`공구 ${toolTable.rows().length}개`);
  });

  // ---------- 동작 ----------
  let lastLatheProgram: LatheProgram | null = null;
  let mode: Mode = 'tool';
  const ensureViewer = (): Promise<void> => {
    viewerLoading ??= import('./viewer/viewer').then((m) => {
      viewer = m.createViewer(viewerView, {
        onLine: (line) => { if (pgMatchOn) editor.selectLine(line); },
        onPick: (line) => editor.selectLine(line),
        stopRule: () => {
          const o = filterPanel.stopOptions();
          return { text: o.stopText, textValue: o.stopTextValue, m00: o.stopM00, m01: o.stopM01 };
        },
        lineText: (line) => editor.view.state.doc.line(Math.min(editor.view.state.doc.lines, line + 1)).text,
        onWebglFailed: (msg) => { fallback2d = createFallback2D(viewerView, msg); },
        onSimChange: () => { const has = !!viewer?.simStatus().hasStock; btnStockClear.disabled = !has; btnStl.disabled = !has; },
      });
      viewer?.setSimLive(filterPanel.liveOn());
      viewer?.setPgMatch(pgMatchOn);
      viewer?.setToolpathVisible(getPref('sim_toolpath_visible') !== '0');
    });
    return viewerLoading;
  };
  /** Viewer 를 현재 프로그램·장비로 다시 계산해 그린다 */
  const refreshViewer = (): void => {
    if (!viewer && fallback2d && viewerStale) {
      viewerStale = false;
      const text = editor.getText();
      const mt = machinePanel.machineType();
      fallback2d.draw(text.trim() ? toolpathFromText(text, mt, machinePanel.spec(mt)) : null, machinePanel.isLathe());
      return;
    }
    if (!viewer || !viewerStale) return;
    viewerStale = false;
    const text = editor.getText();
    const mt = machinePanel.machineType();
    if (!text.trim()) {
      viewer.setProgram(null, mt);
      viewer.setSimProgram(null, null);
      lastResult = null;
      filterPanel.setItems([]);
      return;
    }
    const res = toolpathFromText(text, mt, machinePanel.spec(mt));
    const rows = toolTable.rows();
    const names = machinePanel.isLathe() ? latheToolNameMapFromRows(rows) : toolNameMapFromRows(rows);
    viewer.setToolValues(machinePanel.isLathe() ? null : toolShapeMapFromRows(rows));
    viewer.setProgram(res, mt);
    lastResult = res;
    if (machinePanel.isLathe()) {
      const geometry = geometryMapFromRows(rows);
      lastLatheProgram = buildLatheProgram(res, geometry);
      viewer.setSimProgram(lastLatheProgram, { kind: 'lathe', res, geometry });
    } else {
      lastLatheProgram = null;
      const shapes = toolShapeMapFromRows(rows);
      viewer.setSimProgram(buildSimProgram(res, shapes), { kind: 'mill', res, shapes });
    }
    // v2.4.7: 일부 공정만 골라 보던 중에 다시 그리면 그 선택을 지킨다(전체/없음이면 전체)
    const before = filterPanel.selectedKeys();
    const partial = before.length > 0 && before.length < filterPanel.itemCount();
    filterPanel.setItems([...res.tool_paths.keys()].map((key, i) => ({
      key, label: toolDisplayText(res, key, names), color: cssColor(toolColorForIndex(i)),
    })), partial);
    viewer.setVisible(partial ? filterPanel.selectedKeys() : null);
  };
  filterPanel.onLive = (on) => viewer?.setSimLive(on);
  /** 소재를 지우면 숨겨 둔 툴패스 선을 자동으로 다시 보이게 한다 */
  const clearStock = (): void => {
    viewer?.applyStock(null, null, false);
    setPref('sim_toolpath_visible', '1');
    viewer?.setToolpathVisible(true);
    btnStockClear.disabled = true;
    btnStl.disabled = true;
    toast('소재를 지웠습니다. 툴패스 선을 다시 표시합니다.');
  };
  btnStockClear.addEventListener('click', clearStock);
  btnStl.addEventListener('click', () => {
    const bytes = viewer?.exportStl();
    if (!bytes) { toast('내보낼 가공 형상이 없습니다. 소재를 적용하고 가공 형상을 표시하세요.'); return; }
    void import('./platform/files').then(async ({ saveAs }) => {
      const saved = await saveAs('sumpath_shape.stl', bytes);
      if (saved) toast('STL 파일을 저장했습니다.');
    });
  });
  btnStockTb.addEventListener('click', () => {
    void ensureViewer().then(() => {
      viewerStale = true;
      refreshViewer();
      if (machinePanel.isLathe()) {
        showLatheStockDialog({
          extent: () => (lastResult ? latheToolpathExtent(lastResult) : null),
          apply: (spec, res, enabled) => { viewer?.applyStock(spec.bounds(), res, enabled); },
          clear: clearStock,
          status: () => viewer!.simStatus(),
          setToolpathVisible: (on) => viewer?.setToolpathVisible(on),
          excludedWhy: () => lastLatheProgram?.excludedWhy ?? {},
          info: () => lastLatheProgram,
        });
        return;
      }
      showStockDialog({
        lines: () => editor.getText().split(/\r\n|\r|\n/),
        toolpathBounds: (margin) => (lastResult ? toolpathBounds(lastResult, margin) : null),
        apply: (spec, res, enabled) => { viewer?.applyStock(spec.bounds(), res, enabled); },
        clear: clearStock,
        status: () => viewer!.simStatus(),
        gotoLine: (line) => editor.selectLine(line),
        setToolpathVisible: (on) => viewer?.setToolpathVisible(on),
      });
    });
  });
  const setMode = (next: Mode) => {
    mode = next;
    btnTool.classList.toggle('checked', mode === 'tool');
    btnViewer.classList.toggle('checked', mode === 'viewer');
    toolView.hidden = mode !== 'tool';
    viewerView.hidden = mode !== 'viewer';
    vSplitter.hidden = mode !== 'viewer';
    filterPanel.root.hidden = mode !== 'viewer'; // 필터 영역은 Viewer 모드에서만 (원본과 같다)
    if (mode === 'viewer') void ensureViewer().then(() => refreshViewer());
  };
  // ---------- 툴바 드롭다운 (장비 설정 / 정지 옵션) ----------
  let openPopover: HTMLElement | null = null;
  const attachPopover = (button: HTMLElement, content: HTMLElement): void => {
    const pop = el('div', { class: 'popover' });
    pop.hidden = true;
    pop.append(content);
    document.body.append(pop);
    button.addEventListener('click', (ev) => {
      ev.stopPropagation();
      const show = pop.hidden;
      if (openPopover) openPopover.hidden = true;
      openPopover = null;
      if (show) {
        const r = button.getBoundingClientRect();
        pop.style.top = `${r.bottom + 4}px`;
        pop.style.left = `${Math.max(4, Math.min(r.left, window.innerWidth - 340))}px`;
        pop.hidden = false;
        openPopover = pop;
      }
    });
    pop.addEventListener('click', (ev) => ev.stopPropagation());
  };
  document.addEventListener('click', () => { if (openPopover) { openPopover.hidden = true; openPopover = null; } });
  machinePanel.setExpanded(true);
  machinePanel.root.classList.add('in-popover');
  attachPopover(btnMachine, machinePanel.root);
  attachPopover(btnStop, filterPanel.stopMenu);

  filterPanel.onSelectionChange = (keys) => viewer?.setVisible(keys);
  filterPanel.onActivate = (key) => { const line = lastResult?.process_first_line.get(key); if (line !== undefined) editor.selectLine(line); };
  filterPanel.onReset = () => viewer?.reset();
  filterPanel.onPgMatch = (on) => { pgMatchOn = on; viewer?.setPgMatch(on); if (on) viewer?.setLine(editor.view.state.doc.lineAt(editor.view.state.selection.main.head).number - 1); };
  editor.onCursorLine = (line) => { if (pgMatchOn) viewer?.setLine(line); };
  btnTool.addEventListener('click', () => setMode('tool'));
  btnViewer.addEventListener('click', () => setMode('viewer'));
  setMode('tool');

  btnDark.addEventListener('click', () => {
    theme = theme === 'dark' ? 'light' : 'dark';
    applyTheme(theme);
    setPref('theme', theme);
    paintDark();
  });
  // ---------- 파일·편집 ----------
  const doc = createDocumentController({
    editor,
    onTextReplaced: () => {
      if (editor.getText().trim() === '') {
        toolTable.clear();
        return;
      }
      hasRun = true;
      run();
    },
    onEditRefresh: () => {
      hasRun = true;
      run();
    },
    isTableEdited: () => toolTable.isEdited(),
    onEditModeChange: (editing) => {
      btnEdit.classList.toggle('checked', editing);
      btnEditSave.hidden = !editing;
      btnEditPw.hidden = !editing;
      editLabel.hidden = !editing;
      editorHost.classList.toggle('editing', editing);
    },
    onFileChange: (name) => {
      const caption = document.getElementById('file-caption');
      if (caption) caption.textContent = name ?? 'Android';
    },
  });
  btnOpen.addEventListener('click', () => void doc.open());
  btnEdit.addEventListener('click', () => void doc.toggleEdit());
  btnEditSave.addEventListener('click', () => void doc.save());
  btnEditPw.addEventListener('click', () => void doc.changePassword());
  btnExample.addEventListener('click', async () => {
    await doc.setPlainText(EXAMPLE);
    toast('예제 프로그램을 불러왔습니다');
  });
  btnClear.addEventListener('click', async () => {
    if (editor.getText() && !(await confirmDialog('지우기', '프로그램과 공구 리스트를 지울까요?', '지우기'))) return;
    await doc.setPlainText('');
  });
  // 다른 앱에서 "Sum Path로 열기"/공유로 받은 파일, 앱으로 돌아왔을 때 파일 변경 확인
  void doc.openIncoming();
  onIncoming(() => void doc.openIncoming());
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') void doc.checkExternalChange();
  });
  window.addEventListener('keydown', (e) => {
    const inViewer = mode === 'viewer' && viewer;
    if (e.key === 'F5' && inViewer) { e.preventDefault(); viewer!.reset(); editor.selectLine(0); }
    if (e.key === 'F6') { e.preventDefault(); if (inViewer) viewer!.jumpTool(-1); else searchBar.prevTool(); }
    if (e.key === 'F7' && inViewer) { e.preventDefault(); viewer!.togglePlay(); }
    if (e.key === 'F8') { e.preventDefault(); if (inViewer) viewer!.jumpTool(1); else searchBar.nextTool(); }
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 's' && doc.editing()) { e.preventDefault(); void doc.save(); }
  });
  installLongPressHints(root);
  // Android 뒤로 버튼: 위치 찍기 종료 → 열린 대화상자 닫기 → Tool List 화면으로 → 종료 확인
  void import('@capacitor/app').then(({ App }) => {
    void App.addListener('backButton', async () => {
      if (viewer?.cancelPick()) return;
      const dialogs = [...document.querySelectorAll<HTMLDialogElement>('dialog[open]')];
      if (dialogs.length) { dialogs[dialogs.length - 1]!.close(); return; }
      if (mode === 'viewer') { setMode('tool'); return; }
      if (await confirmDialog('종료', 'Sum Path를 종료할까요?', '종료')) void App.exitApp();
    });
  }).catch(() => undefined);
  btnSettings.addEventListener('click', () => showSettings({
    exportStore: async () => {
      const { saveAs } = await import('./platform/files');
      const bytes = new TextEncoder().encode(JSON.stringify(lathe_store.toJson(), null, 2));
      const saved = await saveAs('sumpath_lathe_specs.json', bytes);
      if (saved) toast(`내보냈습니다: ${saved.name}`);
    },
    importStore: async () => {
      const { openFile } = await import('./platform/files');
      try {
        const file = await openFile();
        if (!file) return;
        const next = new LatheSpecStore(new TextDecoder().decode(file.bytes));
        if (!(await confirmDialog('가져오기', '지금 저장된 선반 스펙을 이 파일 내용으로 바꿀까요?', '바꾸기'))) return;
        lathe_store.replaceWith(next);
        saveStore();
        if (isLathe() && hasRun) run();
        toast('가져왔습니다');
      } catch (error) {
        await alertDialog('가져오기 실패', String((error as Error).message ?? error));
      }
    },
  }));
  btnHelp.addEventListener('click', () => showDialog('도움말', HELP_TEXT));
  btnAbout.addEventListener('click', () => showDialog('About', [
    `${APP_NAME} v${APP_VERSION} (Android)`,
    '만든 사람: Hwang.seonmun',
    '용도: NC 프로그램에서 공구 리스트를 산출하고 NC 경로를 Viewer로 확인하는 도구',
    '',
    '오픈소스: Capacitor, Vite, TypeScript, Three.js',
  ].join('\n')));

  {
    const saved = parseFloat(getPref('program_pane_ratio'));
    if (saved > 0.05 && saved < 0.95) programPane.style.flex = `0 0 ${(saved * 100).toFixed(2)}%`;
  }
  // 가운데 손잡이 끌어서 폭 조절 (원본 QSplitter, 최소 폭 300px)
  splitter.addEventListener('pointerdown', (ev) => {
    splitter.setPointerCapture(ev.pointerId);
    const startX = ev.clientX;
    const startW = programPane.getBoundingClientRect().width;
    const move = (e: PointerEvent) => {
      const max = body.getBoundingClientRect().width - 200;
      const w = Math.max(180, Math.min(max, startW + e.clientX - startX));
      programPane.style.flex = `0 0 ${w}px`;
    };
    const up = () => {
      // 마지막 분할 위치를 비율로 저장해 다음 실행에서 그대로 쓴다
      const ratio = programPane.getBoundingClientRect().width / Math.max(1, body.getBoundingClientRect().width);
      if (ratio > 0.05 && ratio < 0.95) setPref('program_pane_ratio', ratio.toFixed(4));
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
