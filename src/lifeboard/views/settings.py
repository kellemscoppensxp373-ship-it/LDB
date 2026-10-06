"""Settings: hue, goals, AI engine, data vault."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPalette
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__, paths
from ..ai.engine import env_diagnostics
from ..ai.prompts import default_persona
from ..ai.workers import AiController
from ..storage.store import Store
from ..i18n import tr
from ..theme import build_palette, heat_levels
from ..widgets.common import Banner, Card, HRule, SectionLabel, kind, role


class HueSwatch(QWidget):
    """Live strip of the palette derived from the current hue."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._colors: list[QColor] = []
        self.setFixedHeight(26)

    def set_palette(self, palette: dict[str, str]) -> None:
        keys = ["BG0", "BG1", "BG2", "BG3", "BORDER", "ACCENT_DARK", "ACCENT",
                "ACCENT_BRIGHT", "GOOD", "WARN", "DANGER"] + \
               [f"HEAT{i}" for i in range(5)]
        self._colors = [QColor(palette[key]) for key in keys if key in palette]
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        if not self._colors:
            return
        painter = QPainter(self)
        width = self.width() / len(self._colors)
        for index, color in enumerate(self._colors):
            painter.fillRect(int(index * width), 0, int(width) + 1, self.height(), color)
        painter.end()


