# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


import os

app_data = [('assets/nc_tool_list.ico', 'assets')]

# v1.10.0: 형상 시뮬레이션 가속(numba)을 배포에 넣는다. 3+2(G68.2)/동시 5축(G43.4)은 3D 복셀
# 소재라 numba 없이는 수십 배 느려 해상도를 크게 낮춰야 한다. 대신 llvmlite 등으로 배포 폴더가
# 약 +150MB 늘어난다. 빼려면 빌드 전에 환경변수 NC_INCLUDE_NUMBA=0 (그러면 numpy 경로로 동작).
INCLUDE_NUMBA = os.environ.get('NC_INCLUDE_NUMBA', '1').strip() != '0'
numba_imports = []
numba_excludes = []
if INCLUDE_NUMBA:
    numba_imports = ['nc_sim_numba', 'numba', 'llvmlite']
    # numba는 캐시(cache=True)와 컴파일에 커널 소스 파일 경로가 필요하다 — 소스를 데이터로 동봉한다.
    app_data.append(('nc_sim_numba.py', '.'))
else:
    numba_excludes = ['numba', 'llvmlite', 'nc_sim_numba']
viewer_hiddenimports = [
    'numpy',
    # QtNetwork는 v1.6.7 단일 실행(QLocalServer/QLocalSocket)에 필요하다.
    'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtOpenGL', 'PyQt5.QtNetwork',
    'pyqtgraph', 'pyqtgraph.opengl',
    # v1.8.0: 라이선스 검증 공용 모듈(순수 파이썬, 외부 의존성 없음).
    'sumpath_license',
    # v1.9.0: 밀링 3축 형상 가공 시뮬레이션 엔진(순수 numpy, Qt 비의존).
    'nc_sim',
    # v1.10.0: 3D 소재(복셀) 엔진 — 경사면/동시 5축 가공 시뮬레이션.
    'nc_sim3d',
] + numba_imports + collect_submodules('pyqtgraph.opengl') + collect_submodules('OpenGL')

a = Analysis(
    ['NC_Tool_List.py'],
    pathex=[],
    binaries=[],
    datas=app_data,
    hiddenimports=viewer_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'torch', 'matplotlib', 'IPython', 'jupyter_rfb', 'PySide6', 'PyQt6', 'PySide2', 'OpenGL.Tk', 'OpenGL.GLUT'] + numba_excludes,
    noarchive=False,
    optimize=0,
)

# PyOpenGL의 OpenGL\DLLS 폴더는 freeglut32/64, gle32/64 DLL과 그 라이선스/README
# 텍스트 파일만 담고 있고 소프트웨어 렌더링 경로에서는 쓰이지 않으므로 폴더째 제외한다.
excluded_binary_fragments = (
    'OpenGL\\DLLS\\',
)


def _keep_entry(item):
    return not any(
        fragment.lower() in ('%s' % item[0]).lower().replace('/', '\\')
        or fragment.lower() in ('%s' % item[1]).lower().replace('/', '\\')
        for fragment in excluded_binary_fragments
    )


a.binaries = [item for item in a.binaries if _keep_entry(item)]
# OpenGL\DLLS 아래 남는 라이선스/README 텍스트 파일도 배포 폴더에서 제외
a.datas = [item for item in a.datas if _keep_entry(item)]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='NC_Tool_List',
    icon='assets/nc_tool_list.ico',
    version='version_info.txt',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='NC_Tool_List',
)
