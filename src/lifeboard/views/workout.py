"""Workout library + session logger with automatic tonnage maths."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..storage.metrics import workout_totals
from ..storage.store import Store
from ..widgets.common import Card, HRule, InlineBar, SectionLabel, kind, role

MUSCLE_GROUPS = ("Chest", "Back", "Legs", "Shoulders", "Arms", "Core", "General")
EQUIPMENT = ("Barbell", "Dumbbell", "Machine", "Cable", "Kettlebell",
             "Bodyweight", "Band", "Other")
SET_COLUMNS = ("Exercise", "Reps", "Weight", "Volume")


class WorkoutView(QWidget):
    """Exercise CRUD on the left, today's sets on the right."""

    dateChanged = Signal(str)

    def __init__(self, store: Store, palette: dict[str, str],
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._palette = palette
        self._date = date.today()
        self._entries: list[dict[str, Any]] = []
        self._loading = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)
        root.addWidget(self._build_header())

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._build_library())
        splitter.addWidget(self._build_logger())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setChildrenCollapsible(False)
        root.addWidget(splitter, 1)

        self.refresh()

    # -------------------------------------------------------------- building
    def _build_header(self) -> QWidget:
        header = QWidget(self)
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addWidget(SectionLabel("Iron Library", "⚔"))
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

    def _build_library(self) -> QWidget:
        card = Card("Exercise Library", "❖")
        wrapper = QWidget(self)
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        self.exercise_table = QTableWidget(0, 3, card)
        self.exercise_table.setHorizontalHeaderLabels(("Name", "Muscle", "Gear"))
        self.exercise_table.verticalHeader().setVisible(False)
        self.exercise_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.exercise_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection)
        self.exercise_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers)
        header = self.exercise_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        card.content.addWidget(self.exercise_table, 1)

        form = QHBoxLayout()
        form.setSpacing(6)
        self.new_name = QLineEdit(card)
        self.new_name.setPlaceholderText("exercise name")
        form.addWidget(self.new_name, 1)
        self.new_muscle = QComboBox(card)
        self.new_muscle.addItems(MUSCLE_GROUPS)
        form.addWidget(self.new_muscle)
        self.new_equipment = QComboBox(card)
        self.new_equipment.addItems(EQUIPMENT)
        form.addWidget(self.new_equipment)
        card.content.addLayout(form)

        buttons = QHBoxLayout()
        add = QPushButton("✧  ADD EXERCISE", card)
        kind(add, "primary")
        add.clicked.connect(self.add_exercise)
        buttons.addWidget(add)
        self.use_button = QPushButton("⚔  ADD TO SESSION", card)
        kind(self.use_button, "ghost")
        self.use_button.clicked.connect(self.add_selected_to_session)
        buttons.addWidget(self.use_button)
        delete = QPushButton("✕  DELETE", card)
        kind(delete, "danger")
        delete.clicked.connect(self.delete_exercise)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        card.content.addLayout(buttons)
        return wrapper

    def _build_logger(self) -> QWidget:
        card = Card("Session Log", "⚔")
        wrapper = QWidget(self)
        outer = QVBoxLayout(wrapper)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(card)

        meta = QHBoxLayout()
        meta.setSpacing(8)
        session_label = QLabel("session", card)
        role(session_label, "muted")
        meta.addWidget(session_label)
        self.session_name = QLineEdit(card)
        self.session_name.setPlaceholderText("e.g. Push / Chest & Triceps")
        self.session_name.editingFinished.connect(self.save_meta)
        meta.addWidget(self.session_name, 1)
        card.content.addLayout(meta)

        self.set_table = QTableWidget(0, 4, card)
        self.set_table.setHorizontalHeaderLabels(SET_COLUMNS)
        self.set_table.verticalHeader().setVisible(True)
        self.set_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        set_header = self.set_table.horizontalHeader()
        set_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in (1, 2, 3):
            set_header.setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.set_table.itemChanged.connect(self._on_set_edited)
        card.content.addWidget(self.set_table, 1)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self.set_exercise = QComboBox(card)
        self.set_exercise.setMinimumWidth(160)
        add_row.addWidget(self.set_exercise, 1)
        self.set_reps = QSpinBox(card)
        self.set_reps.setRange(0, 500)
        self.set_reps.setValue(8)
        self.set_reps.setSuffix(" reps")
        self.set_reps.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        add_row.addWidget(self.set_reps)
        self.set_weight = QDoubleSpinBox(card)
        self.set_weight.setRange(0, 2000)
        self.set_weight.setValue(60)
        self.set_weight.setDecimals(1)
        self.set_weight.setSuffix(" kg")
        self.set_weight.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        add_row.addWidget(self.set_weight)
        add_set = QPushButton("✧  ADD SET", card)
        kind(add_set, "primary")
        add_set.clicked.connect(self.add_set)
        add_row.addWidget(add_set)
        remove_set = QPushButton("✕  DROP SET", card)
        kind(remove_set, "danger")
        remove_set.clicked.connect(self.remove_selected_set)
        add_row.addWidget(remove_set)
        card.content.addLayout(add_row)

        card.content.addWidget(HRule(card))
        self.tonnage_bar = InlineBar(card, height=16)
        card.content.addWidget(self.tonnage_bar)
        self.tonnage_label = QLabel("—", card)
        role(self.tonnage_label, "accent")
        card.content.addWidget(self.tonnage_label)
        self.breakdown_label = QLabel("", card)
        role(self.breakdown_label, "hint")
        self.breakdown_label.setWordWrap(True)
        card.content.addWidget(self.breakdown_label)
        return wrapper

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
        self._loading = True
        state = self.store.data
        exercises = state.get("exercises", [])

        # ---- library table ------------------------------------------------
        self.exercise_table.setRowCount(0)
        for exercise in exercises:
            row = self.exercise_table.rowCount()
            self.exercise_table.insertRow(row)
            name_item = QTableWidgetItem(exercise["name"])
            name_item.setData(Qt.ItemDataRole.UserRole, exercise["id"])
            self.exercise_table.setItem(row, 0, name_item)
            self.exercise_table.setItem(row, 1, QTableWidgetItem(exercise["muscle"]))
            self.exercise_table.setItem(row, 2, QTableWidgetItem(exercise["equipment"]))

        # ---- exercise pickers --------------------------------------------
        current = self.set_exercise.currentData()
        self.set_exercise.blockSignals(True)
        self.set_exercise.clear()
        for exercise in exercises:
            self.set_exercise.addItem(f"{exercise['name']}  ·  {exercise['muscle']}",
                                      exercise["id"])
        if current is not None:
            index = self.set_exercise.findData(current)
            if index >= 0:
                self.set_exercise.setCurrentIndex(index)
        self.set_exercise.blockSignals(False)

        # ---- session ------------------------------------------------------
        session = state.get("workout_log", {}).get(self.iso_date, {})
        self.session_name.blockSignals(True)
        self.session_name.setText(session.get("name", ""))
        self.session_name.blockSignals(False)
        self._entries = [
            {"exercise_id": entry.get("exercise_id", ""),
             "exercise": entry.get("exercise", "Exercise"),
             "sets": [dict(s) for s in entry.get("sets", [])],
             "notes": entry.get("notes", "")}
            for entry in session.get("entries", [])
        ]
        self._render_sets()
        self.date_label.setText(self._date.strftime("%a %d %b %Y"))
        is_today = self._date == date.today()
        self.next_button.setEnabled(not is_today)
        self.today_button.setEnabled(not is_today)
        self._loading = False

    def _render_sets(self) -> None:
        self.set_table.blockSignals(True)
        self.set_table.setRowCount(0)
        by_id = {e["id"]: e["name"] for e in self.store.data.get("exercises", [])}
        row_index = 0
        for entry_index, entry in enumerate(self._entries):
            for set_index, item in enumerate(entry["sets"]):
                self.set_table.insertRow(row_index)
                name = by_id.get(entry["exercise_id"], entry["exercise"])
                exercise_item = QTableWidgetItem(name)
                exercise_item.setFlags(exercise_item.flags()
                                       & ~Qt.ItemFlag.ItemIsEditable)
                exercise_item.setData(Qt.ItemDataRole.UserRole,
                                      (entry_index, set_index))
                self.set_table.setItem(row_index, 0, exercise_item)

                reps_item = QTableWidgetItem(str(int(item.get("reps", 0))))
                reps_item.setData(Qt.ItemDataRole.UserRole, (entry_index, set_index))
                reps_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.set_table.setItem(row_index, 1, reps_item)

                weight_item = QTableWidgetItem(f"{float(item.get('weight', 0)):.1f}")
                weight_item.setData(Qt.ItemDataRole.UserRole, (entry_index, set_index))
                weight_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self.set_table.setItem(row_index, 2, weight_item)

                volume = float(item.get("reps", 0)) * float(item.get("weight", 0))
                volume_item = QTableWidgetItem(f"{volume:,.0f} kg")
                volume_item.setFlags(volume_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                volume_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                volume_item.setData(Qt.ItemDataRole.UserRole, (entry_index, set_index))
                self.set_table.setItem(row_index, 3, volume_item)
                row_index += 1
        self.set_table.blockSignals(False)
        self._update_totals()

    def _update_totals(self) -> None:
        totals = workout_totals(self._entries)
        goal = float(self.store.goals.get("tonnage", 0) or 0)
        ratio = (totals["tonnage"] / goal) if goal else 0.0
        self.tonnage_bar.set_ratio(ratio, over_limit=goal > 0 and totals["tonnage"] > goal * 1.3)
        self.tonnage_bar.set_caption(
            f"{totals['tonnage']:,.0f} / {goal:,.0f} kg")
        self.tonnage_label.setText(
            f"⚔  TONNAGE {totals['tonnage']:,.0f} kg  ·  {totals['sets']} sets  ·  "
            f"{totals['reps']} reps  ·  {totals['exercises']} exercises")
        top = sorted(totals["per_exercise"].items(), key=lambda kv: -kv[1])[:5]
        self.breakdown_label.setText(
            "top lifts: " + ", ".join(f"{name} {volume:,.0f} kg"
                                     for name, volume in top) if top else
            "no sets logged for this day")

    # -------------------------------------------------------------- actions
    def add_exercise(self) -> None:
        name = self.new_name.text().strip()
        if not name:
            self.new_name.setFocus()
            return
        self.store.add_exercise({
            "name": name,
            "muscle": self.new_muscle.currentText(),
            "equipment": self.new_equipment.currentText(),
            "kind": "strength",
        })
        self.new_name.clear()
        self.refresh()

    def delete_exercise(self) -> None:
        row = self.exercise_table.currentRow()
        if row < 0:
            return
        item = self.exercise_table.item(row, 0)
        if item is None:
            return
        exercise_id = item.data(Qt.ItemDataRole.UserRole)
        self.store.remove_exercise(str(exercise_id))
        self.refresh()

    def _selected_exercise(self) -> dict[str, Any] | None:
        exercise_id = self.set_exercise.currentData()
        for exercise in self.store.data.get("exercises", []):
            if exercise["id"] == exercise_id:
                return exercise
        return None

    def add_selected_to_session(self) -> None:
        row = self.exercise_table.currentRow()
        if row < 0:
            return
        item = self.exercise_table.item(row, 0)
        if item is None:
            return
        index = self.set_exercise.findData(item.data(Qt.ItemDataRole.UserRole))
        if index >= 0:
            self.set_exercise.setCurrentIndex(index)
        self.add_set()

    def add_set(self) -> None:
        exercise = self._selected_exercise()
        if exercise is None:
            return
        entry = next((e for e in self._entries
                      if e["exercise_id"] == exercise["id"]), None)
        if entry is None:
            entry = {"exercise_id": exercise["id"], "exercise": exercise["name"],
                     "sets": [], "notes": ""}
            self._entries.append(entry)
        entry["sets"].append({"reps": int(self.set_reps.value()),
                              "weight": float(self.set_weight.value())})
        self._persist()

    def remove_selected_set(self) -> None:
        row = self.set_table.currentRow()
        if row < 0:
            return
        item = self.set_table.item(row, 0)
        if item is None:
            return
        entry_index, set_index = item.data(Qt.ItemDataRole.UserRole)
        try:
            entry = self._entries[int(entry_index)]
            del entry["sets"][int(set_index)]
        except (IndexError, KeyError, TypeError, ValueError):
            return
        if not entry["sets"]:
            self._entries.pop(int(entry_index))
        self._persist()

    def _on_set_edited(self, item: QTableWidgetItem) -> None:
        if self._loading:
            return
        coords = item.data(Qt.ItemDataRole.UserRole)
        if not coords:
            return
        entry_index, set_index = coords
        try:
            target = self._entries[int(entry_index)]["sets"][int(set_index)]
        except (IndexError, KeyError, TypeError, ValueError):
            return
        column = item.column()
        text = item.text().replace(",", "").strip()
        try:
            if column == 1:
                target["reps"] = max(0, int(float(text or 0)))
            elif column == 2:
                target["weight"] = max(0.0, float(text or 0))
            else:
                return
        except ValueError:
            self._render_sets()
            return
        self._persist()

    def save_meta(self) -> None:
        self._persist()

    def _persist(self) -> None:
        self.store.save_workout(
            self._entries,
            day=self.iso_date,
            name=self.session_name.text().strip(),
            notes="",
        )
        self._loading = True
        self._render_sets()
        self._loading = False

    # -------------------------------------------------------------- theming
    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette
        self.tonnage_bar.set_colors(palette["BG3"], palette["ACCENT_DARK"],
                                    palette["ACCENT"], palette["WARN"], palette["TEXT"])
