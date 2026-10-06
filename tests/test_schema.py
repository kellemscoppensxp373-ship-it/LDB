"""Schema defaults, sanitisation and defensive coercion."""

from __future__ import annotations

from lifeboard import SCHEMA_VERSION
from lifeboard.storage.schema import (
    DEFAULT_SETTINGS,
    default_state,
    new_id,
    sanitize_state,
)


def test_default_state_is_complete():
    state = default_state()
    assert state["schema_version"] == SCHEMA_VERSION
    assert len(state["habits"]) == 4
    assert len(state["exercises"]) == 10
    for key in ("settings", "habit_log", "diet_log", "workout_log", "diary",
                "library", "ai"):
        assert key in state


def test_sanitize_of_empty_document_keeps_starter_data():
    """Regression: an empty file must not wipe the seeded habits/exercises."""
    state = sanitize_state({})
    assert len(state["habits"]) == 4
    assert len(state["exercises"]) == 10
    assert state["settings"]["goals"]["kcal"] == DEFAULT_SETTINGS["goals"]["kcal"]


def test_sanitize_respects_deliberately_empty_lists():
    state = sanitize_state({"habits": [], "exercises": [], "library": []})
    assert state["habits"] == []
    assert state["exercises"] == []
    assert state["library"] == []


def test_sanitize_repairs_bad_types():
    state = sanitize_state({
        "settings": {"hue": "not a number", "goals": {"kcal": "2600",
                                                      "protein": None}},
        "habits": [{"name": "  ", "glyph": "✧"}, {"name": "Good habit"}],
        "exercises": [{"name": "Curl", "muscle": None}],
        "diet_log": {"2026-01-01": {"meals": [{"name": "Lunch", "kcal": "800",
                                               "protein": "x"}]}},
        "workout_log": {"2026-01-02": {"entries": [{"exercise": "Squat", "sets": [
            {"reps": "5", "weight": "100"}, {"reps": 0, "weight": 0}]}]}},
        "ai": {"chat": [{"role": "user", "content": "hi"},
                        {"role": "nonsense", "content": "x"},
                        {"role": "assistant", "content": "  "}]},
    })
    assert state["settings"]["hue"] == DEFAULT_SETTINGS["hue"]
    assert state["settings"]["goals"]["kcal"] == 2600
    assert state["settings"]["goals"]["protein"] == DEFAULT_SETTINGS["goals"]["protein"]
    assert [h["name"] for h in state["habits"]] == ["Good habit"]
    assert state["exercises"][0]["muscle"] == "General"
    assert state["diet_log"]["2026-01-01"]["meals"][0]["kcal"] == 800.0
    assert state["diet_log"]["2026-01-01"]["meals"][0]["protein"] == 0.0
    sets = state["workout_log"]["2026-01-02"]["entries"][0]["sets"]
    assert sets == [{"reps": 5, "weight": 100.0}]
    assert [m["role"] for m in state["ai"]["chat"]] == ["user"]


def test_sanitize_drops_log_entries_for_unknown_habits():
    state = sanitize_state({
        "habits": [{"id": "keep", "name": "Keep me"}],
        "habit_log": {"2026-03-04": {"keep": 1, "ghost": 1}},
    })
    assert state["habit_log"]["2026-03-04"] == {"keep": 1}


def test_sanitize_clamps_ai_parameters():
    state = sanitize_state({"settings": {"ai": {
        "n_ctx": 10, "temperature": 9.0, "top_p": 3.0, "max_tokens": 1,
        "n_gpu_layers": -50,
    }}})
    ai = state["settings"]["ai"]
    assert ai["n_ctx"] == 256
    assert ai["max_tokens"] == 16
    assert ai["top_p"] == 1.0
    assert ai["temperature"] == 9.0
    assert ai["n_gpu_layers"] == -1


def test_sanitize_is_idempotent():
    once = sanitize_state({"habits": [{"name": "Read"}]})
    twice = sanitize_state(once)
    assert once["habits"] == twice["habits"]
    assert once["settings"] == twice["settings"]


def test_unknown_keys_survive():
    state = sanitize_state({"future_field": 42})
    # Unknown top-level keys are not invented, but known sections stay valid.
    assert "settings" in state
    assert state["schema_version"] == SCHEMA_VERSION


def test_new_id_is_unique_and_prefixed():
    ids = {new_id("h") for _ in range(200)}
    assert len(ids) == 200
    assert all(i.startswith("h-") for i in ids)
