"""The proactive morning briefing.

Two layers:

1. :func:`build_briefing` — deterministic, offline, always available.  It reads
   the previous day's log, compares it with the day before and with the
   trailing week, and emits short severity-tagged lines.  This is what the
   dashboard shows before a model is ever loaded, and it is unit-tested.
2. When a GGUF model *is* loaded, the AI worker feeds the serialised metrics to
   the model and replaces this text with a prose version.  The heuristic stays
   as the fallback whenever generation fails or is cancelled.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..storage.metrics import (
    day_metrics,
    habit_progress,
    percent_change,
    streak,
)

#: A day counts as a training day when at least this many sets were logged.
MIN_SETS_FOR_TRAINING_DAY = 1
#: Relative tonnage drop that triggers the rest-day suggestion.
TONNAGE_DROP_ALERT = 5.0
#: Consecutive training days before a rest day is pushed.
CONSECUTIVE_TRAINING_ALERT = 4
#: How far back the "days since you trained" scan walks.
RUN_SCAN_LIMIT = 60


@dataclass(frozen=True)
class BriefingLine:
    text: str
    severity: str = "info"     # info | good | warn | bad
    kind: str = "general"      # training | nutrition | habits | streak | action

    def __str__(self) -> str:
        return self.text


def _training_days_run(state: dict[str, Any], end: date) -> int:
    """Consecutive training days ending at ``end`` (0 if ``end`` is a rest day)."""
    run = 0
    cursor = end
    for _ in range(RUN_SCAN_LIMIT):
        metrics = day_metrics(state, cursor.isoformat())
        if metrics["sets"] >= MIN_SETS_FOR_TRAINING_DAY:
            run += 1
            cursor -= timedelta(days=1)
        else:
            break
    return run


def _rest_days_run(state: dict[str, Any], end: date) -> int:
    run = 0
    cursor = end
    for _ in range(RUN_SCAN_LIMIT):
        if day_metrics(state, cursor.isoformat())["sets"] >= MIN_SETS_FOR_TRAINING_DAY:
            break
        run += 1
        cursor -= timedelta(days=1)
    return run


def build_briefing(state: dict[str, Any], *, end: date | None = None,
                   today: date | None = None) -> list[BriefingLine]:
    """Analyse *yesterday* and produce the actionable lines shown on startup."""
    today = today or date.today()
    end = end or (today - timedelta(days=1))
    prev = end - timedelta(days=1)

    metrics = day_metrics(state, end.isoformat())
    before = day_metrics(state, prev.isoformat())
    goals = state.get("settings", {}).get("goals", {})
    lines: list[BriefingLine] = []

    any_log = (
        metrics["logged"]
        or before["logged"]
        or state.get("habit_log")
        or state.get("diet_log")
        or state.get("workout_log")
    )
    if not any_log:
        return [BriefingLine(
            "The log is empty. Record one habit, one meal or one set today and "
            "the briefing starts working.", "info", "action")]

    # ---- training ---------------------------------------------------------
    if metrics["sets"] > 0:
        delta = percent_change(before["tonnage"], metrics["tonnage"])
        if delta is None:
            lines.append(BriefingLine(
                f"Yesterday you moved {_num(metrics['tonnage'])} kg across "
                f"{metrics['sets']} sets — first logged session, no baseline yet.",
                "info", "training"))
        elif delta <= -TONNAGE_DROP_ALERT:
            lines.append(BriefingLine(
                f"Tonnage dropped by {abs(delta):.1f}% yesterday "
                f"({_num(before['tonnage'])} -> {_num(metrics['tonnage'])} kg); "
                "consider a rest day or drop the working weight 10%.",
                "warn", "training"))
        elif delta >= TONNAGE_DROP_ALERT:
            lines.append(BriefingLine(
                f"Tonnage climbed {delta:.1f}% to {_num(metrics['tonnage'])} kg. "
                "Keep the jump under 5% next session.",
                "good", "training"))
        else:
            lines.append(BriefingLine(
                f"Tonnage held steady at {_num(metrics['tonnage'])} kg over "
                f"{metrics['sets']} sets ({delta:+.1f}%).",
                "info", "training"))
        run = _training_days_run(state, end)
        if run >= CONSECUTIVE_TRAINING_ALERT:
            lines.append(BriefingLine(
                f"{run} training days in a row. Take a full rest day before "
                "the load compounds.", "warn", "training"))
    else:
        rest_run = _rest_days_run(state, end)
        if rest_run >= 3:
            span = f"{rest_run}+" if rest_run >= RUN_SCAN_LIMIT else str(rest_run)
            lines.append(BriefingLine(
                f"No training for {span} days. Run a light full-body "
                "session today — 12 working sets is enough.", "warn", "training"))
        else:
            lines.append(BriefingLine(
                "Yesterday was a rest day.", "info", "training"))

    # ---- nutrition --------------------------------------------------------
    kcal_goal = float(goals.get("kcal") or 0)
    protein_goal = float(goals.get("protein") or 0)
    kcal = metrics["macros"]["kcal"]
    protein = metrics["macros"]["protein"]
    if kcal_goal > 0:
        deviation = ((kcal - kcal_goal) / kcal_goal) * 100.0
        if metrics["meals"] == 0:
            lines.append(BriefingLine(
                f"Nothing was logged to eat yesterday against a "
                f"{_num(kcal_goal)} kcal goal. Log meals as they happen.",
                "warn", "nutrition"))
        elif deviation >= 15.0:
            lines.append(BriefingLine(
                f"Intake ran {deviation:+.0f}% over goal "
                f"({_num(kcal)} vs {_num(kcal_goal)} kcal). "
                "Trim one carb-dense meal today.", "warn", "nutrition"))
        elif deviation <= -20.0:
            lines.append(BriefingLine(
                f"Intake sat {deviation:+.0f}% under goal "
                f"({_num(kcal)} vs {_num(kcal_goal)} kcal). "
                "Under-fuelling will cost you tonnage.", "warn", "nutrition"))
        else:
            lines.append(BriefingLine(
                f"Intake on target: {_num(kcal)} kcal vs {_num(kcal_goal)} goal "
                f"({deviation:+.0f}%).", "good", "nutrition"))
    if protein_goal > 0 and metrics["meals"] > 0:
        ratio = protein / protein_goal
        if ratio < 0.8:
            lines.append(BriefingLine(
                f"Protein came in at {_num(protein)} g of {_num(protein_goal)} g "
                f"({ratio * 100:.0f}%). Front-load 40 g at breakfast.",
                "warn", "nutrition"))

    # ---- habits -----------------------------------------------------------
    done, total = habit_progress(state, end.isoformat())
    if total:
        if done == total:
            lines.append(BriefingLine(
                f"All {total} habits closed yesterday. Clean sheet.", "good", "habits"))
        elif done == 0:
            lines.append(BriefingLine(
                f"0/{total} habits yesterday. Pick the two smallest and close "
                "them before noon today.", "bad", "habits"))
        else:
            lines.append(BriefingLine(
                f"{done}/{total} habits closed yesterday.", "info", "habits"))

    # ---- streak + single action ------------------------------------------
    run = streak(state, end=end)
    if run >= 3:
        lines.append(BriefingLine(
            f"Streak is {run} days. Protect it.", "good", "streak"))
    action = _highest_leverage_action(state, metrics, goals, end)
    if action:
        lines.append(BriefingLine(action, "info", "action"))
    return lines


def _highest_leverage_action(state: dict[str, Any], metrics: dict[str, Any],
                             goals: dict[str, Any], end: date) -> str:
    """Pick the weakest component and turn it into one imperative sentence."""
    parts = {
        "habits": metrics["habit_part"],
        "nutrition": metrics["diet_part"],
        "training": metrics["train_part"],
    }
    weakest = min(parts, key=lambda key: parts[key])
    if weakest == "habits":
        done, total = habit_progress(state, end.isoformat())
        missing = total - done
        return (f"Today: close {max(1, missing)} open habit(s) first; habits are "
                "your weakest lever right now.")
    if weakest == "nutrition":
        protein_goal = goals.get("protein", 0)
        if protein_goal and metrics["macros"]["protein"] < float(protein_goal) * 0.9:
            return (f"Today: hit {_num(float(protein_goal))} g of protein; "
                    "nutrition is your weakest lever right now.")
        return (f"Today: land intake within 5% of "
                f"{_num(float(goals.get('kcal', 0)))} kcal; nutrition is your "
                "weakest lever right now.")
    return (f"Today: reach {_num(float(goals.get('tonnage', 0)))} kg of tonnage; "
            "training volume is your weakest lever right now.")


def _num(value: float, decimals: int = 0) -> str:
    return f"{value:,.{decimals}f}" if decimals else f"{value:,.0f}"


def briefing_text(lines: list[BriefingLine]) -> str:
    """Plain-text rendering used for the chat log and the AI hand-off."""
    if not lines:
        return ""
    return "\n".join(f"• {line.text}" for line in lines)
