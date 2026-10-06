"""Text helpers that bridge markdown, rich text and the AI editor actions.

Qt ships a real markdown parser (``QTextDocument.setMarkdown``), so the diary
can round-trip markdown without a third-party dependency — useful both for
importing notes and for feeding the local model plain text instead of HTML.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtGui import QTextDocument

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"[ \t]*\n[ \t]*")

#: Qt spells this flag ``QTextDocument.MarkdownFeature.MarkdownDialectGitHub``
#: (PySide6 >= 6.0); older shims exposed it as ``MarkdownDialectGitHub``.
_MARKDOWN_DIALECT = getattr(
    getattr(QTextDocument, "MarkdownFeature", QTextDocument),
    "MarkdownDialectGitHub",
    QTextDocument.MarkdownFeature.MarkdownDialectCommonMark,
)


def html_to_markdown(html: str) -> str:
    """Rich text -> markdown (GitHub dialect), used for the AI prompt."""
    if not html:
        return ""
    document = QTextDocument()
    document.setHtml(html)
    return document.toMarkdown(_MARKDOWN_DIALECT)


def html_to_plain(html: str) -> str:
    """Rich text -> plain text (fallback when the Qt markdown writer is empty)."""
    if not html:
        return ""
    document = QTextDocument()
    document.setHtml(html)
    text = document.toPlainText()
    return WS_RE.sub("\n", text).strip()


def markdown_to_html(markdown: str) -> str:
    """Markdown -> rich text, used by *Import markdown* and by the AI output."""
    document = QTextDocument()
    document.setMarkdown(markdown or "", _MARKDOWN_DIALECT)
    return document.toHtml()


def best_plain_text(html: str, markdown: str | None = None) -> str:
    """Whatever reads best as a prompt body."""
    candidate = (markdown or html_to_markdown(html)).strip()
    if len(candidate) < 24:
        candidate = html_to_plain(html)
    return candidate.strip()


def strip_html(html: str) -> str:
    """Crude tag stripper used for search previews only."""
    return TAG_RE.sub("", html or "")


def unique_image_path(directory: Path, original: str) -> Path:
    """``diary-20261006-2145-photo.png`` inside the app's image folder."""
    from datetime import datetime

    suffix = Path(original).suffix.lower() or ".png"
    if suffix not in (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"):
        suffix = ".png"
    stem = Path(original).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem)[:40].strip("-") or "image"
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    directory.mkdir(parents=True, exist_ok=True)
    candidate = directory / f"diary-{stamp}-{stem}{suffix}"
    counter = 1
    while candidate.exists():
        candidate = directory / f"diary-{stamp}-{stem}-{counter}{suffix}"
        counter += 1
    return candidate
