import { describe, expect, it } from 'vitest';
import { writeStlBinary } from '../src/sim/stl';

describe('STL', () => {
  it('삼각형 하나 = 134바이트, 법선 +Z', () => {
    const b = writeStlBinary([0, 0, 0, 1, 0, 0, 0, 1, 0], [0, 1, 2]);
    expect(b.length).toBe(134);
    const dv = new DataView(b.buffer);
    expect(dv.getUint32(80, true)).toBe(1);
    expect(dv.getFloat32(84 + 8, true)).toBeCloseTo(1, 6);
  });
});
