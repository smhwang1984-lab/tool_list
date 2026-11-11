import { describe, expect, it } from 'vitest';
import { cutGroups, groupAt } from '../src/viewer/entryArrow';
import type { PathPoint } from '../src/core/toolpath';

const n = (pt: [number, number, number], type: string, line: number, seq: number): PathPoint => ({ pt, type, valid: true, src_line: line, seq });

describe('진입 방향 화살표 구간', () => {
  const path = [n([0, 0, 10], 'G00', 0, 0), n([0, 0, 0], 'G01', 1, 1), n([10, 0, 0], 'G01', 2, 2), n([10, 0, 5], 'G01', 3, 3), n([20, 0, 5], 'G01', 4, 4)];
  it('축이 안 바뀌면 구간 하나, 첫 절삭 시작점·방향', () => {
    const g = cutGroups(path);
    expect(g).toHaveLength(1);
    expect(g[0]!.entry).toEqual([0, 0, 10]);
    expect(g[0]!.direction).toEqual([0, 0, -1]);
  });
  it('축이 바뀌면 구간이 끝나고 다음 절삭에서 새 구간', () => {
    const axis = new Map<number, [number, number, number]>([[3, [0, 0.5, 0.8]], [4, [0, 0.5, 0.8]]]);
    const g = cutGroups(path, axis);
    expect(g).toHaveLength(2);
    expect(g[0]!.endSeq).toBe(3);
    expect(g[1]!.entry).toEqual([10, 0, 0]);
    expect(groupAt(g, 2)).toBe(g[0]);
    expect(groupAt(g, 4)).toBe(g[1]);
  });
});
