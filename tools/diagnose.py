#!/usr/bin/env python3
"""Environment diagnostics for LifeBoard AI.

Run by ``run_dev.bat`` before the app starts, and useful on its own:

    python tools\\diagnose.py

Prints interpreter / PySide6 / llama-cpp-python facts, where the data file and
models folder resolve to, which GGUF models are present, and whether Qt can
actually create a window on this machine.
"""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lifeboard import __version__, paths  # noqa: E402
from lifeboard.ai.engine import env_diagnostics, list_models  # noqa: E402

OK = "[ ok ]"
BAD = "[FAIL]"
WARN = "[warn]"


def head(title: str) -> None:
    print()
    print("=" * 62)
    print(f"  {title}")
    print("=" * 62)


def check(label: str, value: object, ok: bool = True, warn: bool = False) -> None:
    flag = OK if ok else (WARN if warn else BAD)
    print(f"{flag} {label:<26} {value}")


def main() -> int:
    problems = 0

    head("interpreter")
    check("executable", sys.executable)
    check("version", sys.version.split()[0],
          ok=sys.version_info >= (3, 10), warn=sys.version_info < (3, 12))
    check("platform", f"{platform.system()} {platform.release()} "
                      f"({platform.machine()})")
    check("frozen (PyInstaller)", paths.is_frozen())
    if sys.version_info < (3, 12):
        print(f"       (3.12+ is the supported target; {sys.version_info.major}."
              f"{sys.version_info.minor} works for development)")

    head("Qt / PySide6")
    try:
        import PySide6
        from PySide6.QtCore import QLibraryInfo, qVersion
        from PySide6.QtWidgets import QApplication

        check("PySide6", PySide6.__version__)
        check("Qt", qVersion())
        app = QApplication.instance() or QApplication([])
        check("QApplication", "created")
        check("font families", ", ".join(
            list(app.font().families())[:3]) or "(default)")
        check("plugin path", QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath))
        del app
    except Exception as exc:
        check("PySide6 import", f"{type(exc).__name__}: {exc}", ok=False)
        problems += 1

    head("llama-cpp-python")
    try:
        import llama_cpp

        check("llama_cpp", llama_cpp.__version__)
        package = Path(llama_cpp.__file__).parent
        search = [package, package / "lib", package.parent / "llama_cpp.libs"]
        libs: list[str] = []
        for folder in search:
            if not folder.is_dir():
                continue
            for pattern in ("*.dll", "*.so", "*.so.*", "*.dylib"):
                libs += [p.name for p in folder.glob(pattern) if p.is_file()]
        # Collapse libfoo.so / libfoo.so.0 / libfoo.so.0.25.3 to one entry.
        unique = set(libs)
        libs = sorted(name for name in unique
                      if not any(other != name and name.startswith(other)
                                 for other in unique))
        check("native libraries", ", ".join(libs) if libs else "(none found)",
              ok=True, warn=not libs)
        cuda = [name for name in libs if "cudart" in name.lower()
                or "cublas" in name.lower()]
        check("CUDA runtime bundled", ", ".join(cuda) if cuda else "no (CPU build)",
              ok=True, warn=not cuda)
    except Exception as exc:
        check("llama_cpp import", f"{type(exc).__name__}: {exc}", ok=False,
              warn=True)
        print("       the app still runs; the advisor stays in heuristic mode")

    head("file layout")
    check("writable root", paths.app_root())
    check("data file", paths.data_path(),
          ok=True, warn=not paths.data_path().exists())
    check("backups", paths.backup_dir())
    check("images", paths.image_dir())
    check("theme.qss", paths.theme_path(), ok=paths.theme_path().is_file())
    if not paths.theme_path().is_file():
        problems += 1

    head("models")
    models = list_models()
    check("models folder", paths.model_dir())
    check("LIFEBOARD_MODELS", os.environ.get("LIFEBOARD_MODELS", "(unset)"))
    if models:
        for info in models:
            check(info.family, f"{info.name}  ({paths.human_size(info.size_bytes)})")
    else:
        check("GGUF files", "none — copy a model into the folder above",
              ok=False, warn=True)

    head("GPU")
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            import subprocess

            out = subprocess.run([nvidia, "--query-gpu=name,memory.total,driver_version",
                                  "--format=csv,noheader"],
                                 capture_output=True, text=True, timeout=20)
            check("nvidia-smi", out.stdout.strip() or "(no output)")
        except Exception as exc:
            check("nvidia-smi", f"could not run ({exc})", ok=False, warn=True)
    else:
        check("nvidia-smi", "not on PATH (CPU inference only)", ok=False, warn=True)

    head("engine diagnostics")
    for key, value in env_diagnostics().items():
        check(key, value)

    print()
    if problems:
        print(f"  {problems} blocking problem(s) found — see the [FAIL] lines.")
    else:
        print("  no blocking problems. If the window still will not appear,")
        print("  check crash.log next to the executable.")
    print()
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
