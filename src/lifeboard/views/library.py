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
from ..widgets.common import Card, SectionLabel, kind, role

BOOK_COLUMNS = ("Title", "Author", "Status", "Progress", "★")
BOOK_STATUSES = ("queued", "reading", "finished", "abandoned")
IMG_SRC_RE = re.compile(r'<img[^>]+src="([^"]+)"', re.IGNORECASE)

AI_ACTIONS = (
    ("summarize", "✠  Summarize entry"),
    ("improve", "✠  Improve style"),
    ("ideas", "✠  Generate ideas"),
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
        self.tabs.addTab(self._build_diary(), "✧  Diary")
        self.tabs.addTab(self._build_librarium(), "❖  Librarium")
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
        layout.addWidget(SectionLabel("Librarium & Grimoire", "❖"))
        layout.addStretch(1)
        self.prev_button = QPushButton("◀", self)
        kind(self.prev_button, "icon")
        self.prev_button.clicked.connect(lambda: self.shift_date(-1))
        layout.addWidget(self.prev_button)
        self.date_label = QLabel("", self)
        role(self.date_label, "accent")
        self.date_label.setMinimumWidth(150)
        self.date_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.date_label)
        self.next_button = QPushButton("▶", self)
        kind(self.next_button, "icon")
        self.next_button.clicked.connect(lambda: self.shift_date(1))
        layout.addWidget(self.next_button)
        self.today_button = QPushButton("☾ TODAY", self)
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
            ("B", "Bold (Ctrl+B)", lambda: self._toggle_char("bold")),
            ("I", "Italic (Ctrl+I)", lambda: self._toggle_char("italic")),
            ("U", "Underline (Ctrl+U)", lambda: self._toggle_char("underline")),
            ("H1", "Heading 1", lambda: self._set_heading(1)),
            ("H2", "Heading 2", lambda: self._set_heading(2)),
            ("H3", "Heading 3", lambda: self._set_heading(3)),
            ("•", "Bullet list", lambda: self._set_list(QTextListFormat.ListStyle.ListDisc)),
            ("1.", "Numbered list", lambda: self._set_list(QTextListFormat.ListStyle.ListDecimal)),
            ("—", "Horizontal rule", self._insert_rule),
            ("⌫", "Clear formatting", self._clear_format),
        ):
            button = QPushButton(label, page)
            kind(button, "icon")
            button.setToolTip(tip)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(slot)
            toolbar.addWidget(button)

        toolbar.addSpacing(10)
        image_button = QPushButton("🖼  IMAGE", page)
        kind(image_button, "ghost")
        image_button.setToolTip("Insert a local image (copied into assets/images)")
        image_button.clicked.connect(self.insert_image)
        toolbar.addWidget(image_button)

        import_button = QPushButton("⇩  MARKDOWN", page)
        kind(import_button, "ghost")
        import_button.setToolTip("Import a .md file into this entry")
        import_button.clicked.connect(self.import_markdown)
        toolbar.addWidget(import_button)

        export_button = QPushButton("⇧  EXPORT", page)
        kind(export_button, "ghost")
        export_button.setToolTip("Export this entry as markdown")
        export_button.clicked.connect(self.export_markdown)
        toolbar.addWidget(export_button)

        toolbar.addStretch(1)
        ai_button = QPushButton("✠  ADVISOR", page)
        kind(ai_button, "primary")
        ai_button.setToolTip("Run the local model on this entry")
        ai_menu = QMenu(ai_button)
        for action_key, label in AI_ACTIONS:
            action = QAction(label, ai_menu)
            action.triggered.connect(
                lambda checked=False, key=action_key: self.run_ai(key))
            ai_menu.addAction(action)
        ai_button.setMenu(ai_menu)
        toolbar.addWidget(ai_button)
        layout.addLayout(toolbar)

        self.editor = QTextEdit(page)
        self.editor.setObjectName("DiaryEditor")
        self.editor.setPlaceholderText(
            "Write. Right-click for the advisor: summarize, improve style, "
            "generate ideas…")
        self.editor.setAcceptRichText(True)
        self.editor.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.editor.customContextMenuRequested.connect(self.show_editor_menu)
        self.editor.textChanged.connect(self._on_text_changed)
        layout.addWidget(self.editor, 1)

        footer = QHBoxLayout()
        self.word_count = QLabel("0 words", page)
        role(self.word_count, "hint")
        footer.addWidget(self.word_count)
        self.save_state = QLabel("", page)
        role(self.save_state, "muted")
        footer.addWidget(self.save_state)
        footer.addStretch(1)
        layout.addLayout(footer)

        # ---- AI result panel --------------------------------------------
        self.ai_card = Card("Advisor Output", "✠")
        self.ai_output = QTextEdit(self.ai_card)
        self.ai_output.setReadOnly(True)
        self.ai_output.setPlaceholderText("the advisor's answer appears here")
        self.ai_output.setFixedHeight(120)
        self.ai_card.content.addWidget(self.ai_output)
        ai_buttons = QHBoxLayout()
        for label, tip, slot in (
            ("⇩  INSERT BELOW", "append the answer to the entry", self.insert_ai_below),
            ("⇄  REPLACE SELECTION", "replace the selected text", self.replace_selection_ai),
            ("⧉  COPY", "copy to clipboard", self.copy_ai_output),
            ("✕  CLEAR", "clear the answer", self.ai_output.clear),
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
        self.book_table.setHorizontalHeaderLabels(BOOK_COLUMNS)
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
        self.book_title.setPlaceholderText("title")
        form.addWidget(self.book_title, 2)
        self.book_author = QLineEdit(page)
        self.book_author.setPlaceholderText("author")
        form.addWidget(self.book_author, 1)
        self.book_status = QComboBox(page)
        self.book_status.addItems(BOOK_STATUSES)
        form.addWidget(self.book_status)
        self.book_pages = QSpinBox(page)
        self.book_pages.setRange(0, 100000)
        self.book_pages.setSuffix(" pages")
        self.book_pages.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        form.addWidget(self.book_pages)
        add_book = QPushButton("✧  ADD", page)
        kind(add_book, "primary")
        add_book.clicked.connect(self.add_book)
        form.addWidget(add_book)
        remove_book = QPushButton("✕  REMOVE", page)
        kind(remove_book, "danger")
        remove_book.clicked.connect(self.remove_book)
        form.addWidget(remove_book)
        layout.addLayout(form)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(6)
        progress_label = QLabel("progress", page)
        role(progress_label, "muted")
        progress_row.addWidget(progress_label)
        self.book_read = QSpinBox(page)
        self.book_read.setRange(0, 100000)
        self.book_read.setSuffix(" pages read")
        self.book_read.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.book_read.valueChanged.connect(self.update_book_progress)
        progress_row.addWidget(self.book_read)
        self.book_rating = QComboBox(page)
        self.book_rating.addItems(["—"] + [f"{i} ★" for i in range(1, 6)])
        self.book_rating.currentIndexChanged.connect(self.update_book_rating)
        progress_row.addWidget(self.book_rating)
        self.book_set_status = QComboBox(page)
        self.book_set_status.addItems(BOOK_STATUSES)
        self.book_set_status.currentIndexChanged.connect(self.update_book_status)
        progress_row.addWidget(self.book_set_status)
        progress_row.addStretch(1)
        layout.addLayout(progress_row)

        notes_label = QLabel("❖  NOTES / MARGINALIA", page)
        role(notes_label, "cardTitle")
        layout.addWidget(notes_label)
        self.book_notes = QTextEdit(page)
        self.book_notes.setPlaceholderText("quotes, takeaways, what to apply…")
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
        self.date_label.setText(self._date.strftime("%a %d %b %Y"))
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
        self.save_state.setText(f"saved {entry.get('updated', '—')}")

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
            self.book_table.setItem(row, 2, QTableWidgetItem(book.get("status", "")))
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
        self.save_state.setText("editing…")
        self._autosave.start()

    def _update_word_count(self) -> None:
        words = len(self.editor.toPlainText().split())
        chars = len(self.editor.toPlainText())
        self.word_count.setText(f"{words} words · {chars} chars")

    def _autosave_now(self) -> None:
        self._flush_editor()

    def _flush_editor(self) -> None:
        if self._loading:
            return
        html = self.editor.toHtml()
        text = best_plain_text(html)
        self.store.save_diary(html, text, day=self.iso_date)
        self.save_state.setText(f"saved {self.store.data['diary'].get(self.iso_date, {}).get('updated', '')}")

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
            self, "Insert image", start,
            "Images (*.png *.jpg *.jpeg *.bmp *.gif *.webp);;All files (*)")
        if not chosen:
            return
        try:
            target = unique_image_path(paths.image_dir(), chosen)
            if Path(chosen).resolve() != target.resolve():
                shutil.copy2(chosen, target)
        except OSError as exc:
            QMessageBox.warning(self, "LifeBoard AI",
                                f"Could not copy the image:\n{exc}")
            return
        image = QImage(str(target))
        if image.isNull():
            QMessageBox.warning(self, "LifeBoard AI", "That file is not a readable image.")
            return
        self._register_image(target.name, image)
        self.editor.insertHtml(f'<img src="{target.name}" width="{min(560, image.width())}"/>')
        self.save_state.setText(f"image stored as assets/images/{target.name}")

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
            self, "Import markdown", str(paths.app_root()),
            "Markdown (*.md *.markdown *.txt);;All files (*)")
        if not chosen:
            return
        try:
            source = Path(chosen).read_text(encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "LifeBoard AI", f"Could not read the file:\n{exc}")
            return
        self.editor.setHtml(markdown_to_html(source))
        self._flush_editor()

    def export_markdown(self) -> None:
        default = f"diary-{self.iso_date}.md"
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export as markdown", str(paths.app_root() / default),
            "Markdown (*.md)")
        if not chosen:
            return
        try:
            Path(chosen).write_text(
                html_to_markdown(self.editor.toHtml()), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "LifeBoard AI", f"Could not write the file:\n{exc}")
            return
        self.save_state.setText(f"exported to {chosen}")

    # ------------------------------------------------------------ context menu
    def build_editor_menu(self) -> QMenu:
        """The diary's custom context menu (built, not shown — testable)."""
        menu = QMenu(self.editor)
        menu.addActions(self.editor.createStandardContextMenu().actions())
        menu.addSeparator()
        header = menu.addAction("✠  ADVISOR")
        header.setEnabled(False)
        for action_key, label in AI_ACTIONS:
            action = QAction(label, menu)
            action.triggered.connect(
                lambda checked=False, key=action_key: self.run_ai(key))
            menu.addAction(action)
        menu.addSeparator()
        image_action = QAction("🖼  Insert image…", menu)
        image_action.triggered.connect(self.insert_image)
        menu.addAction(image_action)
        rule_action = QAction("—  Insert rule", menu)
        rule_action.triggered.connect(self._insert_rule)
        menu.addAction(rule_action)
        markdown_action = QAction("⇩  Import markdown…", menu)
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
            self.ai_output.setPlainText(
                "Nothing to work with — write something (or select a passage) first.")
            return
        self._ai_kind = action_key
        self._last_ai_text = ""
        self.ai_output.setPlainText("…")
        labels = dict(AI_ACTIONS)
        self.ai_card.set_title(f"Advisor Output — {labels.get(action_key, action_key)[4:]}", "✠")
        started = self.ai.editor_action(
            action_key, body, state=self.store.snapshot_data(),
            day=self.iso_date, tag="editor")
        if not started:
            self.ai_output.setPlainText(
                "The advisor is busy with another request — stop it first.")

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
        self.ai_output.setPlainText(f"[advisor unavailable] {message}\n\n{self._last_ai_text}")

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
        self.save_state.setText("advisor output copied to clipboard")

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
        index = self.book_set_status.findText(status)
        self.book_set_status.setCurrentIndex(max(0, index))
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
        self.store.add_book({
            "title": title,
            "author": self.book_author.text().strip(),
            "status": self.book_status.currentText(),
            "pages_total": int(self.book_pages.value()),
            "pages_read": 0,
            "rating": 0,
            "started": self.iso_date if self.book_status.currentText() == "reading" else "",
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
        status = self.book_set_status.currentText()
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
