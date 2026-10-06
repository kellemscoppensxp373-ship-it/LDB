"""Главная палуба: счёт, тепловая карта, обряды/питание, сводка, чат советника."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..ai.briefing import briefing_text, build_briefing
from ..ai.workers import AiController
from ..i18n import fmt_date, fmt_day_month, fmt_num, tr
from ..storage.metrics import day_metrics, heatmap_series, streak, summary_block
from ..storage.store import Store
from ..widgets.chat import AiChatPanel
from ..widgets.common import Banner, Card, HRule, InlineBar, ScoreRing, SectionLabel, StatTile, kind, role
from ..widgets.heatmap import ActivityHeatmap
from ..widgets.trackers import HabitRow, MealForm, MealRow, habit_streak


class DashboardView(QWidget):
    """Всё, что должно быть видно в момент открытия приложения."""

    dateChanged = Signal(str)

    HEATMAP_DAYS = 365

    def __init__(self, store: Store, ai: AiController, palette: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.ai = ai
        self._palette = palette
        self._date = date.today()
        self._habit_rows: dict[str, HabitRow] = {}
        self._meal_rows: list[MealRow] = []
        self._building = False

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(10)
        outer.addWidget(self._build_header())

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        container = QWidget()
        self.body = QVBoxLayout(container)
        self.body.setContentsMargins(0, 0, 8, 8)
        self.body.setSpacing(12)
        scroll.setWidget(container)
        outer.addWidget(scroll, 1)

        self._build_tiles()
        self._build_heatmap()
        self._build_trackers()
        self._build_ai()
        self.body.addStretch(1)

        self._wire_ai()
        self.refresh()

    # -------------------------------------------------------------- building
    def _build_header(self) -> QWidget:
        header = QWidget(self)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(SectionLabel(tr("Command Deck", "Командная палуба"), "✠"))
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

    def _build_tiles(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.score_card = Card(tr("Daily Sigil", "Печать дня"), "❖")
        score_box = QHBoxLayout()
        score_box.setSpacing(12)
        self.ring = ScoreRing(self)
        self.ring.set_value(0)
        score_box.addWidget(self.ring, 0, Qt.AlignmentFlag.AlignTop)
        detail = QVBoxLayout()
        detail.setSpacing(4)
        self.score_caption = QLabel("—")
        role(self.score_caption, "hint")
        self.score_caption.setWordWrap(True)
        detail.addWidget(self.score_caption)
        self.streak_label = QLabel("—")
        role(self.streak_label, "accent")
        detail.addWidget(self.streak_label)
        self.week_label = QLabel("—")
        role(self.week_label, "hint")
        detail.addWidget(self.week_label)
        score_box.addLayout(detail, 1)
        self.score_card.content.addLayout(score_box)
        row.addWidget(self.score_card, 1)

        self.tile_kcal = StatTile(tr("Intake", "Калории"), "✧")
        self.tile_protein = StatTile(tr("Protein", "Белок"), "❖")
        self.tile_tonnage = StatTile(tr("Tonnage", "Тоннаж"), "⚔")
        self.tile_habits = StatTile(tr("Habits", "Обряды"), "☾")
        for tile in (self.tile_kcal, self.tile_protein, self.tile_tonnage,
                     self.tile_habits):
            tile.setMinimumWidth(150)
            row.addWidget(tile, 1)
        self.body.addLayout(row)

    def _build_heatmap(self) -> None:
        self.heatmap_card = Card(tr("365-Day Ledger", "Летопись за 365 дней"), "✧")
        self.heatmap = ActivityHeatmap(self._palette, self.heatmap_card)
        self.heatmap.dayClicked.connect(self.set_date)
        self.heatmap.dayHovered.connect(self._on_heatmap_hover)
        self.heatmap_card.content.addWidget(self.heatmap)
        self.heat_hint = QLabel(tr(
            "hover a cell for detail · click to inspect that day",
            "наведите на клетку для деталей · клик — открыть этот день"))
        role(self.heat_hint, "hint")
        self.heatmap_card.content.addWidget(self.heat_hint)
        self.body.addWidget(self.heatmap_card)

    def _build_trackers(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)

        # ---- обряды -------------------------------------------------------
        self.habit_card = Card(tr("Rites", "Обряды"), "⚔")
        add_row = QHBoxLayout()
        self.habit_input = QLineEdit(self.habit_card)
        self.habit_input.setPlaceholderText(tr("new rite…", "новый обряд…"))
        self.habit_input.returnPressed.connect(self.add_habit)
        add_row.addWidget(self.habit_input, 1)
        add_button = QPushButton(tr("✧ ADD", "✧ ДОБАВИТЬ"), self.habit_card)
        kind(add_button, "primary")
        add_button.clicked.connect(self.add_habit)
        add_row.addWidget(add_button)
        self.habit_card.content.addLayout(add_row)

        self.habit_progress = InlineBar(self.habit_card, height=14)
        self.habit_card.content.addWidget(self.habit_progress)
        self.habit_list = QVBoxLayout()
        self.habit_list.setSpacing(2)
        self.habit_card.content.addLayout(self.habit_list)
        self.habit_summary = QLabel("—")
        role(self.habit_summary, "hint")
        self.habit_card.content.addWidget(self.habit_summary)
        row.addWidget(self.habit_card, 1)

        # ---- питание ------------------------------------------------------
        self.diet_card = Card(tr("Sustenance", "Провизия"), "❖")
        self.macro_summary = QLabel("—")
        role(self.macro_summary, "hint")
        self.diet_card.content.addWidget(self.macro_summary)
        self.macro_bars = QVBoxLayout()
        self.macro_bars.setSpacing(3)
        for key in ("kcal", "protein", "carbs", "fat"):
            line = QHBoxLayout()
            line.setSpacing(8)
            label = QLabel(tr({"kcal": "KCAL", "protein": "PROTEIN",
                               "carbs": "CARBS", "fat": "FAT"}[key],
                              {"kcal": "ККАЛ", "protein": "БЕЛОК",
                               "carbs": "УГЛЕВ", "fat": "ЖИРЫ"}[key]), self.diet_card)
            role(label, "muted")
            label.setFixedWidth(58)
            line.addWidget(label)
            bar = InlineBar(self.diet_card, height=11)
            line.addWidget(bar, 1)
            value = QLabel("0", self.diet_card)
            role(value, "accent")
            value.setFixedWidth(110)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(value)
            self.macro_bars.addLayout(line)
            setattr(self, f"_bar_{key}", bar)
            setattr(self, f"_val_{key}", value)
        self.diet_card.content.addLayout(self.macro_bars)
        self.diet_card.content.addWidget(HRule(self.diet_card))

        self.meal_list = QVBoxLayout()
        self.meal_list.setSpacing(1)
        self.diet_card.content.addLayout(self.meal_list)
        self.meal_form = MealForm(self.diet_card)
        self.meal_form.mealAdded.connect(self.add_meal)
        self.diet_card.content.addWidget(self.meal_form)
        row.addWidget(self.diet_card, 1)

        self.body.addLayout(row)

    def _build_ai(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(12)

        self.brief_card = Card(tr("Morning Briefing", "Утренняя сводка"), "☾")
        self.brief_banner = Banner("", "info", self.brief_card)
        self.brief_card.content.addWidget(self.brief_banner)
        self.brief_label = QLabel(tr("no analysis yet", "анализа пока нет"), self.brief_card)
        self.brief_label.setWordWrap(True)
        self.brief_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse)
        role(self.brief_label, "muted")
        self.brief_card.content.addWidget(self.brief_label)
        brief_buttons = QHBoxLayout()
        self.brief_button = QPushButton(tr("⟳  RE-RUN ANALYSIS", "⟳  ПЕРЕСЧИТАТЬ"), self.brief_card)
        kind(self.brief_button, "primary")
        self.brief_button.clicked.connect(self.run_briefing)
        brief_buttons.addWidget(self.brief_button)
        brief_buttons.addStretch(1)
        self.brief_card.content.addLayout(brief_buttons)
        self.brief_card.setMinimumWidth(320)
        row.addWidget(self.brief_card, 1)

        self.chat_card = Card(tr("Advisor", "Советник"), "✠")
        self.chat = AiChatPanel(self._palette, self.chat_card)
        self.chat.setMinimumHeight(360)
        self.chat_card.content.addWidget(self.chat, 1)
        row.addWidget(self.chat_card, 2)

        self.body.addLayout(row, 1)

    # ------------------------------------------------------------------- wire
    def _wire_ai(self) -> None:
        self.ai.token.connect(self._on_token)
        self.ai.response.connect(self._on_response)
        self.ai.error.connect(self._on_error)
        self.ai.busyChanged.connect(self._on_busy)
        self.chat.askRequested.connect(self.ask)
        self.chat.stopRequested.connect(self.ai.cancel)
        self.chat.clearRequested.connect(self.clear_chat)

    # ------------------------------------------------------------------- data
    @property
    def iso_date(self) -> str:
        return self._date.isoformat()

    def shift_date(self, days: int) -> None:
        self.set_date((self._date + timedelta(days=days)).isoformat())

    def go_today(self) -> None:
        self.set_date(date.today().isoformat())

    def set_date(self, iso: str) -> None:
        self._date = date.fromisoformat(str(iso)[:10])
        self.refresh()
        self.dateChanged.emit(self.iso_date)

    def refresh(self) -> None:
        self._building = True
        state = self.store.data
        metrics = day_metrics(state, self.iso_date)
        block = summary_block(state, end=self._date)
        goals = self.store.goals

        self.date_label.setText(fmt_date(self._date))
        is_today = self._date == date.today()
        self.next_button.setEnabled(not is_today)
        self.today_button.setEnabled(not is_today)

        # ---- счёт ---------------------------------------------------------
        self.ring.set_value(metrics["score"])
        self.score_caption.setText(tr(
            f"habits {metrics['habit_part'] * 100:.0f}% · "
            f"diet {metrics['diet_part'] * 100:.0f}% · "
            f"training {metrics['train_part'] * 100:.0f}%",
            f"обряды {metrics['habit_part'] * 100:.0f}% · "
            f"питание {metrics['diet_part'] * 100:.0f}% · "
            f"тренинг {metrics['train_part'] * 100:.0f}%"))
        self.streak_label.setText(tr(
            f"☾ streak {block['streak']}d  ·  logged {block['logged_streak']}d",
            f"☾ серия {block['streak']} дн.  ·  записей {block['logged_streak']} дн."))
        self.week_label.setText(tr(
            f"7-day avg {block['week_avg_score']:.0f}  ·  "
            f"week tonnage {fmt_num(block['week_tonnage'])} kg",
            f"среднее за 7 дн {block['week_avg_score']:.0f}  ·  "
            f"тоннаж за неделю {fmt_num(block['week_tonnage'])} кг"))

        # ---- плитки -------------------------------------------------------
        kcal = metrics["macros"]["kcal"]
        kcal_goal = float(goals.get("kcal", 0) or 0)
        self.tile_kcal.set_value(
            tr(f"{fmt_num(kcal)} kcal", f"{fmt_num(kcal)} ккал"),
            kcal / max(1.0, kcal_goal),
            over=kcal_goal > 0 and kcal > kcal_goal * 1.15,
            caption=tr(f"{(kcal / kcal_goal * 100) if kcal_goal else 0:.0f}% of {fmt_num(kcal_goal)}",
                       f"{(kcal / kcal_goal * 100) if kcal_goal else 0:.0f}% из {fmt_num(kcal_goal)}"))
        protein = metrics["macros"]["protein"]
        self.tile_protein.set_value(
            tr(f"{fmt_num(protein)} g", f"{fmt_num(protein)} г"),
            protein / max(1.0, float(goals.get("protein", 1))),
            caption=tr(f"goal {goals.get('protein', 0)} g", f"цель {goals.get('protein', 0)} г"))
        tonnage = metrics["tonnage"]
        self.tile_tonnage.set_value(
            tr(f"{fmt_num(tonnage)} kg", f"{fmt_num(tonnage)} кг"),
            tonnage / max(1.0, float(goals.get("tonnage", 1))),
            caption=tr(f"{metrics['sets']} sets · {metrics['reps']} reps",
                       f"{metrics['sets']} сет · {metrics['reps']} повт"))
        done, total = metrics["habits_done"], metrics["habits_total"]
        self.tile_habits.set_value(
            f"{done}/{total}", done / max(1, total),
            caption=tr(f"{done / max(1, total) * 100:.0f}% closed",
                       f"{done / max(1, total) * 100:.0f}% закрыто"))

        # ---- тепловая карта ----------------------------------------------
        series = heatmap_series(state, end=self._date, days=self.HEATMAP_DAYS)
        self.heatmap.set_monday_first(bool(self.store.settings.get("week_starts_monday", True)))
        self.heatmap.set_data(series)
        self.heatmap.highlight_day(self.iso_date)

        # ---- обряды -------------------------------------------------------
        self._rebuild_habits(state)
        ratio = done / max(1, total)
        self.habit_progress.set_ratio(ratio, caption=f"{done}/{total}")
        self.habit_summary.setText(tr(
            f"{done} of {total} rites closed · score contribution "
            f"{metrics['habit_part'] * 40:.0f}/40",
            f"закрыто {done} из {total} обрядов · вклад в счёт "
            f"{metrics['habit_part'] * 40:.0f}/40"))

        # ---- питание ------------------------------------------------------
        self._rebuild_meals(state)
        for key in ("kcal", "protein", "carbs", "fat"):
            value = metrics["macros"][key]
            goal = float(goals.get(key, 0) or 0)
            bar: InlineBar = getattr(self, f"_bar_{key}")
            label: QLabel = getattr(self, f"_val_{key}")
            bar.set_ratio(value / goal if goal else 0.0,
                          over_limit=goal > 0 and value > goal * 1.15)
            unit = "" if key == "kcal" else tr(" g", " г")
            bar.set_caption(f"{fmt_num(value)}/{fmt_num(goal)}")
            label.setText(tr(f"{fmt_num(value)}{unit} / {fmt_num(goal)}{unit}",
                             f"{fmt_num(value)}{unit} / {fmt_num(goal)}{unit}"))
        self.macro_summary.setText(tr(
            f"{metrics['meals']} meal(s) logged · "
            f"score contribution {metrics['diet_part'] * 30:.0f}/30",
            f"записано приёмов пищи: {metrics['meals']} · "
            f"вклад в счёт {metrics['diet_part'] * 30:.0f}/30"))

        # ---- сводка / чат -------------------------------------------------
        briefing = state.get("ai", {}).get("briefings", {}).get(self.iso_date, "")
        if briefing:
            self.brief_label.setText(briefing)
            self.brief_label.setProperty("role", "accent")
        else:
            self.brief_label.setText(tr("no analysis stored for this day yet",
                                        "на этот день анализа пока нет"))
        self._building = False

    def _rebuild_habits(self, state: dict[str, Any]) -> None:
        while self.habit_list.count():
            item = self.habit_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._habit_rows.clear()
        log = state.get("habit_log", {}).get(self.iso_date, {})
        habits = [h for h in state.get("habits", []) if h.get("active", True)]
        if not habits:
            empty = QLabel(tr("no rites defined — add one above",
                              "обряды не заданы — добавьте выше"), self)
            role(empty, "hint")
            self.habit_list.addWidget(empty)
            return
        for habit in habits:
            row = HabitRow(
                habit,
                done=bool(log.get(habit["id"])),
                streak=habit_streak(state, habit["id"], end=self._date),
                parent=self,
            )
            row.toggled.connect(self.toggle_habit)
            row.removeRequested.connect(self.remove_habit)
            row.set_accent(self._palette["ACCENT"], self._palette["ACCENT_DARK"],
                           self._palette["BG3"], self._palette["TEXT"])
            self._habit_rows[habit["id"]] = row
            self.habit_list.addWidget(row)

    def _rebuild_meals(self, state: dict[str, Any]) -> None:
        while self.meal_list.count():
            item = self.meal_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._meal_rows.clear()
        meals = state.get("diet_log", {}).get(self.iso_date, {}).get("meals", [])
        if not meals:
            empty = QLabel(tr("nothing logged — record your first meal below",
                              "ничего не записано — добавьте первый приём пищи ниже"), self)
            role(empty, "hint")
            self.meal_list.addWidget(empty)
            return
        for meal in meals:
            row = MealRow(meal, parent=self)
            row.removeRequested.connect(self.remove_meal)
            self._meal_rows.append(row)
            self.meal_list.addWidget(row)

    # -------------------------------------------------------------- actions
    def toggle_habit(self, habit_id: str, done: bool) -> None:
        self.store.set_habit(habit_id, done, day=self.iso_date)
        self.refresh()

    def remove_habit(self, habit_id: str) -> None:
        self.store.remove_habit(habit_id)
        self.refresh()

    def add_habit(self) -> None:
        name = self.habit_input.text().strip()
        if not name:
            return
        self.store.add_habit(name)
        self.habit_input.clear()
        self.refresh()

    def add_meal(self, meal: dict[str, Any]) -> None:
        self.store.add_meal(meal, day=self.iso_date)
        self.refresh()

    def remove_meal(self, meal_id: str) -> None:
        self.store.remove_meal(meal_id, day=self.iso_date)
        self.refresh()

    def clear_chat(self) -> None:
        self.store.clear_chat()
        self.chat.restore([])
        self.chat.set_status(tr("✧  transcript cleared", "✧  история очищена"))

    # --------------------------------------------------------------------- ai
    def ask(self, question: str) -> None:
        state = self.store.snapshot_data()
        self.chat.append_user(question)
        self.store.add_chat_message("user", question)
        self.store.add_chat_message("assistant", "")
        self.chat.begin_assistant("")
        self.chat.set_status(tr("✠  the advisor is reading your log…",
                                "✠  советник читает ваш журнал…"))
        started = self.ai.ask(question, history=self.chat.history()[:-1],
                              state=state, day=self.iso_date, tag="chat")
        if not started:
            self.chat.finish_assistant(tr(
                "(advisor is busy — stop the current run first)",
                "(советник занят — сначала остановите текущий запуск)"))

    def run_briefing(self, *, force_ai: bool = True) -> str:
        state = self.store.snapshot_data()
        lines = build_briefing(state, today=self._date)
        text = briefing_text(lines)
        self.brief_label.setText(text or tr("nothing to analyse yet", "анализировать пока нечего"))
        self.store.set_briefing(text, day=self.iso_date)
        severity = "info"
        if any(line.severity == "bad" for line in lines):
            severity = "bad"
        elif any(line.severity == "warn" for line in lines):
            severity = "warn"
        self.brief_banner.set_message(tr(
            f"{len(lines)} finding(s) for {fmt_day_month(self._date)} — "
            f"weakest lever: {_weakest(lines)}",
            f"выводов за {fmt_day_month(self._date)}: {len(lines)} — "
            f"слабое звено: {_weakest(lines, ru=True)}"), severity)
        if force_ai and self.ai.engine.status().available:
            self.chat.set_status(tr("☾  generating briefing…", "☾  генерация сводки…"))
            self.ai.briefing(state=state, day=self.iso_date, tag="briefing")
        return text

    # --------------------------------------------------------- ai callbacks
    def _on_token(self, piece: str, tag: str) -> None:
        if tag == "chat":
            self.chat.stream_token(piece)

    def _on_response(self, text: str, tag: str) -> None:
        if tag == "chat":
            self.chat.finish_assistant(text)
            self.store.replace_last_assistant_message(text)
            self.chat.set_status(tr("✧  the advisor is idle", "✧  советник свободен"))
        elif tag == "briefing":
            self.brief_label.setText(text)
            self.store.set_briefing(text, day=self.iso_date)
            self.chat.set_status(tr("☾  briefing refreshed", "☾  сводка обновлена"))

    def _on_error(self, message: str, tag: str) -> None:
        if tag in ("chat", "briefing"):
            self.chat.set_status(f"✠  {message[:150]}")
            if tag == "chat":
                self.chat.finish_assistant(
                    tr(f"[advisor unavailable] {message}",
                       f"[советник недоступен] {message}"))

    def _on_busy(self, busy: bool, tag: str) -> None:
        if tag in ("chat", "briefing", ""):
            self.chat.set_busy(busy)
            self.brief_button.setEnabled(not busy)

    def _on_heatmap_hover(self, iso: str) -> None:
        metrics = day_metrics(self.store.data, iso)
        self.heat_hint.setText(tr(
            f"{iso} · score {metrics['score']:.0f} · "
            f"{fmt_num(metrics['macros']['kcal'])} kcal · {metrics['sets']} sets · "
            f"{fmt_num(metrics['tonnage'])} kg · habits "
            f"{metrics['habits_done']}/{metrics['habits_total']}",
            f"{iso} · счёт {metrics['score']:.0f} · "
            f"{fmt_num(metrics['macros']['kcal'])} ккал · {metrics['sets']} сет · "
            f"{fmt_num(metrics['tonnage'])} кг · обряды "
            f"{metrics['habits_done']}/{metrics['habits_total']}"))

    def load_chat_history(self) -> None:
        self.chat.restore(self.store.data.get("ai", {}).get("chat", []))
        self.chat.set_status(tr(
            f"✧  {self.chat.model.count()} message(s) in the local transcript",
            f"✧  в локальной истории сообщений: {self.chat.model.count()}"))

    # --------------------------------------------------------------- theming
    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette
        self.heatmap.set_palette(palette)
        self.chat.set_palette(palette)
        self.ring.set_colors(palette["ACCENT"], palette["BG3"], palette["TEXT"])
        for tile in (self.tile_kcal, self.tile_protein, self.tile_tonnage,
                     self.tile_habits):
            tile.bar.set_colors(palette["BG3"], palette["ACCENT_DARK"],
                                palette["ACCENT"], palette["WARN"], palette["TEXT"])
        self.habit_progress.set_colors(palette["BG3"], palette["ACCENT_DARK"],
                                       palette["ACCENT"], palette["WARN"],
                                       palette["TEXT"])
        for key in ("kcal", "protein", "carbs", "fat"):
            getattr(self, f"_bar_{key}").set_colors(
                palette["BG3"], palette["ACCENT_DARK"], palette["ACCENT"],
                palette["WARN"], palette["TEXT"])
        for row in self._habit_rows.values():
            row.set_accent(palette["ACCENT"], palette["ACCENT_DARK"],
                           palette["BG3"], palette["TEXT"])
        self.refresh()


def _weakest(lines: list[Any], *, ru: bool = False) -> str:
    kinds = {line.kind for line in lines if line.severity in ("warn", "bad")}
    if not kinds:
        return tr("none", "нет") if not ru else "нет"
    names_en = {"training": "training", "nutrition": "nutrition", "habits": "habits",
                "streak": "streak", "action": "action"}
    names_ru = {"training": "тренинг", "nutrition": "питание", "habits": "обряды",
                "streak": "серия", "action": "действие"}
    table = names_ru if ru else names_en
    order = ("training", "nutrition", "habits", "streak", "action")
    for kind_name in order:
        if kind_name in kinds:
            return table[kind_name]
    first = sorted(kinds)[0]
    return table.get(first, first)
