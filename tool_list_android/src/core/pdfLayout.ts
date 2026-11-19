// 공구 리스트 PDF 배치 — 원본 export_tool_list_pdf / export_lathe_tool_list_pdf (ReportLab, NC_Tool_List.py 703~1030)
// pdfmake 문서 정의(순수 데이터)만 만든다. 글꼴을 읽고 PDF 로 굽는 일은 platform/pdf.ts 가 한다.
import { COLUMNS, LATHE_COLUMNS, type Column } from './columns';
import { RADIUS_COMP_DISPLAY_RE, hasCompDisplay, isProbeMismatch } from './radiusComp';
import type { ProgramMetadata } from './metadata';

// v2.5.5: REMARK 88→130(프로브 2줄 표기 자리), NAME 150→135, 홀더 140→113 — 합계 동일
export const PDF_COLUMN_WEIGHTS = [48, 100, 135, 40, 40, 40, 40, 40, 40, 40, 40, 60, 113, 70, 70, 130];
// v2.5.8: 선반 REMARK 74→130(M300/M200 2줄에 측정한 N번호가 붙어 길어짐), INSERT/홀더 합계 56 감소 — 합계 동일
export const LATHE_PDF_COLUMN_WEIGHTS = [46, 148, 30, 30, 38, 146, 32, 60, 30, 32, 32, 80, 66, 130];
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

/** 2줄 REMARK 의 글자 크기, 그 행의 위아래 여백(pt) */
const TWO_LINE_REMARK_FONT = 5.6;
const TWO_LINE_PAD = 1.6;
const rowFont = (i: number): number => (i === 0 ? 7.5 : i === 1 ? 7.2 : 6.5);
/** pdfmake 의 heights 는 안쪽 여백을 뺀 내용 높이다 — 원본 행 높이에서 위아래 여백을 뺀다 */
const verticalPad = (rowHeight: number, fontSize: number): number => Math.max(0, (rowHeight - fontSize * FONT_LINE * LINE_FACTOR) / 2);
const contentHeights = ROW_HEIGHTS.map((h, i) => h - 2 * verticalPad(h, rowFont(i)));

/** 굵은 맑은 고딕 영문·숫자 한 글자의 평균 폭(em) — 실측 0.52에 여유를 얹은 값 */
const REMARK_CHAR_EM = 0.56;
const REMARK_MIN_FONT = 4.2;

/**
 * v2.5.8: REMARK 한 줄이 칸 폭(pt)을 넘으면 글자를 줄이고, 최소 크기에서도 넘으면
 * "N1, M300H3:N3, N7, N12" 의 N 나열을 "M300H3:N3 외2" 로 줄인다 — 줄바꿈으로 다음 줄과 겹치는 것을 막는다.
 */
export function fitRemarkLine(line: string, maxWidth: number, size: number): { line: string; size: number } {
  const width = (t: string, pt: number): number => t.length * pt * REMARK_CHAR_EM;
  if (!maxWidth || width(line, size) <= maxWidth) return { line, size };
  const fitted = (maxWidth / width(line, size)) * size;
  if (fitted >= REMARK_MIN_FONT) return { line, size: fitted };
  const short = line.split(' · ').map((item) => {
    const m = /(M[23]00[^:\s]*):(.*)$/.exec(item);
    const names = m ? m[2]!.split(', ') : [];
    return m && names.length > 1 ? `${item.slice(0, m.index)}${m[1]}:${names[0]} 외${names.length - 1}` : item;
  }).join(' · ');
  return { line: short, size: Math.max(REMARK_MIN_FONT, Math.min(size, (maxWidth / width(short, size)) * size)) };
}

