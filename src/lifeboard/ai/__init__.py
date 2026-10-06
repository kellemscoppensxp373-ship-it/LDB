"""Offline AI advisor: context serialisation, llama.cpp engine, Qt workers.

Nothing in this package imports ``llama_cpp`` at module scope — the app must
start, and be fully usable, on a machine with no model and no llama.cpp build.
"""

from __future__ import annotations

from .context import build_context, retrieve_passages, serialize_day
from .briefing import build_briefing, BriefingLine

__all__ = [
    "build_context",
    "retrieve_passages",
    "serialize_day",
    "build_briefing",
    "BriefingLine",
]
