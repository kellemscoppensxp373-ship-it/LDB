"""Russian localisation.

``tests/conftest.py`` pins ``LIFEBOARD_LANG=en`` so the original English
assertions stay meaningful.  Everything here flips the switch to ``ru`` — the
shipped default — and checks that the user-visible surface, the AI prompts and
the number formatting all come out Russian, while the *stored* data keys stay
canonical (so a Russian UI can read an English archive and vice versa).
"""

from __future__ import annotations

import gc
from datetime import date

import pytest

from lifeboard import i18n
from lifeboard.i18n import fmt_int, fmt_num, is_ru, lang, tr


# --------------------------------------------------------------------- core
def test_default_language_is_russian(monkeypatch):
    monkeypatch.delenv("LIFEBOARD_LANG", raising=False)
    assert lang() == "ru"
    assert is_ru()
    assert tr("Load model", "Загрузить модель") == "Загрузить модель"


def test_environment_overrides_the_language(monkeypatch):
    monkeypatch.setenv("LIFEBOARD_LANG", "en")
    assert not is_ru()
    assert tr("Load model", "Загрузить модель") == "Load model"
    monkeypatch.setenv("LIFEBOARD_LANG", "RU")
    assert is_ru()


def test_number_formatting_uses_locale_separators(monkeypatch):
    monkeypatch.setenv("LIFEBOARD_LANG", "ru")
    assert fmt_int(1234) == "1 234"
    assert fmt_num(1234.0) == "1 234"
    assert fmt_num(1234.5, 1) == "1 234.5"
    assert fmt_num(999999) == "999 999"
    monkeypatch.setenv("LIFEBOARD_LANG", "en")
    assert fmt_int(1234) == "1,234"
    assert fmt_num(1234.5, 1) == "1,234.5"


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def ru(qapp, tmp_path, monkeypatch):
    """A MainWindow built entirely in Russian."""
    from lifeboard.app import MainWindow
    from lifeboard.storage.store import Store

    monkeypatch.setenv("LIFEBOARD_LANG", "ru")
    store = Store(tmp_path / "data.json", backup_min_interval=0.0)
    win = MainWindow(store=store, run_briefing=False)
    win.show()
    qapp.processEvents()
    yield win
    win.close()
    qapp.processEvents()
    del win
    gc.collect()
    qapp.processEvents()
    qapp.sendPostedEvents(None, 0)


# ------------------------------------------------------------- shell / chrome
def test_pages_and_menus_are_russian(ru):
    titles = [ru.sidebar.item(i).text() for i in range(ru.sidebar.count())]
    assert "Командная палуба" in titles
    assert "Железный архив" in titles
    assert "Гримуарий" in titles
    assert "Обряды и настройки" in titles
    menus = [action.text() for action in ru.menuBar().actions()]
    assert any("Файл" in m for m in menus)
    assert any("Советник" in m for m in menus)
    assert any("Справка" in m for m in menus)


def test_dashboard_labels_are_russian(ru):
    dash = ru.dashboard
    # Card / StatTile captions are rendered in upper case by the widget.
    assert "ОБРЯДЫ" in dash.habit_card.title_label.text()
    assert "ПРОВИЗИЯ" in dash.diet_card.title_label.text()
    assert "УТРЕННЯЯ СВОДКА" in dash.brief_card.title_label.text()
    assert "СОВЕТНИК" in dash.chat_card.title_label.text()
    assert dash.tile_kcal.label.text() == "КАЛОРИИ"
    assert dash.tile_tonnage.label.text() == "ТОННАЖ"
    assert dash.today_button.text() == "☾ СЕГОДНЯ"


def test_macro_tile_reports_kcal_in_russian(ru):
    dash = ru.dashboard
    dash.meal_form.name.setText("Рис с курицей")
    dash.meal_form.kcal.setValue(820)
    dash.meal_form.submit()
    text = dash.tile_kcal.value_label.text().replace(" ", "")
    assert text.endswith("ккал")
    assert "820" in text
    # the goal read-out uses Russian thousands separators
    assert dash._val_kcal.text() == "820 / 2 600"


