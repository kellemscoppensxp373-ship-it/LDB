"""The AI advisor chat: QListView transcript + QTextEdit composer."""

from __future__ import annotations

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QSizePolicy,
    QStyledItemDelegate,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .common import kind, role

USER_ROLE = Qt.ItemDataRole.UserRole + 1
TEXT_ROLE = Qt.ItemDataRole.UserRole + 2
TIME_ROLE = Qt.ItemDataRole.UserRole + 3


class ChatModel(QAbstractListModel):
    """Chat transcript as a list model (role, text, timestamp)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[dict[str, str]] = []

    # -- Qt API ----------------------------------------------------------
    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._items)

    def data(self, index: QModelIndex, role_int: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._items)):
            return None
        item = self._items[index.row()]
        if role_int == Qt.ItemDataRole.DisplayRole:
            return item["text"]
        if role_int == USER_ROLE:
            return item["role"]
        if role_int == TEXT_ROLE:
            return item["text"]
        if role_int == TIME_ROLE:
            return item.get("ts", "")
        return None

    # -- mutation --------------------------------------------------------
    def append(self, role_name: str, text: str, ts: str = "") -> int:
        row = len(self._items)
        self.beginInsertRows(QModelIndex(), row, row)
        self._items.append({"role": role_name, "text": text, "ts": ts})
        self.endInsertRows()
        return row

    def update_last(self, text: str) -> None:
        if not self._items:
            return
        row = len(self._items) - 1
        self._items[row]["text"] = text
        index = self.index(row)
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.DisplayRole, TEXT_ROLE])

    def clear(self) -> None:
        if not self._items:
            return
        self.beginResetModel()
        self._items.clear()
        self.endResetModel()

    def history(self) -> list[dict[str, str]]:
        """Conversation without empty placeholders, ready for the engine."""
        return [{"role": item["role"], "content": item["text"]}
                for item in self._items
                if item["role"] in ("user", "assistant") and item["text"].strip()]

    def count(self) -> int:
        return len(self._items)


class ChatDelegate(QStyledItemDelegate):
    """Chat bubble renderer — user right-aligned, advisor left-aligned."""

    PAD_X = 12
    PAD_Y = 8
    MAX_WIDTH_RATIO = 0.86

    def __init__(self, palette: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self._palette = palette

    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette

    # -- sizing ----------------------------------------------------------
    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        text = str(index.data(TEXT_ROLE) or "")
        available = max(140, int((option.rect.width() or 520) * self.MAX_WIDTH_RATIO)
                        - 2 * self.PAD_X - 78)
        metrics = QFontMetrics(option.font)
        box = metrics.boundingRect(QRect(0, 0, available, 10_000),
                                   Qt.TextFlag.TextWordWrap, text)
        height = box.height() + 2 * self.PAD_Y + 16
        return QSize(option.rect.width() or 520, max(46, height))

    # -- painting --------------------------------------------------------
    def paint(self, painter: QPainter, option, index) -> None:  # noqa: N802
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        text = str(index.data(TEXT_ROLE) or "")
        who = str(index.data(USER_ROLE) or "assistant")
        is_user = who == "user"

        accent = QColor(self._palette.get("ACCENT", "#9B7BFF"))
        accent_dark = QColor(self._palette.get("ACCENT_DARK", "#2A2145"))
        bg3 = QColor(self._palette.get("BG3", "#1B2130"))
        border = QColor(self._palette.get("BORDER", "#232A3A"))
        text_color = QColor(self._palette.get("TEXT", "#E6E6F0"))

        bubble_width = int((option.rect.width() or 520) * self.MAX_WIDTH_RATIO)
        total_height = option.rect.height()
        bubble_height = max(30, total_height - 16)
        if is_user:
            x = option.rect.right() - bubble_width
        else:
            x = option.rect.left() + 44
        bubble = QRectF(x, option.rect.top() + 14, bubble_width, bubble_height)

        painter.setPen(QPen(accent if is_user else border, 1.0))
        painter.setBrush(accent_dark if is_user else bg3)
        painter.drawRoundedRect(bubble, 6, 6)

        # Speaker tag above the bubble.
        tag_font = QFont(option.font)
        tag_font.setPointSizeF(max(6.5, option.font.pointSizeF() - 1.5))
        tag_font.setBold(True)
        painter.setFont(tag_font)
        painter.setPen(QPen(accent if is_user else
                            QColor(self._palette.get("TEXT_FAINT", "#6B7280"))))
        label = "☾ YOU" if is_user else "✠ ADVISOR"
        painter.drawText(QRectF(bubble.left(), option.rect.top(),
                                bubble.width(), 14),
                         Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         label)

        body_font = QFont(option.font)
        painter.setFont(body_font)
        painter.setPen(QPen(text_color))
        body = QRectF(bubble.left() + self.PAD_X, bubble.top() + self.PAD_Y - 8,
                      bubble.width() - 2 * self.PAD_X,
                      bubble.height() - 2 * self.PAD_Y + 8)
        painter.drawText(body, Qt.TextFlag.TextWordWrap | Qt.AlignmentFlag.AlignTop,
                         text)
        painter.restore()


class AiChatPanel(QWidget):
    """Chat transcript + composer + status line."""

    askRequested = Signal(str)
    stopRequested = Signal()
    clearRequested = Signal()

    def __init__(self, palette: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._streaming = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.model = ChatModel(self)
        self.view = QListView(self)
        self.view.setObjectName("AiChatList")
        self.view.setModel(self.model)
        self._delegate = ChatDelegate(palette, self.view)
        self.view.setItemDelegate(self._delegate)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.view.setUniformItemSizes(False)
        self.view.setWordWrap(True)
        self.view.setVerticalScrollMode(
            QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setMinimumHeight(190)
        layout.addWidget(self.view, 1)

        self.status = QLabel("✧  the advisor is idle", self)
        role(self.status, "muted")
        layout.addWidget(self.status)

        self.composer = QTextEdit(self)
        self.composer.setObjectName("AiComposer")
        self.composer.setPlaceholderText(
            "Ask about your log…  (Enter sends, Shift+Enter adds a line)")
        self.composer.setFixedHeight(78)
        self.composer.installEventFilter(self)
        layout.addWidget(self.composer)

        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.clear_button = QPushButton("⌫  CLEAR", self)
        kind(self.clear_button, "ghost")
        self.clear_button.clicked.connect(self.clearRequested)
        buttons.addWidget(self.clear_button)
        buttons.addStretch(1)
        self.stop_button = QPushButton("■  STOP", self)
        kind(self.stop_button, "danger")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stopRequested)
        buttons.addWidget(self.stop_button)
        self.send_button = QPushButton("✠  CONSULT", self)
        kind(self.send_button, "primary")
        self.send_button.clicked.connect(self.submit)
        buttons.addWidget(self.send_button)
        layout.addLayout(buttons)

    # ------------------------------------------------------------------ API
    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette
        self._delegate.set_palette(palette)
        self.view.viewport().update()

    def history(self) -> list[dict[str, str]]:
        return self.model.history()

    def restore(self, messages: list[dict[str, str]]) -> None:
        self.model.clear()
        for message in messages[-40:]:
            self.model.append(message.get("role", "assistant"),
                              message.get("content", ""),
                              message.get("ts", ""))
        self._scroll_to_end()

    def append_user(self, text: str) -> None:
        self.model.append("user", text)
        self._scroll_to_end()

    def begin_assistant(self, placeholder: str = "…") -> None:
        self.model.append("assistant", placeholder)
        self._streaming = True
        self._scroll_to_end()

    def stream_token(self, piece: str) -> None:
        if not self._streaming:
            self.begin_assistant("")
        last = self.model.index(self.model.rowCount() - 1)
        current = str(self.model.data(last, TEXT_ROLE) or "")
        self.model.update_last(current + piece)
        self._scroll_to_end()

    def finish_assistant(self, text: str) -> None:
        if self.model.rowCount() == 0:
            self.model.append("assistant", text)
        else:
            self.model.update_last(text)
        self._streaming = False
        self._scroll_to_end()

    def set_busy(self, busy: bool) -> None:
        self.send_button.setEnabled(not busy)
        self.stop_button.setEnabled(busy)
        self.composer.setReadOnly(busy)

    def set_status(self, text: str) -> None:
        self.status.setText(text)

    def submit(self) -> None:
        text = self.composer.toPlainText().strip()
        if not text:
            return
        self.composer.clear()
        self.askRequested.emit(text)

    # ------------------------------------------------------------ internals
    def _scroll_to_end(self) -> None:
        rows = self.model.rowCount()
        if rows:
            self.view.scrollToBottom()
            self.view.viewport().update()

    def eventFilter(self, watched, event) -> bool:  # noqa: N802
        if watched is self.composer and event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not (
                    event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.submit()
                return True
        return super().eventFilter(watched, event)
