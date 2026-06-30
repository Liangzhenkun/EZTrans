# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_data_files, collect_dynamic_libs, collect_submodules

hiddenimports = []
hiddenimports += collect_submodules("argostranslate")
hiddenimports += collect_submodules("piper")
hiddenimports += collect_submodules("pyttsx3")
hiddenimports += collect_submodules("pystray")

datas = [("resources/seed_examples.json", "resources")]
datas += collect_data_files("argostranslate")
datas += collect_data_files("piper")
datas += collect_data_files("pyttsx3")

binaries = []
binaries += collect_dynamic_libs("piper")


a = Analysis(
    ["src/eztrans/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
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
    [],
    exclude_binaries=True,
    name="EZTrans",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="EZTrans",
)
