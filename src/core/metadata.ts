// 출력 정보(PDF 정보행·화면 좌상단) — 원본 parse_program_metadata / program_header_text / default_pdf_filename
import { normalizeMetadataKey } from './text';
import {
  RE_I, RE_M, RE_S, grp, pyRe, pySplitWs, pyStr, pyStrip, reFinditer, reMatch, reSearch, reSub,
} from './py';

export interface ProgramMetadata {
  part_no: string;
  operation: string;
  program: string;
  runtime: string;
  date: string;
}

export const METADATA_ALIASES: Readonly<Record<keyof ProgramMetadata, readonly string[]>> = {
  part_no: ['PARTNO', 'PARTNUMBER', 'PART'],
  operation: ['OPERATION', 'OPERATIONNO', 'OPER', 'OP'],
  program: ['PROGRAM', 'PROGRAMNO', 'PGM', 'PGMNO'],
  runtime: ['RUNTIME', 'COMPLETETIME', 'CYCLETIME', 'MACHININGTIME', 'TOTALTIME'],
  date: ['DATE', 'PROGRAMDATE', 'CREATEDATE', 'CREATIONDATE'],
};
const METADATA_KEYS = Object.keys(METADATA_ALIASES) as (keyof ProgramMetadata)[];

const COMMENT_RE = pyRe(String.raw`\(([^()]*)\)`, RE_S);
const KEY_VALUE_RE = pyRe(String.raw`^\s*([^:=]+?)\s*[:=]\s*(.*?)\s*$`, RE_S);
const PROGRAM_NO_RE = pyRe(String.raw`^\s*(O\d+)\b`, RE_I | RE_M);
const PROGRAM_HEADER_RE = pyRe(String.raw`^\s*(O\d+)\s*(?:\(([^)\r\n]*)\))?`, RE_I | RE_M);
const OPERATION_FROM_PROGRAM_RE = pyRe(
  String.raw`(?<![A-Z0-9])(OP(?:ERATION)?\s*[-_ ]?\d+[A-Z]?)(?=$|[^A-Z0-9])`, RE_I,
);

/** NC 헤더 주석에서 PDF 정보행에 들어갈 값을 뽑는다. */
export function parseProgramMetadata(text: string | null | undefined): ProgramMetadata {
  const src = text || '';
  const metadata: ProgramMetadata = { part_no: '', operation: '', program: '', runtime: '', date: '' };
  for (const c of reFinditer(COMMENT_RE, src)) {
    const comment = c[1]!;
    const match = reMatch(KEY_VALUE_RE, comment);
    if (!match) continue;
    const sourceKey = normalizeMetadataKey(match[1]!);
    const value = pySplitWs(match[2]!).join(' ');
    if (!value) continue;
    for (const target of METADATA_KEYS) {
      if (METADATA_ALIASES[target].includes(sourceKey) && !metadata[target]) {
        metadata[target] = value;
        break;
      }
    }
  }
  const programMatch = reSearch(PROGRAM_NO_RE, src);
  if (!metadata.program && programMatch) metadata.program = programMatch[1]!.toUpperCase();
  const program = metadata.program;
  const opMatch = reSearch(OPERATION_FROM_PROGRAM_RE, program);
  if (opMatch && !metadata.operation) {
    metadata.operation = normalizeMetadataKey(opMatch[1]!).split('OPERATION').join('OP');
  }
  if (opMatch && !metadata.part_no) {
    const remainder = program.slice(0, opMatch.index) + program.slice(opMatch.index + opMatch[0].length);
    metadata.part_no = pyStrip(remainder, ' _-/');
  }
  return metadata;
}

/** 화면 좌상단 문구 — `%` 아래 첫 `Onnnn` 줄을 `Onnnn(내용)`으로 (주석이 비면 `Onnnn`). */
export function programHeaderText(text: string | null | undefined): string {
  const match = reSearch(PROGRAM_HEADER_RE, (text || '').slice(0, 2000));
  if (!match) return '';
  const programNo = match[1]!.toUpperCase();
  const comment = pyStrip(grp(match, 2) ?? '');
  return comment ? `${programNo}(${comment})` : programNo;
}

const PDF_NAME_UNSAFE_RE = pyRe(String.raw`[^\w.-]+`);

/** PDF 기본 파일 이름 (part_no_operation_program_TOOL_LIST.pdf) */
export function defaultPdfFilename(metadata: object): string {
  const parts = ['part_no', 'operation', 'program'].map((key) => (metadata as Record<string, unknown>)[key]);
  let stem = parts.filter((v) => v !== null && v !== undefined && v !== '' && v !== 0 && v !== false)
    .map((v) => pyStrip(pyStr(v))).join('_');
  stem = pyStrip(reSub(PDF_NAME_UNSAFE_RE, '_', stem), '_.');
  return (stem || 'NC') + '_TOOL_LIST.pdf';
}
