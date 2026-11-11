// 선반·턴밀 소재 — 원본 nc_lathe_sim 골든(tests/golden/lathe)과 칸 단위 비교
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import type { ToolGeometry } from '../src/core/latheInsertSpec';
import { processNcLines } from '../src/core/toolpath';
import { buildLatheProgram } from '../src/sim/latheSegments';
import { LatheStock, LatheStockSpec } from '../src/sim/latheStock';
import { TurnMillStock } from '../src/sim/turnMillStock';

const DIR = join(__dirname, 'golden', 'lathe');
const FIX = join(__dirname, 'fixtures');
const LATHE = 'CNC 선반 (턴밀 포함)';

function decode(buf: Buffer): string {
  try { return new TextDecoder('utf-8', { fatal: true }).decode(buf).replace(/^﻿/, ''); } catch { return new TextDecoder('euc-kr').decode(buf); }
}
function fakeGeometry(): Record<string, ToolGeometry> {
  const out: Record<string, ToolGeometry> = {};
  for (let n = 1; n < 100; n++) {
    const g: ToolGeometry = {
      kind: '', hand: 'R', tip: 3, diameter: null, so: null, mill_type: null, chamfer_angle: null, nose_r: 0.4, width: null, pitch: null,
      shape: 'C', tip_angle: 80, clearance_angle: null, ic: 12.7, edge_length: 12, thickness: 4.76, thread_angle: null, approach_angle: 95, shank: null,
    };
    switch (n % 7) {
      case 0: g.kind = '외경'; break;
      case 1: g.kind = '내경'; g.tip = 4; break;
      case 2: Object.assign(g, { kind: '외경홈', width: 3, nose_r: 0.2, shape: null, tip_angle: null }); break;
      case 3: Object.assign(g, { kind: '외경나사', thread_angle: 60, pitch: 1.5, shape: 'T', tip_angle: 60, nose_r: 0.1 }); break;
      case 4: Object.assign(g, { kind: '드릴', diameter: 8, so: 40, mill_type: 'DRILL', shape: null }); break;
      case 5: Object.assign(g, { kind: '엔드밀', diameter: 10, so: 30, mill_type: 'FLAT E/M', shape: null, nose_r: null }); break;
      default: g.kind = '외경'; g.tip = 3; g.nose_r = 0.8;
    }
    for (const key of [`T${String(n).padStart(2, '0')}`, `T${n}`, String(n)]) out[key] = g;
  }
  return out;
}

describe('선반·턴밀 골든', () => {
  for (const file of readdirSync(DIR).filter((f) => f.endsWith('.json'))) {
    it(file, () => {
      const g = JSON.parse(readFileSync(join(DIR, file), 'utf-8'));
      const lines = decode(readFileSync(join(FIX, g.file))).split(/\r\n|\r|\n/).slice(0, 900);
      const res = processNcLines(lines, LATHE, {});
      const prog = buildLatheProgram(res, fakeGeometry());
      expect(prog.engine).toBe(g.engine);
      expect(prog.seg.count).toBe(g.segments);
      const spec = new LatheStockSpec(g.spec.diameter, g.spec.length, g.spec.front_z, g.spec.bore);
      const bin = gunzipSync(readFileSync(join(DIR, file.replace('.json', '.bin.gz'))));
      const u8 = new Uint8Array(bin.buffer, bin.byteOffset, bin.byteLength);
      let lat: LatheStock;
      let turn: TurnMillStock | null = null;
      if (g.turnmill) {
        turn = new TurnMillStock(spec.bounds(), g.resolution, g.voxel_resolution);
        turn.cutRange(prog, 0, prog.seg.count);
        turn.sync();
        lat = turn.lathe;
      } else {
        lat = new LatheStock(spec.bounds(), g.resolution);
        lat.cutRange(prog.seg, prog.tools, 0, prog.seg.count, { pitch: prog.threadPitch, height: prog.threadHeight });
      }
      expect([lat.nz, lat.nr]).toEqual([g.nz, g.nr]);
      const cells = g.nz * g.nr;
      let bad = 0, badCol = 0;
      for (let i = 0; i < cells; i++) {
        if (lat.occ[i] !== u8[i]) bad++;
        else if (lat.occ[i] === 0 && lat.col[i] !== u8[cells + i]) badCol++;
      }
      const stats = { file, cells, bad, badCol, threads: lat.threadCutCount, gt: g.thread_cut_count };
      let vbad = 0, vcol = 0;
      if (turn) {
        const v = turn.voxel;
        const n = v.occ.length;
        const off = cells * 2;
        for (let i = 0; i < n; i++) {
          if (v.occ[i] !== u8[off + i]) vbad++;
          else if (v.occ[i] === 0 && v.col[i] !== u8[off + n + i]) vcol++;
        }
        Object.assign(stats, { vox: n, vbad, vcol });
      }
      console.log(JSON.stringify(stats));
      expect(bad).toBe(0);
      expect(badCol).toBe(0);
      // 복셀은 경계 칸의 부동소수점 차이를 120만 칸 중 10칸까지 허용
      expect(vbad).toBeLessThanOrEqual(10);
      expect(vcol).toBeLessThanOrEqual(10);
    });
  }
});
