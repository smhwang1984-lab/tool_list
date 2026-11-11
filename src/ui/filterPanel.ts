// Viewer 모드 필터 영역 — 원본 filter_panel (NC_Tool_List.py 3351~)
// 텍스트 정지 / 정지(M00) / 옵션정지(M01) / 실시간 형상 / 공정 필터 목록 / Reset / PG 매칭 / 전체 / 해제 / 소재.
// 공정 목록과 3D 연결은 P4, 실시간 형상·소재는 P6에서 채운다(그 전까지 비활성).
import { getPref, setPref } from '../platform/prefs';
import { el } from './dialog';

export interface FilterItem {
  key: string;
  label: string;
  color: string;
}

export interface StopOptions {
  stopText: boolean;
  stopTextValue: string;
  stopM00: boolean;
  stopM01: boolean;
}

export interface FilterPanel {
  root: HTMLElement;
  stopOptions(): StopOptions;
  pgMatch(): boolean;
  /** 공정 목록 채우기 (keepSelection 이면 이전 선택 유지, 아니면 전부 선택) */
  setItems(items: readonly FilterItem[], keepSelection?: boolean): void;
  itemCount(): number;
  selectedKeys(): string[];
  onSelectionChange: (keys: string[]) => void;
  /** 항목을 켰을 때(탭) — 그 공정의 첫 줄로 이동 */
  onActivate: (key: string) => void;
  onReset: () => void;
  onPgMatch: (on: boolean) => void;
  /** 실시간 형상 체크가 바뀜 */
  onLive: (on: boolean) => void;
  liveOn(): boolean;
  /** 툴바 드롭다운에 넣을 정지 옵션(텍스트 정지·정지·옵션정지·실시간 형상) */
  stopMenu: HTMLElement;
  /** 툴바에 둘 소재 단추 */
  stockButton: HTMLButtonElement;
}

const asBool = (raw: string, fallback: boolean): boolean => (raw === '' ? fallback : raw === '1' || raw === 'true');

