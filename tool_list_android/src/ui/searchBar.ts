// 검색 줄: 이전 공구 / 다음 공구 / 문자 검색 / 상태 표시 — 원본 search_bar (NC_Tool_List.py 3300~)
import {
  findNextLiteralSpan, findNextToolChangeSpan, findPrevLiteralSpan, findPrevToolChangeSpan, type Span,
} from '../core/search';
import type { Editor } from './editor';
import { el, toast } from './dialog';

export interface SearchBar {
  root: HTMLElement;
  nextTool(): void;
  prevTool(): void;
  findText(): void;
  /** 원본 v2.6.1: 문자 검색 '이전' */
  findPrevText(): void;
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
    title: '문자 검색 — Enter 다음 / Shift+Enter 이전',
  });
  const btnFindPrev = mk('이전', '입력한 문자열 위쪽으로 찾기 (Shift+Enter)');
  const btnFind = mk('다음', '입력한 문자열 아래쪽으로 찾기 (Enter)');
  const status = el('span', { class: 'search-status' });
  root.append(btnPrev, btnNext, input, btnFindPrev, btnFind, status);

  const setStatus = (text: string, error = false): void => {
    status.textContent = text;
    // 낮은 화면(폰 가로)에서는 상태 줄을 숨기므로 안내를 잠깐 띄운다
    if (window.matchMedia('(max-height: 520px)').matches) toast(text, 1500);
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
    findPrevText() {
      const needle = input.value;
      if (!needle) {
        setStatus('검색어 입력 필요', true);
        return;
      }
      apply(findPrevLiteralSpan(editor.getText(), needle, editor.selectionFrom()),
        '검색 결과 없음', '검색 위치 선택', '끝에서부터 검색');
    },
  };
  btnPrev.addEventListener('click', () => bar.prevTool());
  btnNext.addEventListener('click', () => bar.nextTool());
  btnFind.addEventListener('click', () => bar.findText());
  btnFindPrev.addEventListener('click', () => bar.findPrevText());
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { if (e.shiftKey) bar.findPrevText(); else bar.findText(); }
  });
  return bar;
}
