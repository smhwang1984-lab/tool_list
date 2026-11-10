// 공구 리스트 PDF 배치 — 원본 export_tool_list_pdf / export_lathe_tool_list_pdf (ReportLab, NC_Tool_List.py 703~1030)
// pdfmake 문서 정의(순수 데이터)만 만든다. 글꼴을 읽고 PDF 로 굽는 일은 platform/pdf.ts 가 한다.
import { COLUMNS, LATHE_COLUMNS, type Column } from './columns';
import { RADIUS_COMP_DISPLAY_RE } from './radiusComp';
import type { ProgramMetadata } from './metadata';

export const PDF_COLUMN_WEIGHTS = [48, 100, 150, 40, 40, 40, 40, 40, 40, 40, 40, 60, 140, 70, 70, 88];
export const LATHE_PDF_COLUMN_WEIGHTS = [46, 175, 30, 30, 38, 175, 32, 60, 30, 32, 32, 80, 66, 74];
export const PDF_ROWS_PER_PAGE = 28;
export const PDF_METADATA_FIELDS: readonly [column: number, label: string, key: keyof ProgramMetadata][] = [
  [0, 'PART NO', 'part_no'], [3, 'OPERATION', 'operation'], [7, 'PROGRAM', 'program'], [11, 'RUN TIME', 'runtime'], [13, 'DATE', 'date'],
];

const MM = 72 / 25.4;
export const PAGE_W = 841.89; // A4 가로
export const PAGE_H = 595.276;
export const MARGIN_X = 18 * MM;
export const MARGIN_Y = 19 * MM;
export const AVAILABLE_WIDTH = PAGE_W - 2 * MARGIN_X;

const INFO_BLUE = '#BDDDEE';
const HEADER_GRAY = '#BFBFBF';
const ALT_GRAY = '#D9D9D9';
const FONT_BLUE = '#002F60';
const ALERT_RED = '#D00000';
const GRID_GRAY = '#9A9A9A';
const ROW_HEIGHTS = [16, 20, ...Array<number>(PDF_ROWS_PER_PAGE).fill(15.5)];
/** 글줄 높이(pt) 계산용 — pdfmake lineHeight 로 맞춘다 */
const LINE_FACTOR = 0.7;
/** Noto Sans KR 의 글줄 높이 비율(ascender+descender) */
const FONT_LINE = 1.448;

export const FONT_REGULAR = 'NotoSansKR';

export type PdfRow = Record<string, unknown> & {
  _SO_ALERT?: string; _SPINDL_ALERT?: string; _NO_ALERT?: string;
};

