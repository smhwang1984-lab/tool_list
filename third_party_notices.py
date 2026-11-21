"""오픈소스 라이선스 고지 (v2.7.0).

About 창의 "오픈소스 라이선스" 버튼이 보여 주는 글을 만들고, 빌드할 때 설치된 패키지에서
라이선스 원문 파일을 모아 배포 폴더(`_internal/licenses/`)에 넣는다.

- 원문은 손으로 옮기지 않는다. 빌드 PC의 가상환경(nc_build_venv)에 실제로 설치된 패키지의
  dist-info 안 LICENSE/COPYING/NOTICE 파일을 그대로 복사한다(버전이 바뀌어도 맞게 따라간다).
- 앱 실행 중에는 배포 폴더의 `licenses/THIRD_PARTY_NOTICES.txt`를 읽는다. 없으면(개발 실행)
  지금 설치된 패키지에서 바로 만든다.
- 새 오픈소스를 넣으면 COMPONENTS에 한 줄을 추가한다(tests/test_third_party_notices.py가 확인).
"""

from __future__ import annotations

import importlib.metadata as md
import os
import re
import sys
from pathlib import Path

NOTICE_FILE_NAME = 'THIRD_PARTY_NOTICES.txt'
LICENSE_DIR_NAME = 'licenses'

# (표시 이름, pip 배포 이름 또는 None, 라이선스, 쓰는 곳, 홈페이지)
COMPONENTS = (
    ('Python', None, 'PSF-2.0', '실행 환경', 'https://www.python.org'),
    ('PyQt5', 'PyQt5', 'GPL-3.0 또는 Riverbank 상용 라이선스', '화면(UI)', 'https://www.riverbankcomputing.com/software/pyqt/'),
    ('Qt 5', 'PyQt5-Qt5', 'LGPL-3.0', '화면(UI) 라이브러리', 'https://www.qt.io'),
    ('pyqtgraph', 'pyqtgraph', 'MIT', '3D 뷰어', 'https://www.pyqtgraph.org'),
    ('NumPy', 'numpy', 'BSD-3-Clause', '경로·소재 계산', 'https://numpy.org'),
    ('Numba', 'numba', 'BSD-2-Clause', '소재 시뮬레이션 가속', 'https://numba.pydata.org'),
    ('llvmlite', 'llvmlite', 'BSD-2-Clause (LLVM: Apache-2.0 WITH LLVM-exception)', 'Numba 컴파일러', 'https://github.com/numba/llvmlite'),
    ('PyOpenGL', 'PyOpenGL', 'BSD-3-Clause', '3D 그리기', 'https://pyopengl.sourceforge.net'),
    ('ReportLab', 'reportlab', 'BSD-3-Clause', 'PDF 출력', 'https://www.reportlab.com/opensource/'),
    ('PyInstaller', 'pyinstaller', 'GPL-2.0 WITH Bootloader-exception', '실행 파일 만들기(부트로더만 포함)', 'https://pyinstaller.org'),
    ('Inno Setup', None, 'Inno Setup License', '설치 프로그램 만들기', 'https://jrsoftware.org/isinfo.php'),
)

# 이 이름으로 시작하는 파일을 라이선스 원문으로 본다(dist-info 바로 아래 또는 licenses/ 폴더).
_LICENSE_FILE_RE = re.compile(r'^(LICEN[CS]E|COPYING|NOTICE)', re.I)
# 실행 파일에 들어가지 않는 빌드 전용 의존성은 원문 수집에서 뺀다.
_SKIP_DEPENDENCIES = {'setuptools', 'wheel', 'pip', 'altgraph', 'pefile', 'pywin32-ctypes',
                      'pyinstaller-hooks-contrib', 'packaging', 'macholib'}

# 패키지 안에 라이선스 파일이 없는 경우 원문 위치를 알려 준다.
_FALLBACK_NOTES = {
    'pyqt5': 'PyQt5 패키지에 라이선스 파일이 없습니다. GPL-3.0 전문: https://www.gnu.org/licenses/gpl-3.0.txt\n'
             '(Riverbank 상용 라이선스를 구매한 경우 그 계약 조건을 따릅니다. 전환 계획: PLAN_gpu_sim_and_licensing.md 3장)',
    'pyopengl': 'PyOpenGL 라이선스(BSD-3-Clause 계열) 전문: https://github.com/mcfletch/pyopengl/blob/master/license.txt',
}

HEADER = (
    'Sum Path(NC Tool List)는 아래 오픈소스 소프트웨어를 사용합니다.\n'
    '각 소프트웨어의 저작권은 해당 저작권자에게 있으며, 아래 라이선스 조건에 따라 사용·배포합니다.\n'
    'Sum Path uses the open source software listed below under the terms of their licenses.\n'
)


def _norm(name):
    return re.sub(r'[-_.]+', '-', name).lower()


def _distribution(name):
    try:
        return md.distribution(name)
    except md.PackageNotFoundError:
        return None


def _license_files(dist):
    out = []
    for f in dist.files or ():
        parts = Path(str(f)).parts
        if not parts or not parts[0].endswith('.dist-info'):
            continue
        if len(parts) == 2 or (len(parts) >= 3 and parts[1] == 'licenses'):
            if _LICENSE_FILE_RE.match(parts[-1]):
                path = Path(dist.locate_file(f))
                if path.is_file():
                    out.append(('/'.join(parts[1:]), path))
    return sorted(out, key=lambda item: item[0].lower())


