// 공구 리스트 표 — 원본 _build_tool_panel / set_table_row / _relayout_tool_table (NC_Tool_List.py 4320~, 5432~)
// 밀링 16열 / 선반 14열. 밀링은 패널 폭에 맞춰 줄이고(하한 0.45), 선반은 줄이지 않고 가로 스크롤.
import { spindleAlertText, sameNumber, type SpindleCheck } from '../core/alerts';
import {
  COLUMNS, COL_WIDTH, LATHE_COLUMNS, LATHE_COL_WIDTH, LATHE_SPEC_KEYS, TABLE_CELL_PADDING_PX, TABLE_FONT_PT,
  TOOL_TABLE_MIN_SCALE,
} from '../core/columns';
import { describeHolder, describeInsert, SOURCE_SAVED } from '../core/latheInsertSpec';
import { rowSources } from '../core/latheParser';
import type { ProgramMetadata } from '../core/metadata';
import { RADIUS_COMP_DISPLAY_RE, RADIUS_COMP_MISMATCH_RE } from '../core/radiusComp';
import { el, toast } from './dialog';

export type TableRow = Record<string, unknown>;

const LEFT_ALIGN = new Set(['NAME', 'HOLDER', 'REMARK', 'INSERT']);
const PX_PER_PT = 96 / 72;
const FONT_FAMILY = '"Malgun Gothic", "맑은 고딕", "Noto Sans KR", sans-serif';

const LATHE_FIELD_HINTS: Record<string, string> = {
  R: '노즈 R / 코너 R (mm)',
  T: '홈 바이트 폭 (mm) — 규격을 못 찾으면 직접 입력',
  PITCH: '나사 피치 (mm)',
  KIND: '공구 종류 — 자동 추천 후 고칠 수 있습니다',
  DIR: '공구 방향: R 우수 / L 좌수 / N 중립',
  TIP: '가상 인선 번호(화면에서 X 위, Z 오른쪽 기준): 1 우상 / 2 우하 / 3 좌하 / 4 좌상 / 9 중심',
  D: '턴밀·중심 드릴 공구 지름 (mm) — 문구의 D값 자동, 없으면 직접 입력',
};

const METADATA_FIELDS: readonly [label: string, key: keyof ProgramMetadata][] = [
  ['PART NO', 'part_no'], ['OPERATION', 'operation'], ['PROGRAM', 'program'], ['RUN TIME', 'runtime'], ['DATE', 'date'],
];

export interface ToolTable {
  root: HTMLElement;
  /** 산출 모드 콤보(밀링/선반)가 바뀌었을 때 */
  onModeChange: (lathe: boolean) => void;
  /** 행을 두 번 탭하거나 길게 눌렀을 때 */
  onEdit: (rowIndex: number) => void;
  /** 표 위 버튼 */
  onDelete: () => void;
  onEditButton: () => void;
  onAdd: () => void;
  onTypes: () => void;
  withHeader(): boolean;
  /** 표에서 직접 고친 내용이 있는가(프로그램에서 다시 산출하면 사라진다) */
  isEdited(): boolean;
  /** 복사·PDF용: 현재 열 구성, 출력 정보 */
  isLathe(): boolean;
  metadata(): ProgramMetadata | null;
  /** 표를 TSV(엑셀 붙여넣기용)로 만든다. 행이 없으면 null */
  toTsv(): string | null;
  onPdf: (() => void) | null;
  /** 편집한 행을 바꿔 넣거나(index) 끝에 넣고(null) 그 행을 선택한다. 넣은 행 번호를 돌려준다. */
  putRow(index: number | null, row: TableRow): number;
  removeRows(indices: readonly number[]): void;
  /** 행 내용이 바뀌었을 때 다시 그린다(선택 유지) */
  refresh(): void;
  /** 개수 줄에 안내 문구를 잠깐 보여 준다 */
  flash(message: string, ms?: number): void;
  setMode(lathe: boolean): void;
  setRows(rows: TableRow[], lathe: boolean, metadata: ProgramMetadata): void;
  clear(): void;
  selected(): number[];
  rows(): TableRow[];
  /** 패널 폭이 바뀌었을 때 다시 맞춘다 */
  relayout(): void;
}

function cellText(row: TableRow, key: string): string {
  const value = row[key];
  return value === undefined || value === null || Array.isArray(value) ? '' : String(value);
}

