# -*- mode: python ; coding: utf-8 -*-


import os

import os

image_files = [
    ('images/arrow_right.png', 'images'),
    ('images/docker_logo.png', 'images'),
    ('images/icon.png', 'images'),
    ('images/web_logo.png', 'images'),
]

a = Analysis(
    ['cw2dt.py'],
    pathex=[],
    binaries=[],
    datas=[('version.txt', '.')] + image_files,
    hiddenimports=['PySide6'],
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
    name='Clone Website to Docker Tool',
    version='version.txt',
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
    icon='icon.ico' if os.name == 'nt' else 'icon.icns',
)