/** 앞뒤 공백을 떼고 비어 있으면 오늘 날짜(원본 normalized_pdf_metadata) */
export function normalizedPdfMetadata(metadata: Partial<ProgramMetadata> | null | undefined, today = new Date()): ProgramMetadata {
  const m = (metadata ?? {}) as Record<string, unknown>;
  const get = (k: string) => String(m[k] ?? '').trim();
  const iso = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, '0')}-${String(today.getDate()).padStart(2, '0')}`;
  return {
    part_no: get('part_no'), operation: get('operation'), program: get('program'), runtime: get('runtime'), date: get('date') || iso,
  } as ProgramMetadata;
}

export function pdfColumnWidths(lathe: boolean, available = AVAILABLE_WIDTH): number[] {
  const weights = lathe ? LATHE_PDF_COLUMN_WEIGHTS : PDF_COLUMN_WEIGHTS;
  const total = weights.reduce((a, b) => a + b, 0);
  // pdfmake 의 고정 폭은 안쪽 여백(좌우 2.5pt씩)을 뺀 값이다 — 칸 전체 폭이 원본 비율이 되도록 뺀다
  return weights.map((w) => (available * w) / total - 5);
}

type Align = 'left' | 'center';
const LATHE_CENTER = new Set(['R', 'T', 'PITCH', 'SO', 'KIND', 'DIR', 'TIP', 'D', 'SPINDL', 'FEED']);

function alignFor(lathe: boolean, key: string, col: number, tableRow: number): Align {
  // tableRow: 1 = 머리글, 2~ = 데이터 (원본 표의 행 번호)
  if (col <= 2 && tableRow >= 1) {
    if (lathe && tableRow >= 2 && LATHE_CENTER.has(key)) return 'center';
    return 'left';
  }
  if (lathe) return tableRow >= 2 && !LATHE_CENTER.has(key) ? 'left' : 'center';
  if (tableRow >= 2 && (col === 12 || col === 15)) return 'left';
  return 'center';
}

const rowFont = (i: number): number => (i === 0 ? 7.5 : i === 1 ? 7.2 : 6.5);
/** pdfmake 의 heights 는 안쪽 여백을 뺀 내용 높이다 — 원본 행 높이에서 위아래 여백을 뺀다 */
const verticalPad = (rowHeight: number, fontSize: number): number => Math.max(0, (rowHeight - fontSize * FONT_LINE * LINE_FACTOR) / 2);
const contentHeights = ROW_HEIGHTS.map((h, i) => h - 2 * verticalPad(h, rowFont(i)));

function remarkCell(text: string, fontSize: number, color: string, extra: Record<string, unknown>): Record<string, unknown> {
  // "(G41)" 같은 경보정 표기만 굵게 — 본문은 모두 굵은 글꼴이라 나머지는 보통 글꼴로 되돌린다(원본 v1.7.8)
  if (!text || !RADIUS_COMP_DISPLAY_RE.test(text)) return { text: text ?? '', ...extra, noWrap: true };
  const re = new RegExp(RADIUS_COMP_DISPLAY_RE.source, 'g');
  const parts: Record<string, unknown>[] = [];
  let pos = 0;
  for (const m of text.matchAll(re)) {
    if (m.index! > pos) parts.push({ text: text.slice(pos, m.index), bold: false });
    parts.push({ text: m[0], bold: true });
    pos = m.index! + m[0].length;
  }
  if (pos < text.length) parts.push({ text: text.slice(pos), bold: false });
  return { text: parts, fontSize, color, ...extra };
}

function infoRow(metadata: ProgramMetadata, lathe: boolean, colCount: number): Record<string, unknown>[] {
  const base = { font: FONT_REGULAR, bold: false, fontSize: 7.5, color: '#000000', fillColor: INFO_BLUE, alignment: 'left', noWrap: true };
  if (lathe) {
    const parts = PDF_METADATA_FIELDS.flatMap(([, label, key]) => {
      const value = String(metadata[key] ?? '').trim();
      return value ? [`${label} : ${value}`] : [];
    });
    return [{ ...base, text: parts.join('   |   '), colSpan: colCount }, ...Array.from({ length: colCount - 1 }, () => ({}))];
  }
  const cells: Record<string, unknown>[] = Array.from({ length: colCount }, () => ({ ...base, text: '' }));
  const spans: [number, number][] = [[0, 3], [3, 4], [7, 4], [11, 2], [13, 3]];
  PDF_METADATA_FIELDS.forEach(([col, label, key], i) => {
    cells[col] = { ...base, text: `${label} : ${String(metadata[key] ?? '')}`, colSpan: spans[i]![1] };
    for (let k = 1; k < spans[i]![1]; k++) cells[col + k] = {};
  });
  return cells;
}

function table(rows: PdfRow[], metadata: ProgramMetadata, lathe: boolean): Record<string, unknown> {
  const columns: readonly Column[] = lathe ? LATHE_COLUMNS : COLUMNS;
  const pageRows: (PdfRow | null)[] = [...rows];
  while (pageRows.length < PDF_ROWS_PER_PAGE) pageRows.push(null);

  const body: Record<string, unknown>[][] = [infoRow(metadata, lathe, columns.length)];
  body.push(columns.map(([key, label], col) => ({
    text: label, bold: true, fontSize: 7.2, color: FONT_BLUE, fillColor: HEADER_GRAY, alignment: alignFor(lathe, key, col, 1), noWrap: true,
  })));
  pageRows.forEach((row, i) => {
    const tableRow = i + 2;
    const fill = i % 2 === 1 ? ALT_GRAY : undefined; // 원본: 표의 3,5,7… 번째 줄(데이터 2,4,6… 번째)이 회색
    body.push(columns.map(([key], col) => {
      const value = row ? row[key] : '';
      const text = value === undefined || value === null ? '' : String(value);
      const alertKey = row && !lathe && (key === 'SO' || key === 'SPINDL' || key === 'NO') ? row[`${key}_ALERT`] : '';
      const common = { alignment: alignFor(lathe, key, col, tableRow), ...(fill ? { fillColor: fill } : {}) };
      const color = alertKey ? ALERT_RED : FONT_BLUE;
      if (key === 'REMARK') return remarkCell(text, 6.5, color, common);
      return { text, bold: true, fontSize: 6.5, color, noWrap: true, ...common };
    }));
  });

  return {
    table: { headerRows: 0, widths: pdfColumnWidths(lathe), heights: contentHeights, dontBreakRows: true, body },
    layout: {
      hLineWidth: () => 0.35, vLineWidth: () => 0.35, hLineColor: () => GRID_GRAY, vLineColor: () => GRID_GRAY,
      paddingLeft: () => 2.5, paddingRight: () => 2.5,
      paddingTop: (i: number) => verticalPad(ROW_HEIGHTS[i] ?? 15.5, rowFont(i)),
      paddingBottom: (i: number) => verticalPad(ROW_HEIGHTS[i] ?? 15.5, rowFont(i)),
    },
  };
}

/** pdfmake 문서 정의. rows 는 현재 표의 행(경고 표시용 _SO_ALERT/_SPINDL_ALERT/_NO_ALERT 포함 가능). */
export function buildPdfDefinition(
  rows: readonly PdfRow[], metadata: Partial<ProgramMetadata> | null | undefined, lathe: boolean, today = new Date(),
): Record<string, unknown> {
  const meta = normalizedPdfMetadata(metadata, today);
  const chunks: PdfRow[][] = [];
  for (let i = 0; i < rows.length; i += PDF_ROWS_PER_PAGE) chunks.push(rows.slice(i, i + PDF_ROWS_PER_PAGE));
  if (!chunks.length) chunks.push([]);
  const content = chunks.map((chunk, i) => ({ ...table(chunk, meta, lathe), ...(i < chunks.length - 1 ? { pageBreak: 'after' } : {}) }));
  return {
    pageSize: 'A4',
    pageOrientation: 'landscape',
    pageMargins: [MARGIN_X, MARGIN_Y, MARGIN_X, MARGIN_Y],
    defaultStyle: { font: FONT_REGULAR, fontSize: 6.5, lineHeight: LINE_FACTOR },
    info: { title: 'TOOL LIST', creator: 'Sum Path' },
    content,
  };
}
