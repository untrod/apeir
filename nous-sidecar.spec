# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the embedded Nous Runtime CLI sidecar."""

from PyInstaller.utils.hooks import collect_data_files

# PyInstaller discovers ordinary imports, including imports inside functions.
# Keep this list narrow: collecting every submodule also pulls optional ML and
# scientific packages from the build machine into the base desktop sidecar.
hiddenimports = ["compat", "compat.nki_client"]
datas = collect_data_files("nous_runtime")

optional_excludes = [
    "chromadb",
    "edge_tts",
    "fastembed",
    "faster_whisper",
    "fitz",
    "matplotlib",
    "numpy",
    "onnxruntime",
    "pandas",
    "pytesseract",
    "scipy",
    "sympy",
    "tensorflow",
    "torch",
    "torchaudio",
    "torchvision",
]

a = Analysis(
    ["nous_runtime/cli/main.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", *optional_excludes],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nous-runtime",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    # Keep stdout/stderr available for lifecycle logs. Tauri launches this
    # process with CREATE_NO_WINDOW, so end users still do not see a console.
    console=True,
    disable_windowed_traceback=False,
)
