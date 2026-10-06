"""Reusable, hand-painted building blocks (no Qt Designer, no .ui files)."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget


def role(widget: QWidget, value: str) -> QWidget:
    """Tag a widget with ``role="…"`` so the QSS can target it."""
    widget.setProperty("role", value)
    return widget


def kind(widget: QWidget, value: str) -> QWidget:
    widget.setProperty("kind", value)
    return widget


class HRule(QFrame):
    """A 1px separator that actually respects the stylesheet."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Divider")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setFixedHeight(1)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)


class SectionLabel(QLabel):
    """Gothic section header: ``✠  DASHBOARD``."""

    def __init__(self, text: str, glyph: str = "✠", parent: QWidget | None = None) -> None:
        super().__init__(f"{glyph}  {text.upper()}" if glyph else text.upper(), parent)
        role(self, "section")


class Card(QFrame):
    """Titled panel: header strip with a glyph, then arbitrary content."""

    def __init__(self, title: str, glyph: str = "❖", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Card")
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 12)
        root.setSpacing(10)

        header = QFrame(self)
        header.setObjectName("CardHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 6)
        header_layout.setSpacing(8)
        self.title_label = QLabel(f"{glyph}  {title.upper()}" if glyph else title.upper())
        role(self.title_label, "cardTitle")
        header_layout.addWidget(self.title_label)
        header_layout.addStretch(1)
        self._header_actions = header_layout
        root.addWidget(header)

        self._content = QVBoxLayout()
        self._content.setContentsMargins(0, 0, 0, 0)
        self._content.setSpacing(8)
        root.addLayout(self._content)

    @property
    def content(self) -> QVBoxLayout:
        return self._content

    def add_header_widget(self, widget: QWidget) -> None:
        self._header_actions.addWidget(widget)

    def set_title(self, title: str, glyph: str = "❖") -> None:
        self.title_label.setText(f"{glyph}  {title.upper()}" if glyph else title.upper())


class InlineBar(QWidget):
    """Slim progress bar with a gradient fill, painted by hand.

    ``QProgressBar`` cannot render a centred caption over a 6px track, so the
    tracker rows use this instead.
    """

    def __init__(self, parent: QWidget | None = None, *, height: int = 12,
                 caption: str = "", ratio: float = 0.0) -> None:
        super().__init__(parent)
        self._ratio = max(0.0, min(1.0, float(ratio)))
        self._caption = caption
        self._track = QColor("#1B2130")
        self._start = QColor("#3B2F6B")
        self._end = QColor("#9B7BFF")
        self._over = QColor("#E0607E")
        self._text = QColor("#E6E6F0")
        self._over_limit = False
        self.setFixedHeight(height)
        self.setMinimumWidth(60)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    # -- API ---------------------------------------------------------------
    def set_colors(self, track: str, start: str, end: str, over: str = "",
                   text: str = "") -> None:
        self._track = QColor(track)
        self._start = QColor(start)
        self._end = QColor(end)
        if over:
            self._over = QColor(over)
        if text:
            self._text = QColor(text)
        self.update()

    def set_ratio(self, ratio: float, *, over_limit: bool = False,
                  caption: str | None = None) -> None:
        self._ratio = max(0.0, min(1.0, float(ratio)))
        self._over_limit = over_limit
        if caption is not None:
            self._caption = caption
        self.update()

    def set_caption(self, caption: str) -> None:
        self._caption = caption
        self.update()

    # -- paint -------------------------------------------------------------
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        radius = min(4.0, rect.height() / 2.0)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._track)
        painter.drawRoundedRect(rect, radius, radius)

        if self._ratio > 0:
            fill = QRectF(rect)
            fill.setWidth(max(radius * 2, rect.width() * self._ratio))
            gradient = QLinearGradient(fill.topLeft(), fill.topRight())
            if self._over_limit:
                gradient.setColorAt(0.0, self._over.darker(130))
                gradient.setColorAt(1.0, self._over)
            else:
                gradient.setColorAt(0.0, self._start)
                gradient.setColorAt(1.0, self._end)
            painter.setBrush(gradient)
            path = QPainterPath()
            path.addRoundedRect(fill, radius, radius)
            painter.drawPath(path)

        if self._caption:
            painter.setPen(QPen(self._text))
            font = QFont(self.font())
            font.setPointSizeF(max(6.5, self.height() * 0.58))
            font.setBold(True)
            painter.setFont(font)
            painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._caption)
        painter.end()


