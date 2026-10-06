"""The ``data.json`` shape, its defaults, and defensive sanitisation.

``sanitize_state`` is the single choke-point every loaded document passes
through.  It guarantees that whatever the GUI receives has the right keys and
the right *types*, so a hand-edited or truncated ``data.json`` cannot make a
widget explode at 2 a.m.  Unknown keys are preserved, which keeps forward
compatibility with newer builds.
"""

from __future__ import annotations

import copy
import uuid
from datetime import date, datetime
from typing import Any

#: Bump when the on-disk shape changes in a way old readers cannot handle.
SCHEMA_VERSION = 3

GOAL_KEYS = ("kcal", "protein", "carbs", "fat")


def new_id(prefix: str = "id") -> str:
    """Short, sortable-enough unique id (``h-3f1a9c2b``)."""
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def iso_day(day: date | str | None = None) -> str:
    """Normalise a date to the ``YYYY-MM-DD`` key used everywhere in the file."""
    if day is None:
        return date.today().isoformat()
    if isinstance(day, str):
        return day[:10]
    return day.isoformat()


def now_iso() -> str:
    return datetime.now().replace(microsecond=0).isoformat(sep=" ")


DEFAULT_SETTINGS: dict[str, Any] = {
    "profile_name": "Acolyte",
    "hue": 265,                     # single base HSL hue for the whole palette
    "goals": {
        "kcal": 2600,
        "protein": 180,
        "carbs": 300,
        "fat": 85,
        "tonnage": 6000.0,          # kg lifted per session target
        "habits": 4,                # habits to complete per day
    },
    "units": "kg",                  # kg | lb
    "week_starts_monday": True,
    "ai": {
        "model_file": "",           # absolute path or bare file name in models/
        "n_ctx": 4096,
        "n_gpu_layers": 0,          # 0 = pure CPU; -1 = offload everything
        "n_threads": 0,             # 0 = let llama.cpp decide
        "temperature": 0.7,
        "top_p": 0.92,
        "repeat_penalty": 1.1,
        "max_tokens": 512,
        "stream": True,
        "auto_briefing": True,
        "persona": (
            "You are the LifeBoard Advisor: a terse, direct, slightly gothic "
            "coaching intelligence embedded in a local desktop app. You speak "
            "in short imperative sentences, you never apologise, you never "
            "mention that you are a language model, and you always ground your "
            "advice in the numbers from the user's own logs."
        ),
    },
}

STARTER_HABITS: list[dict[str, Any]] = [
    {"name": "Read 20 pages", "glyph": "✧"},
    {"name": "Move / walk 8k steps", "glyph": "⚔"},
    {"name": "No sugar after 20:00", "glyph": "☾"},
    {"name": "Deep work block (90 min)", "glyph": "❖"},
]


def default_state() -> dict[str, Any]:
    """A brand-new, fully populated document."""
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "created": now_iso(),
        "updated": now_iso(),
        "settings": copy.deepcopy(DEFAULT_SETTINGS),
        "habits": [
            {"id": new_id("h"), "name": h["name"], "glyph": h["glyph"],
             "active": True, "created": now_iso()}
            for h in STARTER_HABITS
        ],
        # day -> {habit_id: 0|1}
        "habit_log": {},
        # day -> {"meals": [...]}
        "diet_log": {},
        "exercises": [
            {"id": new_id("x"), "name": n, "muscle": m, "equipment": e, "kind": "strength"}
            for n, m, e in (
                ("Bench Press", "Chest", "Barbell"),
                ("Incline Dumbbell Press", "Chest", "Dumbbell"),
                ("Back Squat", "Legs", "Barbell"),
                ("Romanian Deadlift", "Legs", "Barbell"),
                ("Deadlift", "Back", "Barbell"),
                ("Pull-Up", "Back", "Bodyweight"),
                ("Barbell Row", "Back", "Barbell"),
                ("Overhead Press", "Shoulders", "Barbell"),
                ("Lateral Raise", "Shoulders", "Dumbbell"),
                ("Barbell Curl", "Arms", "Barbell"),
            )
        ],
        # day -> {"name": str, "notes": str, "entries": [...]}
        "workout_log": {},
        # day -> {"html": str, "text": str, "updated": str, "title": str}
        "diary": {},
        "library": [],
        "ai": {"chat": [], "briefings": {}},
    }
    return state


