// P4-T2: 공구 경로 계산 — 원본 NCViewerWidget.process_nc_lines 골든과 비교
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { processNcLines, type PathPoint } from '../src/core/toolpath';

const DIR = join(__dirname, 'golden', 'toolpath');
const FIX = join(__dirname, 'fixtures');
const TOL = 1e-6;

function decode(buf: Buffer): string {
  try { return new TextDecoder('utf-8', { fatal: true }).decode(buf).replace(/^﻿/, ''); } catch { return new TextDecoder('euc-kr').decode(buf); }
}
const nearly = (a: unknown, b: unknown, path: string): void => {
  if (typeof a === 'number' && typeof b === 'number') { expect(Math.abs(a - b), path).toBeLessThanOrEqual(TOL * Math.max(1, Math.abs(b))); return; }
  if (Array.isArray(a) && Array.isArray(b)) {
    expect(a.length, path + ' 길이').toBe(b.length);
    a.forEach((v, i) => nearly(v, b[i], `${path}[${i}]`));
    return;
  }
  if (a && b && typeof a === 'object' && typeof b === 'object') {
    const ka = Object.keys(a as object).sort();
    expect(ka, path + ' 키').toEqual(Object.keys(b as object).sort());
    for (const k of ka) nearly((a as Record<string, unknown>)[k], (b as Record<string, unknown>)[k], `${path}.${k}`);
    return;
  }
  expect(a, path).toEqual(b);
};
const objOf = <V>(m: Map<number | string, V>): Record<string, V> => Object.fromEntries([...m].map(([k, v]) => [String(k), v]));

const files = readdirSync(DIR).filter((f) => f.endsWith('.json'));
describe('toolpath 골든', () => {
  for (const file of files) {
    it(file, () => {
      const g = JSON.parse(readFileSync(join(DIR, file), 'utf-8'));
      if (g.error) return;
      const lines = decode(readFileSync(join(FIX, g.file))).split(/\r\n|\r|\n/).slice(0, g.line_count);
      const r = processNcLines(lines, g.machine, g.specs);
      // 공정 목록·순서
      expect([...r.tool_paths.keys()]).toEqual(Object.keys(g.tool_paths));
      for (const [key, pts] of r.tool_paths) {
        const gp = g.tool_paths[key] as (PathPoint & { c?: number })[];
        expect(pts.length, `${key} 점 수`).toBe(gp.length);
        pts.forEach((p, i) => {
          nearly(p.pt, gp[i]!.pt, `${key}[${i}].pt`);
          expect([p.type, p.valid, p.src_line, p.seq], `${key}[${i}]`).toEqual([gp[i]!.type, gp[i]!.valid, gp[i]!.src_line, gp[i]!.seq]);
          if (gp[i]!.c !== undefined) nearly(p.c, gp[i]!.c, `${key}[${i}].c`);
        });
      }
      expect(objOf(r.process_tool_map)).toEqual(g.process_tool_map);
      expect(objOf(r.process_first_line)).toEqual(g.process_first_line);
      expect(objOf(r.process_first_seq)).toEqual(g.process_first_seq);
      expect(r.seq_to_line).toEqual(g.seq_to_line);
      expect(objOf(r.line_to_tool_map)).toEqual(g.line_to_tool_map);
      expect(objOf(r.seq_to_tool_map)).toEqual(g.seq_to_tool_map);
      expect(objOf(r.line_to_seq)).toEqual(g.line_to_seq);
      expect(objOf(r.line_to_seq_all)).toEqual(g.line_to_seq_all);
      expect(objOf(r.modal_state_map)).toEqual(g.modal_state_map);
      expect(objOf(r.line_lathe_map)).toEqual(g.line_lathe_map);
      nearly(objOf(r.line_to_coord_map), g.line_to_coord_map, 'line_to_coord_map');
      nearly(objOf(r.seq_to_coord_map), g.seq_to_coord_map, 'seq_to_coord_map');
      nearly(objOf(r.seq_to_c_rot), g.seq_to_c_rot, 'seq_to_c_rot');
      nearly(objOf(r.line_axis_map), g.line_axis_map, 'line_axis_map');
      nearly(objOf(r.line_feed_state), g.line_feed_state, 'line_feed_state');
      nearly(objOf(r.seq_to_dwell_sec), g.seq_to_dwell_sec, 'dwell');
      nearly(objOf(r.seq_to_elapsed_sec), g.seq_to_elapsed_sec, 'elapsed');
      nearly(objOf(r.process_time_sec), g.process_time_sec, 'process_time');
      nearly(r.total_time_sec, g.total_time_sec, 'total');
    });
  }
});