/** 셀에 붙일 경고(붉은 글자 + 설명). 밀링 SO/SPINDL/NO 칸, 선반은 없음. */
function millAlert(key: string, row: TableRow): string {
  if (key === 'SO') {
    const comment = cellText(row, 'SO_CMT');
    const shown = cellText(row, 'SO').trim();
    if ('SO_ALERT' in row) return cellText(row, 'SO_ALERT');
    return comment && shown && !sameNumber(shown, comment) ? `주석 SO ${comment} / 표 SO ${shown}` : '';
  }
  if (key === 'SPINDL') {
    const checks = (Array.isArray(row.SPINDL_CHECKS) ? row.SPINDL_CHECKS : []) as SpindleCheck[];
    return spindleAlertText(checks, cellText(row, 'SPINDL').trim());
  }
  if (key === 'NO') return cellText(row, 'NO_ALERT');
  return '';
}

function latheTooltip(key: string, row: TableRow): string {
  if (key === 'INSERT') return describeInsert(cellText(row, 'INSERT'));
  if (key === 'HOLDER') return describeHolder(cellText(row, 'HOLDER'));
  if ((LATHE_SPEC_KEYS as readonly string[]).includes(key)) {
    const hint = LATHE_FIELD_HINTS[key] ?? '';
    if (cellText(row, key)) {
      const sources = (rowSources(row) ?? {}) as Record<string, string>;
      return `${hint}\n출처: ${sources[key] || SOURCE_SAVED}`;
    }
    return `${hint}\n비어 있음 — [수정]에서 입력하세요`;
  }
  return '';
}

/** "(G41)" 같은 경보정 표기만 굵게 */
function fillRemark(td: HTMLElement, text: string): void {
  const re = new RegExp(RADIUS_COMP_DISPLAY_RE.source, 'g');
  let pos = 0;
  for (const m of text.matchAll(re)) {
    td.append(document.createTextNode(text.slice(pos, m.index)));
    const b = el('b');
    b.textContent = m[0];
    if (RADIUS_COMP_MISMATCH_RE.test(m[0])) b.style.color = '#d00000';
    td.append(b);
    pos = m.index! + m[0].length;
  }
  td.append(document.createTextNode(text.slice(pos)));
}

