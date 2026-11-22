// G8 확대 고정밀 — 원본 tests/test_nc_sim_viewer.py test_quality_zoom_* 와 같은 약속
import { describe, expect, it } from 'vitest';
import { GPU_MIN_RESOLUTION, resolutionForCells } from '../src/sim/gpuCells';
import { clipZoomBounds, ZOOM_CELLS, ZOOM_CPU_CELLS, ZOOM_MIN_RESOLUTION } from '../src/sim/zoomRegion';
import type { Bounds } from '../src/sim/stock';

const STOCK: Bounds = { X: [-50, 50], Y: [-30, 30], Z: [-20, 0] };

describe('확대 고정밀', () => {
  it('보이는 영역으로 소재 XY를 자르고 Z는 그대로 둔다', () => {
    const b = clipZoomBounds(STOCK, { X: [-5, 5], Y: [-5, 5] })!;
    expect(b).toEqual({ X: [-5, 5], Y: [-5, 5], Z: [-20, 0] });
    expect(STOCK.X).toEqual([-50, 50]);                       // 원본은 건드리지 않는다
    expect(clipZoomBounds(STOCK, { X: [40, 200], Y: [-100, 100] })!.X).toEqual([40, 50]);
  });
  it('겹치지 않거나 너무 작으면 거절한다', () => {
    expect(clipZoomBounds(STOCK, { X: [900, 910], Y: [900, 910] })).toBeNull();
    expect(clipZoomBounds(STOCK, { X: [49.99, 60], Y: [-5, 5] })).toBeNull();
  });
  it('4096 칸 · 10mm 영역은 0.01mm 아래 셀(0.002mm 한계까지)', () => {
    const b = clipZoomBounds(STOCK, { X: [-5, 5], Y: [-5, 5] })!;
    const res = resolutionForCells(b, ZOOM_CELLS, ZOOM_MIN_RESOLUTION);
    expect(res).toBeLessThan(0.01);
    expect(res).toBeCloseTo(10 / 4095, 9);
    expect(resolutionForCells(b, 1_000_000, ZOOM_MIN_RESOLUTION)).toBe(ZOOM_MIN_RESOLUTION);
    expect(resolutionForCells(b, ZOOM_CELLS)).toBe(GPU_MIN_RESOLUTION);   // 일반 GPU 엔진은 0.01mm 가 바닥
    expect(ZOOM_CPU_CELLS).toBe(1200);
  });
});
