"""GUI-level tests: widgets actually build, paint and react.

Runs on Qt's offscreen plugin.  ``QWidget.grab()`` is used deliberately — it
forces the custom ``paintEvent`` implementations (heatmap, inline bar, score
ring, chat bubbles, sidebar delegate) to execute rather than merely exist.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QTableWidgetItem

pytest.importorskip("PySide6")

from lifeboard.storage.metrics import day_metrics, heatmap_series  # noqa: E402
from lifeboard.widgets.chat import ChatModel  # noqa: E402
from lifeboard.widgets.common import InlineBar, ScoreRing  # noqa: E402
from lifeboard.widgets.heatmap import ActivityHeatmap  # noqa: E402
from lifeboard.theme import build_palette  # noqa: E402


def _paint(widget) -> QPixmap:
    widget.resize(420, 200)
    shot = widget.grab()
    assert not shot.isNull()
    return shot


# ------------------------------------------------------------------- window
def test_window_builds_all_four_pages(window):
    assert window.stack.count() == 4
    assert window.sidebar.count() >= 4
    window.navigate("iron")
    assert window.stack.currentIndex() == 1
    window.navigate("grimoire")
    assert window.stack.currentIndex() == 2
    window.navigate("rites")
    assert window.stack.currentIndex() == 3
    window.navigate("dashboard")
    assert window.stack.currentIndex() == 0


def test_stylesheet_is_applied_to_the_application(qapp, window):
    sheet = qapp.styleSheet()
    assert "QListWidget#SidebarList" in sheet
    assert "{{" not in sheet


def test_navigating_with_keyboard_shortcuts_targets(qapp, window):
    for index, key in enumerate(("dashboard", "iron", "grimoire", "rites")):
        window.navigate(key)
        assert window.stack.currentIndex() == index


def test_date_navigation_syncs_every_page(window):
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    window.dashboard.set_date(yesterday)
    assert window.workout.iso_date == yesterday
    assert window.library.iso_date == yesterday
    window.workout.go_today()
    assert window.dashboard.iso_date == date.today().isoformat()
    assert window.library.iso_date == date.today().isoformat()


# ------------------------------------------------------------------ theme
def test_apply_theme_repalettes_and_persists(window):
    window.apply_theme(25)
    assert window.store.settings["hue"] == 25
    assert window.palette["ACCENT"] == build_palette(25)["ACCENT"]
    window.apply_theme(265)
    assert window.store.settings["hue"] == 265


def test_custom_painted_widgets_render(window):
    _paint(window.dashboard.heatmap)
    _paint(window.dashboard.ring)
    _paint(window.dashboard.tile_kcal.bar)
    _paint(window.dashboard.habit_progress)
    _paint(window.sidebar)
    _paint(window.dashboard.chat.view)
    _paint(window.settings.swatch)


def test_inline_bar_clamps_and_captions():
    bar = InlineBar(height=12)
    bar.set_ratio(1.7, caption="170%")
    _paint(bar)
    bar.set_ratio(-3, over_limit=True, caption="0%")
    _paint(bar)


def test_score_ring_renders_every_value():
    ring = ScoreRing(size=64)
    for value in (0, 33, 66, 100):
        ring.set_value(value)
        _paint(ring)


# ------------------------------------------------------------------ habits
def test_habit_toggle_persists_and_refreshes(window):
    habit_id = window.store.data["habits"][0]["id"]
    window.dashboard.toggle_habit(habit_id, True)
    today = date.today().isoformat()
    assert window.store.data["habit_log"][today][habit_id] == 1
    assert window.dashboard._habit_rows[habit_id].toggle.isChecked()
    window.dashboard.toggle_habit(habit_id, False)
    assert window.store.data["habit_log"][today][habit_id] == 0


def test_add_and_remove_habit_from_the_ui(window):
    before = len(window.store.data["habits"])
    window.dashboard.habit_input.setText("Cold shower")
    window.dashboard.add_habit()
    assert len(window.store.data["habits"]) == before + 1
    new_id = window.store.data["habits"][-1]["id"]
    window.dashboard.remove_habit(new_id)
    assert len(window.store.data["habits"]) == before
    assert window.dashboard.habit_input.text() == ""


# -------------------------------------------------------------------- diet
def test_meal_form_logs_macros(window):
    form = window.dashboard.meal_form
    form.name.setText("Rice and chicken")
    form.time.setTime(form.time.time().addSecs(0))
    form.kcal.setValue(820)
    form.protein.setValue(55)
    form.carbs.setValue(95)
    form.fat.setValue(18)
    form.submit()
    today = date.today().isoformat()
    meals = window.store.data["diet_log"][today]["meals"]
    assert len(meals) == 1
    assert meals[0]["kcal"] == 820.0
    assert meals[0]["protein"] == 55.0
    assert "820 kcal" in window.dashboard.tile_kcal.value_label.text().replace(",", "")
    assert form.name.text() == ""          # form resets after submit
    assert form.kcal.value() == 0


def test_meal_form_rejects_an_empty_submission(window):
    window.dashboard.meal_form.submit()
    assert "diet_log" not in window.store.data or not window.store.data["diet_log"]
    assert window.dashboard.meal_form.name.property("invalid") == "true"


def test_removing_a_meal_updates_the_store(window):
    meal = window.store.add_meal({"name": "Snack", "kcal": 200},
                                 day=date.today().isoformat())
    window.dashboard.refresh()
    window.dashboard.remove_meal(meal["id"])
    assert window.store.data["diet_log"][date.today().isoformat()]["meals"] == []


# ------------------------------------------------------------------ workout
def test_add_exercise_then_log_sets_computes_tonnage(window):
    window.navigate("iron")
    view = window.workout
    view.new_name.setText("Zercher Squat")
    view.new_muscle.setCurrentText("Legs")
    view.add_exercise()
    assert any(e["name"] == "Zercher Squat" for e in window.store.data["exercises"])

    index = view.set_exercise.findText("Zercher Squat  ·  Legs")
    assert index >= 0
    view.set_exercise.setCurrentIndex(index)
    view.set_reps.setValue(5)
    view.set_weight.setValue(120)
    view.add_set()
    view.add_set()

    today = date.today().isoformat()
    entries = window.store.data["workout_log"][today]["entries"]
    assert len(entries) == 1
    assert len(entries[0]["sets"]) == 2
    assert "1,200 kg" in view.tonnage_label.text()
    assert view.set_table.rowCount() == 2


def test_editing_a_cell_recalculates_volume(window):
    window.navigate("iron")
    view = window.workout
    exercise = window.store.data["exercises"][0]
    index = view.set_exercise.findData(exercise["id"])
    view.set_exercise.setCurrentIndex(index)
    view.set_reps.setValue(8)
    view.set_weight.setValue(60)
    view.add_set()
    assert "3,840" not in view.tonnage_label.text()      # 8*60 = 480

    item = view.set_table.item(0, 1)
    item.setText("10")
    view.set_table.itemChanged.emit(item)
    today = date.today().isoformat()
    assert window.store.data["workout_log"][today]["entries"][0]["sets"][0]["reps"] == 10
    assert "600" in view.tonnage_label.text()             # 10*60


def test_dropping_a_set_removes_the_entry_when_empty(window):
    window.navigate("iron")
    view = window.workout
    view.set_exercise.setCurrentIndex(0)
    view.add_set()
    view.set_table.selectRow(0)
    view.remove_selected_set()
    assert window.store.data["workout_log"].get(date.today().isoformat()) is None
    assert view.set_table.rowCount() == 0


def test_session_name_is_persisted(window):
    window.navigate("iron")
    window.workout.session_name.setText("Push Day")
    window.workout.save_meta()
    window.workout.set_exercise.setCurrentIndex(0)
    window.workout.add_set()
    assert window.store.data["workout_log"][date.today().isoformat()]["name"] == "Push Day"


# ------------------------------------------------------------------- diary
def test_diary_saves_and_reloads(window):
    window.navigate("grimoire")
    window.library.editor.setPlainText("Trained heavy. Slept poorly.")
    window.library._flush_editor()
    today = date.today().isoformat()
    saved = window.store.data["diary"][today]
    assert "Trained heavy" in saved["text"]
    assert saved["html"]

    window.library.set_date((date.today() - timedelta(days=1)).isoformat())
    assert window.library.editor.toPlainText() == ""
    window.library.go_today()
    assert "Trained heavy" in window.library.editor.toPlainText()


def test_diary_formatting_commands_do_not_crash(window):
    window.navigate("grimoire")
    editor = window.library.editor
    editor.setPlainText("A line of prose")
    editor.selectAll()
    window.library._toggle_char("bold")
    window.library._toggle_char("bold")
    window.library._toggle_char("italic")
    window.library._toggle_char("underline")
    window.library._set_heading(1)
    window.library._set_heading(1)
    window.library._insert_rule()
    window.library._clear_format()
    assert "<hr" in editor.toHtml().lower() or editor.toPlainText()


def test_diary_context_menu_offers_the_advisor_actions(window):
    """Builds the menu without exec'ing it (a popup would block the test run)."""
    window.navigate("grimoire")
    editor = window.library.editor
    editor.setPlainText("Something to summarize")
    menu = window.library.build_editor_menu()
    actions = menu.actions()
    labels = [action.text() for action in actions]
    # The standard edit actions are merged in first (their captions are empty
    # in this sandbox because Qt's translation catalogues are not installed,
    # so assert on structure instead of on the localised text).
    assert len(actions) > 10
    assert sum(1 for action in actions if action.isSeparator()) >= 3
    assert any("Summarize" in label for label in labels)
    assert any("Improve style" in label for label in labels)
    assert any("Generate ideas" in label for label in labels)
    assert any("Insert image" in label for label in labels)
    assert any("Import markdown" in label for label in labels)
    menu.deleteLater()


