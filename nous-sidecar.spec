# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller specification for the embedded Nous Runtime CLI sidecar."""

from importlib.util import find_spec

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

# PyInstaller discovers ordinary imports, including imports inside functions.
# Keep this list narrow: collecting every submodule also pulls optional ML and
# scientific packages from the build machine into the base desktop sidecar.
hiddenimports = ["compat", "compat.nki_client"]
datas = collect_data_files("nous_runtime")
# jsonschema's non-GPL IRI checker loads this grammar at import time. Keep the
# existing validator intact and include its data (and upstream license metadata)
# when that optional format dependency is installed in the build environment.
if find_spec("rfc3987_syntax") is not None:
    datas += collect_data_files("rfc3987_syntax", includes=["*.lark"])
    datas += copy_metadata("rfc3987-syntax")

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
