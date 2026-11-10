// 설정 저장소 — 앱에서는 @capacitor/preferences, 웹/시험에서는 localStorage.
// 값은 문자열로만 다루고, 읽기·쓰기 실패는 조용히 기본값으로 돌아간다.
import { Capacitor } from '@capacitor/core';
import { Preferences } from '@capacitor/preferences';

const PREFIX = 'sumpath.';
const cache = new Map<string, string>();

const native = (): boolean => {
  try {
    return Capacitor.isNativePlatform();
  } catch {
    return false;
  }
};

/** 시작할 때 한 번 불러와 캐시에 올린다. 이후 getPref 는 동기로 읽는다. */
export async function loadPrefs(): Promise<void> {
  try {
    if (native()) {
      const { keys } = await Preferences.keys();
      for (const key of keys) {
        const { value } = await Preferences.get({ key });
        if (value !== null) cache.set(key.replace(PREFIX, ''), value);
      }
    } else {
      for (let i = 0; i < localStorage.length; i++) {
        const key = localStorage.key(i);
        if (key?.startsWith(PREFIX)) cache.set(key.slice(PREFIX.length), localStorage.getItem(key) ?? '');
      }
    }
  } catch {
    /* 저장소를 못 쓰면 기본값 */
  }
}

export function getPref(key: string, fallback = ''): string {
  return cache.get(key) ?? fallback;
}

export function getPrefNumber(key: string, fallback: number, min = -Infinity, max = Infinity): number {
  const n = Number(cache.get(key));
  return cache.has(key) && Number.isFinite(n) ? Math.min(max, Math.max(min, n)) : fallback;
}

export function setPref(key: string, value: string): void {
  cache.set(key, value);
  try {
    if (native()) void Preferences.set({ key: PREFIX + key, value });
    else localStorage.setItem(PREFIX + key, value);
  } catch {
    /* 무시 */
  }
}
