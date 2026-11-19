// P6-T1/T2: Z-map 절삭 — 원본 nc_sim.ZMapStock 골든과 비교 (+ 공구 형상·소재 주석 단위 시험)
import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { gunzipSync } from 'node:zlib';
import { describe, expect, it } from 'vitest';
import { processNcLines } from '../src/core/toolpath';
import { buildSimProgram, toolpathBounds } from '../src/sim/segments';
import { autoResolution, parseStockSizeComment, StockSpec } from '../src/sim/stock';
import { toolShapeFromValues, type ToolValues } from '../src/sim/toolShape';
import { ZMapStock } from '../src/sim/zmap';
import { VoxelStock } from '../src/sim/voxel';

const DIR = join(__dirname, 'golden', 'zmap');
const FIX = join(__dirname, 'fixtures');
const M3 = '3축 MCT (X Y Z)';
const TYPES = ['FLAT E/M', 'BALL E/M', 'FILLET E/M', 'DRILL', 'CHAMFER MILL'];

function decode(buf: Buffer): string {
  try { return new TextDecoder('utf-8', { fatal: true }).decode(buf).replace(/^﻿/, ''); } catch { return new TextDecoder('euc-kr').decode(buf); }
}
function fakeShapeMap(): Map<string, ToolValues> {
  const map = new Map<string, ToolValues>();
  for (let n = 1; n < 100; n++) {
    const v: ToolValues = {
      type: TYPES[n % 5]!, D: 6 + (n % 5), FL: 20 + (n % 7), R: n % 5 === 2 ? 1 : null, SIG: n % 5 === 3 ? 118 : null,
      PL: n % 5 === 4 ? 0.5 : null, SO: null,
    };
    for (const key of [`T${String(n).padStart(2, '0')}`, `T${n}`, String(n)]) map.set(key, v);
  }
  return map;
}

describe('Z-map 골든', () => {
  for (const file of readdirSync(DIR).filter((f) => f.endsWith('.json') && !f.includes('__voxel'))) {
    it(file, () => {
      const g = JSON.parse(readFileSync(join(DIR, file), 'utf-8'));
      const lines = decode(readFileSync(join(FIX, g.file))).split(/\r\n|\r|\n/).slice(0, 700);
      const res = processNcLines(lines, M3, {});
      const prog = buildSimProgram(res, fakeShapeMap());
      const b = toolpathBounds(res, 2)!;
      expect(prog.seg.count - prog.tilted).toBe(g.segments);
      expect(prog.engine).toBe('zmap');
      const stock = new ZMapStock(b, g.resolution);
      expect([stock.nx, stock.ny]).toEqual([g.nx, g.ny]);
      stock.cutRange(prog.seg, prog.tools, 0, prog.seg.count);
      const bin = gunzipSync(readFileSync(join(DIR, file.replace('.json', '.bin.gz'))));
      const cells = g.nx * g.ny;
      const gh = new Float32Array(bin.buffer.slice(bin.byteOffset, bin.byteOffset + cells * 4));
      const gc = new Int16Array(bin.buffer.slice(bin.byteOffset + cells * 4, bin.byteOffset + cells * 6));
      let bad = 0;
      let maxDiff = 0;
      let badColor = 0;
      for (let i = 0; i < cells; i++) {
        const d = Math.abs(stock.heights[i]! - gh[i]!);
        maxDiff = Math.max(maxDiff, d);
        if (d > 0.01) bad++;
        if (stock.colorIds[i] !== gc[i]) badColor++;
      }
      expect(maxDiff).toBeLessThanOrEqual(0.01);
      expect(bad / cells).toBeLessThanOrEqual(0.001);
      expect(badColor / cells).toBeLessThanOrEqual(0.001);
      expect(stock.rapidWarnings.map((w) => [w.src, w.seq])).toEqual(g.rapid_warnings);
      expect(stock.anyCut()).toBe(g.cut);
    });
  }
});