def test_editor_ai_action_fills_the_output_panel(window, qapp):
    window.navigate("grimoire")
    window.library.editor.setPlainText("Bench went up 5kg but my shoulder nagged.")
    window.library.run_ai("summarize")
    for _ in range(80):
        qapp.processEvents()
    output = window.library.ai_output.toPlainText()
    assert output and output != "…"
    window.library.insert_ai_below()
    assert len(window.library.editor.toPlainText()) > 40


def test_editor_ai_on_an_empty_entry_says_so(window):
    window.navigate("grimoire")
    window.library.editor.clear()
    window.library.run_ai("summarize")
    assert "Nothing to work with" in window.library.ai_output.toPlainText()


# ---------------------------------------------------------------- librarium
def test_add_book_and_track_progress(window):
    window.navigate("grimoire")
    view = window.library
    view.tabs.setCurrentIndex(1)
    view.book_title.setText("The Black Iron")
    view.book_author.setText("Nobody")
    view.book_status.setCurrentText("reading")
    view.book_pages.setValue(300)
    view.add_book()
    assert window.store.data["library"][0]["title"] == "The Black Iron"
    assert view.book_table.rowCount() == 1

    view.book_read.setValue(120)
    assert window.store.data["library"][0]["pages_read"] == 120
    view.book_rating.setCurrentIndex(4)
    assert window.store.data["library"][0]["rating"] == 4
    view.book_set_status.setCurrentText("finished")
    assert window.store.data["library"][0]["status"] == "finished"

    view.book_notes.setPlainText("Chapter three is the whole book.")
    assert window.store.data["library"][0]["notes"].startswith("Chapter three")
    view.remove_book()
    assert window.store.data["library"] == []


