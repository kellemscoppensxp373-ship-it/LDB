# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec — LifeBoard AI.

Target: Windows, ``--onedir`` (a folder with ``LifeBoard.exe`` plus every DLL),
``console=False`` (no terminal window; crashes go to ``crash.log``).

Build
-----
    build_windows.bat                     # CPU build
    build_windows.bat --cuda              # CUDA build of llama-cpp-python
    pyinstaller LifeBoard.spec --noconfirm --clean      # manual

The spec is deliberately cross-platform so it can also be validated on
Linux/macOS CI; only the version resource and the icon are Windows-specific.

Why --onedir and not --onefile
------------------------------
``--onefile`` unpacks ~400 MB of Qt + llama.cpp into ``%TEMP%`` on every launch
(several seconds of dead time, and it upsets some AV products).  ``--onedir``
starts immediately and keeps ``data.json``, ``models/`` and ``backups/`` right
next to the executable, which is what the app expects.
"""

from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import (
    collect_dynamic_libs,
    collect_submodules,
    is_module_satisfies,
)

# --------------------------------------------------------------------------
# Paths (SPECPATH is injected by PyInstaller and points at this file)
# --------------------------------------------------------------------------
ROOT = Path(SPECPATH).resolve()          # noqa: F821  (PyInstaller global)
SRC = ROOT / "src"
ASSETS = ROOT / "assets"

# --------------------------------------------------------------------------
# Data files that must ship inside the bundle
# --------------------------------------------------------------------------
datas: list[tuple[str, str]] = []

theme_qss = ASSETS / "theme.qss"
if theme_qss.is_file():
    datas.append((str(theme_qss), "assets"))
else:  # pragma: no cover - guard against a broken checkout
    raise SystemExit(f"missing {theme_qss} — the QSS theme is required")

# Optional bundled fonts (drop .ttf/.otf files into assets/fonts).
font_dir = ASSETS / "fonts"
if font_dir.is_dir():
    for font in sorted(font_dir.iterdir()):
        if font.is_file() and font.suffix.lower() in (".ttf", ".otf", ".ttc"):
            datas.append((str(font), "assets/fonts"))

# A ready-to-read note so the shipped models/ folder is not a mystery.
model_note = ROOT / "models" / "README.md"
if model_note.is_file():
    datas.append((str(model_note), "models"))

# --------------------------------------------------------------------------
# llama-cpp-python: submodules + native libraries (libllama / ggml / CUDA)
# --------------------------------------------------------------------------
hiddenimports: list[str] = []
binaries: list[tuple[str, str]] = []

try:
    hiddenimports += collect_submodules("llama_cpp")
except Exception as exc:  # pragma: no cover - package not installed
    print(f"[LifeBoard.spec] WARNING: llama_cpp submodules not collected ({exc})")

try:
    # Picks up libllama.dll / ggml*.dll and, for CUDA builds,
    # cudart64_*.dll + cublas64_*.dll that the wheel ships alongside them.
    collected = collect_dynamic_libs("llama_cpp")
    binaries += collected
    print(f"[LifeBoard.spec] llama_cpp native libraries: {len(collected)}")
except Exception as exc:  # pragma: no cover
    print(f"[LifeBoard.spec] WARNING: llama_cpp DLLs not collected ({exc})")

# llama-cpp-python pulls these in dynamically at import time.
hiddenimports += [
    "diskcache",
    "jinja2",
    "numpy",
    "llama_cpp",
    "llama_cpp.llama",
    "llama_cpp.llama_chat_format",
    "llama_cpp.llama_types",
]

# PySide6: keep only what the app touches.  This is the single biggest size win.
excludes = [
    "tkinter",
    "PyQt5",
    "PyQt6",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebChannel",
    "PySide6.QtWebSockets",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtQuickWidgets",
    "PySide6.Qt3DCore",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtLocation",
    "PySide6.QtSensors",
    "PySide6.QtSerialPort",
    "PySide6.QtBluetooth",
    "PySide6.QtNfc",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "matplotlib",
    "pandas",
    "scipy",
    "pytest",
]

# --------------------------------------------------------------------------
# Windows-only extras
# --------------------------------------------------------------------------
icon = None
for candidate in (ASSETS / "icon.ico", ASSETS / "lifeboard.ico"):
    if candidate.is_file():
        icon = str(candidate)
        break

version_file = ROOT / "packaging" / "version_info.txt"
version = str(version_file) if (os.name == "nt" and version_file.is_file()) else None

# --------------------------------------------------------------------------
# Analysis
# --------------------------------------------------------------------------
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(SRC), str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)                        # noqa: F821

exe = EXE(                               # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,               # <- this is what makes it --onedir
    name="LifeBoard",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX corrupts CUDA / ggml DLLs — keep it off
    console=False,      # windowed app; unhandled exceptions go to crash.log
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=icon,
    version=version,
    uac_admin=False,
)

coll = COLLECT(                          # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="LifeBoard",
)

if is_module_satisfies("pyinstaller>=6.0"):
    print("[LifeBoard.spec] onedir layout -> dist/LifeBoard/LifeBoard.exe")