class SettingsView(QWidget):
    """Every knob the app exposes, plus the data-vault controls."""

    hueChanged = Signal(int)
    goalsChanged = Signal()           # explicit "apply targets"
    miscChanged = Signal()            # week start / profile name (no reload)
    modelRequested = Signal(str)      # path, or "" to unload
    restored = Signal()

    def __init__(self, store: Store, ai: AiController, palette: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.ai = ai
        self._palette = palette
        self._loading = False

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        self.body = QVBoxLayout(container)
        self.body.setContentsMargins(0, 0, 8, 8)
        self.body.setSpacing(12)
        scroll.setWidget(container)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.addWidget(SectionLabel(tr("Rites & Configuration", "Обряды и настройки"), "☾"))
        root.addWidget(scroll, 1)

        self._build_appearance()
        self._build_goals()
        self._build_ai()
        self._build_data()
        self._build_about()
        self.body.addStretch(1)

        ai.statusChanged.connect(self.set_engine_status)
        self.refresh()

    # -------------------------------------------------------------- sections
    def _build_appearance(self) -> None:
        card = Card(tr("Palette — single base hue", "Палитра — один базовый тон"), "✧")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.hue_slider_row = QHBoxLayout()
        from PySide6.QtWidgets import QSlider
        self.hue = QSlider(Qt.Orientation.Horizontal, self)
        self.hue.setRange(0, 359)
        self.hue.valueChanged.connect(self._on_hue)
        self.hue_slider_row.addWidget(self.hue, 1)
        self.hue_value = QLabel("0°", self)
        role(self.hue_value, "accent")
        self.hue_value.setFixedWidth(48)
        self.hue_slider_row.addWidget(self.hue_value)
        form.addRow(tr("hue", "тон"), self._wrap(self.hue_slider_row))

        self.swatch = HueSwatch(self)
        form.addRow(tr("palette", "палитра"), self.swatch)

        self.monday_check = QCheckBox(
            tr("weeks start on Monday (heatmap columns)",
               "недели начинаются в понедельник (колонки тепловой карты)"), self)
        self.monday_check.toggled.connect(self._save_settings)
        form.addRow(tr("calendar", "календарь"), self.monday_check)

        card.content.addLayout(form)
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        for label, value in ((tr("violet", "фиолет"), 265), (tr("blood", "кровь"), 350),
                             (tr("absinthe", "абсент"), 95), (tr("cyanide", "цианид"), 190),
                             (tr("ember", "угли"), 25), (tr("bone", "кость"), 45)):
            button = QPushButton(f"{label} {value}°", self)
            kind(button, "ghost")
            button.clicked.connect(lambda checked=False, v=value: self.hue.setValue(v))
            preset_row.addWidget(button)
        preset_row.addStretch(1)
        card.content.addLayout(preset_row)
        self.body.addWidget(card)

    def _build_goals(self) -> None:
        card = Card(tr("Targets", "Цели"), "❖")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.kcal = self._spin(0, 20000, tr(" kcal", " ккал"))
        self.protein = self._spin(0, 1000, tr(" g", " г"))
        self.carbs = self._spin(0, 2000, tr(" g", " г"))
        self.fat = self._spin(0, 1000, tr(" g", " г"))
        self.tonnage = QDoubleSpinBox(self)
        self.tonnage.setRange(0, 100000)
        self.tonnage.setDecimals(0)
        self.tonnage.setSuffix(tr(" kg", " кг"))
        self.habits_goal = self._spin(0, 50, tr(" rites", " обрядов"))

        for label, widget in ((tr("calories", "калории"), self.kcal),
                              (tr("protein", "белок"), self.protein),
                              (tr("carbs", "углеводы"), self.carbs),
                              (tr("fat", "жиры"), self.fat),
                              (tr("session tonnage", "тоннаж тренировки"), self.tonnage),
                              (tr("habits per day", "обрядов в день"), self.habits_goal)):
            widget.valueChanged.connect(self._save_settings)
            form.addRow(label, widget)

        self.profile = QTextEdit(self)
        self.profile.setFixedHeight(34)
        self.profile.textChanged.connect(self._save_settings)
        form.addRow(tr("profile name", "имя профиля"), self.profile)

        apply_button = QPushButton(tr("✧  APPLY TARGETS", "✧  ПРИМЕНИТЬ ЦЕЛИ"), self)
        kind(apply_button, "primary")
        apply_button.clicked.connect(self.apply_goals)
        card.content.addLayout(form)
        card.content.addWidget(apply_button, 0, Qt.AlignmentFlag.AlignRight)
        self.body.addWidget(card)

    def _build_ai(self) -> None:
        card = Card(tr("Local AI Engine", "Локальный ИИ-движок"), "✠")
        self.engine_banner = Banner("", "info", card)
        card.content.addWidget(self.engine_banner)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        models_row = QHBoxLayout()
        self.model_combo = QComboBox(self)
        self.model_combo.setMinimumWidth(280)
        models_row.addWidget(self.model_combo, 1)
        rescan = QPushButton("⟳", self)
        kind(rescan, "icon")
        rescan.setToolTip(tr("Rescan the models folder", "Пересканировать папку моделей"))
        rescan.clicked.connect(self.refresh_models)
        models_row.addWidget(rescan)
        open_dir = QPushButton("🗀", self)
        kind(open_dir, "icon")
        open_dir.setToolTip(tr("Open the models folder", "Открыть папку моделей"))
        open_dir.clicked.connect(self.open_models_dir)
        models_row.addWidget(open_dir)
        form.addRow(tr("model", "модель"), self._wrap(models_row))

        self.models_hint = QLabel("", self)
        role(self.models_hint, "hint")
        form.addRow(tr("folder", "папка"), self.models_hint)

        self.n_ctx = self._spin(256, 262144, "")
        self.n_gpu = self._spin(-1, 999, tr(" layers", " слоёв"))
        self.n_threads = self._spin(0, 512, tr(" threads", " потоков"))
        self.temperature = QDoubleSpinBox(self)
        self.temperature.setRange(0.0, 2.0)
        self.temperature.setSingleStep(0.05)
        self.temperature.setDecimals(2)
        self.top_p = QDoubleSpinBox(self)
        self.top_p.setRange(0.0, 1.0)
        self.top_p.setSingleStep(0.01)
        self.top_p.setDecimals(2)
        self.max_tokens = self._spin(16, 16384, tr(" tokens", " токенов"))

        for label, widget in ((tr("context window", "окно контекста"), self.n_ctx),
                              (tr("GPU layers", "слои на GPU"), self.n_gpu),
                              (tr("CPU threads", "потоки CPU"), self.n_threads),
                              (tr("temperature", "температура"), self.temperature),
                              ("top_p", self.top_p),
                              (tr("max answer", "макс. ответ"), self.max_tokens)):
            form.addRow(label, widget)

        self.auto_briefing = QCheckBox(
            tr("generate the morning briefing on startup",
               "строить утреннюю сводку при запуске"), self)
        form.addRow(tr("startup", "запуск"), self.auto_briefing)

        self.persona = QTextEdit(self)
        self.persona.setFixedHeight(80)
        self.persona.setPlaceholderText(tr(
            "leave empty to use the built-in advisor persona (shown here)",
            "оставьте пустым - будет использована встроенная персона советника "
            "(показана ниже)"))
        form.addRow(tr("persona", "персона"), self.persona)
        card.content.addLayout(form)

        buttons = QHBoxLayout()
        self.load_button = QPushButton(tr("⚡  LOAD MODEL", "⚡  ЗАГРУЗИТЬ МОДЕЛЬ"), self)
        kind(self.load_button, "primary")
        self.load_button.clicked.connect(self.load_model)
        buttons.addWidget(self.load_button)
        self.unload_button = QPushButton(tr("■  UNLOAD", "■  ВЫГРУЗИТЬ"), self)
        kind(self.unload_button, "danger")
        self.unload_button.clicked.connect(self.unload_model)
        buttons.addWidget(self.unload_button)
        apply_ai = QPushButton(tr("✧  SAVE PARAMETERS", "✧  СОХРАНИТЬ ПАРАМЕТРЫ"), self)
        kind(apply_ai, "ghost")
        apply_ai.clicked.connect(self.apply_ai_settings)
        buttons.addWidget(apply_ai)
        buttons.addStretch(1)
        card.content.addLayout(buttons)

        self.diagnostics = QLabel("", self)
        role(self.diagnostics, "hint")
        self.diagnostics.setWordWrap(True)
        self.diagnostics.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        card.content.addWidget(HRule(card))
        card.content.addWidget(self.diagnostics)
        self.body.addWidget(card)

    def _build_data(self) -> None:
        card = Card(tr("Data Vault", "Хранилище данных"), "❖")
        self.data_path_label = QLabel("", self)
        role(self.data_path_label, "hint")
        self.data_path_label.setWordWrap(True)
        self.data_path_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        card.content.addWidget(self.data_path_label)

        self.backup_combo = QComboBox(self)
        self.backup_combo.setMinimumWidth(320)
        card.content.addWidget(self.backup_combo)

        buttons = QHBoxLayout()
        for label, tip, slot, style in (
            (tr("⟳  REFRESH LIST", "⟳  ОБНОВИТЬ СПИСОК"),
             tr("rescan the backups folder", "пересканировать папку backups/"),
             self.refresh_backups, "ghost"),
            (tr("✧  BACKUP NOW", "✧  СОЗДАТЬ КОПИЮ"),
             tr("write a snapshot into backups/", "записать снимок в backups/"),
             self.backup_now, "primary"),
            (tr("⇪  RESTORE", "⇪  ВОССТАНОВИТЬ"),
             tr("restore the selected snapshot", "восстановить выбранный снимок"),
             self.restore_backup, "danger"),
            (tr("⧉  EXPORT JSON", "⧉  ЭКСПОРТ JSON"),
             tr("write a copy of data.json", "записать копию data.json"),
             self.export_json, "ghost"),
        ):
            button = QPushButton(label, self)
            kind(button, style)
            button.setToolTip(tip)
            button.clicked.connect(slot)
            buttons.addWidget(button)
        buttons.addStretch(1)
        card.content.addLayout(buttons)

        self.vault_hint = QLabel(tr(
            "Every save is atomic (temp file + os.replace). The five newest "
            "snapshots are kept; older ones are pruned automatically.",
            "Каждое сохранение атомарно (временный файл + os.replace). "
            "Хранятся пять последних снимков; более старые удаляются автоматически.",
        ), self)
        role(self.vault_hint, "muted")
        self.vault_hint.setWordWrap(True)
        card.content.addWidget(self.vault_hint)
        self.body.addWidget(card)

    def _build_about(self) -> None:
        card = Card(tr("About", "О программе"), "✠")
        about = QLabel(tr(
            f"{__app_name__} v{__version__}\n"
            "Native PySide6 desktop app. No browser, no server, no telemetry.\n"
            "The advisor runs entirely offline on a quantised GGUF model.",
            f"{__app_name__} v{__version__}\n"
            "Нативное приложение на PySide6. Без браузера, сервера и телеметрии.\n"
            "Советник работает полностью офлайн на квантованной модели GGUF.",
        ), self)
        role(about, "muted")
        about.setWordWrap(True)
        card.content.addWidget(about)
        self.body.addWidget(card)

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _wrap(layout: QHBoxLayout) -> QWidget:
        holder = QWidget()
        holder.setLayout(layout)
        return holder

    @staticmethod
    def _spin(minimum: int, maximum: int, suffix: str) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(suffix)
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        return spin

    # ---------------------------------------------------------------- refresh
    def refresh(self) -> None:
        self._loading = True
        settings = self.store.settings
        goals = settings["goals"]
        ai = settings["ai"]

        self.hue.setValue(int(settings.get("hue", 265)))
        self.hue_value.setText(f"{int(settings.get('hue', 265))}°")
        self.swatch.set_palette(build_palette(int(settings.get("hue", 265))))
        self.monday_check.setChecked(bool(settings.get("week_starts_monday", True)))

        self.kcal.setValue(int(goals.get("kcal", 0)))
        self.protein.setValue(int(goals.get("protein", 0)))
        self.carbs.setValue(int(goals.get("carbs", 0)))
        self.fat.setValue(int(goals.get("fat", 0)))
        self.tonnage.setValue(float(goals.get("tonnage", 0)))
        self.habits_goal.setValue(int(goals.get("habits", 0)))
        self.profile.setPlainText(str(settings.get("profile_name", "")))

        self.n_ctx.setValue(int(ai.get("n_ctx", 4096)))
        self.n_gpu.setValue(int(ai.get("n_gpu_layers", 0)))
        self.n_threads.setValue(int(ai.get("n_threads", 0)))
        self.temperature.setValue(float(ai.get("temperature", 0.7)))
        self.top_p.setValue(float(ai.get("top_p", 0.92)))
        self.max_tokens.setValue(int(ai.get("max_tokens", 512)))
        self.auto_briefing.setChecked(bool(ai.get("auto_briefing", True)))
        self.persona.setPlainText(str(ai.get("persona", "")))
        self.persona.setToolTip(tr("Effective persona:", "Действующая персона:")
                                + "\n" + default_persona())

        self.data_path_label.setText(tr(
            f"data file   {self.store.path}\n"
            f"backups     {self.store.backup_dir}  (keep {self.store.backup_keep})\n"
            f"images      {paths.image_dir()}",
            f"файл данных   {self.store.path}\n"
            f"резервные копии  {self.store.backup_dir}  (хранить {self.store.backup_keep})\n"
            f"рисунки       {paths.image_dir()}"))

        self.refresh_models()
        self.refresh_backups()
        self.set_engine_status(self.ai.status())
        self._loading = False

    def refresh_models(self) -> None:
        engine = self.ai.engine
        models = engine.list_models()
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem(tr("— no model selected —", "— модель не выбрана —"), "")
        for info in models:
            self.model_combo.addItem(f"[{info.family}] {info.label}", str(info.path))
        configured = engine.configured_model()
        if configured is not None:
            index = self.model_combo.findData(str(configured))
            if index >= 0:
                self.model_combo.setCurrentIndex(index)
        self.model_combo.blockSignals(False)
        self.models_hint.setText(tr(
            f"{paths.model_dir()}  ·  {len(models)} GGUF file(s) found  ·  "
            f"override with LIFEBOARD_MODELS",
            f"{paths.model_dir()}  ·  найдено GGUF-файлов: {len(models)}  ·  "
            f"переопределяется через LIFEBOARD_MODELS"))
        self._update_diagnostics()

    def _update_diagnostics(self) -> None:
        facts = env_diagnostics()
        self.diagnostics.setText(
            tr("diagnostics", "диагностика") + ":  "
            + "   |   ".join(f"{k}={v}" for k, v in facts.items()))

    def refresh_backups(self) -> None:
        backups = self.store.list_backups()
        self.backup_combo.clear()
        for path in backups:
            self.backup_combo.addItem(
                f"{path.name}  ·  {paths.human_size(path.stat().st_size)}",
                str(path))
        if not backups:
            self.backup_combo.addItem(tr("— no snapshots yet —", "— снимков пока нет —"), "")

    # ---------------------------------------------------------------- actions
    def _on_hue(self, value: int) -> None:
        self.hue_value.setText(f"{value}°")
        self.swatch.set_palette(build_palette(value))
        if not self._loading:
            self.hueChanged.emit(int(value))

    def _save_settings(self, *_args: Any) -> None:
        """Persist the light-weight settings without reloading the form.

        Deliberately does *not* emit ``goalsChanged``: a full refresh would
        re-read the store and throw away whatever the user is still typing.
        """
        if self._loading:
            return
        self.store.update_settings(
            week_starts_monday=self.monday_check.isChecked(),
            profile_name=self.profile.toPlainText().strip() or tr("Acolyte", "Адепт"),
        )
        self.miscChanged.emit()

    def apply_goals(self) -> None:
        self.store.update_settings(
            goals={
                "kcal": self.kcal.value(),
                "protein": self.protein.value(),
                "carbs": self.carbs.value(),
                "fat": self.fat.value(),
                "tonnage": float(self.tonnage.value()),
                "habits": self.habits_goal.value(),
            },
            profile_name=self.profile.toPlainText().strip() or tr("Acolyte", "Адепт"),
            week_starts_monday=self.monday_check.isChecked(),
        )
        self.goalsChanged.emit()

    def apply_ai_settings(self) -> None:
        self.store.update_settings(
            ai={
                "n_ctx": self.n_ctx.value(),
                "n_gpu_layers": self.n_gpu.value(),
                "n_threads": self.n_threads.value(),
                "temperature": float(self.temperature.value()),
                "top_p": float(self.top_p.value()),
                "max_tokens": self.max_tokens.value(),
                "auto_briefing": self.auto_briefing.isChecked(),
                "persona": self.persona.toPlainText().strip(),
                "model_file": self.model_combo.currentData() or "",
            })
        self.set_engine_status(self.ai.status())

    def load_model(self) -> None:
        self.apply_ai_settings()
        chosen = self.model_combo.currentData() or ""
        if not chosen:
            QMessageBox.information(
                self, __app_name__,
                tr("No model selected. Drop a .gguf file into the models folder "
                   "and press the rescan button.",
                   "Модель не выбрана. Положите файл .gguf в папку models "
                   "и нажмите кнопку пересканирования."))
            return
        self.load_button.setEnabled(False)
        self.modelRequested.emit(str(chosen))

    def unload_model(self) -> None:
        self.modelRequested.emit("")

    def set_engine_status(self, status: dict) -> None:
        self.load_button.setEnabled(True)
        available = bool(status.get("available"))
        level = "info" if available else "warn"
        backend = status.get("backend", "?")
        model = status.get("model") or tr("none", "нет")
        message = status.get("message", "")
        self.engine_banner.set_message(tr(
            f"engine: {backend}  ·  model: {model}  ·  {message}",
            f"движок: {backend}  ·  модель: {model}  ·  {message}"), level)
        params = status.get("params", {})
        if params:
            self.diagnostics.setToolTip(str(params))

    def backup_now(self) -> None:
        path = self.store.snapshot("manual")
        self.refresh_backups()
        if path is None:
            QMessageBox.warning(self, __app_name__,
                            tr("Nothing to back up yet.", "Сохранять пока нечего."))
        else:
            self.vault_hint.setText(tr(f"snapshot written: {path.name}",
                               f"снимок записан: {path.name}"))

    def restore_backup(self) -> None:
        chosen = self.backup_combo.currentData()
        if not chosen:
            return
        answer = QMessageBox.question(
            self, __app_name__,
            tr(f"Restore {chosen}?\n\nThe current data.json is snapshotted first, "
               "so this can be undone.",
               f"Восстановить {chosen}?\n\nТекущий data.json сначала будет "
               "сохранён в снимок, так что действие обратимо."),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.store.restore(chosen)
        self.refresh_backups()
        self.restored.emit()

    def export_json(self) -> None:
        default = str(paths.app_root() / f"lifeboard-export.json")
        chosen, _ = QFileDialog.getSaveFileName(
            self, tr("Export data.json", "Экспорт data.json"), default,
            tr("JSON (*.json)", "JSON (*.json)"))
        if not chosen:
            return
        import json
        try:
            with open(chosen, "w", encoding="utf-8") as handle:
                json.dump(self.store.snapshot_data(), handle, indent=2,
                          ensure_ascii=False)
        except OSError as exc:
            QMessageBox.warning(self, __app_name__,
                                tr(f"Export failed:\n{exc}",
                                   f"Ошибка экспорта:\n{exc}"))
            return
        self.vault_hint.setText(tr(f"exported to {chosen}", f"экспортировано в {chosen}"))

    def open_models_dir(self) -> None:
        directory = paths.model_dir()
        directory.mkdir(parents=True, exist_ok=True)
        QFileDialog.getOpenFileName(self, tr("Models folder", "Папка моделей"),
                                    str(directory))

    # --------------------------------------------------------------- theming
    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette
        self.swatch.set_palette(palette)
