"""LifeBoard AI — a native, offline, PySide6 life-tracking workbench.

The package is deliberately import-cheap: importing :mod:`lifeboard` must never
pull in PySide6 or ``llama_cpp`` so that the pure-Python core (storage,
context serialisation, theming maths) stays unit-testable on a headless box.
"""

from __future__ import annotations

__version__ = "1.0.0"
__app_name__ = "LifeBoard AI"
__app_sigil__ = "✠"

SCHEMA_VERSION = 3

__all__ = ["__version__", "__app_name__", "__app_sigil__", "SCHEMA_VERSION"]
