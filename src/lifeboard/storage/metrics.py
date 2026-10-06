"""Pure, GUI-free analytics over a state document.

Everything the dashboard, the heatmap, the AI context serialiser and the
proactive briefing need is derived here, from plain dicts, with no Qt import.
That is what makes the "Tonnage dropped by 5%" claim in the briefing a
testable function rather than a hallucination.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Iterable

#: Weights of the composite daily score.  They sum to 100.
W_HABITS = 40.0
W_DIET = 30.0
W_TRAINING = 30.0

MUSCLE_ORDER = ("Chest", "Back", "Legs", "Shoulders", "Arms", "General")


def iso_day(day: date | str | None = None) -> str:
    if day is None:
        return date.today().isoformat()
    if isinstance(day, str):
        return day[:10]
    return day.isoformat()


def parse_day(day: str) -> date:
    return date.fromisoformat(day[:10])


# --------------------------------------------------------------------------- #
# raw aggregates
# --------------------------------------------------------------------------- #
def macro_totals(meals: Iterable[dict[str, Any]]) -> dict[str, float]:
    totals = {"kcal": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    for meal in meals:
        for key in totals:
            try:
                totals[key] += float(meal.get(key, 0.0) or 0.0)
            except (TypeError, ValueError):
                continue
    return {k: round(v, 1) for k, v in totals.items()}


def set_volume(sets: Iterable[dict[str, Any]]) -> tuple[float, int, int]:
    """Return ``(tonnage, total_reps, set_count)`` for one exercise's sets."""
    tonnage = 0.0
    reps = 0
    count = 0
    for entry in sets:
        try:
            r = float(entry.get("reps", 0) or 0)
            w = float(entry.get("weight", 0) or 0)
        except (TypeError, ValueError):
            continue
        if r <= 0:
            continue
        tonnage += r * w
        reps += int(r)
        count += 1
    return round(tonnage, 1), reps, count


