#!/usr/bin/env node
// 버전 올리기 도구 — package.json / src/version.ts / android/app/build.gradle 을 한 번에 바꾼다.
//
// 규칙(CLAUDE.md 2절): MAJOR.MINOR.PATCH, 각 자리 0~9. 자리가 10이 되면 0으로 돌리고 윗자리를 1 올린다.
//   1.0.8 → 1.0.9 → 1.1.0      1.9.9 → 2.0.0
// versionCode = MAJOR×100 + MINOR×10 + PATCH
//
// 사용법
//   node tools/bump_version.mjs            PATCH +1 (자리올림 포함)
//   node tools/bump_version.mjs --minor    MINOR +1, PATCH 0 (단계가 끝날 때)
//   node tools/bump_version.mjs --set 1.1.0
//   node tools/bump_version.mjs --check    바꾸지 않고 세 파일 값과 일치 여부만 출력
import { readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const DIGIT_LIMIT = 10;
export const DEFAULT_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');

export function parseVersion(text) {
  const m = /^\s*(\d+)\.(\d+)\.(\d+)\s*$/.exec(String(text));
  if (!m) throw new Error(`버전 형식은 X.Y.Z 입니다: ${text}`);
  return [Number(m[1]), Number(m[2]), Number(m[3])];
}

export function isValidVersion(text) {
  try {
    const parts = parseVersion(text);
    return parts.every((p) => p < DIGIT_LIMIT);
  } catch {
    return false;
  }
}

export function nextVersion(text, part = 'patch') {
  let [major, minor, patch] = parseVersion(text);
  if (part === 'minor') {
    patch = 0;
    minor += 1;
  } else {
    patch += 1;
  }
  if (patch >= DIGIT_LIMIT) {
    patch = 0;
    minor += 1;
  }
  if (minor >= DIGIT_LIMIT) {
    minor = 0;
    major += 1;
  }
  return `${major}.${minor}.${patch}`;
}

export function versionCode(text) {
  const [major, minor, patch] = parseVersion(text);
  return major * 100 + minor * 10 + patch;
}

const FILES = {
  pkg: 'package.json',
  ts: 'src/version.ts',
  gradle: 'android/app/build.gradle',
};

function read(root, name) {
  return readFileSync(join(root, name), 'utf8');
}

export function currentVersions(root = DEFAULT_ROOT) {
  const pkg = JSON.parse(read(root, FILES.pkg)).version ?? null;
  const ts = /APP_VERSION = '([^']+)'/.exec(read(root, FILES.ts))?.[1] ?? null;
  const gradleText = read(root, FILES.gradle);
  const gradle = /versionName "([^"]+)"/.exec(gradleText)?.[1] ?? null;
  const code = Number(/versionCode (\d+)/.exec(gradleText)?.[1] ?? NaN);
  return { [FILES.pkg]: pkg, [FILES.ts]: ts, [FILES.gradle]: gradle, versionCode: code };
}

export function applyVersion(version, root = DEFAULT_ROOT) {
  if (!isValidVersion(version)) throw new Error(`규칙(각 자리 0~9)에 맞지 않는 버전입니다: ${version}`);
  const replace = (name, re, to) => {
    const text = read(root, name);
    if (!re.test(text)) throw new Error(`${name} 에서 버전 위치를 찾지 못했습니다`);
    writeFileSync(join(root, name), text.replace(re, to));
  };
  replace(FILES.pkg, /("version"\s*:\s*")[^"]+(")/, `$1${version}$2`);
  replace(FILES.ts, /(APP_VERSION = ')[^']+(')/, `$1${version}$2`);
  replace(FILES.gradle, /(versionName ")[^"]+(")/, `$1${version}$2`);
  replace(FILES.gradle, /(versionCode )\d+/, `$1${versionCode(version)}`);
  return version;
}

function main(argv) {
  const root = DEFAULT_ROOT;
  const found = currentVersions(root);
  const current = found[FILES.pkg];
  if (argv.includes('--check')) {
    for (const [k, v] of Object.entries(found)) console.log(`${k}: ${v}`);
    const same = found[FILES.ts] === current && found[FILES.gradle] === current
      && found.versionCode === versionCode(current);
    console.log(same ? `OK ${current} → 다음 ${nextVersion(current)}` : '[주의] 파일끼리 버전이 다릅니다');
    return same ? 0 : 1;
  }
  const setIndex = argv.indexOf('--set');
  const target = setIndex >= 0 ? argv[setIndex + 1]
    : nextVersion(current, argv.includes('--minor') ? 'minor' : 'patch');
  applyVersion(target, root);
  console.log(`${current} → ${target} (versionCode ${versionCode(target)})`);
  return 0;
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try {
    process.exitCode = main(process.argv.slice(2));
  } catch (error) {
    console.error(String(error instanceof Error ? error.message : error));
    process.exitCode = 1;
  }
}