export function createToolTable(): ToolTable {
  const root = el('div', { class: 'tool-panel' });
  const bar = el('div', { class: 'tool-bar' });
  const label = el('span', { class: 'tool-title' });
  label.textContent = '공구 리스트 (복사용)';
  const count = el('span', { class: 'tool-count' });
  count.textContent = '공구 0개';
  const modeCombo = el('select', { 'aria-label': '산출 모드', title: '산출 모드: 밀링 / 선반' });
  modeCombo.append(new Option('밀링', 'mill'), new Option('선반', 'lathe'));
  bar.append(label, count, modeCombo);
  const actions = el('div', { class: 'tool-actions' });
  const mkBtn = (text: string, title: string): HTMLButtonElement => {
    const b = el('button', { type: 'button', title });
    b.textContent = text;
    return b;
  };
  const btnDelete = mkBtn('삭제', '선택한 행 삭제');
  const btnEdit = mkBtn('수정', '선택한 행 수정 (두 번 탭)');
  const btnAdd = mkBtn('행 추가', '빈 행 추가');
  const btnTypes = mkBtn('이름 경우의 수', '공구 이름 → TYPE 변환표 편집');
  const btnCopy = mkBtn('복사', '표를 복사 (엑셀에 붙여넣기)');
  const btnPdf = mkBtn('PDF', '공구 리스트 PDF 만들기');
  const headerLabel = el('label', { class: 'with-header' });
  const headerCheck = el('input', { type: 'checkbox' });
  headerLabel.append(headerCheck, document.createTextNode(' 머리글 포함'));
  actions.append(btnDelete, btnEdit, btnAdd, btnTypes, btnCopy, btnPdf, headerLabel);
  const summary = el('div', { class: 'metadata-summary' });
  summary.textContent = '출력 정보: -';
  const scroller = el('div', { class: 'table-scroll' });
  const table = el('table', { class: 'tool-table' });
  scroller.append(table);
  const hint = el('div', { class: 'tool-hint' });
  hint.textContent = '행을 두 번 탭하거나 길게 누르면 편집할 수 있습니다. (N번호 ~ 공구 교체 사이 괄호 주석을 읽음 / 밀링 M6T, 선반 Tnn00)';
  btnCopy.addEventListener('click', async () => {
    const tsv = api.toTsv();
    if (tsv === null) return toast('먼저 공구 리스트를 생성하세요.');
    try {
      await navigator.clipboard.writeText(tsv);
      toast('복사됨! 엑셀에서 붙여넣기');
    } catch {
      toast('복사하지 못했습니다');
    }
  });
  btnPdf.addEventListener('click', () => api.onPdf?.());
  root.append(bar, actions, summary, scroller, hint);

  let lathe = false;
  let edited = false;
  let meta: ProgramMetadata | null = null;
  let data: TableRow[] = [];
  let dynamicWidths: Record<string, number> = {};
  const selected = new Set<number>();
  let measureCtx: CanvasRenderingContext2D | null = null;

  const columns = () => (lathe ? LATHE_COLUMNS : COLUMNS);
  const baseWidth = (key: string): number => (lathe ? (dynamicWidths[key] ?? LATHE_COL_WIDTH[key]) : COL_WIDTH[key]) ?? 60;
  const widthTotal = (): number => columns().reduce((sum, [key]) => sum + baseWidth(key), 0);

  /** 선반: 실제 글자 폭이 고정폭보다 넓으면 그 값을 쓴다(잘리지 않게). */
  const measureLatheWidths = (): void => {
    dynamicWidths = {};
    if (!lathe) return;
    measureCtx ??= document.createElement('canvas').getContext('2d');
    const ctx = measureCtx;
    if (!ctx) return;
    const px = TABLE_FONT_PT * PX_PER_PT;
    for (const [key, name] of LATHE_COLUMNS) {
      ctx.font = `700 ${px}px ${FONT_FAMILY}`;
      let content = ctx.measureText(name).width;
      ctx.font = `${px}px ${FONT_FAMILY}`;
      for (const row of data) {
        const text = cellText(row, key);
        if (text) content = Math.max(content, ctx.measureText(text).width + (key === 'REMARK' ? 4 : 0));
      }
      dynamicWidths[key] = Math.max(Math.ceil(content) + TABLE_CELL_PADDING_PX * 2 + 12, LATHE_COL_WIDTH[key] ?? 60);
    }
  };

  const relayout = (): void => {
    const total = widthTotal();
    const available = scroller.clientWidth;
    if (total <= 0 || available <= 0) return;
    const scale = lathe ? 1 : Math.min(1, Math.max(TOOL_TABLE_MIN_SCALE, available / total));
    table.style.fontSize = `${TABLE_FONT_PT * scale * PX_PER_PT}px`;
    const cols = columns();
    const colgroup = table.querySelector('colgroup');
    colgroup?.querySelectorAll('col').forEach((c, i) => {
      c.style.width = `${Math.max(1, Math.floor(baseWidth(cols[i]![0]) * scale))}px`;
    });
    table.style.width = `${cols.reduce((s, [key]) => s + Math.max(1, Math.floor(baseWidth(key) * scale)), 0)}px`;
  };

  const updateCount = (): void => {
    let text = `공구 ${data.length}개`;
    let sBad = 0;
    let hBad = 0;
    let bad = false;
    if (!lathe) {
      for (const row of data) {
        if (millAlert('SPINDL', row)) sBad++;
        if (millAlert('NO', row)) hBad++;
      }
      bad = sBad > 0 || hBad > 0;
      if (bad) text += ` · S값 불일치 ${sBad} · H번호 불일치 ${hBad}`;
    }
    count.textContent = text;
    count.classList.toggle('error', bad);
    count.title = bad ? '붉은 SPINDL/NO 칸을 길게 누르면 프로그램 위치(행)가 보입니다.' : '';
  };

  const paintSelection = (): void => {
    table.querySelectorAll('tbody tr').forEach((tr, i) => tr.classList.toggle('selected', selected.has(i)));
  };

  const build = (): void => {
    table.replaceChildren();
    const cols = columns();
    const colgroup = el('colgroup');
    for (let i = 0; i < cols.length; i++) colgroup.append(el('col'));
    const thead = el('thead');
    const headRow = el('tr');
    for (const [, name] of cols) {
      const th = el('th');
      th.textContent = name;
      headRow.append(th);
    }
    thead.append(headRow);
    const tbody = el('tbody');
    data.forEach((row, index) => {
      const tr = el('tr', { 'data-row': String(index) });
      for (const [key] of cols) {
        const td = el('td');
        const text = cellText(row, key);
        if (!LEFT_ALIGN.has(key)) td.classList.add('center');
        if (key === 'REMARK') fillRemark(td, text);
        else td.textContent = text;
        let tip = '';
        if (lathe) tip = latheTooltip(key, row);
        else {
          const alert = millAlert(key, row);
          if (alert) {
            td.classList.add('alert');
            tip = alert;
          }
        }
        if (tip) td.title = tip;
        tr.append(td);
      }
      tbody.append(tr);
    });
    table.append(colgroup, thead, tbody);
    paintSelection();
    relayout();
  };

  // 선택: 탭하면 한 행(이미 선택된 행을 다시 탭하면 해제), 길게 누르거나 두 번 탭하면 편집
  let pressTimer = 0;
  let longPressed = false;
  let lastTap = { row: -1, time: 0 };
  const rowOf = (target: EventTarget | null): number => {
    const tr = (target as HTMLElement | null)?.closest<HTMLElement>('tbody tr');
    return tr ? Number(tr.dataset.row) : -1;
  };
  table.addEventListener('pointerdown', (e) => {
    longPressed = false;
    const row = rowOf(e.target);
    window.clearTimeout(pressTimer);
    if (row < 0) return;
    pressTimer = window.setTimeout(() => {
      longPressed = true;
      selected.clear();
      selected.add(row);
      paintSelection();
      api.onEdit(row);
    }, 650);
  });
  for (const type of ['pointerup', 'pointercancel', 'pointermove']) {
    table.addEventListener(type, () => window.clearTimeout(pressTimer));
  }
  table.addEventListener('click', (e) => {
    const row = rowOf(e.target);
    if (row < 0 || longPressed) return;
    const now = Date.now();
    if (lastTap.row === row && now - lastTap.time < 400) {
      lastTap = { row: -1, time: 0 };
      selected.clear();
      selected.add(row);
      paintSelection();
      api.onEdit(row);
      return;
    }
    lastTap = { row, time: now };
    if (selected.has(row)) selected.delete(row);
    else selected.add(row);
    paintSelection();
  });
  btnDelete.addEventListener('click', () => api.onDelete());
  btnEdit.addEventListener('click', () => api.onEditButton());
  btnAdd.addEventListener('click', () => api.onAdd());
  btnTypes.addEventListener('click', () => api.onTypes());
  let flashTimer = 0;
  modeCombo.addEventListener('change', () => api.onModeChange(modeCombo.value === 'lathe'));
  new ResizeObserver(() => relayout()).observe(scroller);

  const api: ToolTable = {
    root,
    onModeChange: () => {},
    onEdit: () => {},
    onDelete: () => {},
    onEditButton: () => {},
    onAdd: () => {},
    onTypes: () => {},
    withHeader: () => headerCheck.checked,
    isEdited: () => edited,
    isLathe: () => lathe,
    metadata: () => meta,
    onPdf: null,
    toTsv() {
      if (!data.length) return null;
      const cols = columns();
      const cell = (v: unknown) => (v === null || v === undefined ? '' : String(v));
      const lines: string[] = [];
      if (headerCheck.checked) lines.push(cols.map(([, label]) => label).join('\t'));
      for (const row of data) lines.push(cols.map(([key]) => cell(row[key])).join('\t'));
      return lines.join('\n');
    },
    putRow(index, row) {
      edited = true;
      let at = index;
      if (at === null || at < 0 || at >= data.length) {
        data.push(row);
        at = data.length - 1;
      } else data[at] = row;
      selected.clear();
      selected.add(at);
      measureLatheWidths();
      build();
      updateCount();
      table.querySelector(`tbody tr[data-row="${at}"]`)?.scrollIntoView({ block: 'nearest' });
      return at;
    },
    removeRows(indices) {
      edited = true;
      const drop = new Set(indices);
      data = data.filter((_, i) => !drop.has(i));
      selected.clear();
      measureLatheWidths();
      build();
      updateCount();
    },
    refresh() {
      measureLatheWidths();
      build();
      updateCount();
    },
    flash(message, ms = 5000) {
      count.textContent = message;
      window.clearTimeout(flashTimer);
      flashTimer = window.setTimeout(updateCount, ms);
    },
    setMode(next) {
      lathe = next;
      modeCombo.value = next ? 'lathe' : 'mill';
    },
    setRows(rows, isLathe, metadata) {
      edited = false;
      lathe = isLathe;
      meta = metadata;
      modeCombo.value = isLathe ? 'lathe' : 'mill';
      data = rows;
      selected.clear();
      measureLatheWidths();
      build();
      updateCount();
      summary.textContent = '출력 정보: ' + METADATA_FIELDS.map(([name, key]) => `${name} ${metadata[key] || '-'}`).join(' | ');
    },
    clear() {
      edited = false;
      data = [];
      selected.clear();
      dynamicWidths = {};
      build();
      updateCount();
      summary.textContent = '출력 정보: -';
    },
    selected: () => [...selected].sort((a, b) => a - b),
    rows: () => data,
    relayout,
  };
  return api;
}
