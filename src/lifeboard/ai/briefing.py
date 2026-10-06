"""Утренняя (проактивная) сводка.

Два слоя:

1. :func:`build_briefing` — детерминированная, офлайн, всегда доступна. Читает
   лог за вчера, сравнивает с позавчера и с последней неделей и выдаёт короткие
   строки с уровнем важности. Показывается на старте ещё до загрузки модели и
   покрыта тестами.
2. Когда GGUF-модель загружена, ИИ-воркер передаёт сериализованные метрики
   модели и заменяет этот текст прозой. Эвристика остаётся запасным вариантом,
   если генерация не удалась или была отменена.

Строки локализованы (по умолчанию русский).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..i18n import fmt_num, tr
from ..storage.metrics import (
    day_metrics,
    habit_progress,
    percent_change,
    streak,
)

#: День считается тренировочным, если записано не меньше этого числа сетов.
MIN_SETS_FOR_TRAINING_DAY = 1
#: Падение тоннажа, при котором советуем день отдыха.
TONNAGE_DROP_ALERT = 5.0
#: Столько тренировочных дней подряд — и предлагаем отдых.
CONSECUTIVE_TRAINING_ALERT = 4
#: Как глубоко идём назад при подсчёте «дней без тренировок».
RUN_SCAN_LIMIT = 60


@dataclass(frozen=True)
class BriefingLine:
    text: str
    severity: str = "info"     # info | good | warn | bad
    kind: str = "general"      # training | nutrition | habits | streak | action

    def __str__(self) -> str:
        return self.text


def _training_days_run(state: dict[str, Any], end: date) -> int:
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
    """Проанализировать *вчера* и собрать строки для показа на старте."""
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
        return [BriefingLine(tr(
            "The log is empty. Record one habit, one meal or one set today and "
            "the briefing starts working.",
            "Журнал пуст. Запишите сегодня один обряд, один приём пищи или один "
            "сет — и сводка начнёт работать."), "info", "action")]

    # ---- тренировки -------------------------------------------------------
    if metrics["sets"] > 0:
        delta = percent_change(before["tonnage"], metrics["tonnage"])
        if delta is None:
            lines.append(BriefingLine(tr(
                f"Yesterday you moved {fmt_num(metrics['tonnage'])} kg across "
                f"{metrics['sets']} sets — first logged session, no baseline yet.",
                f"Вчера вы подняли {fmt_num(metrics['tonnage'])} кг за "
                f"{metrics['sets']} сет(ов) — первая запись, базы для сравнения "
                "ещё нет."), "info", "training"))
        elif delta <= -TONNAGE_DROP_ALERT:
            lines.append(BriefingLine(tr(
                f"Tonnage dropped by {abs(delta):.1f}% yesterday "
                f"({fmt_num(before['tonnage'])} -> {fmt_num(metrics['tonnage'])} kg); "
                "consider a rest day or drop the working weight 10%.",
                f"Тоннаж вчера упал на {abs(delta):.1f}% "
                f"({fmt_num(before['tonnage'])} -> {fmt_num(metrics['tonnage'])} кг); "
                "подумайте о дне отдыха или снизьте рабочий вес на 10%."),
                "warn", "training"))
        elif delta >= TONNAGE_DROP_ALERT:
            lines.append(BriefingLine(tr(
                f"Tonnage climbed {delta:.1f}% to {fmt_num(metrics['tonnage'])} kg. "
                "Keep the jump under 5% next session.",
                f"Тоннаж вырос на {delta:.1f}% до {fmt_num(metrics['tonnage'])} кг. "
                "В следующей тренировке держите прирост до 5%."), "good", "training"))
        else:
            lines.append(BriefingLine(tr(
                f"Tonnage held steady at {fmt_num(metrics['tonnage'])} kg over "
                f"{metrics['sets']} sets ({delta:+.1f}%).",
                f"Тоннаж стабилен: {fmt_num(metrics['tonnage'])} кг за "
                f"{metrics['sets']} сет(ов) ({delta:+.1f}%)."), "info", "training"))
        run = _training_days_run(state, end)
        if run >= CONSECUTIVE_TRAINING_ALERT:
            lines.append(BriefingLine(tr(
                f"{run} training days in a row. Take a full rest day before "
                "the load compounds.",
                f"{run} тренировочных дня подряд. Возьмите полноценный день "
                "отдыха, пока нагрузка не накопилась."), "warn", "training"))
    else:
        rest_run = _rest_days_run(state, end)
        if rest_run >= 3:
            span = f"{rest_run}+" if rest_run >= RUN_SCAN_LIMIT else str(rest_run)
            lines.append(BriefingLine(tr(
                f"No training for {span} days. Run a light full-body "
                "session today — 12 working sets is enough.",
                f"Без тренировок уже {span} дн. Проведите сегодня лёгкую "
                "фулл-боди тренировку — хватит 12 рабочих сетов."), "warn", "training"))
        else:
            lines.append(BriefingLine(tr(
                "Yesterday was a rest day.", "Вчера был день отдыха."),
                "info", "training"))

    # ---- питание ----------------------------------------------------------
    kcal_goal = float(goals.get("kcal") or 0)
    protein_goal = float(goals.get("protein") or 0)
    kcal = metrics["macros"]["kcal"]
    protein = metrics["macros"]["protein"]
    if kcal_goal > 0:
        deviation = ((kcal - kcal_goal) / kcal_goal) * 100.0
        if metrics["meals"] == 0:
            lines.append(BriefingLine(tr(
                f"Nothing was logged to eat yesterday against a "
                f"{fmt_num(kcal_goal)} kcal goal. Log meals as they happen.",
                f"Вчера ничего не записано из еды при цели "
                f"{fmt_num(kcal_goal)} ккал. Записывайте приёмы пищи по факту."),
                "warn", "nutrition"))
        elif deviation >= 15.0:
            lines.append(BriefingLine(tr(
                f"Intake ran {deviation:+.0f}% over goal "
                f"({fmt_num(kcal)} vs {fmt_num(kcal_goal)} kcal). "
                "Trim one carb-dense meal today.",
                f"Калораж превысил цель на {deviation:+.0f}% "
                f"({fmt_num(kcal)} против {fmt_num(kcal_goal)} ккал). "
                "Сегодня уберите один углеводный приём пищи."), "warn", "nutrition"))
        elif deviation <= -20.0:
            lines.append(BriefingLine(tr(
                f"Intake sat {deviation:+.0f}% under goal "
                f"({fmt_num(kcal)} vs {fmt_num(kcal_goal)} kcal). "
                "Under-fuelling will cost you tonnage.",
                f"Калораж оказался на {deviation:+.0f}% ниже цели "
                f"({fmt_num(kcal)} против {fmt_num(kcal_goal)} ккал). "
                "Недоедание обойдётся вам в тоннаже."), "warn", "nutrition"))
        else:
            lines.append(BriefingLine(tr(
                f"Intake on target: {fmt_num(kcal)} kcal vs {fmt_num(kcal_goal)} goal "
                f"({deviation:+.0f}%).",
                f"Калораж в цели: {fmt_num(kcal)} ккал при цели "
                f"{fmt_num(kcal_goal)} ({deviation:+.0f}%)."), "good", "nutrition"))
    if protein_goal > 0 and metrics["meals"] > 0:
        ratio = protein / protein_goal
        if ratio < 0.8:
            lines.append(BriefingLine(tr(
                f"Protein came in at {fmt_num(protein)} g of {fmt_num(protein_goal)} g "
                f"({ratio * 100:.0f}%). Front-load 40 g at breakfast.",
                f"Белка получено {fmt_num(protein)} г из {fmt_num(protein_goal)} г "
                f"({ratio * 100:.0f}%). Перенесите 40 г на завтрак."), "warn", "nutrition"))

    # ---- обряды (привычки) ------------------------------------------------
    done, total = habit_progress(state, end.isoformat())
    if total:
        if done == total:
            lines.append(BriefingLine(tr(
                f"All {total} habits closed yesterday. Clean sheet.",
                f"Вчера закрыты все {total} обряда. Чистый лист."), "good", "habits"))
        elif done == 0:
            lines.append(BriefingLine(tr(
                f"0/{total} habits yesterday. Pick the two smallest and close "
                "them before noon today.",
                f"Вчера 0/{total} обрядов. Выберите два самых простых и закройте "
                "их до полудня."), "bad", "habits"))
        else:
            lines.append(BriefingLine(tr(
                f"{done}/{total} habits closed yesterday.",
                f"Вчера закрыто {done}/{total} обрядов."), "info", "habits"))

    # ---- серия + одно действие -------------------------------------------
    run = streak(state, end=end)
    if run >= 3:
        lines.append(BriefingLine(tr(
            f"Streak is {run} days. Protect it.",
            f"Серия — {run} дн. Берегите её."), "good", "streak"))
    action = _highest_leverage_action(state, metrics, goals, end)
    if action:
        lines.append(BriefingLine(action, "info", "action"))
    return lines


def _highest_leverage_action(state: dict[str, Any], metrics: dict[str, Any],
                             goals: dict[str, Any], end: date) -> str:
    parts = {
        "habits": metrics["habit_part"],
        "nutrition": metrics["diet_part"],
        "training": metrics["train_part"],
    }
    weakest = min(parts, key=lambda key: parts[key])
    if weakest == "habits":
        done, total = habit_progress(state, end.isoformat())
        missing = total - done
        return tr(
            f"Today: close {max(1, missing)} open habit(s) first; habits are "
            "your weakest lever right now.",
            f"Сегодня: сначала закройте {max(1, missing)} открытых обряда(ов); "
            "обряды — ваше самое слабое звено сейчас.")
    if weakest == "nutrition":
        protein_goal = goals.get("protein", 0)
        if protein_goal and metrics["macros"]["protein"] < float(protein_goal) * 0.9:
            return tr(
                f"Today: hit {fmt_num(float(protein_goal))} g of protein; "
                "nutrition is your weakest lever right now.",
                f"Сегодня: доберите {fmt_num(float(protein_goal))} г белка; "
                "питание — ваше самое слабое звено сейчас.")
        return tr(
            f"Today: land intake within 5% of "
            f"{fmt_num(float(goals.get('kcal', 0)))} kcal; nutrition is your "
            "weakest lever right now.",
            f"Сегодня: удержите калораж в пределах 5% от "
            f"{fmt_num(float(goals.get('kcal', 0)))} ккал; питание — ваше самое "
            "слабое звено сейчас.")
    return tr(
        f"Today: reach {fmt_num(float(goals.get('tonnage', 0)))} kg of tonnage; "
        "training volume is your weakest lever right now.",
        f"Сегодня: наберите {fmt_num(float(goals.get('tonnage', 0)))} кг тоннажа; "
        "объём тренировок — ваше самое слабое звено сейчас.")


def briefing_text(lines: list[BriefingLine]) -> str:
    """Плоский текст для лога чата и передачи в ИИ."""
    if not lines:
        return ""
    return "\n".join(f"• {line.text}" for line in lines)