def workout_totals(entries: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Tonnage, volume, set/rep counts and a per-muscle split for a session."""
    tonnage = 0.0
    total_reps = 0
    total_sets = 0
    per_exercise: dict[str, float] = {}
    for entry in entries:
        volume, reps, sets = set_volume(entry.get("sets", []))
        tonnage += volume
        total_reps += reps
        total_sets += sets
        name = str(entry.get("exercise", "Exercise"))
        per_exercise[name] = round(per_exercise.get(name, 0.0) + volume, 1)
    return {
        "tonnage": round(tonnage, 1),
        "reps": total_reps,
        "sets": total_sets,
        "exercises": len(per_exercise),
        "per_exercise": per_exercise,
    }


def habit_progress(state: dict[str, Any], day: str | None = None) -> tuple[int, int]:
    """``(completed, total)`` for active habits on ``day``."""
    day = iso_day(day)
    log = state.get("habit_log", {}).get(day, {})
    habits = [h for h in state.get("habits", []) if h.get("active", True)]
    done = sum(1 for h in habits if log.get(h["id"]))
    return done, len(habits)


# --------------------------------------------------------------------------- #
# scoring
# --------------------------------------------------------------------------- #
def diet_score(macros: dict[str, float], goals: dict[str, Any]) -> float:
    """0..1 adherence: kcal accuracy dominates, protein is the secondary term."""
    kcal_goal = float(goals.get("kcal") or 0)
    protein_goal = float(goals.get("protein") or 0)
    if kcal_goal <= 0:
        return 0.0
    kcal_error = abs(macros.get("kcal", 0.0) - kcal_goal) / kcal_goal
    kcal_part = max(0.0, 1.0 - kcal_error)          # within goal -> 1.0
    if protein_goal <= 0:
        return kcal_part
    protein_part = min(1.0, macros.get("protein", 0.0) / protein_goal)
    return round(0.7 * kcal_part + 0.3 * protein_part, 4)


def training_score(tonnage: float, goals: dict[str, Any]) -> float:
    goal = float(goals.get("tonnage") or 0)
    if goal <= 0:
        return 1.0 if tonnage > 0 else 0.0
    return round(min(1.0, tonnage / goal), 4)


def day_metrics(state: dict[str, Any], day: str | None = None) -> dict[str, Any]:
    """The complete per-day picture used by every surface of the app."""
    day = iso_day(day)
    goals = state.get("settings", {}).get("goals", {})
    meals = state.get("diet_log", {}).get(day, {}).get("meals", [])
    session = state.get("workout_log", {}).get(day, {})
    macros = macro_totals(meals)
    totals = workout_totals(session.get("entries", []))
    done, total_habits = habit_progress(state, day)

    habit_part = (done / total_habits) if total_habits else 0.0
    diet_part = diet_score(macros, goals)
    train_part = training_score(totals["tonnage"], goals)
    score = W_HABITS * habit_part + W_DIET * diet_part + W_TRAINING * train_part

    diary = state.get("diary", {}).get(day, {})
    return {
        "date": day,
        "score": round(score, 1),
        "habits_done": done,
        "habits_total": total_habits,
        "habit_part": round(habit_part, 4),
        "macros": macros,
        "diet_part": diet_part,
        "meals": len(meals),
        "tonnage": totals["tonnage"],
        "reps": totals["reps"],
        "sets": totals["sets"],
        "exercises": totals["exercises"],
        "train_part": train_part,
        "session_name": session.get("name", ""),
        "per_exercise": totals["per_exercise"],
        "diary_words": len(str(diary.get("text", "")).split()),
        "logged": bool(done or macros["kcal"] > 0 or totals["sets"] > 0 or diary),
    }


def heatmap_series(
    state: dict[str, Any],
    *,
    end: date | None = None,
    days: int = 365,
) -> list[dict[str, Any]]:
    """``days`` consecutive day-metrics ending at ``end`` (default: today)."""
    end = end or date.today()
    start = end - timedelta(days=days - 1)
    out: list[dict[str, Any]] = []
    cursor = start
    for _ in range(days):
        key = cursor.isoformat()
        has_data = (
            key in state.get("habit_log", {})
            or key in state.get("diet_log", {})
            or key in state.get("workout_log", {})
            or key in state.get("diary", {})
        )
        if has_data:
            out.append(day_metrics(state, key))
        else:
            out.append({"date": key, "score": 0.0, "logged": False,
                        "tonnage": 0.0, "reps": 0, "sets": 0, "exercises": 0,
                        "macros": {"kcal": 0.0, "protein": 0.0,
                                   "carbs": 0.0, "fat": 0.0},
                        "habits_done": 0, "habits_total": 0})
        cursor += timedelta(days=1)
    return out


def score_bucket(score: float) -> int:
    """0..4 intensity bucket for the heatmap grid (GitHub style)."""
    if score <= 0:
        return 0
    if score < 25:
        return 1
    if score < 50:
        return 2
    if score < 75:
        return 3
    return 4


def streak(state: dict[str, Any], *, end: date | None = None, threshold: float = 40.0) -> int:
    """Consecutive days (ending at ``end``) whose score clears ``threshold``."""
    end = end or date.today()
    count = 0
    cursor = end
    for _ in range(400):
        metrics = day_metrics(state, cursor.isoformat())
        if metrics["score"] >= threshold:
            count += 1
            cursor -= timedelta(days=1)
        else:
            break
    return count


def logged_streak(state: dict[str, Any], *, end: date | None = None) -> int:
    """Consecutive days with *any* entry — a gentler 'showed up' streak."""
    end = end or date.today()
    count = 0
    cursor = end
    for _ in range(400):
        if day_metrics(state, cursor.isoformat())["logged"]:
            count += 1
            cursor -= timedelta(days=1)
        else:
            break
    return count


def rolling_average(state: dict[str, Any], field: str, *, end: date | None = None,
                    days: int = 7) -> float:
    end = end or date.today()
    total = 0.0
    for offset in range(days):
        metrics = day_metrics(state, (end - timedelta(days=offset)).isoformat())
        value = metrics.get(field, 0.0)
        total += float(value) if isinstance(value, (int, float)) else 0.0
    return round(total / max(1, days), 2)


def percent_change(previous: float, current: float) -> float | None:
    """Signed percentage change, or ``None`` when there is no baseline."""
    if not previous:
        return None
    return round(((current - previous) / abs(previous)) * 100.0, 1)


def week_days(anchor: date | None = None, *, monday_first: bool = True) -> list[date]:
    """The seven days of the week containing ``anchor``."""
    anchor = anchor or date.today()
    start = anchor - timedelta(days=anchor.weekday() if monday_first else (anchor.weekday() + 1) % 7)
    return [start + timedelta(days=i) for i in range(7)]


def summary_block(state: dict[str, Any], *, end: date | None = None) -> dict[str, Any]:
    """Headline numbers for the dashboard tiles and the AI system prompt."""
    end = end or date.today()
    today = day_metrics(state, end.isoformat())
    yesterday = day_metrics(state, (end - timedelta(days=1)).isoformat())
    week = week_days(end)
    week_metrics = [day_metrics(state, d.isoformat()) for d in week]
    return {
        "date": end.isoformat(),
        "today": today,
        "yesterday": yesterday,
        "streak": streak(state, end=end),
        "logged_streak": logged_streak(state, end=end),
        "week_avg_score": round(sum(m["score"] for m in week_metrics) / 7.0, 1),
        "week_tonnage": round(sum(m["tonnage"] for m in week_metrics), 1),
        "week_kcal_avg": round(sum(m["macros"]["kcal"] for m in week_metrics) / 7.0, 1),
        "train_days_7d": sum(1 for m in week_metrics if m["sets"] > 0),
        "tonnage_delta": percent_change(yesterday["tonnage"], today["tonnage"]),
    }