describe('공구 형상 / 소재', () => {
  const v = (type: string, extra: Partial<ToolValues> = {}): ToolValues => ({ type, D: 10, FL: null, R: null, SIG: null, PL: null, SO: null, ...extra });
  it('공구 형상 종류', () => {
    expect(toolShapeFromValues(v('FLAT E/M'))!.radialLut(0.1).lut.every((x) => x === 0)).toBe(true);
    const ball = toolShapeFromValues(v('BALL E/M'))!.radialLut(0.1);
    expect(ball.lut[0]).toBeCloseTo(0, 9);
    expect(ball.lut[ball.lut.length - 2]).toBeCloseTo(5, 6); // 반경 끝 높이 = 반구 높이 R
    const drill = toolShapeFromValues(v('DRILL'))!.radialLut(0.1);
    expect(drill.lut[drill.lut.length - 2]).toBeCloseTo(5 / Math.tan((118 / 2) * (Math.PI / 180)), 6);
    expect(toolShapeFromValues(v('FLAT E/M', { D: 0 }))).toBeNull();
    expect(toolShapeFromValues(v('X', { PL: 1 }))!.radialLut(0.1).lut.at(-2)).toBeCloseTo(1, 6);
  });
  it('STOCK SIZE 주석', () => {
    expect(parseStockSizeComment(['%', '(STOCK SIZE : T50 W95 L385)', 'G0'])).toEqual({ T: 50, W: 95, L: 385 });
    expect(parseStockSizeComment(['(STOCK SIZE 10 20 30)'])).toEqual({ T: 10, W: 20, L: 30 });
    expect(parseStockSizeComment(['G1 X1 Y1', '(STOCK SIZE : T50 W95 L385)'])).toBeNull();
    expect(parseStockSizeComment(['(STOCK SIZE : T0 W95 L385)'])).toBeNull();
  });
  it('StockSpec bounds / 자동 해상도', () => {
    const s = new StockSpec({ T: 20, W: 40, L: 100 }, { T: 'Z', W: 'Y', L: 'X' });
    expect(s.bounds()).toEqual({ X: [-50, 50], Y: [-20, 20], Z: [-20, 0] });
    const s2 = new StockSpec({ T: 20, W: 40, L: 100 }, { T: 'Z', W: 'Y', L: 'X' }, { X: 'neg', Z: 'bottom' }, { Y: 5 });
    expect(s2.bounds()).toEqual({ X: [0, 100], Y: [-15, 25], Z: [0, 20] });
    expect(() => new StockSpec({ T: 1, W: 1, L: 1 }, { T: 'Z', W: 'Z', L: 'X' })).toThrow();
    expect(autoResolution(s.bounds())).toBe(autoResolution({ X: [-50, 50], Y: [-20, 20], Z: [-20, 0] }));
    expect(autoResolution({ X: [0, 1], Y: [0, 1], Z: [0, 1] })).toBe(0.05);
  });
});

describe('3D 복셀 골든', () => {
  for (const file of readdirSync(DIR).filter((f) => f.endsWith('__voxel.json'))) {
    it(file, () => {
      const g = JSON.parse(readFileSync(join(DIR, file), 'utf-8'));
      const lines = decode(readFileSync(join(FIX, g.file))).split(/\r\n|\r|\n/).slice(0, 700);
      const res = processNcLines(lines, g.machine, g.specs);
      const prog = buildSimProgram(res, fakeShapeMap());
      expect(prog.engine).toBe('voxel');
      const b = toolpathBounds(res, 2)!;
      const stock = new VoxelStock(b, g.resolution);
      expect([stock.nx, stock.ny, stock.nz]).toEqual(g.shape);
      stock.cutRange(prog.seg, prog.tools, prog.axes0, prog.axes1, 0, Math.min(g.limit, prog.seg.count));
      const bin = gunzipSync(readFileSync(join(DIR, file.replace('.json', '.bin.gz'))));
      const n = g.shape[0] * g.shape[1] * g.shape[2];
      let badOcc = 0;
      let badCol = 0;
      for (let i = 0; i < n; i++) {
        if (stock.occ[i] !== bin[i]) badOcc++;
        else if (stock.col[i] !== bin[n + i]) badCol++;
      }
      expect(badOcc / n).toBeLessThanOrEqual(0.001);
      expect(badCol / n).toBeLessThanOrEqual(0.001);
      expect(stock.rapidWarnings.map((w) => [w.src, w.seq])).toEqual(g.rapid_warnings);
    });
  }
});
