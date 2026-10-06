"""Каркас приложения: главное окно, тема, ИИ-обвязка, завершение работы."""

from __future__ import annotations

import sys
import traceback
from datetime import date
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from . import __app_name__, __version__, paths
from .ai.engine import AIEngine
from .ai.workers import AiController
from .i18n import tr
from .storage.store import CorruptionRecovered, Store
from .theme import FONT_FAMILIES, build_palette, build_stylesheet, load_template
from .views import DashboardView, LibraryView, SettingsView, WorkoutView
from .widgets.common import role
from .widgets.sidebar import Sidebar

# (ключ, английский заголовок, глиф) — заголовки локализуются через tr()
PAGES = (
    ("dashboard", "Command Deck", "✠"),
    ("iron", "Iron Library", "⚔"),
    ("grimoire", "Librarium", "❖"),
    ("rites", "Rites & Config", "☾"),
)


def page_title(key: str) -> str:
    titles = {
        "dashboard": tr("Command Deck", "Командная палуба"),
        "iron": tr("Iron Library", "Железный архив"),
        "grimoire": tr("Librarium", "Гримуарий"),
        "rites": tr("Rites & Config", "Обряды и настройки"),
    }
    return titles.get(key, key)


def page_glyph(key: str) -> str:
    for page_key, _en, glyph in PAGES:
        if page_key == key:
            return glyph
    return "✧"


def install_crash_handler() -> Path:
    """Перехват необработанных исключений в ``crash.log`` рядом с exe.

    Сборка PyInstaller с ``console=False`` не имеет stderr, поэтому без этого
    краш выглядел бы как «программа молча не запустилась».
    """
    log_path = paths.app_root() / "crash.log"

    def hook(exc_type, exc_value, exc_tb) -> None:
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        try:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(f"\n=== {date.today().isoformat()} ===\n{text}")
        except OSError:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = hook
    return log_path


