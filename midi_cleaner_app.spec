# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_data_files

project_root = Path(os.getcwd()).resolve()

music21_datas, music21_binaries, music21_hidden = collect_all("music21")
pyside_datas, pyside_binaries, pyside_hidden = collect_all("PySide6")
pretty_midi_datas = collect_data_files("pretty_midi")

datas = music21_datas + pyside_datas + pretty_midi_datas
binaries = music21_binaries + pyside_binaries
hiddenimports = list(set(music21_hidden + pyside_hidden + ["pretty_midi", "mido", "numpy", "scipy"]))

a = Analysis(
    ["app_ui.py"],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name="MidiCleaner",
    exclude_binaries=True,
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

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MidiCleaner",
)

app = BUNDLE(
    coll,
    name="MidiCleaner.app",
    icon=None,
    bundle_identifier="com.punkhazard.midicleaner",
)

