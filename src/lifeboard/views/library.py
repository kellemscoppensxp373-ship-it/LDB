"""Librarium (book shelf) + Diary (rich text editor with AI context menu)."""

from __future__ import annotations

import re
import shutil
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import (
    QAction,
    QFont,
    QImage,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextListFormat,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import paths
from ..ai.workers import AiController
from ..storage.store import Store
from ..text import best_plain_text, html_to_markdown, markdown_to_html, unique_image_path
from ..i18n import fmt_date, tr
from ..widgets.common import Card, SectionLabel, kind, role

#: canonical status keys (stored in data.json); only their display form is translated
BOOK_STATUSES = ("queued", "reading", "finished", "abandoned")

_STATUS_RU = {"queued": "в очереди", "reading": "читаю",
              "finished": "прочитано", "abandoned": "брошено"}


def _book_columns() -> tuple[str, ...]:
    return (tr("Title", "Название"), tr("Author", "Автор"),
            tr("Status", "Статус"), tr("Progress", "Прогресс"), "★")


def _status(value: str) -> str:
    """Display form of a book status in the active language."""
    return tr(value, _STATUS_RU.get(value, value))
IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)

def _ai_actions() -> tuple[tuple[str, str], ...]:
    return (
        ("summarize", tr("✠  Summarize entry", "✠  Краткое содержание")),
        ("improve", tr("✠  Improve style", "✠  Улучшить стиль")),
        ("ideas", tr("✠  Generate ideas", "✠  Сгенерировать идеи")),
    )


