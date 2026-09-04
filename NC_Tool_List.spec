# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


app_data = [('assets/nc_tool_list.ico', 'assets')]
viewer_hiddenimports = [
    'numpy',
    'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtOpenGL',
    'pyqtgraph', 'pyqtgraph.opengl',
] + collect_submodules('pyqtgraph.opengl')

a = Analysis(
    ['NC_Tool_List.py'],
    pathex=[],
    binaries=[],
    datas=app_data,
    hiddenimports=viewer_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'torch', 'matplotlib', 'IPython', 'jupyter_rfb', 'PySide6', 'PyQt6', 'PySide2', 'OpenGL.Tk', 'OpenGL.GLUT', 'OpenGL.raw.GLUT', 'OpenGL.raw.GLX', 'OpenGL.raw.GLES1', 'OpenGL.raw.GLES2', 'OpenGL.raw.GLES3'],
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
