import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { parseProgram } from '../src/core/millParser';
import { decodeProgramBytes } from '../src/core/programText';

// P1-T8: 큰 파일(ncdata.nc 약 600KB)을 읽고 산출하는 시간. 200ms 안이면 메인 스레드에서 직접 돌려도 된다.
describe('성능: 큰 NC 파일', () => {
  it('ncdata.nc 읽기+밀링 산출이 빠르다', () => {
    const raw = new Uint8Array(readFileSync(new URL('./fixtures/ncdata.nc', import.meta.url)));
    parseProgram(decodeProgramBytes(raw).text); // 예열
    const t0 = performance.now();
    const text = decodeProgramBytes(raw).text;
    const rows = parseProgram(text);
    const ms = performance.now() - t0;
    console.log(`ncdata.nc ${raw.length} bytes, rows ${rows.length}, ${ms.toFixed(1)} ms`);
    expect(ms).toBeLessThan(400);
  });
});
