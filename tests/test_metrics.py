"""Analytics: tonnage, scoring, streaks, heatmap series."""

from __future__ import annotations

from datetime import date, timedelta

from lifeboard.storage.metrics import (
    day_metrics,
    week_days,
    diet_score,
    heatmap_series,
    macro_totals,
    percent_change,
    rolling_average,
    score_bucket,
    set_volume,
    streak,
    summary_block,
    training_score,
    workout_totals,
)


def test_set_volume_multiplies_reps_by_weight():
    volume, reps, sets = set_volume([
        {"reps": 8, "weight": 80.0},
        {"reps": 5, "weight": 100.0},
        {"reps": 0, "weight": 200.0},   # ignored: no reps
    ])
    assert volume == 1140.0
    assert reps == 13
    assert sets == 2


def test_workout_totals_aggregate_and_split_per_exercise():
    totals = workout_totals([
        {"exercise": "Bench Press", "sets": [{"reps": 5, "weight": 100}] * 3},
        {"exercise": "Bench Press", "sets": [{"reps": 5, "weight": 80}] * 2},
        {"exercise": "Row", "sets": [{"reps": 10, "weight": 60}]},
    ])
    assert totals["tonnage"] == 2300.0 + 600.0
    assert totals["sets"] == 6
    assert totals["reps"] == 35
    assert totals["exercises"] == 2
    assert totals["per_exercise"]["Bench Press"] == 2300.0  # 1500 + 800


def test_macro_totals_sum_every_meal():
    totals = macro_totals([
        {"kcal": 500, "protein": 30, "carbs": 60, "fat": 15},
        {"kcal": 700, "protein": 40, "carbs": 80, "fat": 20},
    ])
    assert totals == {"kcal": 1200.0, "protein": 70.0, "carbs": 140.0, "fat": 35.0}


def test_diet_score_rewards_accuracy_and_protein():
    goals = {"kcal": 2600, "protein": 180}
    perfect = diet_score({"kcal": 2600, "protein": 180}, goals)
    assert perfect == 1.0
    underfed = diet_score({"kcal": 1300, "protein": 60}, goals)
    assert underfed < perfect
    overfed = diet_score({"kcal": 3900, "protein": 180}, goals)
    assert overfed < perfect


def test_training_score_caps_at_one():
    assert training_score(0, {"tonnage": 6000}) == 0.0
    assert training_score(3000, {"tonnage": 6000}) == 0.5
    assert training_score(99999, {"tonnage": 6000}) == 1.0


def test_day_metrics_composite_score_is_weighted(state):
    day = "2026-02-03"
    habit_ids = [h["id"] for h in state["habits"]]
    state["habit_log"][day] = {hid: 1 for hid in habit_ids}
    state["diet_log"][day] = {"meals": [
        {"kcal": 2600, "protein": 180, "carbs": 300, "fat": 85}]}
    state["workout_log"][day] = {"name": "Push", "notes": "", "entries": [
        {"exercise": "Bench Press", "sets": [{"reps": 5, "weight": 120}] * 10}]}
    metrics = day_metrics(state, day)
    # habits 4/4 (40) + diet 1.0 (30) + tonnage 6000/6000 (30)
    assert metrics["score"] == 100.0
    assert metrics["tonnage"] == 6000.0
    assert metrics["exercises"] == 1
    assert metrics["logged"] is True


def test_empty_day_scores_zero(state):
    metrics = day_metrics(state, "2020-01-01")
    assert metrics["score"] == 0.0
    assert metrics["logged"] is False
    assert metrics["macros"]["kcal"] == 0.0


def test_score_bucket_boundaries():
    assert score_bucket(0) == 0
    assert score_bucket(10) == 1
    assert score_bucket(40) == 2
    assert score_bucket(60) == 3
    assert score_bucket(90) == 4


def test_heatmap_series_length_and_dates(state):
    end = date(2026, 3, 1)
    series = heatmap_series(state, end=end, days=365)
    assert len(series) == 365
    assert series[-1]["date"] == end.isoformat()
    assert series[0]["date"] == (end - timedelta(days=364)).isoformat()


def test_streak_counts_consecutive_days(state):
    end = date(2026, 4, 10)
    habit_ids = [h["id"] for h in state["habits"]]
    for offset in range(3):
        day = (end - timedelta(days=offset)).isoformat()
        state["habit_log"][day] = {hid: 1 for hid in habit_ids}
        state["diet_log"][day] = {"meals": [{"kcal": 2600, "protein": 180}]}
    assert streak(state, end=end) == 3
    assert streak(state, end=end - timedelta(days=5)) == 0


def test_percent_change_handles_missing_baseline():
    assert percent_change(0, 500) is None
    assert percent_change(2000, 1800) == -10.0
    assert percent_change(2000, 2100) == 5.0


def test_rolling_average_over_a_week(state):
    end = date(2026, 5, 20)
    habit_ids = [h["id"] for h in state["habits"]]
    for offset in range(7):
        day = (end - timedelta(days=offset)).isoformat()
        state["habit_log"][day] = {hid: 1 for hid in habit_ids}
    assert rolling_average(state, "habit_part", end=end, days=7) == 1.0


def test_summary_block_shape(week_of_logs):
    """Weekly numbers are a *calendar* week, so derive the expectation."""
    logged, end = week_of_logs
    block = summary_block(logged, end=end)
    week = week_days(end)
    expected_tonnage = round(
        sum(day_metrics(logged, d.isoformat())["tonnage"] for d in week), 1)
    expected_train_days = sum(
        1 for d in week if day_metrics(logged, d.isoformat())["sets"] > 0)

    assert block["date"] == end.isoformat()
    assert block["week_tonnage"] == expected_tonnage
    assert block["train_days_7d"] == expected_train_days
    assert block["tonnage_delta"] is None or isinstance(block["tonnage_delta"], float)
    assert "today" in block and "yesterday" in block
    assert block["yesterday"]["tonnage"] == 2250.0


def test_summary_block_on_a_fixed_week():
    """Same maths with a pinned date so the numbers are absolute."""
    from lifeboard.storage.schema import sanitize_state

    state = sanitize_state({})
    monday = date(2026, 3, 2)
    for offset in (0, 1):
        day = (monday + timedelta(days=offset)).isoformat()
        state["workout_log"][day] = {"name": "S", "notes": "", "entries": [
            {"exercise": "Squat", "sets": [{"reps": 5, "weight": 100}] * 5}]}
    block = summary_block(state, end=monday + timedelta(days=2))
    assert block["week_tonnage"] == 5000.0
    assert block["train_days_7d"] == 2
