// 공구 행 수정/추가 대화상자 — 원본 show_row_editor (NC_Tool_List.py 5127~)
import { COLUMNS, LATHE_COLUMNS, LATHE_SPEC_KEYS } from '../core/columns';
import {
  DIRECTIONS, DIRECTION_LABELS, KINDS, PROGRAM_SPECIFIC_SOURCES, recommendFields, TIPS, TIP_LABELS,
} from '../core/latheInsertSpec';
import { el, showDialog } from './dialog';

const HINTS: Record<string, string> = {
  R: '노즈 R / 코너 R (mm)',
  T: '홈 바이트 폭 (mm) — 규격을 못 찾으면 직접 입력',
  PITCH: '나사 피치 (mm)',
  KIND: '공구 종류 — 자동 추천 후 고칠 수 있습니다',
  DIR: '공구 방향: R 우수 / L 좌수 / N 중립',
  TIP: '가상 인선 번호(화면에서 X 위, Z 오른쪽 기준): 1 우상 / 2 우하 / 3 좌하 / 4 좌상 / 9 중심',
  D: '턴밀·중심 드릴 공구 지름 (mm) — 문구의 D값 자동, 없으면 직접 입력',
};

const CHOICES: Record<string, [value: string, label: string][]> = {
  KIND: KINDS.map((k) => [k, k]),
  DIR: DIRECTIONS.map((d) => [d, DIRECTION_LABELS[d] ?? d]),
  TIP: TIPS.map((t) => [t, TIP_LABELS[t] ?? t]),
};

export interface RowEditorOptions {
  lathe: boolean;
  /** 수정할 행이면 true (제목만 달라진다) */
  editing: boolean;
  values: Readonly<Record<string, string>>;
  /** 선반: R/T/PITCH/종류/방향/인선/D 의 값 출처 */
  sources?: Readonly<Record<string, string>>;
  /** 저장 눌렀을 때. 값은 앞뒤 공백을 뗀 문자열. */
  onSave: (row: Record<string, string>) => void;
}

export function showRowEditor(opts: RowEditorOptions): void {
  const columns = opts.lathe ? LATHE_COLUMNS : COLUMNS;
  const form = el('div', { class: 'row-form' });
  const inputs = new Map<string, HTMLInputElement | HTMLSelectElement>();

  const setValue = (key: string, text: string): void => {
    const input = inputs.get(key)!;
    if (input instanceof HTMLSelectElement) {
      if (text && ![...input.options].some((o) => o.value === text)) input.append(new Option(text, text));
      input.value = text;
    } else input.value = text;
  };
  const valueOf = (key: string): string => inputs.get(key)!.value.trim();

  for (const [key, label] of columns) {
    const wrap = el('label');
    const name = el('span');
    name.textContent = label;
    let input: HTMLInputElement | HTMLSelectElement;
    if (opts.lathe && CHOICES[key]) {
      input = el('select');
      input.append(new Option('', ''));
      for (const [value, text] of CHOICES[key]!) input.append(new Option(text, value));
    } else {
      input = el('input', { type: 'text', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false' });
    }
    inputs.set(key, input);
    setValue(key, String(opts.values[key] ?? ''));
    if (opts.lathe && (LATHE_SPEC_KEYS as readonly string[]).includes(key)) {
      let hint = HINTS[key] ?? '';
      if (PROGRAM_SPECIFIC_SOURCES.includes(opts.sources?.[key] ?? '')) {
        hint += '\n※ 프로그램에서 온 값입니다 — 고쳐도 이번 표에서만 바뀝니다';
      }
      wrap.title = hint;
      const small = el('small');
      small.textContent = hint.split('\n')[0]!;
      wrap.append(name, input, small);
    } else wrap.append(name, input);
    form.append(wrap);
  }

  const save = (): boolean => {
    const row: Record<string, string> = {};
    for (const [key] of columns) row[key] = valueOf(key);
    opts.onSave(row);
    return true;
  };
  const buttons = [{ label: '취소' }] as { label: string; primary?: boolean; onClick?: () => boolean | void }[];
  if (opts.lathe) {
    buttons.push({
      label: '자동 추천',
      onClick: () => {
        const recommended = recommendFields(valueOf('INSERT'), valueOf('HOLDER')) as unknown as Record<string, string>;
        for (const key of LATHE_SPEC_KEYS) if (recommended[key]) setValue(key, recommended[key]!);
        return false;
      },
    });
  }
  buttons.push({ label: '저장', primary: true, onClick: save });
  showDialog(opts.editing ? '공구 행 수정' : '공구 행 추가', form, buttons).classList.add('wide');
}
