#!/usr/bin/env python3
"""Populate a data.json with ~60 days of plausible logs.

Useful for screenshots, UI work and for trying the app without a month of
manual logging:

    python tools\\seed_demo.py                 # writes ./data.json
    python tools\\seed_demo.py --path D:\\demo\\data.json
    python tools\\seed_demo.py --days 120

The generated numbers are deterministic (fixed seed) so screenshots are
reproducible.
"""

from __future__ import annotations

import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from lifeboard.i18n import tr  # noqa: E402
from lifeboard.storage.store import Store  # noqa: E402

#: ``(english, russian)`` pairs — the active language is picked by ``tr``.
SESSIONS = (
    (("Push", "Жим"), [("Bench Press", "Жим лёжа", 5, 5),
                      ("Incline Dumbbell Press", "Жим гантелей на наклонной", 4, 10),
                      ("Overhead Press", "Жим стоя", 3, 8),
                      ("Lateral Raise", "Махи гантелями в стороны", 3, 15)]),
    (("Pull", "Тяга"), [("Deadlift", "Становая тяга", 4, 4),
                        ("Pull-Up", "Подтягивания", 4, 8),
                        ("Barbell Row", "Тяга штанги в наклоне", 4, 10),
                        ("Barbell Curl", "Подъём штанги на бицепс", 3, 12)]),
    (("Legs", "Ноги"), [("Back Squat", "Приседания со штангой", 5, 5),
                        ("Romanian Deadlift", "Румынская тяга", 4, 8),
                        ("Back Squat", "Приседания со штангой", 2, 12)]),
)

MEALS = (
    (("Oats and whey", "Овсянка с протеином"), "07:30", 620, 45, 78, 14),
    (("Chicken and rice", "Курица с рисом"), "13:00", 780, 55, 92, 18),
    (("Whey shake", "Протеиновый коктейль"), "16:30", 240, 30, 6, 3),
    (("Salmon and potatoes", "Лосось с картофелем"), "20:00", 880, 58, 84, 32),
)

DIARY_NOTES = (
    ("Slept badly, bench felt heavy. Shoulders nagged all evening.",
     "Спал плохо, жим шёл тяжело. Плечи ныли весь вечер."),
    ("Good session. Added 2.5 kg to the squat and it moved fine.",
     "Хорошая тренировка. Добавил 2.5 кг к приседу, пошло легко."),
    ("Long walk, no training. Read forty pages, which is more than usual.",
     "Долгая прогулка, без тренировки. Прочитал сорок страниц - больше обычного."),
    ("Skipped sugar entirely today. Energy was flat until lunch, then fine.",
     "Сегодня совсем без сахара. До обеда энергии не было, потом нормально."),
    ("Deep work block went long — two hours, no phone. Do that again.",
     "Блок глубокой работы затянулся - два часа без телефона. Повторить."),
)

BOOKS = (
    (("Meditations", "Размышления"), ("Marcus Aurelius", "Марк Аврелий"),
     "reading", 254, 118, 0),
    (("The Black Iron", "Чёрное железо"), ("Unknown", "Неизвестен"),
     "finished", 412, 412, 4),
    (("Thinking in Systems", "Азбука системного мышления"),
     ("Donella Meadows", "Донелла Медоуз"), "queued", 240, 0, 0),
)


def seed(path: Path, days: int = 60, hue: int = 265) -> Path:
    rng = random.Random(20260606)
    store = Store(path, backup_min_interval=0.0)
    store.data["settings"]["hue"] = hue
    by_name = {exercise["name"]: exercise["id"]
               for exercise in store.data["exercises"]}

    for offset in range(days, 0, -1):
        day = (date.today() - timedelta(days=offset)).isoformat()

        # habits: mostly good, occasional blank day
        for habit in store.data["habits"]:
            store.data["habit_log"].setdefault(day, {})[habit["id"]] = (
                1 if rng.random() > 0.28 else 0)

        # diet: 2-4 meals with some scatter around the goal
        for (name_en, name_ru), when, kcal, protein, carbs, fat in MEALS:
            if rng.random() > 0.18:
                name = tr(name_en, name_ru)
                store.data["diet_log"].setdefault(day, {"meals": []})["meals"].append({
                    "id": f"m-{day}-{name[:3].lower()}",
                    "name": name, "time": when,
                    "kcal": round(kcal * rng.uniform(0.85, 1.2), 1),
                    "protein": round(protein * rng.uniform(0.8, 1.2), 1),
                    "carbs": round(carbs * rng.uniform(0.8, 1.2), 1),
                    "fat": round(fat * rng.uniform(0.8, 1.2), 1),
                    "notes": "",
                })

        # training: 4 days in 7
        if offset % 7 not in (3, 6, 9 % 7):
            (session_en, session_ru), exercises = SESSIONS[offset % len(SESSIONS)]
            session_name = tr(session_en, session_ru)
            entries = []
            for exercise_en, exercise_ru, sets, reps in exercises:
                exercise = tr(exercise_en, exercise_ru)
                base = 60.0 + (offset % 9) * 1.25
                entries.append({
                    "exercise_id": by_name.get(exercise, ""),
                    "exercise": exercise,
                    "sets": [{"reps": reps,
                              "weight": round(base * rng.uniform(0.9, 1.1), 1)}
                             for _ in range(sets)],
                    "notes": "",
                })
            store.data["workout_log"][day] = {
                "name": session_name, "notes": "", "entries": entries}

        if rng.random() > 0.6:
            note_en, note_ru = rng.choice(DIARY_NOTES)
            note = tr(note_en, note_ru)
            store.data["diary"][day] = {
                "html": f"<p>{note}</p>",
                "text": note,
                "title": "",
                "updated": f"{day} 21:40:00",
            }

    for (title_en, title_ru), (author_en, author_ru), status, total, read, rating \
            in BOOKS:
        store.add_book({"title": tr(title_en, title_ru),
                        "author": tr(author_en, author_ru), "status": status,
                        "pages_total": total, "pages_read": read,
                        "rating": rating, "started": "", "finished": "",
                        "notes": "" if status == "queued" else tr(
                            "Apply the discipline chapters to the training block.",
                            "Применить главы о дисциплине к тренировочному блоку.")})

    store.save()
    return store.path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(ROOT / "data.json"))
    parser.add_argument("--days", type=int, default=60)
    parser.add_argument("--hue", type=int, default=265)
    args = parser.parse_args()
    written = seed(Path(args.path), days=args.days, hue=args.hue)
    print(tr(f"demo data written to {written} ({args.days} days)",
             f"демонстрационные данные записаны в {written} ({args.days} дней)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
