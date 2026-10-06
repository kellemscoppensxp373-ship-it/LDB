#!/usr/bin/env python3
"""LifeBoard AI — entry point.

Works three ways:

* ``python main.py``                     (source checkout, console visible)
* ``python -m lifeboard``                (package style)
* ``LifeBoard.exe``                      (PyInstaller --onedir bundle)

``src/`` is put on ``sys.path`` first so the checkout needs no install step.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from lifeboard.app import main  # noqa: E402  (path setup must come first)

if __name__ == "__main__":
    raise SystemExit(main())
