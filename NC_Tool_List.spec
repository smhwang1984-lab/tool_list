# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules


app_data = [('assets/nc_tool_list.ico', 'assets')]
viewer_hiddenimports = [
    'numpy',
    'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets', 'PyQt5.QtOpenGL',
    'pyqtgraph', 'pyqtgraph.opengl',
] + collect_submodules('pyqtgraph.opengl') + collect_submodules('OpenGL')

a = Analysis(
    ['NC_Tool_List.py'],
    pathex=[],
    binaries=[],
    datas=app_data,
    hiddenimports=viewer_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'torch', 'matplotlib', 'IPython', 'jupyter_rfb', 'PySide6', 'PyQt6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='NC_Tool_List',
    icon='assets/nc_tool_list.ico',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
