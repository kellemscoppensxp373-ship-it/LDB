"""Left navigation rail: a QListWidget with a hand-painted delegate."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QStyle, QStyledItemDelegate


class SidebarDelegate(QStyledItemDelegate):
    """Draws ``glyph + title`` with an accent rule under the active entry."""

    GLYPH_WIDTH = 26

    def __init__(self, palette: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self._palette = palette

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(option.rect.width() or 180, 42)

    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rect = QRectF(option.rect).adjusted(6, 1, -6, -1)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)

        accent = QColor(self._palette.get("ACCENT", "#9B7BFF"))
        bright = QColor(self._palette.get("ACCENT_BRIGHT", "#C9B6FF"))
        wash = QColor(self._palette.get("ACCENT_WASH", "#1D1830"))
        dim = QColor(self._palette.get("TEXT_DIM", "#8A8FA3"))
        text = QColor(self._palette.get("TEXT", "#E6E6F0"))

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(wash)
            painter.drawRoundedRect(rect, 3, 3)
            painter.setBrush(accent)
            painter.drawRect(QRectF(rect.left(), rect.top() + 4, 2, rect.height() - 8))
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(self._palette.get("ACCENT_A18", "#221C33")))
            painter.drawRoundedRect(rect, 3, 3)

        glyph_font = QFont(option.font)
        glyph_font.setPointSizeF(option.font.pointSizeF() + 2.5)
        painter.setFont(glyph_font)
        painter.setPen(QPen(bright if selected else dim))
        glyph_rect = QRectF(rect.left() + 6, rect.top(), self.GLYPH_WIDTH, rect.height())
        painter.drawText(glyph_rect, Qt.AlignmentFlag.AlignCenter,
                         str(index.data(Qt.ItemDataRole.UserRole + 1) or "✧"))

        title_font = QFont(option.font)
        title_font.setBold(selected)
        painter.setFont(title_font)
        painter.setPen(QPen(bright if selected else (text if hovered else dim)))
        text_rect = QRectF(rect.left() + 6 + self.GLYPH_WIDTH, rect.top(),
                           rect.width() - self.GLYPH_WIDTH - 10, rect.height())
        painter.drawText(text_rect,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        painter.restore()


class Sidebar(QListWidget):
    """Navigation list emitting ``navigate(key)``."""

    navigate = Signal(str)

    def __init__(self, palette: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("SidebarList")
        self._palette = palette
        self._delegate = SidebarDelegate(palette, self)
        self.setItemDelegate(self._delegate)
        self.setUniformItemSizes(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedWidth(196)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.currentRowChanged.connect(self._on_row_changed)

    # ------------------------------------------------------------------ API
    def add_page(self, key: str, title: str, glyph: str) -> QListWidgetItem:
        item = QListWidgetItem(title, self)
        item.setData(Qt.ItemDataRole.UserRole, key)
        item.setData(Qt.ItemDataRole.UserRole + 1, glyph)
        item.setToolTip(title)
        return item

    def select_page(self, key: str) -> None:
        for row in range(self.count()):
            if self.item(row).data(Qt.ItemDataRole.UserRole) == key:
                self.setCurrentRow(row)
                return

    def set_status(self, text: str) -> None:
        """Update (or create) the small footer line under the nav entries."""
        item = self.item(self.count() - 1) if self.count() else None
        if item is None or item.data(Qt.ItemDataRole.UserRole) != "__status__":
            item = QListWidgetItem("", self)
            item.setData(Qt.ItemDataRole.UserRole, "__status__")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
        item.setText(text)
        self.itemWidget  # no-op: keeps linters aware the widget exists
        self.viewport().update()

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette
        self._delegate.set_palette(palette)
        self.viewport().update()

    # -------------------------------------------------------------- internal
    def _on_row_changed(self, row: int) -> None:
        if row < 0:
            return
        key = self.item(row).data(Qt.ItemDataRole.UserRole)
        if key and key != "__status__":
            self.navigate.emit(str(key))
