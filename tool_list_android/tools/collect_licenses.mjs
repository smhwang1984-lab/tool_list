// 오픈소스 라이선스 고지문 만들기 (Android v2.1.1)
// package-lock.json 의 배포용(개발용 제외) 패키지마다 node_modules 안 LICENSE 원문을 모아
// public/THIRD_PARTY_NOTICES.txt 를 만든다. vite build 가 APK 에 그대로 넣고, About → 오픈소스 라이선스가 읽는다.
// 원문은 손으로 옮기지 않는다. 글꼴(OFL)·AndroidX(Apache-2.0) 원문은 tools/licenses/ 에 둔 공식 파일을 쓴다.
// 실행: npm run licenses  (npm run build 가 먼저 부른다)
import { existsSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const LINE = '='.repeat(72);

// 앱 화면에 보이는 주요 구성 요소 — 데스크톱 third_party_notices.COMPONENTS 와 같은 형식
export const COMPONENTS = [
  ['Capacitor', 'MIT', '안드로이드 앱 틀', 'https://capacitorjs.com'],
  ['three.js', 'MIT', '3D 뷰어', 'https://threejs.org'],
  ['CodeMirror', 'MIT', 'NC 편집기', 'https://codemirror.net'],
  ['pdfmake', 'MIT', 'PDF 출력', 'https://pdfmake.github.io'],
  ['Noto Sans KR', 'OFL-1.1', 'PDF 글꼴', 'https://fonts.google.com/noto/specimen/Noto+Sans+KR'],
  ['AndroidX (appcompat, coordinatorlayout, core-splashscreen)', 'Apache-2.0', '안드로이드 기본 라이브러리', 'https://developer.android.com/jetpack/androidx'],
];

const LICENSE_RE = /^(licen[cs]e|copying|notice)/i;
// 줄바꿈은 LF 로 맞춘다(Windows 체크아웃의 CRLF 와 상관없이 같은 결과)
const readText = (path) => readFileSync(path, 'utf8').replace(/\r\n?/g, '\n');

function licenseFiles(dir) {
  if (!existsSync(dir)) return [];
  return readdirSync(dir).filter((f) => LICENSE_RE.test(f)).sort().map((f) => [f, join(dir, f)]);
}

export function buildNotices() {
  const lock = JSON.parse(readFileSync(join(root, 'package-lock.json'), 'utf8'));
  const pkgs = Object.entries(lock.packages)
    .filter(([key, v]) => key && !v.dev && !v.devOptional)
    .map(([key, v]) => ({ key, name: key.replace(/^.*node_modules\//, ''), version: v.version, license: v.license ?? '' }))
    .sort((a, b) => a.name.localeCompare(b.name) || a.key.localeCompare(b.key));

  const out = [
    'Sum Path(NC Tool List) Android는 아래 오픈소스 소프트웨어를 사용합니다.',
    '각 소프트웨어의 저작권은 해당 저작권자에게 있으며, 아래 라이선스 조건에 따라 사용·배포합니다.',
    'Sum Path Android uses the open source software listed below under the terms of their licenses.',
    '',
    LINE, '구성 요소 요약', LINE,
    ...COMPONENTS.map(([n, l, u, url]) => `- ${n}  |  ${l}  |  ${u}  |  ${url}`),
    '',
    `포함된 npm 패키지 (${pkgs.length}개):`,
    ...pkgs.map((p) => `- ${p.name} ${p.version}  |  ${p.license || '라이선스 원문 참조'}`),
    '',
  ];
  const missing = [];
  for (const p of pkgs) {
    const files = licenseFiles(join(root, p.key));
    out.push(LINE, `${p.name} ${p.version}`, LINE);
    if (!files.length) {
      missing.push(p.name);
      const meta = JSON.parse(readFileSync(join(root, p.key, 'package.json'), 'utf8'));
      const author = typeof meta.author === 'string' ? meta.author : meta.author?.name;
      out.push(`(패키지에 라이선스 파일이 없습니다. package.json 의 license: ${p.license || '없음'}` +
        (author ? `, 저작권자: ${author}` : '') + (meta.repository ? `, 저장소: ${meta.repository.url ?? meta.repository}` : '') + ')');
    }
    for (const [label, path] of files) out.push(`--- ${label} ---`, readText(path).trimEnd());
    out.push('');
  }
  for (const [title, file] of [['Noto Sans KR (OFL-1.1)', 'NotoSansKR-OFL.txt'], ['AndroidX — Apache License 2.0', 'Apache-2.0.txt']]) {
    out.push(LINE, title, LINE, readText(join(root, 'tools', 'licenses', file)).trimEnd(), '');
  }
  return { text: out.join('\n') + '\n', count: pkgs.length, missing };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const { text, count, missing } = buildNotices();
  const dest = join(root, 'public', 'THIRD_PARTY_NOTICES.txt');
  writeFileSync(dest, text, 'utf8');
  console.log(`THIRD_PARTY_NOTICES.txt: npm 패키지 ${count}개, ${Math.round(text.length / 1024)}KB` + (missing.length ? ` (라이선스 파일 없음: ${missing.join(', ')})` : ''));
}
