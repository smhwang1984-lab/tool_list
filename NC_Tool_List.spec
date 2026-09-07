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

excluded_binary_fragments = (
    'OpenGL\\DLLS\\freeglut',
    'OpenGL\\DLLS\\gle32',
    'OpenGL\\DLLS\\gle64',
)
a.binaries = [
    item for item in a.binaries
    if not any(fragment.lower() in ('%s' % item[0]).lower().replace('/', '\\')
               or fragment.lower() in ('%s' % item[1]).lower().replace('/', '\\')
               for fragment in excluded_binary_fragments)
]
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='NC_Tool_List',
    icon='assets/nc_tool_list.ico',
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
