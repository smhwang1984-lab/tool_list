// 프로그램 파일 읽기/저장: 인코딩·줄바꿈 보존 — 원본 decode_program_bytes / save_program_text(인코딩 부분) /
// program_text_digest (v2.2.7)
//
// - 읽기: UTF-8(BOM 있든 없든) → CP949 순으로 엄격하게 시도하고, 둘 다 안 되면 UTF-8 로 읽되 깨진 글자를
//   대체 문자로 바꾸고 "손실" 표시를 한다. 줄바꿈은 LF 로 통일하고 원래 줄바꿈(CRLF/LF)을 따로 돌려준다.
// - 저장: 읽을 때의 인코딩/줄바꿈으로 되돌린다. 인코딩할 수 없는 글자가 있으면 아무것도 쓰기 전에 오류.
//   (.bak 남기기·임시 파일·교체 같은 파일 작업은 platform/ 에서 한다)
// - PG ADD(여러 파일 이어붙이기)는 Android 버전에서 제외했다.
//
// CP949 는 원본 Python 코덱의 표를 cp949Table.ts 에 내장해 쓴다(WebView·Node 의 euc-kr 은 표가 달라 쓰지 않는다).
// 같은 표인지는 tests/golden 으로 전체 2바이트 조합을 비교해 확인한다.
import { CP949_RUNS } from './cp949Table';
import { PyError } from './py';

export type ProgramEncoding = 'utf-8' | 'utf-8-sig' | 'cp949';

export interface DecodedProgram {
  /** 줄바꿈을 LF 로 통일한 본문 */
  text: string;
  encoding: ProgramEncoding;
  /** 원래 파일의 줄바꿈 */
  newline: '\n' | '\r\n';
  /** 어느 인코딩으로도 못 읽어 깨진 글자를 대체 문자로 바꿨는가 */
  lossy: boolean;
}

const BOM = [0xef, 0xbb, 0xbf];

function startsWithBom(raw: Uint8Array): boolean {
  return raw.length >= 3 && raw[0] === BOM[0] && raw[1] === BOM[1] && raw[2] === BOM[2];
}

function containsCrLf(raw: Uint8Array): boolean {
  for (let i = 0; i + 1 < raw.length; i++) if (raw[i] === 0x0d && raw[i + 1] === 0x0a) return true;
  return false;
}

/** 바이트 -> {본문, 인코딩, 줄바꿈, 손실 여부}. */
export function decodeProgramBytes(raw: Uint8Array): DecodedProgram {
  let text: string;
  let encoding: ProgramEncoding;
  let lossy = false;
  try {
    text = new TextDecoder('utf-8', { fatal: true }).decode(raw); // BOM 은 읽으면서 걷어낸다
    encoding = startsWithBom(raw) ? 'utf-8-sig' : 'utf-8';
  } catch {
    const cp949 = decodeCp949(raw);
    if (cp949 !== null) {
      text = cp949;
      encoding = 'cp949';
    } else {
      // 둘 다 안 된다 — UTF-8 로 읽고 깨진 곳은 대체 문자. (Python 'replace' 처럼 BOM 글자도 그대로 둔다)
      text = new TextDecoder('utf-8', { ignoreBOM: true }).decode(raw);
      encoding = 'utf-8';
      lossy = true;
    }
  }
  const newline = containsCrLf(raw) ? '\r\n' : '\n';
  return { text: text.replace(/\r\n/g, '\n').replace(/\r/g, '\n'), encoding, newline, lossy };
}

// ---------------------------------------------------------------- CP949 (내장 표)
let decodeMap: Map<number, number> | null = null;
let encodeMap: Map<number, number> | null = null;

function loadCp949(): void {
  if (decodeMap) return;
  decodeMap = new Map();
  encodeMap = new Map();
  let pos = 0;
  let cp = 0;
  for (let i = 0; i < CP949_RUNS.length; i += 3) {
    pos += CP949_RUNS[i]!;
    cp += CP949_RUNS[i + 1]!;
    const n = CP949_RUNS[i + 2]!;
    for (let k = 0; k < n; k++) {
      decodeMap.set(pos + k, cp + k);
      encodeMap.set(cp + k, pos + k);
    }
    pos += n;
    cp += n;
  }
}

/** 엄격한 CP949 읽기(Python bytes.decode('cp949')). 표에 없으면 null. */
export function decodeCp949(raw: Uint8Array): string | null {
  loadCp949();
  const parts: string[] = [];
  let ascii = '';
  for (let i = 0; i < raw.length; i++) {
    const b = raw[i]!;
    if (b < 0x80) {
      ascii += String.fromCharCode(b);
      continue;
    }
    if (i + 1 >= raw.length) return null;
    const cp = decodeMap!.get(b * 256 + raw[i + 1]!);
    if (cp === undefined) return null;
    ascii += String.fromCodePoint(cp);
    i++;
  }
  parts.push(ascii);
  return parts.join('');
}

/** 모든 글자를 CP949 로. 표에 없는 글자는 UnicodeEncodeError (PyError). */
export function encodeCp949(text: string): Uint8Array {
  loadCp949();
  const out: number[] = [];
  for (const ch of text) {
    const cp = ch.codePointAt(0)!;
    if (cp < 0x80) {
      out.push(cp);
      continue;
    }
    const pos = encodeMap!.get(cp);
    if (pos === undefined) throw new PyError('UnicodeEncodeError', `'cp949' codec can't encode character U+${cp.toString(16)}`);
    out.push(pos >> 8, pos & 255);
  }
  return Uint8Array.from(out);
}

/** 저장할 바이트. 본문의 LF 를 원래 줄바꿈으로 되돌리고 원래 인코딩으로 만든다. */
export function encodeProgramText(
  text: string, encoding: ProgramEncoding | string = 'utf-8', newline: string = '\n',
): Uint8Array {
  const body = text.split('\n').join(newline);
  if (encoding === 'cp949') return encodeCp949(body);
  if (encoding === 'utf-8' || encoding === 'utf-8-sig') {
    if (/[\ud800-\udfff]/.test(body.replace(/[\ud800-\udbff][\udc00-\udfff]/g, ''))) {
      throw new PyError('UnicodeEncodeError', "'utf-8' codec can't encode surrogate");
    }
    const bytes = new TextEncoder().encode(body);
    if (encoding === 'utf-8') return bytes;
    const withBom = new Uint8Array(bytes.length + 3);
    withBom.set(BOM, 0);
    withBom.set(bytes, 3);
    return withBom;
  }
  throw new PyError('LookupError', `unknown encoding: ${encoding}`);
}

/** 편집 내용이 바뀌었는지, 파일이 밖에서 바뀌었는지 비교하는 SHA-1 (소문자 16진수) */
export async function programTextDigest(text: string): Promise<string> {
  const hash = await crypto.subtle.digest('SHA-1', new TextEncoder().encode(text));
  return Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, '0')).join('');
}
