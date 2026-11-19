// 장비 타입·스펙 패널 — 원본 _build_machine_settings_panel (NC_Tool_List.py 4053~)
// ▶/▼ 접이식, 장비 타입 콤보, 스펙 입력칸, "현재 장비 스펙 기록/저장". 저장하면 자동으로 접힌다.
import { type MachineSpecs, isLatheMachine, loadMachineSpecs } from '../core/machines';
import { getPref, setPref } from '../platform/prefs';
import { el } from './dialog';

export const MACHINE_PANEL_TITLE = '장비 타입 및 스펙 설정';

export interface MachinePanel {
  root: HTMLElement;
  machineType(): string;
  isLathe(): boolean;
  /** 장비 이름 목록 (선반 제외 MCT 포함 전체, 원본 순서) */
  machineTypes(): string[];
  setMachineType(name: string): void;
  setExpanded(expanded: boolean): void;
  collapse(): void;
  spec(name?: string): Record<string, string>;
}

export function createMachinePanel(onChange: (machineType: string) => void): MachinePanel {
  const specs: MachineSpecs = loadMachineSpecs(getPref('machine_specs', ''));
  const names = Object.keys(specs);
  let current = getPref('machine_type');
  if (!(current in specs)) current = names[0]!;
  let expanded = getPref('machine_panel_expanded') === '1';

  const root = el('div', { class: 'machine-panel' });
  const toggle = el('button', { type: 'button', class: 'machine-toggle' });
  const body = el('div', { class: 'machine-body' });
  const combo = el('select', { 'aria-label': '장비 타입' });
  for (const name of names) combo.append(new Option(name, name));
  const form = el('div', { class: 'machine-form' });
  const save = el('button', { type: 'button', class: 'machine-save' });
  save.textContent = '현재 장비 스펙 기록/저장';
  const status = el('div', { class: 'machine-status' });
  body.append(combo, form, save);
  root.append(toggle, body, status);

  const paintToggle = (): void => {
    toggle.textContent = `${expanded ? '▼' : '▶'} ${MACHINE_PANEL_TITLE}`;
    body.hidden = !expanded;
  };
  const rebuildForm = (): void => {
    form.replaceChildren();
    for (const [key, value] of Object.entries(specs[current] ?? {})) {
      const label = el('label');
      const name = el('span');
      name.textContent = `${key}:`;
      const input = el('input', { type: 'text', 'data-key': key, inputmode: 'text', autocomplete: 'off' });
      input.value = value;
      label.append(name, input);
      form.append(label);
    }
  };
  const setExpanded = (next: boolean): void => {
    expanded = next;
    setPref('machine_panel_expanded', next ? '1' : '0');
    paintToggle();
  };

  combo.value = current;
  rebuildForm();
  paintToggle();

  toggle.addEventListener('click', () => setExpanded(!expanded));
  combo.addEventListener('change', () => {
    current = combo.value;
    setPref('machine_type', current);
    rebuildForm();
    status.textContent = '';
    onChange(current);
  });
  save.addEventListener('click', () => {
    const next: Record<string, string> = {};
    for (const input of form.querySelectorAll<HTMLInputElement>('input[data-key]')) {
      next[input.dataset.key!] = input.value.trim();
    }
    specs[current] = next;
    setPref('machine_specs', JSON.stringify(specs));
    status.textContent = '장비 스펙 설정이 저장되었습니다.';
    setExpanded(false);
  });

  return {
    root,
    machineType: () => current,
    isLathe: () => isLatheMachine(current),
    machineTypes: () => [...names],
    setMachineType(name) {
      if (!(name in specs) || name === current) return;
      current = name;
      combo.value = name;
      setPref('machine_type', name);
      rebuildForm();
      status.textContent = '';
      onChange(name);
    },
    setExpanded,
    collapse: () => {
      if (expanded) setExpanded(false);
    },
    spec: (name) => ({ ...(specs[name ?? current] ?? {}) }),
  };
}
