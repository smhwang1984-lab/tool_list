// 파일 접근 — 앱에서는 네이티브 플러그인(NcFilesPlugin, SAF), 브라우저(개발·시험)에서는 <input type=file> / 내려받기.
import { Capacitor, registerPlugin, type PluginListenerHandle } from '@capacitor/core';

export interface FileInfo {
  /** 같은 파일에 다시 쓰거나 다시 읽을 때 쓰는 주소(브라우저에서는 null) */
  uri: string | null;
  name: string;
  size: number;
  /** 수정 시각(ms, 모르면 0) */
  modified: number;
  /** 같은 파일에 덮어쓸 수 있는가 */
  writable: boolean;
}

export interface OpenedFile extends FileInfo {
  bytes: Uint8Array;
}

interface NativeResult extends Partial<FileInfo> {
  cancelled?: boolean;
  none?: boolean;
  missing?: boolean;
  data?: string;
  path?: string;
}

interface NcFilesNative {
  openDocument(): Promise<NativeResult>;
  readDocument(o: { uri: string }): Promise<NativeResult>;
  statDocument(o: { uri: string }): Promise<NativeResult>;
  writeDocument(o: { uri: string; data: string }): Promise<NativeResult>;
  createDocument(o: { name: string; data: string }): Promise<NativeResult>;
  saveBackup(o: { name: string; data: string }): Promise<NativeResult>;
  takeIncoming(): Promise<NativeResult>;
  addListener(event: 'incoming', fn: () => void): Promise<PluginListenerHandle>;
}

const native = (): boolean => {
  try {
    return Capacitor.isNativePlatform();
  } catch {
    return false;
  }
};
const plugin = registerPlugin<NcFilesNative>('NcFiles');

export function toBase64(bytes: Uint8Array): string {
  let s = '';
  const CHUNK = 0x8000;
  for (let i = 0; i < bytes.length; i += CHUNK) s += String.fromCharCode(...bytes.subarray(i, i + CHUNK));
  return btoa(s);
}

export function fromBase64(b64: string): Uint8Array {
  const s = atob(b64);
  const out = new Uint8Array(s.length);
  for (let i = 0; i < s.length; i++) out[i] = s.charCodeAt(i);
  return out;
}

const info = (r: NativeResult): FileInfo => ({
  uri: r.uri ?? null, name: r.name ?? 'program.nc', size: r.size ?? 0, modified: r.modified ?? 0, writable: Boolean(r.writable),
});

const opened = (r: NativeResult): OpenedFile => ({ ...info(r), bytes: fromBase64(r.data ?? '') });

/** 이 환경에서 같은 파일에 다시 쓰고 변경을 감지할 수 있는가 (앱에서만) */
export const canWriteInPlace = (): boolean => native();

/** 파일 선택기에서 NC 파일 하나를 고른다. 취소하면 null. */
export async function openFile(): Promise<OpenedFile | null> {
  if (native()) {
    const r = await plugin.openDocument();
    return r.cancelled ? null : opened(r);
  }
  return new Promise((resolve) => {
    const input = document.createElement('input');
    input.type = 'file';
    input.addEventListener('change', async () => {
      const file = input.files?.[0];
      if (!file) return resolve(null);
      resolve({
        uri: null, name: file.name, size: file.size, modified: file.lastModified, writable: false,
        bytes: new Uint8Array(await file.arrayBuffer()),
      });
    });
    input.addEventListener('cancel', () => resolve(null));
    input.click();
  });
}

export async function readFile(uri: string): Promise<OpenedFile> {
  return opened(await plugin.readDocument({ uri }));
}

/** 크기·수정 시각. 파일이 없어졌으면 null. */
export async function statFile(uri: string): Promise<FileInfo | null> {
  if (!native()) return null;
  const r = await plugin.statDocument({ uri });
  return r.missing ? null : info(r);
}

/** 같은 파일에 덮어쓴다. */
export async function writeFile(uri: string, bytes: Uint8Array): Promise<FileInfo> {
  return info(await plugin.writeDocument({ uri, data: toBase64(bytes) }));
}

/** 다른 이름으로 저장. 앱에서는 저장 위치를 고르고, 브라우저에서는 내려받는다. 취소하면 null. */
export async function saveAs(name: string, bytes: Uint8Array): Promise<FileInfo | null> {
  if (native()) {
    const r = await plugin.createDocument({ name, data: toBase64(bytes) });
    return r.cancelled ? null : info({ ...r, writable: true });
  }
  const url = URL.createObjectURL(new Blob([bytes as BlobPart], { type: 'application/octet-stream' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
  return { uri: null, name, size: bytes.length, modified: Date.now(), writable: false };
}

/** 덮어쓰기 전에 원래 내용을 앱 폴더에 .bak 로 남긴다. 실패해도 저장은 막지 않으므로 결과만 돌려준다. */
export async function saveBackup(name: string, bytes: Uint8Array): Promise<boolean> {
  if (!native()) return false;
  try {
    await plugin.saveBackup({ name, data: toBase64(bytes) });
    return true;
  } catch {
    return false;
  }
}

/** 다른 앱에서 "Sum Path로 열기"/공유로 받은 파일(없으면 null) */
export async function takeIncoming(): Promise<OpenedFile | null> {
  if (!native()) return null;
  const r = await plugin.takeIncoming();
  return r.none ? null : opened(r);
}

/** 앱이 열려 있는 동안 새로 받은 파일 알림 */
export function onIncoming(fn: () => void): void {
  if (native()) void plugin.addListener('incoming', fn);
}