def _requirements(dist):
    """실행에 필요한 의존성 이름(extra 제외, 환경 표식은 이 PC 기준으로 판단)."""
    try:
        from packaging.requirements import Requirement
    except ImportError:  # packaging이 없으면 extra만 빼고 이름만 본다
        Requirement = None
    names = []
    for req in dist.requires or ():
        if Requirement is not None:
            try:
                parsed = Requirement(req)
            except Exception:
                continue
            if parsed.marker is not None and not parsed.marker.evaluate({'extra': ''}):
                continue
            names.append(parsed.name)
            continue
        if 'extra' in req:
            continue
        m = re.match(r'\s*([A-Za-z0-9_.\-]+)', req)
        if m:
            names.append(m.group(1))
    return names


def collect_distributions():
    """COMPONENTS의 패키지와 그 실행 의존성(설치된 것만)을 [(dist, 직접 여부)]로 돌려준다."""
    seen, result = set(), []
    queue = [(c[1], True) for c in COMPONENTS if c[1]]
    while queue:
        name, direct = queue.pop(0)
        key = _norm(name)
        if key in seen or key in _SKIP_DEPENDENCIES:
            continue
        seen.add(key)
        dist = _distribution(name)
        if dist is None:
            continue
        result.append((dist, direct))
        queue.extend((req, False) for req in _requirements(dist))
    return result


def _python_license_file():
    for base in (sys.base_prefix, sys.prefix, os.path.dirname(os.__file__)):
        for name in ('LICENSE.txt', 'LICENSE'):
            path = Path(base) / name
            if path.is_file():
                return path
    return None


def summary_lines():
    """About 본문에 넣는 한 줄 요약(이름 — 라이선스)."""
    return ['%s — %s' % (name, lic) for name, _dist, lic, _use, _url in COMPONENTS]


def build_notice_text():
    """지금 설치된 패키지로 전체 고지문(요약 + 라이선스 원문)을 만든다."""
    lines = [HEADER, '=' * 72, '구성 요소 요약', '=' * 72]
    for name, dist_name, lic, use, url in COMPONENTS:
        dist = _distribution(dist_name) if dist_name else None
        version = (' ' + dist.version) if dist is not None else ''
        lines.append('- %s%s  |  %s  |  %s  |  %s' % (name, version, lic, use, url))
    lines.append('')
    lines.append('PyQt5: GPL-3.0 또는 Riverbank Computing 상용 라이선스로 제공됩니다.')
    lines.append('PyInstaller: 부트로더 예외(Bootloader exception)에 따라 실행 파일에 포함된 부트로더는 라이선스 제한 없이 배포할 수 있습니다.')
    lines.append('Inno Setup: 설치 프로그램 제작에만 쓰며 Inno Setup License(상업적 사용 허용)를 따릅니다.')
    lines.append('')

    sections = []
    py = _python_license_file()
    if py is not None:
        sections.append(('Python %s' % sys.version.split()[0], [(py.name, py)], None))
    for dist, direct in collect_distributions():
        name = dist.metadata.get('Name', '?')
        files = _license_files(dist)
        if not direct:
            lic = dist.metadata.get('License-Expression') or (dist.metadata.get('License') or '').splitlines()[0:1]
            lic = lic if isinstance(lic, str) else (lic[0] if lic else '')
            lines.append('- (의존) %s %s  |  %s' % (name, dist.version, lic or '라이선스 원문 참조'))
        sections.append(('%s %s' % (name, dist.version), files, _FALLBACK_NOTES.get(_norm(name))))
    lines.append('')
    for title, files, fallback in sections:
        lines.append('=' * 72)
        lines.append(title)
        lines.append('=' * 72)
        if not files:
            lines.append(fallback or '(라이선스 파일을 패키지에서 찾지 못했습니다. 위 홈페이지의 라이선스를 따릅니다.)')
        for label, path in files:
            lines.append('--- %s ---' % label)
            lines.append(path.read_text(encoding='utf-8', errors='replace').rstrip())
        lines.append('')
    return '\n'.join(lines) + '\n'


def write_notice_bundle(dest_dir):
    """빌드용: dest_dir/THIRD_PARTY_NOTICES.txt를 쓰고 그 경로를 돌려준다(PyInstaller spec이 부른다)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / NOTICE_FILE_NAME
    path.write_text(build_notice_text(), encoding='utf-8')
    return path


def bundled_notice_path():
    """배포 폴더의 고지문 경로(없으면 None)."""
    base = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
    path = base / LICENSE_DIR_NAME / NOTICE_FILE_NAME
    return path if path.is_file() else None


def load_notice_text():
    """About 창이 보여 줄 고지문. 배포본은 동봉 파일, 개발 실행은 즉석 생성."""
    path = bundled_notice_path()
    if path is not None:
        return path.read_text(encoding='utf-8', errors='replace')
    try:
        return build_notice_text()
    except Exception as error:  # 고지문 생성 실패가 About 창을 막지 않게 한다
        return HEADER + '\n' + '\n'.join('- ' + s for s in summary_lines()) + '\n\n(원문 생성 실패: %s)\n' % error


if __name__ == '__main__':
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join('build', LICENSE_DIR_NAME)
    print(write_notice_bundle(target))
