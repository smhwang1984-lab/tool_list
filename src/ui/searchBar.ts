// 검색 줄: 이전 공구 / 다음 공구 / 문자 검색 / 상태 표시 — 원본 search_bar (NC_Tool_List.py 3300~)
import {
  findNextLiteralSpan, findNextToolChangeSpan, findPrevToolChangeSpan, type Span,
} from '../core/search';
import type { Editor } from './editor';
import { el } from './dialog';

export interface SearchBar {
  root: HTMLElement;
  nextTool(): void;
  prevTool(): void;
  findText(): void;
}

export function createSearchBar(editor: Editor, isLathe: () => boolean): SearchBar {
  const root = el('div', { class: 'search-bar' });
  const mk = (label: string, title: string) => {
    const b = el('button', { type: 'button', title });
    b.textContent = label;
    return b;
  };
  const btnPrev = mk('이전 공구', '이전 공구 (F6) — 위쪽 공구 교체 지점');
  const btnNext = mk('다음 공구', '다음 공구 (F8) — 아래쪽 공구 교체 지점');
  const input = el('input', {
    type: 'search', placeholder: '문자 검색', enterkeyhint: 'search', autocomplete: 'off', autocapitalize: 'off',
    title: '문자 검색 — 입력한 문자열이 있는 다음 줄 (Enter)',
  });
  const btnFind = mk('검색', '입력한 문자열 찾기');
  const status = el('span', { class: 'search-status' });
  root.append(btnPrev, btnNext, input, btnFind, status);

  const setStatus = (text: string, error = false): void => {
    status.textContent = text;
    status.classList.toggle('error', error);
  };
  const apply = (result: Span | null, noneText: string, foundText: string, wrapText: string): void => {
    if (!result) {
      setStatus(noneText, true);
      editor.focus();
      return;
    }
    const [start, end, wrapped] = result;
    editor.select(start, end);
    editor.focus();
    setStatus(wrapped ? wrapText : foundText);
  };

  const bar: SearchBar = {
    root,
    nextTool() {
      const lathe = isLathe();
      apply(findNextToolChangeSpan(editor.getText(), editor.selectionTo(), lathe),
        lathe ? 'Tnn00 항목 없음' : 'M6T 항목 없음', '공구 위치 선택', '처음부터 검색');
    },
    prevTool() {
      const lathe = isLathe();
      apply(findPrevToolChangeSpan(editor.getText(), editor.selectionFrom(), lathe),
        lathe ? 'Tnn00 항목 없음' : 'M6T 항목 없음', '공구 위치 선택', '끝에서부터 검색');
    },
    findText() {
      const needle = input.value;
      if (!needle) {
        setStatus('검색어 입력 필요', true);
        return;
      }
      apply(findNextLiteralSpan(editor.getText(), needle, editor.selectionTo()),
        '검색 결과 없음', '검색 위치 선택', '처음부터 검색');
    },
  };
  btnPrev.addEventListener('click', () => bar.prevTool());
  btnNext.addEventListener('click', () => bar.nextTool());
  btnFind.addEventListener('click', () => bar.findText());
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') bar.findText();
  });
  return bar;
}
