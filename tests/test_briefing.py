"""The deterministic morning briefing (no model required)."""

from __future__ import annotations

from datetime import date, timedelta

from lifeboard.ai.briefing import (
    BriefingLine,
    briefing_text,
    build_briefing,
)


def _kinds(lines: list[BriefingLine]) -> set[str]:
    return {line.kind for line in lines}


def test_empty_log_gets_a_getting_started_line(state):
    lines = build_briefing(state, today=date(2026, 1, 10))
    assert len(lines) == 1
    assert "log is empty" in lines[0].text
    assert lines[0].kind == "action"


def test_tonnage_drop_produces_rest_day_advice(week_of_logs):
    logged, end = week_of_logs
    lines = build_briefing(logged, today=end)
    text = briefing_text(lines)
    # 2500 kg -> 2250 kg is exactly -10%.
    assert "Tonnage dropped by 10.0% yesterday (2,500 -> 2,250 kg)" in text
    assert "consider a rest day" in text
    assert any(line.kind == "training" and line.severity == "warn"
               for line in lines)


def test_tonnage_gain_is_celebrated(state):
    end = date(2026, 6, 1)
    state["workout_log"][(end - timedelta(days=2)).isoformat()] = {
        "name": "Pull", "notes": "", "entries": [
            {"exercise": "Row", "sets": [{"reps": 5, "weight": 80}] * 4}]}
    state["workout_log"][(end - timedelta(days=1)).isoformat()] = {
        "name": "Pull", "notes": "", "entries": [
            {"exercise": "Row", "sets": [{"reps": 5, "weight": 100}] * 4}]}
    text = briefing_text(build_briefing(state, today=end))
    assert "Tonnage climbed 25.0%" in text


def test_consecutive_training_days_trigger_a_rest_day(state):
    end = date(2026, 6, 10)
    for offset in range(1, 5):
        state["workout_log"][(end - timedelta(days=offset)).isoformat()] = {
            "name": "Session", "notes": "", "entries": [
                {"exercise": "Squat", "sets": [{"reps": 5, "weight": 100}]}]}
    text = briefing_text(build_briefing(state, today=end))
    assert "4 training days in a row" in text


def test_underfuelling_is_flagged(week_of_logs):
    logged, end = week_of_logs
    text = briefing_text(build_briefing(logged, today=end))
    # 1800 kcal against a 2600 goal is -31%.
    assert "under goal" in text
    assert "-31%" in text


def test_protein_shortfall_is_flagged(week_of_logs):
    logged, end = week_of_logs
    text = briefing_text(build_briefing(logged, today=end))
    assert "Protein came in at 115 g of 180 g" in text


def test_perfect_habit_day_is_praised(state):
    end = date(2026, 7, 1)
    day = (end - timedelta(days=1)).isoformat()
    state["habit_log"][day] = {h["id"]: 1 for h in state["habits"]}
    state["diet_log"][day] = {"meals": [{"kcal": 2600, "protein": 180,
                                         "carbs": 300, "fat": 85}]}
    text = briefing_text(build_briefing(state, today=end))
    assert "All 4 habits closed yesterday" in text


def test_zero_habit_day_is_a_bad_severity(state):
    end = date(2026, 7, 2)
    day = (end - timedelta(days=1)).isoformat()
    state["habit_log"][day] = {h["id"]: 0 for h in state["habits"]}
    lines = build_briefing(state, today=end)
    assert any(line.kind == "habits" and line.severity == "bad" for line in lines)


def test_every_briefing_ends_with_one_action(state, week_of_logs):
    logged, end = week_of_logs
    lines = build_briefing(logged, today=end)
    actions = [line for line in lines if line.kind == "action"]
    assert len(actions) == 1
    assert actions[0].text.startswith("Today:")


def test_briefing_text_is_bullet_plain_text(week_of_logs):
    logged, end = week_of_logs
    text = briefing_text(build_briefing(logged, today=end))
    assert text
    assert all(line.startswith("• ") for line in text.splitlines())
    assert briefing_text([]) == ""