def test_habit_row_and_heatmap_axes_are_russian(ru):
    from lifeboard.widgets.heatmap import month_names, weekday_labels

    assert month_names()[0] == "янв"
    assert month_names()[11] == "дек"
    assert weekday_labels()[0] == "Пн"
    assert weekday_labels()[6] == "Вс"
    habit_id = ru.store.data["habits"][0]["id"]
    row = ru.dashboard._habit_rows[habit_id]
    assert "дн." in row.streak_label.text()
    assert row.remove.toolTip() == "Удалить обряд"


def test_workout_view_is_russian_but_keys_stay_canonical(ru):
    view = ru.workout
    ru.navigate("iron")
    assert "Ноги" in [view.new_muscle.itemText(i)
                      for i in range(view.new_muscle.count())]
    view.new_name.setText("Zercher Squat")
    view.new_muscle.setCurrentIndex(2)          # "Ноги"
    view.add_exercise()
    stored = ru.store.data["exercises"][-1]
    assert stored["muscle"] == "Legs"           # canonical key, not the caption
    index = view.set_exercise.findText("Zercher Squat  ·  Ноги")
    assert index >= 0
    view.set_exercise.setCurrentIndex(index)
    view.set_reps.setValue(5)
    view.set_weight.setValue(120)
    view.add_set()
    label = view.tonnage_label.text()
    assert "ТОННАЖ" in label
    assert "600 кг" in label
    assert "сетов: 1" in label


def test_library_view_is_russian(ru):
    view = ru.library
    ru.navigate("grimoire")
    assert ru.library.tabs.tabText(0).endswith("Дневник")
    assert ru.library.tabs.tabText(1).endswith("Гримуарий")
    statuses = [view.book_status.itemText(i)
                for i in range(view.book_status.count())]
    assert statuses == ["в очереди", "читаю", "прочитано", "брошено"]
    view.book_title.setText("Чёрное железо")
    view.book_status.setCurrentIndex(1)         # "читаю"
    view.add_book()
    assert ru.store.data["library"][0]["status"] == "reading"   # canonical
    assert view.book_table.item(0, 2).text() == "читаю"


def test_diary_context_menu_is_russian(ru):
    ru.navigate("grimoire")
    ru.library.editor.setPlainText("Что-то, что надо сжать")
    menu = ru.library.build_editor_menu()
    labels = [action.text() for action in menu.actions()]
    assert any("Краткое содержание" in label for label in labels)
    assert any("Улучшить стиль" in label for label in labels)
    assert any("Сгенерировать идеи" in label for label in labels)
    assert any("Вставить рисунок" in label for label in labels)
    assert any("Импорт markdown" in label for label in labels)
    menu.deleteLater()


def test_settings_page_is_russian(ru):
    ru.navigate("rites")
    settings = ru.settings
    assert "ккал" in settings.kcal.suffix()
    assert "кг" in settings.tonnage.suffix()
    assert settings.model_combo.itemText(0) == "— модель не выбрана —"
    assert "Гримуарий" not in settings.vault_hint.text()
    assert "атомарно" in settings.vault_hint.text()


# ------------------------------------------------------------------ advisor
def test_briefing_text_is_russian(week_of_logs, monkeypatch):
    from lifeboard.ai.briefing import briefing_text, build_briefing

    logged, end = week_of_logs
    monkeypatch.setenv("LIFEBOARD_LANG", "ru")
    lines = build_briefing(logged, today=end)
    text = briefing_text(lines)
    assert "Тоннаж вчера упал на 10.0% (2 500 -> 2 250 кг)" in text
    actions = [line for line in lines if line.kind == "action"]
    assert len(actions) == 1
    assert actions[0].text.startswith("Сегодня:")
    assert text.count("Сегодня:") == 1
    assert all(line.text.startswith("• ") is False for line in lines)


