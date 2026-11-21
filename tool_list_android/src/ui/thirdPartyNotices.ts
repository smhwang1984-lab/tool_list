// 오픈소스 라이선스 고지 (v2.1.1) — About → 오픈소스 라이선스.
// 원문은 빌드 때 tools/collect_licenses.mjs 가 만든 public/THIRD_PARTY_NOTICES.txt(APK 에 포함)를 읽는다.
// 데스크톱 원본: third_party_notices.py + About → 오픈소스 라이선스 고지.
import { el, showDialog, toast } from './dialog';

/** About 본문의 한 줄 요약 — tools/collect_licenses.mjs 의 COMPONENTS 와 같게 둔다 */
export const NOTICE_SUMMARY: readonly string[] = [
  'Capacitor — MIT',
  'three.js — MIT',
  'CodeMirror — MIT',
  'pdfmake — MIT',
  'Noto Sans KR (PDF 글꼴) — OFL-1.1',
  'AndroidX — Apache-2.0',
];

export const NOTICE_FILE = 'THIRD_PARTY_NOTICES.txt';

export async function loadNoticeText(fetcher: typeof fetch = fetch): Promise<string> {
  try {
    const res = await fetcher(NOTICE_FILE);
    if (res.ok) return await res.text();
  } catch { /* 아래 요약으로 대신한다 */ }
  return ['라이선스 원문 파일을 읽지 못했습니다. 요약:', ...NOTICE_SUMMARY.map((s) => `- ${s}`)].join('\n');
}

export async function showThirdPartyNotices(): Promise<void> {
  const text = await loadNoticeText();
  const body = el('pre', { class: 'notice-text' });
  body.textContent = text;
  showDialog('오픈소스 라이선스 고지', body, [
    {
      label: '전체 복사',
      onClick: () => {
        navigator.clipboard?.writeText(text).then(() => toast('복사했습니다'), () => toast('복사하지 못했습니다'));
        return false;
      },
    },
    { label: '닫기', primary: true },
  ]);
}
