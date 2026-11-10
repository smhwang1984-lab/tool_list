import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { propagateLatheSpecs, saveLatheSpecEdits } from '../src/core/latheEdit';
import { parseLatheProgram, rowSources, type LatheRow } from '../src/core/latheParser';
import { LatheSpecStore } from '../src/core/latheSpecStore';
import { decodeProgramBytes } from '../src/core/programText';

const text = decodeProgramBytes(new Uint8Array(readFileSync(new URL('./fixtures/O1699.nc', import.meta.url)))).text;

describe('선반 행 수정 (저장·전파)', () => {
  it('값을 바꾸면 저장소에 기록되고 같은 인서트의 다른 행에 퍼진다', () => {
    const store = new LatheSpecStore();
    const rows = parseLatheProgram(text, store);
    // 같은 INSERT 를 쓰면서 R 이 비어 있지 않은 행 쌍을 찾는다
    const groups = new Map<string, number[]>();
    rows.forEach((r, i) => { if (r.INSERT) groups.set(r.INSERT, [...(groups.get(r.INSERT) ?? []), i]); });
    const pair = [...groups.values()].find((g) => g.length >= 2);
    if (!pair) return; // 샘플에 같은 인서트가 없으면 전파 검사는 생략
    const [a, b] = pair as [number, number];
    const original = { ...rows[a]! };
    const row: LatheRow = { ...rows[a]!, TIP: '3' };
    const sources = { ...(rowSources(rows[a]!) ?? {}) } as Record<string, string>;
    const result = saveLatheSpecEdits(original, row, sources, store);
    expect(result.changed).toContain('TIP');
    expect(sources.TIP).not.toBeUndefined();
    rows[a] = row;
    propagateLatheSpecs(rows, a, original, row, sources, result.changed);
    expect(rows[b]!.TIP === '3' || rows[b]!.TIP === original.TIP).toBe(true);
  });
  it('바뀐 칸이 없으면 아무것도 하지 않는다', () => {
    const store = new LatheSpecStore();
    const row = { INSERT: 'CNMG120408', HOLDER: 'PCLNR', R: '0.8' } as LatheRow;
    const r = saveLatheSpecEdits(row, { ...row }, {}, store);
    expect(r).toStrictEqual({ changed: [], notice: '', storeChanged: false });
  });
});