class MainWindow(QMainWindow):
    """Боковая навигация + стек модулей, между ними — ИИ-контроллер."""

    def __init__(self, store: Store | None = None, *, run_briefing: bool = True,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{__app_name__}  ·  v{__version__}")
        self.resize(1360, 860)
        self.setMinimumSize(1080, 700)
        # Окно владеет всеми представлениями — освобождаем дерево при закрытии.
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        paths.ensure_runtime_dirs()
        self.store = store or Store()
        self._template = load_template()
        self.palette = build_palette(float(self.store.settings.get("hue", 265)))

        self.engine = AIEngine(
            lambda: self.store.settings,
            models_dir=paths.model_dir(),
            state_provider=self.store.snapshot_data,
        )
        self.ai = AiController(self.engine, self)
        self.ai.statusChanged.connect(self._on_status_changed)
        self.ai.error.connect(self._on_ai_error)

        self._build_ui()
        self.apply_theme(int(self.store.settings.get("hue", 265)))

        self.dashboard.load_chat_history()
        self._update_status()

        if run_briefing and bool(self.store.settings["ai"].get("auto_briefing", True)):
            QTimer.singleShot(120, self.run_startup_briefing)

    # -------------------------------------------------------------------- UI
    def _build_ui(self) -> None:
        central = QWidget(self)
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- боковая панель ----------------------------------------------
        rail = QWidget(self)
        rail.setObjectName("Sidebar")
        rail.setFixedWidth(196)
        rail_layout = QVBoxLayout(rail)
        rail_layout.setContentsMargins(10, 14, 10, 10)
        rail_layout.setSpacing(8)

        brand = QLabel(f"{__app_name__.upper()}", rail)
        role(brand, "appTitle")
        rail_layout.addWidget(brand)
        tagline = QLabel(tr("✠  offline life ledger", "✠  офлайн-летопись жизни"), rail)
        role(tagline, "muted")
        rail_layout.addWidget(tagline)

        self.sidebar = Sidebar(self.palette, rail)
        for key, _en, glyph in PAGES:
            self.sidebar.add_page(key, page_title(key), glyph)
        self.sidebar.navigate.connect(self.navigate)
        rail_layout.addWidget(self.sidebar, 1)

        self.rail_status = QLabel("", rail)
        role(self.rail_status, "muted")
        self.rail_status.setWordWrap(True)
        rail_layout.addWidget(self.rail_status)
        root.addWidget(rail)

        # ---- стек страниц -------------------------------------------------
        self.stack = QStackedWidget(self)
        self.dashboard = DashboardView(self.store, self.ai, self.palette)
        self.workout = WorkoutView(self.store, self.palette)
        self.library = LibraryView(self.store, self.ai, self.palette)
        self.settings = SettingsView(self.store, self.ai, self.palette)
        for page in (self.dashboard, self.workout, self.library, self.settings):
            self.stack.addWidget(page)
        root.addWidget(self.stack, 1)

        self.setCentralWidget(central)
        self._build_menus()
        self._build_status_bar()

        self.sidebar.select_page("dashboard")
        for view in (self.dashboard, self.workout, self.library):
            view.dateChanged.connect(self._on_date_changed)
        self.settings.hueChanged.connect(self.apply_theme)
        self.settings.goalsChanged.connect(self.refresh_all)
        self.settings.miscChanged.connect(self.refresh_tracking_views)
        self.settings.modelRequested.connect(self.ai.load_model)
        self.settings.restored.connect(self.refresh_all)

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu(tr("✠  File", "✠  Файл"))
        backup = QAction(tr("Backup now", "Создать резервную копию"), self)
        backup.triggered.connect(self.settings.backup_now)
        file_menu.addAction(backup)
        export = QAction(tr("Export data.json…", "Экспорт data.json…"), self)
        export.triggered.connect(self.settings.export_json)
        file_menu.addAction(export)
        file_menu.addSeparator()
        folder = QAction(tr("Open data folder", "Открыть папку данных"), self)
        folder.triggered.connect(lambda: self._open_path(paths.app_root()))
        file_menu.addAction(folder)
        file_menu.addSeparator()
        quit_action = QAction(tr("Quit", "Выход"), self)
        quit_action.setShortcut("Ctrl+Q")
        quit_action.triggered.connect(self.close)
        file_menu.addAction(quit_action)

        advisor = bar.addMenu(tr("☾  Advisor", "☾  Советник"))
        load = QAction(tr("Load model", "Загрузить модель"), self)
        load.triggered.connect(self.settings.load_model)
        advisor.addAction(load)
        unload = QAction(tr("Unload model", "Выгрузить модель"), self)
        unload.triggered.connect(self.settings.unload_model)
        advisor.addAction(unload)
        advisor.addSeparator()
        briefing = QAction(tr("Re-run morning briefing", "Пересчитать утреннюю сводку"), self)
        briefing.setShortcut("Ctrl+R")
        briefing.triggered.connect(lambda: self.dashboard.run_briefing())
        advisor.addAction(briefing)
        stop = QAction(tr("Stop generation", "Остановить генерацию"), self)
        stop.setShortcut("Esc")
        stop.triggered.connect(self.ai.cancel)
        advisor.addAction(stop)

        view_menu = bar.addMenu(tr("❖  View", "❖  Вид"))
        for index, (key, _en, glyph) in enumerate(PAGES):
            action = QAction(f"{glyph}  {page_title(key)}", self)
            action.setShortcut(f"Ctrl+{index + 1}")
            action.triggered.connect(lambda checked=False, k=key: self.navigate(k))
            view_menu.addAction(action)

        help_menu = bar.addMenu(tr("✧  Help", "✧  Справка"))
        about = QAction(tr("About", "О программе"), self)
        about.triggered.connect(self._show_about)
        help_menu.addAction(about)
        models_help = QAction(tr("Where do models go?", "Куда класть модели?"), self)
        models_help.triggered.connect(self._show_model_help)
        help_menu.addAction(models_help)

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        self.status_date = QLabel("", self)
        self.status_save = QLabel("", self)
        self.status_ai = QLabel("", self)
        for widget in (self.status_date, self.status_save, self.status_ai):
            bar.addWidget(widget)
        bar.addPermanentWidget(self.status_ai)

    # ----------------------------------------------------------------- theme
    def apply_theme(self, hue: int) -> None:
        """Пересобрать палитру + QSS из одного оттенка и перекрасить всё."""
        self.palette = build_palette(float(hue))
        stylesheet = build_stylesheet(float(hue), self._template)[0]
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet)
        self.store.update_settings(hue=int(hue))
        for view in (self.dashboard, self.workout, self.library, self.settings):
            view.set_palette(self.palette)
        self.sidebar.set_palette(self.palette)
        self._update_status()

    # -------------------------------------------------------------- navigation
    def navigate(self, key: str) -> None:
        keys = [page[0] for page in PAGES]
        if key in keys:
            self.stack.setCurrentIndex(keys.index(key))
            self.sidebar.select_page(key)

    def _on_date_changed(self, iso: str) -> None:
        for view in (self.dashboard, self.workout, self.library):
            if view.iso_date != iso:
                view.set_date(iso)
        self.refresh_all()

    def refresh_all(self) -> None:
        for view in (self.dashboard, self.workout, self.library, self.settings):
            view.refresh()
        self._update_status()

    def refresh_tracking_views(self) -> None:
        for view in (self.dashboard, self.workout, self.library):
            view.refresh()
        self._update_status()

    # --------------------------------------------------------------------- AI
    def run_startup_briefing(self) -> None:
        text = self.dashboard.run_briefing(force_ai=False)
        status = self.engine.status()
        self._set_save_status(
            tr(f"briefing ready · {len(text)} chars",
               f"сводка готова · {len(text)} симв."))
        if status.available:
            self.dashboard.run_briefing(force_ai=True)
        else:
            self._set_save_status(
                tr(f"briefing ready (heuristic) · {status.message[:90]}",
                   f"сводка готова (эвристика) · {status.message[:90]}"))

    def _on_status_changed(self, status: dict) -> None:
        backend = status.get("backend", "?")
        model = status.get("model") or tr("none", "нет")
        available = bool(status.get("available"))
        glyph = "✠" if available else "☾"
        self.status_ai.setText(f"{glyph}  {backend} · {model}")
        self.rail_status.setText(
            f"{glyph}  {backend}\n{model}\n{str(status.get('message', ''))[:70]}")
        self.settings.set_engine_status(status)

    def _on_ai_error(self, message: str, tag: str) -> None:
        self._set_save_status(tr(f"advisor: {message[:110]}",
                                 f"советник: {message[:110]}"))

    # ----------------------------------------------------------------- status
    def _update_status(self) -> None:
        self.status_date.setText(f"✧  {self.dashboard.iso_date}")
        self._set_save_status(
            tr(f"saved {self.store.data.get('updated', '')}  ·  {self.store.path.name}",
               f"сохранено {self.store.data.get('updated', '')}  ·  {self.store.path.name}"))
        self._on_status_changed(self.ai.status())

    def _set_save_status(self, text: str) -> None:
        self.status_save.setText(text)

    # ------------------------------------------------------------------ misc
    def _open_path(self, path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _show_about(self) -> None:
        status = self.engine.status()
        QMessageBox.about(
            self, tr(f"About {__app_name__}", f"О программе {__app_name__}"),
            tr(
                f"<b>{__app_name__}</b> v{__version__}<br/>"
                "Native PySide6 desktop application — no browser, no HTTP server, "
                "no telemetry.<br/><br/>",
                f"<b>{__app_name__}</b> v{__version__}<br/>"
                "Нативное приложение PySide6 — без браузера, без HTTP-сервера, "
                "без телеметрии.<br/><br/>")
            + tr("data", "данные") + f": {self.store.path}<br/>"
            + tr("models", "модели") + f": {paths.model_dir()}<br/>"
            + tr("engine", "движок") + f": {status.backend} · {status.model or '—'}<br/>"
            + f"{status.message}")

    def _show_model_help(self) -> None:
        QMessageBox.information(
            self, tr("Local models", "Локальные модели"),
            tr(
                f"Drop a quantised GGUF file into:\n\n{paths.model_dir()}\n\n"
                "Recommended: Llama-3-8B-Instruct Q4_K_M (~4.9 GB) or "
                "Phi-3-mini-4k-instruct Q4_K_M (~2.2 GB).\n\n"
                "Set the environment variable LIFEBOARD_MODELS to point at models "
                "stored on another drive.\n\n"
                "For GPU acceleration install the CUDA build of llama-cpp-python "
                "and raise “GPU layers” in Rites & Config.",
                f"Положите квантованный GGUF-файл в папку:\n\n{paths.model_dir()}\n\n"
                "Рекомендуется: Llama-3-8B-Instruct Q4_K_M (~4,9 ГБ) или "
                "Phi-3-mini-4k-instruct Q4_K_M (~2,2 ГБ).\n\n"
                "Переменная окружения LIFEBOARD_MODELS указывает на модели, "
                "хранящиеся на другом диске.\n\n"
                "Для ускорения на GPU установите CUDA-сборку llama-cpp-python "
                "и увеличите «Слои GPU» в «Обрядах и настройках»."))

    # -------------------------------------------------------------- shutdown
    def closeEvent(self, event) -> None:  # noqa: N802
        self.library._flush_editor()
        self.ai.shutdown()
        try:
            self.store.shutdown()
        except Exception as exc:  # pragma: no cover - defensive
            QMessageBox.warning(
                self, __app_name__,
                tr(f"Could not write the final save:\n{exc}",
                   f"Не удалось выполнить итоговое сохранение:\n{exc}"))
        super().closeEvent(event)


def build_application(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    """Создать QApplication + окно (отдельно — ради тестов)."""
    app = QApplication.instance() or QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(__app_name__)
    app.setApplicationVersion(__version__)
    app.setOrganizationName("LifeBoard")
    app.setDesktopFileName("lifeboard-ai")

    font = QFont()
    font.setFamilies(list(FONT_FAMILIES))
    font.setStyleHint(QFont.StyleHint.Monospace)
    font.setPointSize(10)
    app.setFont(font)

    icon = QIcon()
    if not icon.isNull():  # pragma: no cover - only when an .ico is bundled
        app.setWindowIcon(icon)

    window = MainWindow()
    return app, window


def main(argv: list[str] | None = None) -> int:
    crash_log = install_crash_handler()
    try:
        app, window = build_application(argv)
    except CorruptionRecovered as exc:
        app = QApplication.instance() or QApplication(argv or sys.argv)
        QMessageBox.warning(None, __app_name__, f"{exc}\n\nCrash log: {crash_log}")
        return 1
    window.show()
    return app.exec()
