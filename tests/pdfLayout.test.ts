import { describe, expect, it } from 'vitest';
import { AVAILABLE_WIDTH, buildPdfDefinition, normalizedPdfMetadata, pdfColumnWidths, PDF_ROWS_PER_PAGE } from '../src/core/pdfLayout';

describe('pdfLayout', () => {
  it('열 폭 합(여백 포함)이 인쇄 폭과 같다', () => {
    for (const lathe of [false, true]) {
      const sum = pdfColumnWidths(lathe).reduce((a, b) => a + b + 5, 0);
      expect(sum).toBeCloseTo(AVAILABLE_WIDTH, 6);
    }
  });
  it('28행마다 페이지가 나뉘고 빈 목록도 한 쪽이다', () => {
    const rows = Array.from({ length: PDF_ROWS_PER_PAGE * 2 + 1 }, (_, i) => ({ NO: `T${i}` }));
    expect((buildPdfDefinition(rows, {}, false).content as unknown[]).length).toBe(3);
    expect((buildPdfDefinition([], {}, false).content as unknown[]).length).toBe(1);
  });
  it('날짜가 비면 오늘 날짜', () => {
    expect(normalizedPdfMetadata({}, new Date(2026, 10, 9)).date).toBe('2026-11-09');
    expect(normalizedPdfMetadata({ date: ' 2020-01-01 ' }).date).toBe('2020-01-01');
  });
});
