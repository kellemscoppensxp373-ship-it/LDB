"""365-day contribution grid.

A ``QGraphicsView`` subclass: each day is a ``QGraphicsRectItem`` in the scene
(so hit-testing, tooltips and hover come for free), while ``paintEvent`` is
overridden to draw the parts that are *not* data — the month axis, the weekday
axis and the intensity legend — straight onto the viewport.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QGraphicsRectItem, QGraphicsScene, QGraphicsView, QSizePolicy

from ..storage.metrics import score_bucket

WEEKDAY_LABELS = ("M", "", "W", "", "F", "", "S")
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class ActivityHeatmap(QGraphicsView):
    """GitHub-style yearly grid driven by daily scores."""

    dayClicked = Signal(str)
    dayHovered = Signal(str)

    CELL_MAX = 15.0
    CELL_MIN = 7.0
    GAP = 3.0
    AXIS_LEFT = 18.0
    AXIS_TOP = 18.0
    AXIS_BOTTOM = 26.0

    def __init__(self, palette: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setObjectName("Heatmap")
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._palette = palette
        self._heat = [QColor(palette.get(f"HEAT{i}", "#1B2130")) for i in range(5)]
        self._axis_color = QColor(palette.get("TEXT_FAINT", "#6B7280"))
        self._border_color = QColor(palette.get("BORDER", "#232A3A"))
        self._series: list[dict[str, Any]] = []
        self._cells: dict[str, QGraphicsRectItem] = {}
        self._month_marks: list[tuple[float, str]] = []
        self._cell = 12.0
        self._monday_first = True
        self.setRenderHints(QPainter.RenderHint.Antialiasing
                            | QPainter.RenderHint.TextAntialiasing)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setMinimumHeight(150)
        self._last_hover: QGraphicsRectItem | None = None

    # ------------------------------------------------------------------ API
    def set_palette(self, palette: dict[str, str]) -> None:
        self._palette = palette
        self._heat = [QColor(palette.get(f"HEAT{i}", "#1B2130")) for i in range(5)]
        self._axis_color = QColor(palette.get("TEXT_FAINT", "#6B7280"))
        self._border_color = QColor(palette.get("BORDER", "#232A3A"))
        if self._series:
            self.set_data(self._series)
        self.viewport().update()

    def set_data(self, series: list[dict[str, Any]]) -> None:
        """``series`` is a list of day-metrics dicts (see ``metrics.heatmap_series``)."""
        self._series = list(series)
        self._rebuild()

    def set_monday_first(self, value: bool) -> None:
        self._monday_first = bool(value)
        if self._series:
            self._rebuild()

    # ------------------------------------------------------------- geometry
    def _grid_geometry(self) -> tuple[date, int] | None:
        if not self._series:
            return None
        end = date.fromisoformat(self._series[-1]["date"])
        start = date.fromisoformat(self._series[0]["date"])
        if self._monday_first:
            shift = start.weekday()
        else:
            shift = (start.weekday() + 1) % 7
        grid_start = start - timedelta(days=shift)
        total = (end - grid_start).days + 1
        weeks = max(1, math.ceil(total / 7.0))
        return grid_start, weeks

    def _fit_cell(self, weeks: int) -> float:
        available = max(80.0, self.viewport().width() - self.AXIS_LEFT - 12.0)
        cell = (available / weeks) - self.GAP
        return max(self.CELL_MIN, min(self.CELL_MAX, cell))

    def _rebuild(self) -> None:
        self._scene.clear()
        self._cells.clear()
        self._month_marks.clear()
        geometry = self._grid_geometry()
        if geometry is None:
            self.setFixedHeight(60)
            return
        grid_start, weeks = geometry
        self._cell = self._fit_cell(weeks)
        step = self._cell + self.GAP
        height = self.AXIS_TOP + 7 * step + self.AXIS_BOTTOM
        self.setFixedHeight(int(height))

        pen = QPen(self._border_color)
        pen.setWidthF(0.6)
        seen_months: set[tuple[int, int]] = set()

        for day_data in self._series:
            key = str(day_data.get("date", ""))[:10]
            try:
                day = date.fromisoformat(key)
            except ValueError:
                continue
            offset = (day - grid_start).days
            column, row = divmod(offset, 7)
            x = self.AXIS_LEFT + column * step
            y = self.AXIS_TOP + row * step
            bucket = score_bucket(float(day_data.get("score", 0.0)))
            item = QGraphicsRectItem(QRectF(x, y, self._cell, self._cell))
            item.setBrush(QBrush(self._heat[bucket]))
            item.setPen(pen)
            item.setData(0, key)
            item.setData(1, day_data)
            item.setToolTip(self._tooltip(day, day_data))
            item.setAcceptHoverEvents(True)
            self._scene.addItem(item)
            self._cells[key] = item

            month_key = (day.year, day.month)
            if month_key not in seen_months:
                seen_months.add(month_key)
                if day.day <= 7:
                    self._month_marks.append((x, MONTH_NAMES[day.month - 1]))

        width = self.AXIS_LEFT + weeks * step + 8.0
        self._scene.setSceneRect(0, 0, width, height)

    @staticmethod
    def _tooltip(day: date, data: dict[str, Any]) -> str:
        score = float(data.get("score", 0.0))
        parts = [f"{day.strftime('%a %d %b %Y')} — score {score:.0f}/100"]
        macros = data.get("macros", {})
        if macros:
            parts.append(f"{macros.get('kcal', 0):,.0f} kcal · "
                         f"P {macros.get('protein', 0):,.0f} g")
        if data.get("sets"):
            parts.append(f"{data['sets']} sets · {data.get('tonnage', 0):,.0f} kg")
        if data.get("habits_total"):
            parts.append(f"habits {data.get('habits_done', 0)}/{data['habits_total']}")
        if not data.get("logged"):
            parts.append("nothing logged")
        return "\n".join(parts)

    # ---------------------------------------------------------------- paint
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.viewport().rect(),
                         QColor(self._palette.get("BG2", "#11151F")))

        font = QFont(self.font())
        font.setPointSizeF(7.5)
        painter.setFont(font)
        painter.setPen(QPen(self._axis_color))

        step = self._cell + self.GAP
        for index, label in enumerate(WEEKDAY_LABELS):
            if label:
                painter.drawText(
                    QRectF(0, self.AXIS_TOP + index * step - 1, self.AXIS_LEFT - 4,
                           step + 2),
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                    label)

        for x, label in self._month_marks:
            if x + 24 > self.viewport().width():
                continue
            painter.drawText(QRectF(x, 2, 44, self.AXIS_TOP - 4),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             label)

        painter.end()
        super().paintEvent(event)
        self._draw_legend()

    def _draw_legend(self) -> None:
        """``less ▢▢▢▢▢ more`` in the bottom-right corner."""
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        font = QFont(self.font())
        font.setPointSizeF(7.0)
        painter.setFont(font)
        painter.setPen(QPen(self._axis_color))

        label = "less"
        metrics = painter.fontMetrics()
        text_w = metrics.horizontalAdvance(label)
        size = max(6.0, self._cell * 0.7)
        total = text_w + 6 + 5 * (size + 2) + 6 + metrics.horizontalAdvance("more")
        x = self.viewport().width() - total - 4
        y = self.AXIS_TOP + 7 * (self._cell + self.GAP) + 6
        if x < self.AXIS_LEFT:
            painter.end()
            return
        painter.drawText(QRectF(x, y, text_w, size + 2),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         label)
        x += text_w + 6
        for color in self._heat:
            painter.setPen(QPen(self._border_color, 0.6))
            painter.setBrush(QBrush(color))
            painter.drawRect(QRectF(x, y, size, size))
            x += size + 2
        painter.setPen(QPen(self._axis_color))
        painter.drawText(QRectF(x + 4, y, 40, size + 2),
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         "more")
        painter.end()

    # ------------------------------------------------------------ interaction
    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._series:
            self._rebuild()

    def mousePressEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        key = item.data(0) if item is not None else None
        if key:
            self.dayClicked.emit(str(key))
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        item = self.itemAt(event.position().toPoint())
        if item is not self._last_hover:
            if self._last_hover is not None:
                pen = QPen(self._border_color)
                pen.setWidthF(0.6)
                self._last_hover.setPen(pen)
            self._last_hover = item if isinstance(item, QGraphicsRectItem) else None
            if self._last_hover is not None:
                highlight = QPen(QColor(self._palette.get("ACCENT_BRIGHT", "#FFFFFF")))
                highlight.setWidthF(1.4)
                self._last_hover.setPen(highlight)
                key = self._last_hover.data(0)
                if key:
                    self.dayHovered.emit(str(key))
        super().mouseMoveEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if self._last_hover is not None:
            pen = QPen(self._border_color)
            pen.setWidthF(0.6)
            self._last_hover.setPen(pen)
            self._last_hover = None
        super().leaveEvent(event)

    def highlight_day(self, key: str) -> None:
        """Draw a ring around one day (used when a date is picked elsewhere)."""
        for other in self._cells.values():
            pen = QPen(self._border_color)
            pen.setWidthF(0.6)
            other.setPen(pen)
        item = self._cells.get(key)
        if item is not None:
            pen = QPen(QColor(self._palette.get("ACCENT_BRIGHT", "#FFFFFF")))
            pen.setWidthF(1.8)
            item.setPen(pen)


def center_on(view: QGraphicsView, point: QPointF) -> None:
    """Helper: scroll a scene point into the middle of the viewport."""
    view.centerOn(point)
