// 편집 모드 비밀번호 — 원본 _edit_password_hash / verify_edit_password / set_edit_password (v2.2.7)
//
// 기본값은 1234. 새로 설정하면 PBKDF2-SHA256 해시(+salt)만 설정에 저장한다. 설정에 항목이 없거나 깨졌으면
// 기본값으로 되돌아간다(관리자가 항목을 지우면 초기화). 해시 형식이 원본과 같아서, 데스크톱 앱이 만든
// 항목을 이 앱이 검증하고 이 앱이 만든 항목을 데스크톱 앱이 검증할 수 있다.
//
// 설정 파일(Preferences) 읽기·쓰기는 platform/ 에서 한다 — 여기서는 항목(entry) 객체만 다룬다.
import { PyError, pyIntFrom, pyStr } from './py';

export const EDIT_PASSWORD_DEFAULT = '1234';
export const EDIT_PASSWORD_ITERATIONS = 200000;
const DEFAULT_SALT = new TextEncoder().encode('NCToolList-edit-default');

/** 설정에 저장하는 모양 { algo, iter, salt(16진수), hash(16진수) } */
export interface EditPasswordEntry {
  algo: 'pbkdf2_sha256';
  iter: number;
  salt: string;
  hash: string;
}

/** PBKDF2-HMAC-SHA256, 결과 32바이트 */
export async function editPasswordHash(password: unknown, salt: Uint8Array, iterations: number): Promise<Uint8Array> {
  if (!(iterations >= 1)) throw new PyError('ValueError', 'iterations must be positive');
  const key = await crypto.subtle.importKey('raw', new TextEncoder().encode(pyStr(password)), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: salt as Uint8Array<ArrayBuffer>, iterations }, key, 256);
  return new Uint8Array(bits);
}

const ASCII_WS = new Set([' ', '\t', '\n', '\r', '\x0b', '\x0c']);
const hexVal = (c: string | undefined): number => (c !== undefined && /^[0-9a-fA-F]$/.test(c) ? parseInt(c, 16) : -1);

/** bytes.fromhex — 바이트 사이의 공백은 건너뛰고, 짝이 안 맞거나 16진수가 아니면 ValueError */
export function hexToBytes(s: unknown): Uint8Array {
  if (typeof s !== 'string') throw new PyError('TypeError', 'fromhex() argument must be str');
  const out: number[] = [];
  let i = 0;
  while (i < s.length) {
    if (ASCII_WS.has(s[i]!)) {
      i++;
      continue;
    }
    const hi = hexVal(s[i]);
    const lo = hexVal(s[i + 1]);
    if (hi < 0 || lo < 0) throw new PyError('ValueError', 'non-hexadecimal number found in fromhex()');
    out.push(hi * 16 + lo);
    i += 2;
  }
  return Uint8Array.from(out);
}

export function bytesToHex(bytes: Uint8Array): string {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

/** 길이가 다르면 false, 같으면 모든 바이트를 끝까지 비교한다 (hmac.compare_digest) */
function constantTimeEqual(a: Uint8Array, b: Uint8Array): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a[i]! ^ b[i]!;
  return diff === 0;
}

const isDict = (v: unknown): v is Record<string, unknown> => v !== null && typeof v === 'object' && !Array.isArray(v);

/**
 * 비밀번호가 맞는지. entry 는 설정에 저장된 항목(없거나 깨졌으면 undefined/아무 값이나).
 * 항목이 올바르면 그 해시와 비교하고, 아니면 기본 비밀번호(1234)와 비교한다.
 */
export async function verifyEditPassword(password: unknown, entry?: unknown): Promise<boolean> {
  try {
    if (isDict(entry) && entry.algo === 'pbkdf2_sha256') {
      for (const key of ['iter', 'salt', 'hash']) if (!(key in entry)) throw new PyError('KeyError', key);
      const iterations = pyIntFrom(entry.iter);
      const salt = hexToBytes(entry.salt);
      const expected = hexToBytes(entry.hash);
      return constantTimeEqual(await editPasswordHash(password, salt, iterations), expected);
    }
  } catch (error) {
    if (!(error instanceof PyError) || !['KeyError', 'ValueError', 'TypeError'].includes(error.pyType)) throw error;
  }
  return constantTimeEqual(
    await editPasswordHash(password, DEFAULT_SALT, 1000),
    await editPasswordHash(EDIT_PASSWORD_DEFAULT, DEFAULT_SALT, 1000),
  );
}

/** 새 비밀번호의 설정 항목을 만든다. salt 를 안 주면 무작위 16바이트. */
export async function createEditPasswordEntry(password: unknown, salt?: Uint8Array): Promise<EditPasswordEntry> {
  const s = salt ?? crypto.getRandomValues(new Uint8Array(16));
  return {
    algo: 'pbkdf2_sha256',
    iter: EDIT_PASSWORD_ITERATIONS,
    salt: bytesToHex(s),
    hash: bytesToHex(await editPasswordHash(password, s, EDIT_PASSWORD_ITERATIONS)),
  };
}