function remarkCell(text: string, fontSize: number, color: string, extra: Record<string, unknown>, maxWidth = 0): Record<string, unknown> {
  // "(G41)" 같은 경보정 표기만 굵게 — 본문은 모두 굵은 글꼴이라 나머지는 보통 글꼴로 되돌린다(원본 v1.7.8)
  if (!text || !hasCompDisplay(text)) return { text: text ?? '', ...extra, noWrap: true };
  const re = new RegExp(RADIUS_COMP_DISPLAY_RE.source, 'gu');
  const parts: Record<string, unknown>[] = [];
  const twoLine = text.includes('\n');
  text.split('\n').forEach((rawLine, index) => {
    if (index > 0) parts.push({ text: '\n', bold: false });
    const base = twoLine ? (index === 1 ? TWO_LINE_REMARK_FONT - 0.6 : TWO_LINE_REMARK_FONT) : fontSize;
    const { line, size: lineSize } = fitRemarkLine(rawLine, maxWidth, base);
    const size = Math.abs(lineSize - (twoLine ? TWO_LINE_REMARK_FONT : fontSize)) > 0.05 ? { fontSize: lineSize } : {};
    let pos = 0;
    for (const m of line.matchAll(re)) {
      if (m.index! > pos) parts.push({ text: line.slice(pos, m.index), bold: false, ...size });
      parts.push(isProbeMismatch(m[0]) ? { text: m[0], bold: true, color: '#d00000', ...size } : { text: m[0], bold: true, ...size });
      pos = m.index! + m[0].length;
    }
    if (pos < line.length) parts.push({ text: line.slice(pos), bold: false, ...size });
  });
  // 2줄이면 15.5pt 행에 들어가게 글자·줄간격을 줄인다(원본 v2.5.5)
  return twoLine ? { text: parts, fontSize: TWO_LINE_REMARK_FONT, lineHeight: 0.75, color, ...extra } : { text: parts, fontSize, color, ...extra };
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
  const widths = pdfColumnWidths(lathe);
  const tight = pageRows.map((row) => !lathe && !!row && String(row['REMARK'] ?? '').includes('\n'));
  pageRows.forEach((row, i) => {
    const tableRow = i + 2;
    const fill = i % 2 === 1 ? ALT_GRAY : undefined; // 원본: 표의 3,5,7… 번째 줄(데이터 2,4,6… 번째)이 회색
    body.push(columns.map(([key], col) => {
      const value = row ? row[key] : '';
      const text = value === undefined || value === null ? '' : String(value);
      const alertKey = row && !lathe && (key === 'SO' || key === 'SPINDL' || key === 'NO') ? row[`${key}_ALERT`] : '';
      // 2줄 REMARK 행: 여백을 줄였으므로 다른 칸은 아래로 내려 세로 가운데에 맞춘다
      const shift = tight[i] && key !== 'REMARK' ? { margin: [0, verticalPad(ROW_HEIGHTS[tableRow]!, rowFont(tableRow)) - TWO_LINE_PAD, 0, 0] } : {};
      const common = { alignment: alignFor(lathe, key, col, tableRow), ...(fill ? { fillColor: fill } : {}), ...shift };
      const color = alertKey ? ALERT_RED : FONT_BLUE;
      if (key === 'REMARK') return remarkCell(text, 6.5, color, common, widths[col]!);
      return { text, bold: true, fontSize: 6.5, color, noWrap: true, ...common };
    }));
  });

  return {
    table: { headerRows: 0, widths, heights: contentHeights, dontBreakRows: true, body },
    layout: {
      hLineWidth: () => 0.35, vLineWidth: () => 0.35, hLineColor: () => GRID_GRAY, vLineColor: () => GRID_GRAY,
      paddingLeft: () => 2.5, paddingRight: () => 2.5,
      paddingTop: (i: number) => (i >= 2 && tight[i - 2] ? TWO_LINE_PAD : verticalPad(ROW_HEIGHTS[i] ?? 15.5, rowFont(i))),
      paddingBottom: (i: number) => (i >= 2 && tight[i - 2] ? TWO_LINE_PAD : verticalPad(ROW_HEIGHTS[i] ?? 15.5, rowFont(i))),
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