export function createFilterPanel(): FilterPanel {
  const root = el('div', { class: 'filter-panel' });
  const check = (text: string, title: string, checked: boolean): [HTMLLabelElement, HTMLInputElement] => {
    const label = el('label', { class: 'pb-check', title });
    const input = el('input', { type: 'checkbox' });
    input.checked = checked;
    label.append(input, document.createTextNode(text));
    return [label, input];
  };
  const btn = (text: string, title: string): HTMLButtonElement => {
    const b = el('button', { type: 'button', title });
    b.textContent = text;
    return b;
  };

  const stopTextTip = '오른쪽 입력창의 문자열이 포함된 줄에서 자동 재생을 멈춥니다.\n위쪽 "문자 검색"과는 별개의 값입니다.';
  const [textLabel, textCheck] = check('텍스트 정지', stopTextTip, asBool(getPref('stop_at_text'), false));
  const textInput = el('input', { type: 'text', placeholder: '정지 문자', title: stopTextTip, autocomplete: 'off', autocapitalize: 'off' });
  textInput.value = getPref('stop_text_value');
  textInput.disabled = !textCheck.checked;
  const [m00Label, m00Check] = check('정지', 'M0 또는 M00에서 자동 재생을 멈춥니다.', asBool(getPref('stop_at_m00'), true));
  const [m01Label, m01Check] = check('옵션정지', 'M1 또는 M01에서 자동 재생을 멈춥니다.', asBool(getPref('stop_at_m01'), true));
  const [liveLabel, liveCheck] = check('실시간 형상', '체크하면 재생·커서 위치까지 소재를 깎아 보여 줍니다. 끄면 선택한 공정의 끝까지 깎은 모양을 보여 줍니다.', asBool(getPref('sim_live'), false));
  const stopBar = el('div', { class: 'filter-row' });
  stopBar.append(textLabel, textInput, m00Label, m01Label, liveLabel);

  const title = el('span', { class: 'filter-title', title: '공정별 경로 필터 선택 — 아래 목록에서 3D 화면에 그릴 공정을 고릅니다.' });
  title.textContent = '공정 필터';
  const btnReset = btn('Reset', '프로그램 커서를 맨 상단(첫 줄)으로 이동합니다. (F5)');
  const [pgLabel, pgCheck] = check('PG 매칭', '체크하면 그려진 경로를 지우고, 커서가 있는 공정만\n프로그램 방향키에 맞춰 실시간으로 그리고 지웁니다.', false);
  const btnAll = btn('전체', '모든 공정 경로 표시');
  const btnNone = btn('해제', '모든 공정 경로 숨기기');
  const btnStock = btn('소재', '소재(STOCK) 설정과 가공 형상 시뮬레이션');
  const filterBar = el('div', { class: 'filter-row' });
  filterBar.append(title, el('span', { class: 'spacer' }), btnReset, pgLabel, btnAll, btnNone);

  const list = el('div', { class: 'filter-list', role: 'listbox', 'aria-multiselectable': 'true' });
  root.append(filterBar, list);

  let items: FilterItem[] = [];
  const selected = new Set<string>();

  const paint = (): void => {
    list.replaceChildren();
    if (!items.length) {
      const empty = el('div', { class: 'filter-empty' });
      empty.textContent = '공정 목록은 Viewer에서 경로를 그린 뒤 표시됩니다.';
      list.append(empty);
      return;
    }
    for (const it of items) {
      const row = el('div', { class: 'filter-item' + (selected.has(it.key) ? ' selected' : ''), role: 'option', 'data-key': it.key });
      const chip = el('i', { class: 'chip' });
      chip.style.background = it.color;
      const text = el('span');
      text.textContent = it.label;
      row.append(chip, text);
      list.append(row);
    }
  };

  const api: FilterPanel = {
    root,
    stopOptions: () => ({
      stopText: textCheck.checked, stopTextValue: textInput.value, stopM00: m00Check.checked, stopM01: m01Check.checked,
    }),
    pgMatch: () => pgCheck.checked,
    stopMenu: stopBar,
    stockButton: btnStock,
    itemCount: () => items.length,
    selectedKeys: () => items.filter((i) => selected.has(i.key)).map((i) => i.key),
    onSelectionChange: () => {},
    onActivate: () => {},
    onReset: () => {},
    onPgMatch: () => {},
    onLive: () => {},
    liveOn: () => liveCheck.checked,
    setItems(next, keepSelection = false) {
      const prev = new Set(selected);
      items = [...next];
      selected.clear();
      for (const it of items) if (!keepSelection || prev.has(it.key)) selected.add(it.key);
      if (keepSelection && !selected.size) for (const it of items) selected.add(it.key); // 겹치는 공정이 없으면 전체
      paint();
    },
  };

  list.addEventListener('click', (e) => {
    const row = (e.target as HTMLElement).closest<HTMLElement>('.filter-item');
    if (!row) return;
    const key = row.dataset.key!;
    const turnedOn = !selected.has(key);
    if (turnedOn) selected.add(key);
    else selected.delete(key);
    paint();
    api.onSelectionChange(api.selectedKeys());
    if (turnedOn) api.onActivate(key); // v2.3.9: 켤 때만 프로그램 위치 이동, 끌 때는 그대로
  });
  btnAll.addEventListener('click', () => {
    items.forEach((i) => selected.add(i.key));
    paint();
    api.onSelectionChange(api.selectedKeys());
  });
  btnNone.addEventListener('click', () => {
    selected.clear();
    paint();
    api.onSelectionChange(api.selectedKeys());
  });
  btnReset.addEventListener('click', () => api.onReset());
  pgCheck.addEventListener('change', () => api.onPgMatch(pgCheck.checked));
  liveCheck.addEventListener('change', () => { setPref('sim_live', liveCheck.checked ? '1' : '0'); api.onLive(liveCheck.checked); });
  const save = (): void => {
    setPref('stop_at_text', textCheck.checked ? '1' : '0');
    setPref('stop_text_value', textInput.value);
    setPref('stop_at_m00', m00Check.checked ? '1' : '0');
    setPref('stop_at_m01', m01Check.checked ? '1' : '0');
  };
  textCheck.addEventListener('change', () => {
    textInput.disabled = !textCheck.checked;
    save();
  });
  textInput.addEventListener('input', save);
  m00Check.addEventListener('change', save);
  m01Check.addEventListener('change', save);
  paint();
  return api;
}