def test_context_block_is_serialised_in_russian(week_of_logs, monkeypatch):
    from lifeboard.ai.context import (
        build_context,
        serialize_deltas,
        serialize_goals,
        serialize_recent,
    )

    logged, end = week_of_logs
    monkeypatch.setenv("LIFEBOARD_LANG", "ru")
    assert "ЦЕЛИ" in serialize_goals(logged)
    assert "ккал 2 600" in serialize_goals(logged)
    assert "тоннаж тренировки 6 000 кг" in serialize_goals(logged)
    recent = serialize_recent(logged, end=end, days=7)
    assert "ПОСЛЕДНИЕ 7 ДНЕЙ" in recent
    assert "средний приём 1 543 ккал/день" in recent
    assert "тоннаж за окно 4 750 кг" in recent
    deltas = serialize_deltas(logged, end=end)
    assert "ИЗМЕНЕНИЯ" in deltas
    assert "тоннаж 2 250 кг (-10.0% от 2 500)" in deltas
    assert "сегодня пока" in deltas
    assert "день не закончен" in deltas
    context = build_context(logged, day=(end.isoformat()), max_chars=200)
    assert context.endswith("[контекст обрезан]")


def test_hidden_prompt_and_editor_instructions_are_russian(monkeypatch):
    from lifeboard.ai.prompts import default_persona, editor_prompt, rules, system_prompt

    monkeypatch.setenv("LIFEBOARD_LANG", "ru")
    assert "Советник LifeBoard" in default_persona()
    assert "Отвечай по-русски" in default_persona()
    assert rules().startswith("ПРАВИЛА:")
    assert "Никогда не придумывай тренировки" in rules()
    prompt = system_prompt("", "ЦЕЛИ\n  ккал 2600")
    assert "ТЕКУЩИЕ ДАННЫЕ ПОЛЬЗОВАТЕЛЯ (источник истины, только чтение):" in prompt
    summarize = editor_prompt("summarize", "Тренировался тяжело.")
    assert "Сожми следующую запись дневника" in summarize
    assert summarize.rstrip().endswith("Тренировался тяжело.")
    assert "ЗАПИСЬ:" in summarize
    ideas = editor_prompt("ideas", "Плечи болели.", context="ЦЕЛИ\n  ккал 2600")
    assert "предложи 5 конкретных тем" in ideas
    assert "(НЕДАВНИЙ КОНТЕКСТ)" in ideas


def test_heuristic_answer_is_russian(tmp_path, monkeypatch, week_of_logs):
    from lifeboard.ai.engine import AIEngine

    logged, _ = week_of_logs
    monkeypatch.setenv("LIFEBOARD_LANG", "ru")
    engine = AIEngine(lambda: {"model_file": "", "n_ctx": 2048},
                      models_dir=tmp_path, state_provider=lambda: logged)
    answer = engine.heuristic_answer("как я выгляжу?")
    assert answer.startswith("[режим эвристики")
    assert "ИСХОДНЫЕ ДАННЫЕ" in answer
    assert "Тоннаж вчера упал" in answer
    status = engine.status()
    assert status.backend == "heuristic"        # machine key stays English
    assert "моделей нет" in status.message


def test_chat_ask_returns_a_russian_answer(ru, qapp):
    ru.dashboard.ask("Стоит ли сегодня тренироваться?")
    for _ in range(200):
        qapp.processEvents()
    chat = ru.dashboard.chat
    last = chat.model.data(chat.model.index(1), 0x0102)
    assert "режим эвристики" in last
    assert "✧  советник свободен" in chat.status.text()
    assert ru.status_ai.text().startswith("☾")


def test_startup_briefing_writes_russian_text(ru):
    text = ru.dashboard.run_briefing(force_ai=False)
    assert text
    today = date.today().isoformat()
    assert ru.store.data["ai"]["briefings"][today] == text
    assert ru.dashboard.brief_banner.label.text().startswith("выводов за")
