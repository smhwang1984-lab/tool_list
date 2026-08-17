# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

import tkinterdnd2
from PyInstaller.utils.hooks import collect_data_files


dnd_package_dir = Path(tkinterdnd2.__file__).resolve().parent
dnd_platform_dirs = ('win-x64', 'win-x64-tcl9')
dnd_data = collect_data_files(
    'tkinterdnd2',
    includes=[f'tkdnd/{platform_dir}/**' for platform_dir in dnd_platform_dirs],
)
dnd_binaries = [
    (str(dll), f'tkinterdnd2/tkdnd/{platform_dir}')
    for platform_dir in dnd_platform_dirs
    for dll in (dnd_package_dir / 'tkdnd' / platform_dir).glob('*.dll')
]

a = Analysis(
    ['NC_Tool_List.py'],
    pathex=[],
    binaries=dnd_binaries,
    datas=dnd_data,
    hiddenimports=['tkinterdnd2.TkinterDnD'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
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
