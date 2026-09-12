# -*- mode: python ; coding: utf-8 -*-
# SumPath License Maker — 발급자 전용 빌드. 절대 NC_Tool_List 설치본/포터블/
# 업데이트 공유 폴더에 포함하지 않는다(v1.8.0_PLAN.md §3.6).

maker_hiddenimports = [
    'PyQt5.QtCore', 'PyQt5.QtGui', 'PyQt5.QtWidgets',
    'cryptography.hazmat.primitives.asymmetric.ed25519',
    'sumpath_license',
]

a = Analysis(
    ['SumPath_License_Maker.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=maker_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['scipy', 'torch', 'matplotlib', 'IPython', 'PySide6', 'PyQt6', 'PySide2'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='SumPath_License_Maker',
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
    name='SumPath_License_Maker',
)