# --------------------------------------------------------------------------- #
# coercion helpers
# --------------------------------------------------------------------------- #
def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_str(value: Any, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if result == result else default  # NaN guard


def _as_int(value: Any, default: int = 0, lo: int | None = None, hi: int | None = None) -> int:
    try:
        result = int(round(float(value)))
    except (TypeError, ValueError):
        result = default
    if lo is not None:
        result = max(lo, result)
    if hi is not None:
        result = min(hi, result)
    return result


def _as_bool(value: Any, default: bool = True) -> bool:
    return value if isinstance(value, bool) else default


def _merge_settings(raw: Any) -> dict[str, Any]:
    """Deep-merge stored settings over the defaults (missing keys -> default)."""
    out = copy.deepcopy(DEFAULT_SETTINGS)
    raw = _as_dict(raw)
    for key, value in raw.items():
        if key in ("goals", "ai") and isinstance(value, dict):
            out[key].update({k: v for k, v in value.items() if k in out[key]})
        elif key in out:
            out[key] = value
    out["hue"] = _as_int(out["hue"], DEFAULT_SETTINGS["hue"], 0, 359)
    goals = out["goals"]
    goals["kcal"] = _as_int(goals["kcal"], 2600, 0, 20000)
    goals["protein"] = _as_int(goals["protein"], 180, 0, 1000)
    goals["carbs"] = _as_int(goals["carbs"], 300, 0, 2000)
    goals["fat"] = _as_int(goals["fat"], 85, 0, 1000)
    goals["tonnage"] = max(0.0, _as_float(goals["tonnage"], 6000.0))
    goals["habits"] = _as_int(goals["habits"], 4, 0, 50)
    ai = out["ai"]
    ai["n_ctx"] = _as_int(ai["n_ctx"], 4096, 256, 262144)
    ai["n_gpu_layers"] = _as_int(ai["n_gpu_layers"], 0, -1, 999)
    ai["n_threads"] = _as_int(ai["n_threads"], 0, 0, 512)
    ai["temperature"] = max(0.0, _as_float(ai["temperature"], 0.7))
    ai["top_p"] = min(1.0, max(0.0, _as_float(ai["top_p"], 0.92)))
    ai["repeat_penalty"] = max(0.0, _as_float(ai["repeat_penalty"], 1.1))
    ai["max_tokens"] = _as_int(ai["max_tokens"], 512, 16, 16384)
    ai["stream"] = _as_bool(ai["stream"], True)
    ai["auto_briefing"] = _as_bool(ai["auto_briefing"], True)
    ai["model_file"] = _as_str(ai["model_file"])
    ai["persona"] = _as_str(ai["persona"], DEFAULT_SETTINGS["ai"]["persona"])
    return out


def _sanitize_habit(raw: Any) -> dict[str, Any] | None:
    raw = _as_dict(raw)
    name = _as_str(raw.get("name")).strip()
    if not name:
        return None
    return {
        "id": _as_str(raw.get("id")) or new_id("h"),
        "name": name[:120],
        "glyph": _as_str(raw.get("glyph"), "✧")[:4] or "✧",
        "active": _as_bool(raw.get("active"), True),
        "created": _as_str(raw.get("created"), now_iso()),
    }


def _sanitize_exercise(raw: Any) -> dict[str, Any] | None:
    raw = _as_dict(raw)
    name = _as_str(raw.get("name")).strip()
    if not name:
        return None
    return {
        "id": _as_str(raw.get("id")) or new_id("x"),
        "name": name[:120],
        "muscle": _as_str(raw.get("muscle"), "General")[:40] or "General",
        "equipment": _as_str(raw.get("equipment"), "Bodyweight")[:40] or "Bodyweight",
        "kind": _as_str(raw.get("kind"), "strength")[:20] or "strength",
    }


def _sanitize_set(raw: Any) -> dict[str, Any] | None:
    raw = _as_dict(raw)
    reps = _as_int(raw.get("reps"), 0, 0, 10000)
    weight = max(0.0, _as_float(raw.get("weight"), 0.0))
    if reps <= 0 and weight <= 0:
        return None
    return {"reps": reps, "weight": round(weight, 2)}


def _sanitize_workout_entry(raw: Any) -> dict[str, Any] | None:
    raw = _as_dict(raw)
    sets = [s for s in (_sanitize_set(s) for s in _as_list(raw.get("sets"))) if s]
    if not sets:
        return None
    return {
        "exercise_id": _as_str(raw.get("exercise_id")),
        "exercise": _as_str(raw.get("exercise"), "Exercise")[:120],
        "sets": sets,
        "notes": _as_str(raw.get("notes"))[:400],
    }


def _sanitize_meal(raw: Any) -> dict[str, Any] | None:
    raw = _as_dict(raw)
    name = _as_str(raw.get("name")).strip()
    macros = {
        "kcal": max(0.0, _as_float(raw.get("kcal"), 0.0)),
        "protein": max(0.0, _as_float(raw.get("protein"), 0.0)),
        "carbs": max(0.0, _as_float(raw.get("carbs"), 0.0)),
        "fat": max(0.0, _as_float(raw.get("fat"), 0.0)),
    }
    if not name and not any(macros.values()):
        return None
    return {
        "id": _as_str(raw.get("id")) or new_id("m"),
        "name": (name or "Meal")[:120],
        "time": _as_str(raw.get("time"))[:8],
        "notes": _as_str(raw.get("notes"))[:400],
        **macros,
    }


def _sanitize_book(raw: Any) -> dict[str, Any] | None:
    raw = _as_dict(raw)
    title = _as_str(raw.get("title")).strip()
    if not title:
        return None
    return {
        "id": _as_str(raw.get("id")) or new_id("b"),
        "title": title[:200],
        "author": _as_str(raw.get("author"))[:120],
        "status": _as_str(raw.get("status"), "queued")[:20] or "queued",
        "pages_total": _as_int(raw.get("pages_total"), 0, 0, 100000),
        "pages_read": _as_int(raw.get("pages_read"), 0, 0, 100000),
        "rating": _as_int(raw.get("rating"), 0, 0, 5),
        "started": _as_str(raw.get("started"))[:10],
        "finished": _as_str(raw.get("finished"))[:10],
        "notes": _as_str(raw.get("notes"))[:4000],
    }


def sanitize_state(raw: Any) -> dict[str, Any]:
    """Coerce an arbitrary (possibly corrupt) document into a valid state."""
    raw = _as_dict(raw)
    state = default_state()

    state["created"] = _as_str(raw.get("created"), state["created"])
    state["updated"] = _as_str(raw.get("updated"), state["updated"])
    state["schema_version"] = _as_int(raw.get("schema_version"), SCHEMA_VERSION, 1, 999)
    state["settings"] = _merge_settings(raw.get("settings"))

    # Lists keep their defaults only when the key is *absent* from the file.
    # A user who deliberately deleted every habit must not get them back.
    if "habits" in raw:
        state["habits"] = [
            h for h in (_sanitize_habit(h) for h in _as_list(raw.get("habits"))) if h
        ]
    if "exercises" in raw:
        state["exercises"] = [
            e for e in (_sanitize_exercise(e) for e in _as_list(raw.get("exercises"))) if e
        ]
    if "library" in raw:
        state["library"] = [
            b for b in (_sanitize_book(b) for b in _as_list(raw.get("library"))) if b
        ]

    habit_ids = {h["id"] for h in state["habits"]}
    habit_log: dict[str, Any] = {}
    for day, entries in _as_dict(raw.get("habit_log")).items():
        entries = _as_dict(entries)
        cleaned = {
            hid: 1 if _as_int(v, 0, 0, 1) else 0
            for hid, v in entries.items()
            if hid in habit_ids
        }
        if cleaned:
            habit_log[iso_day(day)] = cleaned
    state["habit_log"] = habit_log

    diet_log: dict[str, Any] = {}
    for day, entry in _as_dict(raw.get("diet_log")).items():
        meals = [m for m in (_sanitize_meal(m) for m in _as_list(_as_dict(entry).get("meals"))) if m]
        if meals:
            diet_log[iso_day(day)] = {"meals": meals}
    state["diet_log"] = diet_log

    workout_log: dict[str, Any] = {}
    for day, entry in _as_dict(raw.get("workout_log")).items():
        entry = _as_dict(entry)
        entries = [e for e in (_sanitize_workout_entry(e) for e in _as_list(entry.get("entries"))) if e]
        if entries:
            workout_log[iso_day(day)] = {
                "name": _as_str(entry.get("name"), "Session")[:120],
                "notes": _as_str(entry.get("notes"))[:2000],
                "entries": entries,
            }
    state["workout_log"] = workout_log

    diary: dict[str, Any] = {}
    for day, entry in _as_dict(raw.get("diary")).items():
        entry = _as_dict(entry)
        html = _as_str(entry.get("html"))
        text = _as_str(entry.get("text"))
        if html or text:
            diary[iso_day(day)] = {
                "html": html,
                "text": text,
                "title": _as_str(entry.get("title"))[:200],
                "updated": _as_str(entry.get("updated"), now_iso()),
            }
    state["diary"] = diary

    ai = _as_dict(raw.get("ai"))
    chat = []
    for msg in _as_list(ai.get("chat"))[-400:]:
        msg = _as_dict(msg)
        role = _as_str(msg.get("role"))
        content = _as_str(msg.get("content")).strip()
        if role in ("user", "assistant", "system") and content:
            chat.append({"role": role, "content": content, "ts": _as_str(msg.get("ts"), now_iso())})
    briefings = {
        iso_day(day): _as_str(text)[:8000]
        for day, text in _as_dict(ai.get("briefings")).items()
        if _as_str(text).strip()
    }
    state["ai"] = {"chat": chat, "briefings": briefings}
    return state
