// 이름 → TYPE 경우의 수 목록·수정 — 원본 show_type_list (NC_Tool_List.py 5978~)
import { DEFAULT_NAME_TYPES, type NameType } from '../core/nameTypes';
import { confirmDialog, el, showDialog, toast } from './dialog';

/** items 는 호출한 쪽이 들고 있는 목록(제자리에서 바뀐다). onChange 로 저장한다. */
export function showTypeList(items: NameType[], onChange: () => void): void {
  const body = el('div', { class: 'type-list' });
  const list = el('div', { class: 'type-rows', role: 'listbox' });
  const controls = el('div', { class: 'type-controls' });
  body.append(list, controls);
  let selected = -1;

  const refresh = (): void => {
    list.replaceChildren();
    const head = el('div', { class: 'type-row head' });
    head.append(Object.assign(el('span'), { textContent: '이름(약어·표현)' }), Object.assign(el('span'), { textContent: 'TYPE' }));
    list.append(head);
    items.forEach(([abbr, typ], i) => {
      const row = el('div', { class: 'type-row' + (i === selected ? ' selected' : ''), role: 'option' });
      row.append(Object.assign(el('span'), { textContent: abbr }), Object.assign(el('span'), { textContent: typ }));
      row.addEventListener('click', () => {
        selected = i;
        refresh();
      });
      row.addEventListener('dblclick', () => open(i));
      list.append(row);
    });
  };

  const open = (index: number | null): void => {
    const current: NameType = index === null ? ['', ''] : items[index]!;
    const form = el('div', { class: 'row-form single' });
    const mk = (label: string, value: string): HTMLInputElement => {
      const wrap = el('label');
      wrap.append(Object.assign(el('span'), { textContent: label }));
      const input = el('input', { type: 'text', autocomplete: 'off', autocapitalize: 'off', spellcheck: 'false' });
      input.value = value;
      wrap.append(input);
      form.append(wrap);
      return input;
    };
    const nameInput = mk('이름(약어·표현)', current[0]);
    const typeInput = mk('TYPE', current[1]);
    showDialog(index === null ? '이름 경우 추가' : '이름 경우 수정', form, [
      { label: '취소' },
      {
        label: '저장', primary: true,
        onClick: () => {
          const abbr = nameInput.value.trim();
          const typ = typeInput.value.trim();
          if (!abbr || !typ) {
            toast('이름과 TYPE을 모두 입력하세요.');
            return false;
          }
          if (items.some((pair, i) => pair[0].toUpperCase() === abbr.toUpperCase() && i !== index)) {
            toast('같은 이름 경우가 이미 있습니다.');
            return false;
          }
          if (index === null) items.push([abbr, typ]);
          else items[index] = [abbr, typ];
          onChange();
          refresh();
          return true;
        },
      },
    ]);
  };

  const mkButton = (text: string, onClick: () => void): void => {
    const b = el('button', { type: 'button' });
    b.textContent = text;
    b.addEventListener('click', onClick);
    controls.append(b);
  };
  mkButton('＋ 추가', () => open(null));
  mkButton('수정', () => (selected < 0 ? toast('수정하거나 삭제할 경우를 선택하세요.') : open(selected)));
  mkButton('삭제', async () => {
    if (selected < 0) return toast('수정하거나 삭제할 경우를 선택하세요.');
    if (!(await confirmDialog('이름 경우 삭제', '선택한 이름 경우를 삭제할까요?', '삭제'))) return;
    items.splice(selected, 1);
    selected = -1;
    onChange();
    refresh();
  });
  mkButton('기본값 복원', async () => {
    if (!(await confirmDialog('기본값 복원', '기본 이름 경우의 수로 되돌릴까요?'))) return;
    items.splice(0, items.length, ...DEFAULT_NAME_TYPES.map(([a, t]) => [a, t] as NameType));
    selected = -1;
    onChange();
    refresh();
  });
  refresh();
  showDialog('이름 → TYPE 경우의 수', body).classList.add('wide');
}
