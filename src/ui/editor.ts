// 프로그램 입력창 — CodeMirror 6. 줄 번호, ncColor 색칠, 현재 줄 강조, 읽기 전용/편집 전환, 핀치 글자 크기.
import { defaultKeymap, history, historyKeymap } from '@codemirror/commands';
import { Compartment, EditorState, type Extension } from '@codemirror/state';
import {
  Decoration, type DecorationSet, EditorView, ViewPlugin, type ViewUpdate, highlightActiveLine, keymap,
  lineNumbers,
} from '@codemirror/view';
import { ncColorLine, type NcColorKey } from '../core/ncColor';

export const FONT_MIN = 9;
export const FONT_MAX = 32;

const marks: Record<NcColorKey, Decoration> = {
  nc_g0: Decoration.mark({ class: 'nc-g0' }), nc_g1: Decoration.mark({ class: 'nc-g1' }),
  nc_g2: Decoration.mark({ class: 'nc-g2' }), nc_g3: Decoration.mark({ class: 'nc-g3' }),
  nc_cycle: Decoration.mark({ class: 'nc-cycle' }), nc_spindle: Decoration.mark({ class: 'nc-spindle' }),
  nc_coolant: Decoration.mark({ class: 'nc-coolant' }),
};

/** 줄 시작 상태를 캐시해 두고 보이는 줄만 색칠한다(큰 파일도 스크롤이 끊기지 않게). */
function colorPlugin(isLathe: () => boolean) {
  return ViewPlugin.fromClass(class {
    decorations: DecorationSet;
    /** startStates[i] = i+1번 줄을 시작할 때의 상태 */
    startStates: number[] = [0];
    lathe = isLathe();

    constructor(view: EditorView) {
      this.decorations = this.build(view);
    }

    update(update: ViewUpdate): void {
      const lathe = isLathe();
      if (update.docChanged || lathe !== this.lathe) {
        this.startStates = [0];
        this.lathe = lathe;
      }
      if (update.docChanged || update.viewportChanged || update.transactions.length) {
        this.decorations = this.build(update.view);
      }
    }

    build(view: EditorView): DecorationSet {
      const { doc } = view.state;
      const lastLine = doc.lineAt(view.viewport.to).number;
      while (this.startStates.length < lastLine) {
        const n = this.startStates.length; // 다음에 계산할 줄 번호(1부터)
        const [, next] = ncColorLine(doc.line(n).text, this.startStates[n - 1]!, this.lathe);
        this.startStates.push(next);
      }
      const ranges = [];
      const first = doc.lineAt(view.viewport.from).number;
      for (let n = first; n <= lastLine; n++) {
        const line = doc.line(n);
        const [spans] = ncColorLine(line.text, this.startStates[n - 1]!, this.lathe);
        for (const [s, e, key] of spans) ranges.push(marks[key].range(line.from + s, line.from + e));
      }
      return Decoration.set(ranges, true);
    }
  }, { decorations: (v) => v.decorations });
}

const baseTheme = EditorView.theme({
  '&': { height: '100%', backgroundColor: 'var(--editor_bg)', color: 'var(--editor_text)' },
  '.cm-scroller': { fontFamily: 'Consolas, "D2Coding", "Noto Sans Mono", monospace', lineHeight: '1.45', overflow: 'auto' },
  '.cm-content': { caretColor: 'var(--editor_text)' },
  '.cm-gutters': { backgroundColor: 'var(--panel_bg)', color: 'var(--faint_text)', border: 'none' },
  '.cm-activeLine': { backgroundColor: 'var(--current_line)' },
  '.cm-activeLineGutter': { backgroundColor: 'var(--current_line)' },
  '.cm-selectionBackground, &.cm-focused .cm-selectionBackground': { backgroundColor: 'var(--accent) !important' },
  '.cm-line': { padding: '0 4px' },
  '&.cm-focused': { outline: 'none' },
});

