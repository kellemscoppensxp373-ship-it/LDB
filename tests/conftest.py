"""Shared pytest fixtures.

The GUI tests run against Qt's ``offscreen`` platform plugin, so the whole
suite works on a headless CI box (and inside the PyInstaller build machine).
"""

from __future__ import annotations

import gc
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("LIFEBOARD_MODELS", str(ROOT / "models"))
# The shipped default language is Russian; the existing English assertions run
# against the English catalogue.  A dedicated test_i18n.py flips to "ru".
os.environ.setdefault("LIFEBOARD_LANG", "en")

import pytest  # noqa: E402

from lifeboard.storage.schema import sanitize_state  # noqa: E402
from lifeboard.storage.store import Store  # noqa: E402


@pytest.fixture
def state() -> dict:
    """A pristine default document."""
    return sanitize_state({})


@pytest.fixture
def tmp_store(tmp_path: Path) -> Store:
    """A Store rooted in a temporary directory (no backups churn)."""
    return Store(tmp_path / "data.json", backup_min_interval=0.0)


@pytest.fixture(scope="session")
def qapp():
    """One QApplication for the whole session."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def window(qapp, tmp_path: Path):
    """A fully built MainWindow on throwaway data."""
    from lifeboard.app import MainWindow

    store = Store(tmp_path / "data.json", backup_min_interval=0.0)
    win = MainWindow(store=store, run_briefing=False)
    win.show()
    qapp.processEvents()
    yield win
    win.close()
    qapp.processEvents()
    # MainWindow sets WA_DeleteOnClose; drop the Python refs and run a cycle
    # collection so 30+ windows do not pile up and slow every later fixture.
    del win
    gc.collect()
    qapp.processEvents()
    qapp.sendPostedEvents(None, 0)


@pytest.fixture
def week_of_logs(state: dict) -> tuple[dict, date]:
    """A week of realistic logs ending yesterday, for briefing/context tests."""
    end = date.today()
    habit_ids = [h["id"] for h in state["habits"]]
    for offset in range(1, 8):
        day = (end - timedelta(days=offset)).isoformat()
        state["habit_log"][day] = {
            hid: (1 if index < 3 else 0) for index, hid in enumerate(habit_ids)
        }
        state["diet_log"][day] = {"meals": [
            {"id": f"m{offset}a", "name": "Breakfast", "time": "08:00",
             "kcal": 700, "protein": 45, "carbs": 80, "fat": 22, "notes": ""},
            {"id": f"m{offset}b", "name": "Dinner", "time": "20:00",
             "kcal": 1100, "protein": 70, "carbs": 120, "fat": 35, "notes": ""},
        ]}
    # Two sessions with a measurable tonnage drop on the most recent day.
    heavy = {"name": "Push", "notes": "", "entries": [
        {"exercise_id": "x1", "exercise": "Bench Press", "notes": "",
         "sets": [{"reps": 5, "weight": 100.0}] * 5},
    ]}
    light = {"name": "Push", "notes": "", "entries": [
        {"exercise_id": "x1", "exercise": "Bench Press", "notes": "",
         "sets": [{"reps": 5, "weight": 90.0}] * 5},
    ]}
    state["workout_log"][(end - timedelta(days=2)).isoformat()] = heavy
    state["workout_log"][(end - timedelta(days=1)).isoformat()] = light
    state["diary"][(end - timedelta(days=1)).isoformat()] = {
        "html": "<p>Slept badly. Bench felt heavy.</p>",
        "text": "Slept badly. Bench felt heavy. Shoulders ached all evening.",
        "title": "Heavy bench",
        "updated": "2026-01-01 08:00:00",
    }
    return state, end