class ScoreRing(QWidget):
    """Circular 0-100 gauge used for the daily score on the dashboard."""

    def __init__(self, parent: QWidget | None = None, size: int = 108) -> None:
        super().__init__(parent)
        self._value = 0.0
        self._accent = QColor("#9B7BFF")
        self._track = QColor("#1B2130")
        self._text = QColor("#E6E6F0")
        self.setFixedSize(size, size)

    def set_colors(self, accent: str, track: str, text: str) -> None:
        self._accent = QColor(accent)
        self._track = QColor(track)
        self._text = QColor(text)
        self.update()

    def set_value(self, value: float) -> None:
        self._value = max(0.0, min(100.0, float(value)))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height())
        stroke = max(6.0, side * 0.085)
        rect = QRectF(0, 0, side - stroke, side - stroke)
        rect.moveCenter(QPointF(self.width() / 2.0, self.height() / 2.0))

        pen = QPen(self._track, stroke, Qt.PenStyle.SolidLine,
                   Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)

        span = int(-self._value * 3.6 * 16)
        pen = QPen(self._accent, stroke, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 90 * 16, span)

        painter.setPen(QPen(self._text))
        big = QFont(self.font())
        big.setPointSizeF(side * 0.20)
        big.setBold(True)
        painter.setFont(big)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, f"{self._value:.0f}")
        painter.end()


class StatTile(QFrame):
    """One headline number with a caption and an optional inline bar."""

    def __init__(self, label: str, glyph: str = "✧", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Well")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(4)

        head = QHBoxLayout()
        head.setSpacing(6)
        self.glyph_label = QLabel(glyph)
        role(self.glyph_label, "accent")
        head.addWidget(self.glyph_label)
        self.label = QLabel(label.upper())
        role(self.label, "statLabel")
        head.addWidget(self.label)
        head.addStretch(1)
        layout.addLayout(head)

        self.value_label = QLabel("—")
        role(self.value_label, "stat")
        layout.addWidget(self.value_label)

        self.bar = InlineBar(self, height=8)
        self.bar.set_ratio(0.0)
        layout.addWidget(self.bar)

    def set_value(self, text: str, ratio: float = 0.0, *, over: bool = False,
                  caption: str = "") -> None:
        self.value_label.setText(text)
        self.bar.set_ratio(ratio, over_limit=over)
        self.bar.set_caption(caption)


class Banner(QFrame):
    """Coloured notice strip: info / warn / bad."""

    def __init__(self, text: str = "", level: str = "info",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._level = level
        self.setObjectName(self._object_name(level))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        self.label = QLabel(text)
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        self.setVisible(bool(text))

    @staticmethod
    def _object_name(level: str) -> str:
        return {"warn": "BannerWarn", "bad": "BannerBad"}.get(level, "BannerInfo")

    def set_message(self, text: str, level: str | None = None) -> None:
        if level and level != self._level:
            self._level = level
            self.setObjectName(self._object_name(level))
            # Re-polish so the new objectName-based rule applies.
            style = self.style()
            style.unpolish(self)
            style.polish(self)
        self.label.setText(text)
        self.setVisible(bool(text))
        self.update()


class GlyphButton(QLabel):
    """Clickable glyph used as an icon button in dense rows."""

    clicked = Signal()

    def __init__(self, glyph: str, tooltip: str = "", parent: QWidget | None = None) -> None:
        super().__init__(glyph, parent)
        self.setToolTip(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        role(self, "accent")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)
