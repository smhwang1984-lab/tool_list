// 선반 행 수정 시 R/T/PITCH/종류/방향 처리 — 원본 _save_lathe_spec_edits / _propagate_lathe_specs (NC_Tool_List.py 5290~)
import { INSERT_FIELDS, type LatheSpecStore } from './latheSpecStore';
import { LATHE_SPEC_KEYS } from './columns';
import {
  BLANK, type FieldSources, normalizeKey, PROGRAM_SPECIFIC_SOURCES, resolveFields, SOURCE_MANUAL, SOURCE_SAVED,
} from './latheInsertSpec';
import { rowSources, setRowSources, type LatheRow } from './latheParser';

type Sources = Record<string, string>;

export const PROGRAM_ONLY_NOTICE = '프로그램(주석 태그/G76·G32)에서 온 값은 고쳐도 이번 표에서만 바뀝니다';

export interface SaveResult {
  changed: string[];
  notice: string;
  /** 저장소 내용이 실제로 바뀌었는가(바뀌었으면 파일에 쓰고 파싱 캐시를 비운다) */
  storeChanged: boolean;
}

/**
 * [수정] 창에서 바꾼 값을 처리하고 sources(값 출처)를 갱신한다.
 * - 문구만으로 나오는 추천값과 같으면 저장값을 지우고 그 출처로 표시한다.
 * - 프로그램에서 온 값은 이번 표에서만 바꾼다(저장 안 함).
 * - 그 밖에는 인서트(종류/방향은 홀더+인서트) 이름별로 저장한다.
 */
export function saveLatheSpecEdits(
  original: Readonly<Record<string, string>>, row: LatheRow, sources: Sources, store: LatheSpecStore,
): SaveResult {
  const changed = LATHE_SPEC_KEYS.filter((k) => String(row[k] ?? '') !== String(original[k] ?? '')) as string[];
  if (!changed.length) return { changed: [], notice: '', storeChanged: false };
  const insertText = row.INSERT ?? '';
  const holderText = row.HOLDER ?? '';
  const [autoValues, autoSources] = resolveFields(insertText, holderText);
  const insertValues: Record<string, string> = {};
  const toolValues: Record<string, string> = {};
  for (const key of changed) {
    const typed = String(row[key] ?? '');
    const auto = (autoValues as unknown as Record<string, string>)[key] ?? '';
    let stored: string | null;
    let source: string;
    if (typed && typed === auto) {
      stored = '';
      source = (autoSources as unknown as Record<string, string>)[key] ?? '';
    } else if (PROGRAM_SPECIFIC_SOURCES.includes(sources[key] ?? '')) {
      stored = null;
      source = SOURCE_MANUAL;
    } else if (!typed) {
      if (auto) {
        stored = BLANK;
        source = SOURCE_SAVED;
      } else {
        stored = '';
        source = '';
      }
    } else {
      stored = typed;
      source = SOURCE_SAVED;
    }
    sources[key] = source;
    if (stored === null) continue;
    if ((INSERT_FIELDS as readonly string[]).includes(key)) insertValues[key] = stored;
    else toolValues[key] = stored;
  }
  const notice = changed.some((k) => sources[k] === SOURCE_MANUAL) ? PROGRAM_ONLY_NOTICE : '';
  const snapshot = JSON.stringify([store.insert, store.tool]);
  store.updateInsert(insertText, insertValues, holderText);
  store.updateTool(holderText, insertText, toolValues);
  return { changed, notice, storeChanged: JSON.stringify([store.insert, store.tool]) !== snapshot };
}

/** 같은 인서트를 쓰는 다른 행의 비었거나 옛 값 그대로인 칸에 방금 바꾼 값을 채운다. 바뀐 행 번호를 돌려준다. */
export function propagateLatheSpecs(
  rows: LatheRow[], editedIndex: number, original: Readonly<Record<string, string>>, row: LatheRow,
  sources: Sources, changed: readonly string[],
): number[] {
  const touched: number[] = [];
  if (!changed.length) return touched;
  const insertKey = normalizeKey(row.INSERT ?? '');
  const holderKey = normalizeKey(row.HOLDER ?? '');
  if (!insertKey) return touched;
  rows.forEach((target, index) => {
    if (index === editedIndex) return;
    if (normalizeKey(target.INSERT ?? '') !== insertKey) return;
    const sameHolder = normalizeKey(target.HOLDER ?? '') === holderKey;
    let any = false;
    for (const key of changed) {
      if (sources[key] === SOURCE_MANUAL) continue;
      if ((key === 'KIND' || key === 'DIR') && !sameHolder) continue;
      const now = String(target[key] ?? '');
      if (now !== '' && now !== String(original[key] ?? '')) continue;
      const targetSources = (rowSources(target) ?? {}) as Sources;
      if (PROGRAM_SPECIFIC_SOURCES.includes(targetSources[key] ?? '')) continue;
      target[key] = String(row[key] ?? '');
      targetSources[key] = sources[key] ?? SOURCE_SAVED;
      setRowSources(target, targetSources as unknown as FieldSources);
      any = true;
    }
    if (any) touched.push(index);
  });
  return touched;
}
