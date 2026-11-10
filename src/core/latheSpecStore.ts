// 직접 입력 저장소(메모리 부분) — 원본 lathe_insert_spec.LatheSpecStore
// 사용자가 툴리스트 [수정] 창에서 넣은 값을 인서트 이름별로 기억한다.
//   insert : 정규화한 인서트 문구 -> {R, T, PITCH, D}
//   tool   : '홀더||인서트' -> {KIND, DIR, TIP}  (같은 인서트도 홀더에 따라 종류가 다르다)
// 파일/Preferences 읽기·쓰기는 platform/ 에서 한다(P3-T9). 여기서는 JSON <-> 객체 변환만 한다.
import type { SpecStore } from './latheInsertSpec';
import { normalizeKey } from './latheInsertSpec';
import { pyStr, pyStrip, pyTruthy } from './py';

export type SpecEntry = Record<string, string>;
export type SpecTable = Record<string, SpecEntry>;

const INSERT_FIELDS = ['R', 'T', 'PITCH', 'D'] as const;
const TOOL_FIELDS = ['KIND', 'DIR', 'TIP'] as const;

const isDict = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);

export class LatheSpecStore implements SpecStore {
  insert: SpecTable = {};
  tool: SpecTable = {};

  /** JSON 텍스트(또는 이미 읽은 값)에서 읽는다. 깨진 파일은 빈 저장소가 된다(원본과 같다). */
  constructor(json?: string | unknown) {
    if (json !== undefined) this.load(json);
  }

  static insertKey(insertText: unknown, holderText: unknown = ''): string {
    const key = normalizeKey(insertText);
    if (key) return key;
    const holder = normalizeKey(holderText);
    return holder ? '@' + holder : '';
  }

  static toolKey(holderText: unknown, insertText: unknown): string {
    return `${normalizeKey(holderText)}||${normalizeKey(insertText)}`;
  }

  load(json: string | unknown): void {
    this.insert = {};
    this.tool = {};
    let data: unknown = json;
    if (typeof json === 'string') {
      try {
        data = JSON.parse(json);
      } catch {
        return;
      }
    }
    if (!isDict(data)) return;
    const sections: [string, SpecTable, readonly string[]][] = [
      ['insert', this.insert, INSERT_FIELDS], ['tool', this.tool, TOOL_FIELDS],
    ];
    for (const [section, target, fields] of sections) {
      const entries = data[section];
      if (!isDict(entries)) continue;
      for (const [key, value] of Object.entries(entries)) {
        if (!isDict(value)) continue;
        const clean: SpecEntry = {};
        for (const f of fields) {
          if (f in value && pyStrip(pyStr(value[f]))) clean[f] = pyStrip(pyStr(value[f]));
        }
        if (Object.keys(clean).length) target[key] = clean;
      }
    }
  }

  /** 파일에 쓸 내용 (키 정렬은 쓰는 쪽에서) */
  toJson(): { version: number; insert: SpecTable; tool: SpecTable } {
    return { version: 1, insert: this.insert, tool: this.tool };
  }

  getInsert(insertText: unknown, holderText: unknown = ''): SpecEntry {
    return { ...(this.insert[LatheSpecStore.insertKey(insertText, holderText)] ?? {}) };
  }

  getTool(holderText: unknown, insertText: unknown): SpecEntry {
    return { ...(this.tool[LatheSpecStore.toolKey(holderText, insertText)] ?? {}) };
  }

  private static update(target: SpecTable, key: string, values: Record<string, unknown>, fields: readonly string[]): void {
    const entry: SpecEntry = { ...(target[key] ?? {}) };
    for (const field of fields) {
      if (!(field in values)) continue;
      const raw = values[field];
      const value = pyStrip(pyTruthy(raw) ? pyStr(raw) : '');
      if (value) entry[field] = value;
      else delete entry[field];
    }
    if (Object.keys(entry).length) target[key] = entry;
    else delete target[key];
  }

  /** values에 든 R/T/PITCH/D만 갱신한다(빈 값 = 저장값 삭제). 인서트·홀더 이름이 모두 비면 무시. */
  updateInsert(insertText: unknown, values: Record<string, unknown>, holderText: unknown = ''): void {
    const key = LatheSpecStore.insertKey(insertText, holderText);
    if (key) LatheSpecStore.update(this.insert, key, values, INSERT_FIELDS);
  }

  updateTool(holderText: unknown, insertText: unknown, values: Record<string, unknown>): void {
    const key = LatheSpecStore.toolKey(holderText, insertText);
    if (key !== '||') LatheSpecStore.update(this.tool, key, values, TOOL_FIELDS);
  }
}
