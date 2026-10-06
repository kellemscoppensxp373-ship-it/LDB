"""Habit + diet tracker rows (used inside the dashboard card)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTimeEdit,
    QVBoxLayout,
    QWidget,
)

from .common import GlyphButton, InlineBar, kind, role


def habit_streak(state: dict[str, Any], habit_id: str, *, end: date | None = None) -> int:
    """Consecutive days (ending at ``end``) this habit was ticked."""
    end = end or date.today()
    log = state.get("habit_log", {})
    count = 0
    cursor = end
    for _ in range(400):
        if log.get(cursor.isoformat(), {}).get(habit_id):
            count += 1
            cursor -= timedelta(days=1)
        else:
            break
    return count


class HabitRow(QWidget):
    """``[✧] Read 20 pages ········· [streak 4] [bar 1/1] [✕]``"""

    toggled = Signal(str, bool)
    removeRequested = Signal(str)

    def __init__(self, habit: dict[str, Any], *, done: bool = False, streak: int = 0,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.habit_id = str(habit.get("id", ""))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(8)

        self.toggle = QPushButton(habit.get("glyph", "✧"), self)
        self.toggle.setCheckable(True)
        self.toggle.setChecked(bool(done))
        self.toggle.setFixedSize(28, 26)
        self.toggle.setProperty("checkable", "true")
        self.toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle.setToolTip(f"Toggle “{habit.get('name', '')}”")
        self.toggle.toggled.connect(self._on_toggle)
        layout.addWidget(self.toggle)

        self.name = QLabel(habit.get("name", ""), self)
        self.name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(self.name, 1)

        self.streak_label = QLabel(f"☾ {streak}d", self)
        role(self.streak_label, "muted")
        self.streak_label.setToolTip("Current streak for this habit")
        layout.addWidget(self.streak_label)

        self.bar = InlineBar(self, height=10)
        self.bar.setFixedWidth(70)
        self.bar.set_ratio(1.0 if done else 0.0, caption="✓" if done else "")
        layout.addWidget(self.bar)

        self.remove = GlyphButton("✕", "Delete habit", self)
        self.remove.clicked.connect(lambda: self.removeRequested.emit(self.habit_id))
        layout.addWidget(self.remove)

    def _on_toggle(self, checked: bool) -> None:
        self.bar.set_ratio(1.0 if checked else 0.0, caption="✓" if checked else "")
        self.toggled.emit(self.habit_id, bool(checked))

    def set_done(self, done: bool) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(bool(done))
        self.toggle.blockSignals(False)
        self.bar.set_ratio(1.0 if done else 0.0, caption="✓" if done else "")

    def set_streak(self, streak: int) -> None:
        self.streak_label.setText(f"☾ {streak}d")

    def set_accent(self, accent: str, accent_dark: str, bg: str, text: str) -> None:
        self.bar.set_colors(track=bg, start=accent_dark, end=accent, text=text)


class MealRow(QWidget):
    """One logged meal with its macros and a delete glyph."""

    removeRequested = Signal(str)

    def __init__(self, meal: dict[str, Any], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.meal_id = str(meal.get("id", ""))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(8)

        time_label = QLabel(str(meal.get("time") or "--:--"), self)
        role(time_label, "muted")
        time_label.setFixedWidth(44)
        layout.addWidget(time_label)

        name = QLabel(str(meal.get("name", "Meal")), self)
        name.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout.addWidget(name, 1)

        macros = QLabel(
            f"{float(meal.get('kcal', 0)):.0f} kcal · "
            f"P {float(meal.get('protein', 0)):.0f} "
            f"C {float(meal.get('carbs', 0)):.0f} "
            f"F {float(meal.get('fat', 0)):.0f}", self)
        role(macros, "accent")
        layout.addWidget(macros)

        remove = GlyphButton("✕", "Remove meal", self)
        remove.clicked.connect(lambda: self.removeRequested.emit(self.meal_id))
        layout.addWidget(remove)


class MealForm(QWidget):
    """Inline macro entry: name, time, kcal, P/C/F."""

    mealAdded = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(6)

        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(4)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.name = QLineEdit(self)
        self.name.setPlaceholderText("Meal name (e.g. Post-workout rice)")
        form.addRow("name", self.name)

        self.time = QTimeEdit(self)
        self.time.setDisplayFormat("HH:mm")
        form.addRow("time", self.time)

        spin_row = QHBoxLayout()
        spin_row.setSpacing(6)
        self.kcal = self._spin(0, 5000, 0, "kcal")
        self.protein = self._spin(0, 500, 0, "P g")
        self.carbs = self._spin(0, 900, 0, "C g")
        self.fat = self._spin(0, 400, 0, "F g")
        for spin in (self.kcal, self.protein, self.carbs, self.fat):
            spin_row.addWidget(spin)
        form.addRow("macros", self._wrap(spin_row))

        outer.addLayout(form)

        button_row = QHBoxLayout()
        self.add_button = QPushButton("✧  LOG MEAL", self)
        kind(self.add_button, "primary")
        self.add_button.clicked.connect(self.submit)
        button_row.addStretch(1)
        button_row.addWidget(self.add_button)
        outer.addLayout(button_row)

    @staticmethod
    def _wrap(layout: QHBoxLayout) -> QWidget:
        holder = QWidget()
        holder.setLayout(layout)
        return holder

    @staticmethod
    def _spin(minimum: int, maximum: int, value: int, suffix: str) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setValue(value)
        spin.setDecimals(0)
        spin.setSuffix(f" {suffix}")
        spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        spin.setMinimumWidth(76)
        return spin

    def submit(self) -> None:
        name = self.name.text().strip()
        kcal = self.kcal.value()
        if not name and kcal <= 0:
            self.name.setProperty("invalid", "true")
            self.name.style().unpolish(self.name)
            self.name.style().polish(self.name)
            self.name.setFocus()
            return
        self.name.setProperty("invalid", "false")
        self.mealAdded.emit({
            "name": name or "Meal",
            "time": self.time.time().toString("HH:mm"),
            "kcal": float(kcal),
            "protein": float(self.protein.value()),
            "carbs": float(self.carbs.value()),
            "fat": float(self.fat.value()),
        })
        self.reset()

    def reset(self) -> None:
        self.name.clear()
        for spin in (self.kcal, self.protein, self.carbs, self.fat):
            spin.setValue(0)
        self.name.setFocus()