class LibraryView(QWidget):
    """Diary + book shelf in one page."""

    dateChanged = Signal(str)

    def __init__(self, store: Store, ai: AiController, palette: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.ai = ai
        self._palette = palette
        self._date = date.today()
        self._loading = False
        self._ai_kind = "summarize"
        self._last_ai_text = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(self._build_header())

        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._build_diary(), tr("✧  Diary", "✧  Дневник"))
        self.tabs.addTab(self._build_librarium(), tr("❖  Librarium", "❖  Гримуарий"))
        root.addWidget(self.tabs, 1)

        self._autosave = QTimer(self)
        self._autosave.setSingleShot(True)
        self._autosave.setInterval(900)
        self._autosave.timeout.connect(self._autosave_now)

        self.ai.token.connect(self._on_ai_token)
        self.ai.response.connect(self._on_ai_response)
        self.ai.error.connect(self._on_ai_error)
        self.refresh()

    # -------------------------------------------------------------- building
    def _build_header(self) -> QWidget:
        header = QWidget(self)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(SectionLabel(tr("Librarium & Grimoire", "Гримуарий и дневник"), "❖"))
        layout.addStretch(1)
        self.prev_button = QPushButton("◀", self)
        kind(self.prev_button, "icon")
        self.prev_button.setToolTip(tr("Previous day", "Предыдущий день"))
        self.prev_button.clicked.connect(lambda: self.shift_date(-1))
        layout.addWidget(self.prev_button)
        self.date_label = QLabel("", self)
        role(self.date_label, "accent")
        self.date_label.setMinimumWidth(150)
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.date_label)
        self.next_button = QPushButton("▶", self)
        kind(self.next_button, "icon")
        self.next_button.setToolTip(tr("Next day", "Следующий день"))
        self.next_button.clicked.connect(lambda: self.shift_date(1))
        layout.addWidget(self.next_button)
        self.today_button = QPushButton(tr("☾ TODAY", "☾ СЕГОДНЯ"), self)
        kind(self.today_button, "ghost")
        self.today_button.clicked.connect(self.go_today)
        layout.addWidget(self.today_button)
        return header

    def _build_diary(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 6, 2, 2)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        for label, tip, slot in (
            ("B", tr("Bold (Ctrl+B)", "Жирный (Ctrl+B)"), lambda: self._toggle_char("bold")),
            ("I", tr("Italic (Ctrl+I)", "Курсив (Ctrl+I)"), lambda: self._toggle_char("italic")),
            ("U", tr("Underline (Ctrl+U)", "Подчёркнутый (Ctrl+U)"), lambda: self._toggle_char("underline")),
            ("H1", tr("Heading 1", "Заголовок 1"), lambda: self._set_heading(1)),
            ("H2", tr("Heading 2", "Заголовок 2"), lambda: self._set_heading(2)),
            ("H3", tr("Heading 3", "Заголовок 3"), lambda: self._set_heading(3)),
            ("•", tr("Bullet list", "Маркированный список"), lambda: self._set_list(QTextListFormat.ListStyle.ListDisc)),
            ("1.", tr("Numbered list", "Нумерованный список"), lambda: self._set_list(QTextListFormat.ListStyle.ListDecimal)),
            ("—", tr("Horizontal rule", "Горизонтальная линия"), self._insert_rule),
            ("⌫", tr("Clear formatting", "Очистить форматирование"), self._clear_format),
        ):
            button = QPushButton(label, page)
            kind(button, "icon")
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(slot)
            toolbar.addWidget(button)

        toolbar.addSpacing(10)
        image_button = QPushButton(tr("🖼  IMAGE", "🖼  РИСУНОК"), page)
        kind(image_button, "ghost")
        image_button.setToolTip(tr("Insert a local image (copied into assets/images)",
                                   "Вставить локальный рисунок (копируется в assets/images)"))
        image_button.clicked.connect(self.insert_image)
        toolbar.addWidget(image_button)

        import_button = QPushButton(tr("⇩  MARKDOWN", "⇩  MARKDOWN"), page)
        kind(import_button, "ghost")
        import_button.setToolTip(tr("Import a .md file into this entry",
                                    "Импортировать файл .md в эту запись"))
        import_button.clicked.connect(self.import_markdown)
        toolbar.addWidget(import_button)

        export_button = QPushButton(tr("⇧  EXPORT", "⇧  ЭКСПОРТ"), page)
        kind(export_button, "ghost")
        export_button.setToolTip(tr("Export this entry as markdown",
                                    "Экспортировать запись в markdown"))
        export_button.clicked.connect(self.export_markdown)
        toolbar.addWidget(export_button)

        toolbar.addStretch(1)
        ai_button = QPushButton(tr("✠  ADVISOR", "✠  СОВЕТНИК"), page)
        kind(ai_button, "primary")
        ai_button.setToolTip(tr("Run the local model on this entry",
                                "Прогнать локальную модель по этой записи"))
        ai_menu = QMenu(ai_button)
        for action_key, label in _ai_actions():
            action = QAction(label, ai_menu)
            action.triggered.connect(
                lambda checked=False, key=action_key: self.run_ai(key))
            ai_menu.addAction(action)
        ai_button.setMenu(ai_menu)
        toolbar.addWidget(ai_button)
        layout.addLayout(toolbar)

        self.editor = QTextEdit(page)
        self.editor.setObjectName("DiaryEditor")
        self.editor.setPlaceholderText(tr(
            "Write. Right-click for the advisor: summarize, improve style, "
            "generate ideas…",
            "Пишите. Правый клик — советник: краткое содержание, "
            "улучшить стиль, сгенерировать идеи…"))
        self.editor.setAcceptRichText(True)
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self.show_editor_menu)
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor, 1)

        footer = QHBoxLayout()
        self.word_count = QLabel(tr("0 words", "0 слов"), page)
        role(self.word_count, "hint")
        footer.addWidget(self.word_count)
        self.save_state = QLabel("", page)
        role(self.save_state, "muted")
        footer.addWidget(self.save_state)
        footer.addStretch(1)
        layout.addLayout(footer)

        # ---- AI result panel --------------------------------------------
        self.ai_card = Card(tr("Advisor Output", "Вывод советника"), "✠")
        self.ai_output = QTextEdit(self.ai_card)
        self.ai_output.setReadOnly(True)
        self.ai_output.setPlaceholderText(tr("the advisor's answer appears here",
                                         "здесь появится ответ советника"))
        self.ai_output.setFixedHeight(120)
        self.ai_card.content.addWidget(self.ai_output)
        ai_buttons = QHBoxLayout()
        for label, tip, slot in (
            (tr("⇩  INSERT BELOW", "⇩  ВСТАВИТЬ ВНИЗ"),
             tr("append the answer to the entry", "дописать ответ в запись"),
             self.insert_ai_below),
            (tr("⇄  REPLACE SELECTION", "⇄  ЗАМЕНИТЬ ВЫДЕЛЕНИЕ"),
             tr("replace the selected text", "заменить выделенный текст"),
             self.replace_selection_ai),
            (tr("⧉  COPY", "⧉  КОПИРОВАТЬ"),
             tr("copy to clipboard", "копировать в буфер обмена"),
             self.copy_ai_output),
            (tr("✕  CLEAR", "✕  ОЧИСТИТЬ"),
             tr("clear the answer", "очистить ответ"),
             self.ai_output.clear),
        ):
            button = QPushButton(label, self.ai_card)
            kind(button, "ghost")
            button.setToolTip(tip)
            button.clicked.connect(slot)
            ai_buttons.addWidget(button)
        ai_buttons.addStretch(1)
        self.ai_card.content.addLayout(ai_buttons)
        layout.addWidget(self.ai_card)
        return page

    def _build_librarium(self) -> QWidget:
        page = QWidget(self)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(2, 6, 2, 2)
        layout.setSpacing(8)

        self.book_table = QTableWidget(0, 5, page)
        self.book_table.setHorizontalHeaderLabels(_book_columns())
        self.book_table.verticalHeader().setVisible(False)
        self.book_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.book_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.book_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.book_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3, 4):
            header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.book_table.currentCellChanged.connect(self._on_book_selected)
        layout.addWidget(self.book_table, 1)

        form = QHBoxLayout()
        form.setSpacing(6)
        self.book_title = QLineEdit(page)
        self.book_title.setPlaceholderText(tr("title", "название"))
        form.addWidget(self.book_title, 2)
        self.book_author = QLineEdit(page)
        self.book_author.setPlaceholderText(tr("author", "автор"))
        form.addWidget(self.book_author, 1)
        self.book_status = QComboBox(page)
        self.book_status.addItems([_status(s) for s in BOOK_STATUSES])
        form.addWidget(self.book_status)
        self.book_pages = QSpinBox(page)
        self.book_pages.setRange(0, 100000)
        self.book_pages.setSuffix(tr(" pages", " стр."))
        self.book_pages.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        form.addWidget(self.book_pages)
        add_book = QPushButton(tr("✧  ADD", "✧  ДОБАВИТЬ"), page)
        kind(add_book, "primary")
        add_book.clicked.connect(self.add_book)
        form.addWidget(add_book)
        remove_book = QPushButton(tr("✕  REMOVE", "✕  УДАЛИТЬ"), page)
        kind(remove_book, "danger")
        remove_book.clicked.connect(self.remove_book)
        form.addWidget(remove_book)
        layout.addLayout(form)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(6)
        progress_label = QLabel(tr("progress", "прогресс"), page)
        role(progress_label, "muted")
        progress_row.addWidget(progress_label)
        self.book_read = QSpinBox(page)
        self.book_read.setRange(0, 100000)
        self.book_read.setSuffix(tr(" pages read", " стр. прочитано"))
        self.book_read.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.book_read.valueChanged.connect(self.update_book_progress)
        progress_row.addWidget(self.book_read)
        self.book_rating = QComboBox(page)
        self.book_rating.addItems(["—"] + [f"{i} ★" for i in range(1, 6)])
        self.book_rating.currentIndexChanged.connect(self.update_book_rating)
        progress_row.addWidget(self.book_rating)
        self.book_set_status = QComboBox(page)
        self.book_set_status.addItems([_status(s) for s in BOOK_STATUSES])
        self.book_set_status.currentIndexChanged.connect(self.update_book_status)
        progress_row.addWidget(self.book_set_status)
        progress_row.addStretch(1)
        layout.addLayout(progress_row)

        notes_label = QLabel(tr("❖  NOTES / MARGINALIA", "❖  ЗАМЕТКИ / ВЫПИСКИ"), page)
        role(notes_label, "cardTitle")
        layout.addWidget(notes_label)
        self.book_notes = QTextEdit(page)
        self.book_notes.setPlaceholderText(tr("quotes, takeaways, what to apply…",
                                          "цитаты, выводы, что применить…"))
        self.book_notes.setMaximumHeight(130)
        self.book_notes.textChanged.connect(self._on_notes_changed)
        layout.addWidget(self.book_notes)
        return page

    # ------------------------------------------------------------------- date
    @property
    def iso_date(self) -> str:
        return self._date.isoformat()

    def shift_date(self, days: int) -> None:
        self.set_date((self._date + timedelta(days=days)).isoformat())

    def go_today(self) -> None:
        self.set_date(date.today().isoformat())

    def set_date(self, iso: str) -> None:
        self._flush_editor()
        self._date = date.fromisoformat(str(iso)[:10])
        self.refresh()
        self.dateChanged.emit(self.iso_date)

    # ---------------------------------------------------------------- refresh
    def refresh(self) -> None:
        self._loading = True
        state = self.store.data
        self.date_label.setText(fmt_date(self._date))
        is_today = self._date == date.today()
        self.next_button.setEnabled(not is_today)
        self.today_button.setEnabled(not is_today)

        entry = state.get("diary", {}).get(self.iso_date, {})
        html = entry.get("html", "")
        self.editor.blockSignals(True)
        self.editor.setHtml(html)
        self._register_image_resources(html)
        self.editor.blockSignals(False)
        self._update_word_count()
        self.save_state.setText(tr(f"saved {entry.get('updated', '—')}",
                               f"сохранено {entry.get('updated', '—')}"))

        self._refresh_books()
        self._loading = False

    def _refresh_books(self) -> None:
        books = self.store.data.get("library", [])
        self.book_table.setRowCount(0)
        for book in books:
            row = self.book_table.rowCount()
            self.book_table.insertRow(row)
            title_item = QTableWidgetItem(book["title"])
            title_item.setData(Qt.ItemDataRole.UserRole, book["id"])
            self.book_table.setItem(row, 0, title_item)
            self.book_table.setItem(row, 1, QTableWidgetItem(book.get("author", "")))
            self.book_table.setItem(row, 2, QTableWidgetItem(_status(book.get("status", ""))))
            total = book.get("pages_total") or 0
            read = book.get("pages_read") or 0
            progress = f"{read}/{total}"
            if total:
                progress += f"  ({read / total * 100:.0f}%)"
            self.book_table.setItem(row, 3, QTableWidgetItem(progress))
            rating = book.get("rating") or 0
            self.book_table.setItem(row, 4, QTableWidgetItem("★" * rating or "—"))
        if books:
            self.book_table.selectRow(0)
            self._load_book(books[0])

    # ------------------------------------------------------------------ diary
    def _on_text_changed(self) -> None:
        if self._loading:
            return
        self._update_word_count()
        self.save_state.setText(tr("editing…", "редактирование…"))
        self._autosave.start()

    def _update_word_count(self) -> None:
        words = len(self.editor.toPlainText().split())
        chars = len(self.editor.toPlainText())
        self.word_count.setText(tr(f"{words} words · {chars} chars",
                               f"слов: {words} · символов: {chars}"))

    def _autosave_now(self) -> None:
        self._flush_editor()

    def _flush_editor(self) -> None:
        if self._loading:
            return
        html = self.editor.toHtml()
        text = best_plain_text(html)
        self.store.save_diary(html, text, day=self.iso_date)
        stamp = self.store.data["diary"].get(self.iso_date, {}).get("updated", "")
        self.save_state.setText(tr(f"saved {stamp}", f"сохранено {stamp}"))

    # ------------------------------------------------------- editor commands
    def _toggle_char(self, which: str) -> None:
        """Flip bold / italic / underline on the current selection."""
        cursor = self.editor.textCursor()
        fmt = QTextCharFormat(cursor.charFormat())
        if which == "bold":
            is_bold = fmt.fontWeight() >= QFont.Weight.Bold
            fmt.setFontWeight(QFont.Weight.Normal if is_bold else QFont.Weight.Bold)
        elif which == "italic":
            fmt.setFontItalic(not fmt.fontItalic())
        elif which == "underline":
            fmt.setFontUnderline(not fmt.fontUnderline())
        cursor.setCharFormat(fmt)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _set_heading(self, level: int) -> None:
        """Markdown-style heading: 0 clears, 1..3 set the block level."""
        cursor = self.editor.textCursor()
        block_fmt = cursor.blockFormat()
        block_fmt.setHeadingLevel(0 if block_fmt.headingLevel() == level else level)
        cursor.setBlockFormat(block_fmt)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()


    def _set_list(self, style: Any) -> None:
        cursor = self.editor.textCursor()
        list_fmt = QTextListFormat()
        if cursor.currentList() is not None:
            list_fmt = cursor.currentList().format()
        list_fmt.setStyle(style)
        cursor.createList(list_fmt)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def _insert_rule(self) -> None:
        self.editor.insertHtml("<hr/>")
        self.editor.setFocus()

    def _clear_format(self) -> None:
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            cursor.setCharFormat(QTextCharFormat())
            block_fmt = cursor.blockFormat()
            block_fmt.setHeadingLevel(0)
            cursor.setBlockFormat(block_fmt)
        self.editor.setFocus()

    # ----------------------------------------------------------------- images
    def insert_image(self) -> None:
        start = str(paths.image_dir())
        chosen, _ = QFileDialog.getOpenFileName(
            self, tr("Insert image", "Вставка рисунка"), start,
            tr("Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)",
               "Рисунки (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;Все файлы (*)"))
        if not chosen:
            return
        try:
            target = unique_image_path(paths.image_dir(), chosen)
            if Path(chosen).resolve() != target.resolve():
                shutil.copy2(chosen, target)
        except OSError as exc:
            QMessageBox.warning(self, "LifeBoard AI",
                                tr(f"Could not copy the image:\n{exc}",
                                   f"Не удалось скопировать рисунок:\n{exc}"))
            return
        image = QImage(str(target))
        if image.isNull():
            QMessageBox.warning(self, "LifeBoard AI",
                                tr("That file is not a readable image.",
                                   "Этот файл не является читаемым рисунком."))
            return
        self._register_image(target.name, image)
        self.editor.insertHtml(f'<img src="{target.name}" width="{min(560, image.width())}"/>')
        self.save_state.setText(tr(f"image stored as assets/images/{target.name}",
                               f"рисунок сохранён как assets/images/{target.name}"))

    def _register_image(self, name: str, image: QImage) -> None:
        self.editor.document().addResource(
            QTextDocument.ResourceType.ImageResource, QUrl(name), image)

    def _register_image_resources(self, html: str) -> None:
        """Rebind every ``<img src>`` in a stored entry to its file on disk."""
        if "<img" not in html.lower():
            return
        for match in IMG_SRC_RE.finditer(html):
            name = Path(match.group(1)).name
            candidate = paths.image_dir() / name
            if candidate.is_file():
                image = QImage(str(candidate))
                if not image.isNull():
                    self._register_image(name, image)

    # -------------------------------------------------------------- markdown
    def import_markdown(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, tr("Import markdown", "Импорт markdown"), str(paths.app_root()),
            tr("Markdown (*.md *.markdown *.txt);;All files (*)",
               "Markdown (*.md *.markdown *.txt);;Все файлы (*)"))
        if not chosen:
            return
        try:
            source = Path(chosen).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "LifeBoard AI",
                                tr(f"Could not read the file:\n{exc}",
                                   f"Не удалось прочитать файл:\n{exc}"))
            return
        self.editor.setHtml(markdown_to_html(source))
        self._flush_editor()

    def export_markdown(self) -> None:
        default = f"diary-{self.iso_date}.md"
        chosen, _ = QFileDialog.getSaveFileName(
            self, tr("Export as markdown", "Экспорт в markdown"),
            str(paths.app_root() / default),
            tr("Markdown (*.md)", "Markdown (*.md)"))
        if not chosen:
            return
        try:
            Path(chosen).write_text(
                html_to_markdown(self.editor.toHtml()), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "LifeBoard AI",
                                tr(f"Could not write the file:\n{exc}",
                                   f"Не удалось записать файл:\n{exc}"))
            return
        self.save_state.setText(tr(f"exported to {chosen}", f"экспортировано в {chosen}"))

    # ------------------------------------------------------------ context menu
    def build_editor_menu(self) -> QMenu:
        """The diary's custom context menu (built, not shown — testable)."""
        menu = QMenu(self.editor)
        menu.addActions(self.editor.createStandardContextMenu().actions())
        menu.addSeparator()
        header = menu.addAction(tr("✠  ADVISOR", "✠  СОВЕТНИК"))
        header.setEnabled(False)
        for action_key, label in _ai_actions():
            action = QAction(label, menu)
            action.triggered.connect(
                lambda checked=False, key=action_key: self.run_ai(key))
            menu.addAction(action)
        menu.addSeparator()
        image_action = QAction(tr("🖼  Insert image…", "🖼  Вставить рисунок…"), menu)
        image_action.triggered.connect(self.insert_image)
        menu.addAction(image_action)
        rule_action = QAction(tr("—  Insert rule", "—  Вставить линию"), menu)
        rule_action.triggered.connect(self._insert_rule)
        menu.addAction(rule_action)
        markdown_action = QAction(tr("⇩  Import markdown…", "⇩  Импорт markdown…"), menu)
        markdown_action.triggered.connect(self.import_markdown)
        menu.addAction(markdown_action)
        return menu

    def show_editor_menu(self, position) -> None:
        self.build_editor_menu().exec(self.editor.mapToGlobal(position))

    # --------------------------------------------------------------------- AI
    def _ai_body(self) -> str:
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            return cursor.selection().toPlainText().strip()
        return best_plain_text(self.editor.toHtml())

    def run_ai(self, action_key: str) -> None:
        self._flush_editor()
        body = self._ai_body()
        if not body:
            self.ai_output.setPlainText(tr(
                "Nothing to work with — write something (or select a passage) first.",
                "Нечего обрабатывать — сначала что-нибудь напишите "
                "(или выделите фрагмент)."))
            return
        self._ai_kind = action_key
        self._last_ai_text = ""
        self.ai_output.setPlainText("…")
        labels = dict(_ai_actions())
        caption = labels.get(action_key, action_key)[4:]
        self.ai_card.set_title(
            tr(f"Advisor Output — {caption}", f"Вывод советника — {caption}"), "✠")
        started = self.ai.editor_action(
            action_key, body, state=self.store.snapshot_data(),
            day=self.iso_date, tag="editor")
        if not started:
            self.ai_output.setPlainText(tr(
                "The advisor is busy with another request — stop it first.",
                "Советник занят другим запросом — сначала остановите его."))

    def _on_ai_token(self, piece: str, tag: str) -> None:
        if tag != "editor":
            return
        if self._last_ai_text == "" and self.ai_output.toPlainText() == "…":
            self.ai_output.clear()
        self._last_ai_text += piece
        self.ai_output.setPlainText(self._last_ai_text)

    def _on_ai_response(self, text: str, tag: str) -> None:
        if tag != "editor":
            return
        self._last_ai_text = text
        self.ai_output.setPlainText(text)

    def _on_ai_error(self, message: str, tag: str) -> None:
        if tag != "editor":
            return
        self.ai_output.setPlainText(tr(
            f"[advisor unavailable] {message}\n\n{self._last_ai_text}",
            f"[советник недоступен] {message}\n\n{self._last_ai_text}"))

    def insert_ai_below(self) -> None:
        text = self.ai_output.toPlainText().strip()
        if not text:
            return
        self.editor.moveCursor(QTextCursor.MoveOperation.End)
        self.editor.insertHtml("<hr/>" + markdown_to_html(text))
        self._flush_editor()

    def replace_selection_ai(self) -> None:
        text = self.ai_output.toPlainText().strip()
        if not text:
            return
        cursor = self.editor.textCursor()
        if cursor.hasSelection():
            cursor.insertHtml(markdown_to_html(text))
        else:
            self.editor.moveCursor(QTextCursor.MoveOperation.End)
            self.editor.insertHtml("<hr/>" + markdown_to_html(text))
        self._flush_editor()

    def copy_ai_output(self) -> None:
        QApplication.clipboard().setText(self.ai_output.toPlainText())
        self.save_state.setText(tr("advisor output copied to clipboard",
                               "вывод советника скопирован в буфер обмена"))

    # ------------------------------------------------------------- librarium
    def _current_book(self) -> dict[str, Any] | None:
        row = self.book_table.currentRow()
        if row < 0:
            return None
        item = self.book_table.item(row, 0)
        if item is None:
            return None
        book_id = item.data(Qt.ItemDataRole.UserRole)
        for book in self.store.data.get("library", []):
            if book["id"] == book_id:
                return book
        return None

    def _load_book(self, book: dict[str, Any]) -> None:
        self._loading = True
        self.book_read.blockSignals(True)
        self.book_rating.blockSignals(True)
        self.book_set_status.blockSignals(True)
        self.book_read.setMaximum(max(1, int(book.get("pages_total") or 1)))
        self.book_read.setValue(int(book.get("pages_read") or 0))
        rating = int(book.get("rating") or 0)
        self.book_rating.setCurrentIndex(rating)
        status = book.get("status", "queued")
        self.book_set_status.setCurrentIndex(
            BOOK_STATUSES.index(status) if status in BOOK_STATUSES else 0)
        self.book_notes.blockSignals(True)
        self.book_notes.setPlainText(book.get("notes", ""))
        self.book_notes.blockSignals(False)
        self.book_read.blockSignals(False)
        self.book_rating.blockSignals(False)
        self.book_set_status.blockSignals(False)
        self._loading = False

    def _on_book_selected(self, row: int, _col: int, _prev_row: int,
                          _prev_col: int) -> None:
        book = self._current_book()
        if book is not None:
            self._load_book(book)

    def _on_notes_changed(self) -> None:
        if self._loading:
            return
        book = self._current_book()
        if book is None:
            return
        self.store.update_book(book["id"], notes=self.book_notes.toPlainText())

    def add_book(self) -> None:
        title = self.book_title.text().strip()
        if not title:
            self.book_title.setFocus()
            return
        status_index = self.book_status.currentIndex()
        status = BOOK_STATUSES[status_index] if 0 <= status_index < len(BOOK_STATUSES) \
            else "queued"
        self.store.add_book({
            "title": title,
            "author": self.book_author.text().strip(),
            "status": status,
            "pages_total": int(self.book_pages.value()),
            "pages_read": 0,
            "rating": 0,
            "started": self.iso_date if status == "reading" else "",
            "finished": "",
            "notes": "",
        })
        self.book_title.clear()
        self.book_author.clear()
        self.book_pages.setValue(0)
        self.refresh()

    def remove_book(self) -> None:
        book = self._current_book()
        if book is None:
            return
        self.store.remove_book(book["id"])
        self.refresh()

    def update_book_progress(self, value: int) -> None:
        book = self._current_book()
        if book is None or self._loading:
            return
        self.store.update_book(book["id"], pages_read=int(value))
        self._refresh_books()

    def update_book_rating(self, index: int) -> None:
        book = self._current_book()
        if book is None or self._loading:
            return
        self.store.update_book(book["id"], rating=max(0, index))
        self._refresh_books()

    def update_book_status(self, _index: int) -> None:
        book = self._current_book()
        if book is None or self._loading:
            return
        index = self.book_set_status.currentIndex()
        status = BOOK_STATUSES[index] if 0 <= index < len(BOOK_STATUSES) else "queued"
        fields: dict[str, Any] = {"status": status}
        if status == "reading" and not book.get("started"):
            fields["started"] = self.iso_date
        if status == "finished" and not book.get("finished"):
            fields["finished"] = self.iso_date
        self.store.update_book(book["id"], **fields)
        self._refresh_books()

    # -------------------------------------------------------------- theming
    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette
