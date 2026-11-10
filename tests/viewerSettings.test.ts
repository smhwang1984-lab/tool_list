import { describe, expect, it } from 'vitest';
import { clampLineWidthPct, CUT_LINE_BASE_WIDTH, toolpathLineWidth } from '../src/core/viewerSettings';

// 원본 nc_viewer_widget.py clamp_line_width_pct / toolpath_line_width 와 같은 값 (Python 로 계산한 정답)
describe('Viewer 설정 값', () => {
  it('선 굵기 % 는 10 단위로 맞추고 범위를 자른다(.5는 짝수쪽)', () => {
    const cases: [unknown, number][] = [[90, 90], [25, 20], [35, 40], [5, 10], [0, 10], [250, 100], ['70', 70], ['x', 90], [null, 90], ['', 90], [14.9, 10], [15, 20]];
    for (const [input, want] of cases) expect(clampLineWidthPct(input), String(input)).toBe(want);
  });
  it('기준 90% 는 기준 굵기, 100% 는 10% 더 굵고, 10% 는 1px', () => {
    expect(toolpathLineWidth(CUT_LINE_BASE_WIDTH, 90)).toBeCloseTo(2.5, 10);
    expect(toolpathLineWidth(CUT_LINE_BASE_WIDTH, 100)).toBeCloseTo(2.75, 10);
    expect(toolpathLineWidth(CUT_LINE_BASE_WIDTH, 10)).toBeCloseTo(1.0, 10);
    expect(toolpathLineWidth(CUT_LINE_BASE_WIDTH, 50)).toBeCloseTo(1.0 + (1.5 * 40) / 80, 10);
  });
});
