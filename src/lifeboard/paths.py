"""Filesystem layout resolution.

The single most common failure mode of a PyInstaller app is "where do I write
my files?".  Everything in LifeBoard funnels through this module:

* **Frozen** (``LifeBoard.exe``): the writable root is the folder that holds
  the executable, so ``data.json``, ``backups/`` and ``models/`` sit right next
  to the ``.exe`` and can be carried on a USB stick.
* **Source run** (``python main.py``): the writable root is the repository
  root, i.e. the parent of ``src/``.
* **Read-only bundled resources** (the QSS theme, bundled fonts) live next to
  the code, which under PyInstaller ``--onedir`` is ``_internal/``; they are
  resolved separately from the writable root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DATA_FILENAME = "data.json"
BACKUP_DIRNAME = "backups"
MODEL_DIRNAME = "models"
IMAGE_DIRNAME = "assets/images"
THEME_RELATIVE = ("assets", "theme.qss")


def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return bool(getattr(sys, "frozen", False))


def _repo_root_fallback() -> Path:
    """src/lifeboard/paths.py -> <root>."""
    return Path(__file__).resolve().parent.parent.parent


def app_root() -> Path:
    """Writable root: folder containing the ``.exe`` (or the repo root)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return _repo_root_fallback()


def resource_root() -> Path:
    """Read-only resource root (``_internal`` when frozen, repo root otherwise)."""
    if is_frozen():
        # PyInstaller sets _MEIPASS for both onefile and onedir builds.
        bundle = getattr(sys, "_MEIPASS", None)
        if bundle:
            return Path(bundle)
        return app_root()
    return _repo_root_fallback()


def data_path() -> Path:
    return app_root() / DATA_FILENAME


def backup_dir() -> Path:
    return app_root() / BACKUP_DIRNAME


def model_dir() -> Path:
    """GGUF weights directory.

    Also honours ``LIFEBOARD_MODELS`` so a user with a 5 GB model on another
    drive does not have to duplicate it next to the exe.
    """
    override = os.environ.get("LIFEBOARD_MODELS")
    if override:
        return Path(override).expanduser()
    return app_root() / MODEL_DIRNAME


def image_dir() -> Path:
    return app_root() / IMAGE_DIRNAME


def theme_path() -> Path:
    """Bundled QSS template.  Falls back to the repo copy if not bundled."""
    candidate = resource_root().joinpath(*THEME_RELATIVE)
    if candidate.is_file():
        return candidate
    return _repo_root_fallback().joinpath(*THEME_RELATIVE)


def ensure_runtime_dirs() -> dict[str, Path]:
    """Create every directory the app needs at runtime and return them."""
    dirs = {
        "root": app_root(),
        "backups": backup_dir(),
        "models": model_dir(),
        "images": image_dir(),
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def human_size(num_bytes: float) -> str:
    """Render a byte count the way a human reads it (used in the model picker)."""
    value = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(value) < 1024.0:
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} PB"