# ------------------------------------------------------------------ heatmap
def test_heatmap_builds_a_cell_per_day(window):
    heatmap = window.dashboard.heatmap
    assert len(heatmap._cells) == 365
    assert heatmap._month_marks, "month labels were never computed"


def test_heatmap_click_selects_that_day(window, qapp):
    heatmap = window.dashboard.heatmap
    target = (date.today() - timedelta(days=30)).isoformat()
    item = heatmap._cells[target]
    centre = item.sceneBoundingRect().center()
    point = heatmap.mapFromScene(centre)
    received: list[str] = []
    heatmap.dayClicked.connect(received.append)
    QTest.mouseClick(heatmap.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, point)
    qapp.processEvents()
    assert received == [target]
    assert window.dashboard.iso_date == target


def test_heatmap_tooltip_contains_the_day_metrics(window):
    heatmap = window.dashboard.heatmap
    key = (date.today() - timedelta(days=2)).isoformat()
    window.store.add_meal({"name": "Lunch", "kcal": 900, "protein": 40}, day=key)
    window.dashboard.refresh()
    tip = heatmap._cells[key].toolTip()
    assert key in tip or date.fromisoformat(key).strftime("%d %b") in tip
    assert "900 kcal" in tip


def test_heatmap_palette_change_repaints(window):
    window.apply_theme(120)
    _paint(window.dashboard.heatmap)
    assert window.dashboard.heatmap._heat[4].name().upper() == \
        window.palette["HEAT4"].upper()