export interface Editor {
  view: EditorView;
  getText(): string;
  setText(text: string): void;
  setReadOnly(readOnly: boolean): void;
  /** 글자 범위를 선택하고 화면 가운데로 */
  select(start: number, end: number): void;
  selectionFrom(): number;
  selectionTo(): number;
  setLathe(lathe: boolean): void;
  setFontSize(px: number): void;
  fontSize(): number;
  focus(): void;
}

export interface EditorOptions {
  fontSize: number;
  onChange?: () => void;
  onFontSize?: (px: number) => void;
  /** 읽기 전용일 때 탭하면 불린다(스펙 패널 접기에 쓴다) */
  onTap?: () => void;
}

export function createEditor(parent: HTMLElement, opts: EditorOptions): Editor {
  let lathe = false;
  let size = Math.min(FONT_MAX, Math.max(FONT_MIN, opts.fontSize));
  const readOnly = new Compartment();
  const fontTheme = new Compartment();
  const fontExt = (px: number): Extension => EditorView.theme({ '.cm-scroller': { fontSize: `${px}px` } });
  const extensions: Extension[] = [
    lineNumbers(), highlightActiveLine(), history(),
    keymap.of([...defaultKeymap, ...historyKeymap]),
    baseTheme, colorPlugin(() => lathe),
    readOnly.of([EditorState.readOnly.of(true), EditorView.editable.of(true)]),
    fontTheme.of(fontExt(size)),
    EditorView.updateListener.of((u) => { if (u.docChanged) opts.onChange?.(); }),
  ];
  const view = new EditorView({ state: EditorState.create({ doc: '', extensions }), parent });

  const setFontSize = (px: number): void => {
    size = Math.min(FONT_MAX, Math.max(FONT_MIN, Math.round(px * 2) / 2));
    view.dispatch({ effects: fontTheme.reconfigure(fontExt(size)) });
  };

  // 두 손가락 핀치로 글자 크기 조절
  const pointers = new Map<number, { x: number; y: number }>();
  let pinchStart = 0;
  let sizeStart = size;
  const dist = (): number => {
    const [a, b] = [...pointers.values()];
    return Math.hypot(a!.x - b!.x, a!.y - b!.y);
  };
  const dom = view.dom;
  dom.style.touchAction = 'pan-x pan-y';
  dom.addEventListener('pointerdown', (e) => {
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2) {
      pinchStart = dist();
      sizeStart = size;
    }
  });
  dom.addEventListener('pointermove', (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 2 && pinchStart > 0) setFontSize(sizeStart * (dist() / pinchStart));
  });
  const endPointer = (e: PointerEvent): void => {
    const wasPinch = pointers.size === 2;
    pointers.delete(e.pointerId);
    if (wasPinch) {
      pinchStart = 0;
      opts.onFontSize?.(size);
    }
  };
  dom.addEventListener('pointerup', endPointer);
  dom.addEventListener('pointercancel', endPointer);
  dom.addEventListener('click', () => opts.onTap?.());

  return {
    view,
    getText: () => view.state.doc.toString(),
    setText(text) {
      view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: text }, selection: { anchor: 0 } });
      view.scrollDOM.scrollTop = 0;
    },
    setReadOnly(ro) {
      view.dispatch({
        effects: readOnly.reconfigure([EditorState.readOnly.of(ro), EditorView.editable.of(true)]),
      });
    },
    select(start, end) {
      const len = view.state.doc.length;
      const a = Math.min(start, len);
      const b = Math.min(end, len);
      view.dispatch({ selection: { anchor: a, head: b }, effects: EditorView.scrollIntoView(a, { y: 'center' }) });
    },
    selectionFrom: () => view.state.selection.main.from,
    selectionTo: () => view.state.selection.main.to,
    setLathe(next) {
      lathe = next;
      view.dispatch({}); // 플러그인이 다시 색칠하도록 깨운다
    },
    setFontSize,
    fontSize: () => size,
    focus: () => view.focus(),
  };
}
