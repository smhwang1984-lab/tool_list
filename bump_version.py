# -*- coding: utf-8 -*-
"""버전 올리기 도구 (v2.2.9부터 적용하는 번호 규칙).

규칙: 버전은 MAJOR.MINOR.PATCH 이고 각 자리는 0~9 만 쓴다. 자리가 10 이 되면 0 으로 돌리고
윗자리를 1 올린다.
    2.2.8 → 2.2.9 → 2.3.0      2.9.9 → 3.0.0
(v1.5.10, v1.6.10 처럼 두 자리 PATCH 는 더 이상 만들지 않는다.)

한 번에 고치는 파일: NC_Tool_List.py(APP_VERSION, APP_BUILD_DATE), NC_Tool_List.iss(MyAppVersion),
version_info.txt(filevers/prodvers/FileVersion/ProductVersion).

사용법 (Windows: py bump_version.py ...)
    python bump_version.py            현재 → 다음 버전으로 올린다
    python bump_version.py --check    올리지 않고 현재/다음 버전과 파일 간 일치 여부만 출력
    python bump_version.py --set 2.3.0  지정한 버전으로 맞춘다(규칙에 맞는 값만)
"""
import argparse
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DIGIT_LIMIT = 10  # 자리가 이 값이 되면 다음 자리로 넘긴다


def parse_version(text):
    match = re.fullmatch(r'\s*(\d+)\.(\d+)\.(\d+)\s*', str(text))
    if not match:
        raise ValueError('버전 형식은 X.Y.Z 입니다: %r' % (text,))
    return tuple(int(part) for part in match.groups())


def is_valid_version(text):
    try:
        major, minor, patch = parse_version(text)
    except ValueError:
        return False
    return minor < DIGIT_LIMIT and patch < DIGIT_LIMIT


def next_version(text):
    major, minor, patch = parse_version(text)
    patch += 1
    if patch >= DIGIT_LIMIT:
        patch = 0
        minor += 1
    if minor >= DIGIT_LIMIT:
        minor = 0
        major += 1
    return '%d.%d.%d' % (major, minor, patch)


def _read(name):
    return (ROOT / name).read_text(encoding='utf-8-sig')  # BOM은 _write가 원래대로 되살린다


def current_versions():
    found = {}
    m = re.search(r"^APP_VERSION = '([^']+)'", _read('NC_Tool_List.py'), re.M)
    found['NC_Tool_List.py'] = m.group(1) if m else None
    m = re.search(r'^#define MyAppVersion "([^"]+)"', _read('NC_Tool_List.iss'), re.M)
    found['NC_Tool_List.iss'] = m.group(1) if m else None
    m = re.search(r"StringStruct\(u'ProductVersion', u'(\d+\.\d+\.\d+)\.0'\)", _read('version_info.txt'))
    found['version_info.txt'] = m.group(1) if m else None
    return found


def _write(name, text):
    path = ROOT / name
    raw = path.read_bytes()
    bom = raw.startswith(b'\xef\xbb\xbf')
    newline = '\r\n' if b'\r\n' in raw else '\n'
    text = text.replace('\r\n', '\n').replace('\n', newline)
    path.write_bytes((b'\xef\xbb\xbf' if bom else b'') + text.encode('utf-8'))


def apply_version(version, build_date=None):
    if not is_valid_version(version):
        raise ValueError('규칙(각 자리 0~9)에 맞지 않는 버전입니다: %s' % version)
    major, minor, patch = parse_version(version)
    build_date = build_date or date.today().isoformat()

    text = _read('NC_Tool_List.py')
    text = re.sub(r"^APP_VERSION = '[^']+'", "APP_VERSION = '%s'" % version, text, count=1, flags=re.M)
    text = re.sub(r"^APP_BUILD_DATE = '[^']+'", "APP_BUILD_DATE = '%s'" % build_date, text, count=1, flags=re.M)
    _write('NC_Tool_List.py', text)

    text = _read('NC_Tool_List.iss')
    text = re.sub(r'^#define MyAppVersion "[^"]+"', '#define MyAppVersion "%s"' % version, text, count=1, flags=re.M)
    _write('NC_Tool_List.iss', text)

    text = _read('version_info.txt')
    tup = '(%d, %d, %d, 0)' % (major, minor, patch)
    text = re.sub(r'filevers=\([^)]*\)', 'filevers=' + tup, text, count=1)
    text = re.sub(r'prodvers=\([^)]*\)', 'prodvers=' + tup, text, count=1)
    text = re.sub(r"(StringStruct\(u'(?:FileVersion|ProductVersion)', u')[^']+(')",
                  r'\g<1>%s.0\g<2>' % version, text)
    _write('version_info.txt', text)


def main(argv=None):
    parser = argparse.ArgumentParser(description='NC Tool List 버전 올리기(각 자리 10이 되면 윗자리로)')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--set', dest='set_version')
    args = parser.parse_args(argv)

    found = current_versions()
    for name, value in found.items():
        print('%-18s %s' % (name, value))
    values = set(found.values())
    if len(values) != 1 or None in values:
        print('경고: 파일 간 버전이 서로 다릅니다.')
    current = found['NC_Tool_List.py']
    target = args.set_version or next_version(current)
    print('현재 %s → 다음 %s' % (current, target))
    if args.check:
        return 0 if len(values) == 1 and None not in values else 1
    apply_version(target)
    print('적용 완료: %s' % target)
    return 0


if __name__ == '__main__':
    sys.exit(main())