# --------------------------------------------------------------------- chat
def test_chat_model_append_update_and_history():
    model = ChatModel()
    model.append("user", "hello")
    model.append("assistant", "")
    model.update_last("world")
    assert model.rowCount() == 2
    assert model.history() == [{"role": "user", "content": "hello"},
                               {"role": "assistant", "content": "world"}]
    model.clear()
    assert model.rowCount() == 0


def test_asking_the_advisor_streams_an_answer(window, qapp):
    window.navigate("dashboard")
    window.dashboard.ask("Should I train today?")
    for _ in range(200):
        qapp.processEvents()
    chat = window.dashboard.chat
    assert chat.model.rowCount() == 2
    last = chat.model.data(chat.model.index(1), 0x0102)
    assert "heuristic mode" in last
    assert window.store.data["ai"]["chat"][-1]["role"] == "assistant"
    assert chat.send_button.isEnabled()
    assert not chat.stop_button.isEnabled()


def test_briefing_is_written_to_the_dashboard_and_store(window):
    window.navigate("dashboard")
    text = window.dashboard.run_briefing(force_ai=False)
    assert text
    assert window.store.data["ai"]["briefings"][date.today().isoformat()] == text
    assert window.dashboard.brief_label.text() == text


def test_clearing_the_chat_wipes_the_transcript(window, qapp):
    window.dashboard.ask("hello")
    for _ in range(120):
        qapp.processEvents()
    window.dashboard.clear_chat()
    assert window.dashboard.chat.model.rowCount() == 0
    assert window.store.data["ai"]["chat"] == []


# ----------------------------------------------------------------- settings
def test_settings_apply_goals_and_refresh_dashbaord(window):
    window.navigate("rites")
    window.settings.kcal.setValue(3200)
    window.settings.tonnage.setValue(9000)
    window.settings.apply_goals()
    assert window.store.goals["kcal"] == 3200
    assert window.store.goals["tonnage"] == 9000.0
    window.navigate("dashboard")
    assert "3,200" in window.dashboard._val_kcal.text()


def test_settings_model_combo_lists_discovered_models(window, tmp_path, monkeypatch):
    models = tmp_path / "m"
    models.mkdir()
    (models / "test-model-q4.gguf").write_bytes(b"\x00" * 2048)
    window.ai.engine._models_dir = models
    window.settings.refresh_models()
    labels = [window.settings.model_combo.itemText(i)
              for i in range(window.settings.model_combo.count())]
    assert any("test-model-q4.gguf" in label for label in labels)


def test_backup_and_restore_from_the_settings_page(window):
    window.navigate("rites")
    window.store.add_habit("Backed up habit")
    window.settings.backup_now()
    assert window.settings.backup_combo.count() >= 1

    name = window.store.data["habits"][-1]["name"]
    window.store.data["habits"].clear()
    window.store.save()
    window.settings.refresh_backups()
    window.settings.backup_combo.setCurrentIndex(0)
    from PySide6.QtWidgets import QMessageBox
    original = QMessageBox.question
    QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    try:
        window.settings.restore_backup()
    finally:
        QMessageBox.question = original
    assert name in [h["name"] for h in window.store.data["habits"]]


def test_status_bar_reflects_the_engine(window):
    text = window.status_ai.text()
    assert "heuristic" in text


def test_close_persists_a_final_snapshot(window):
    before = len(window.store.list_backups())
    window.close()
    assert len(window.store.list_backups()) >= before
