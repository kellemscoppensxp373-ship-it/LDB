"""Turn ``data.json`` into the hidden system context for the local model.

This is the retrieval half of the RAG pipeline: nothing goes to the LLM that
was not read out of the user's own file.  :func:`retrieve_passages` is a tiny
keyword-over-recency retriever over diary entries and book notes — enough to
keep a 4k-context quantised model on topic without dragging the whole archive
into the prompt.
"""

from __future__ import annotations

import math
import re
from datetime import date, timedelta
from typing import Any, Iterable

from ..storage.metrics import (
    day_metrics,
    heatmap_series,
    macro_totals,
    percent_change,
    rolling_average,
    streak,
    summary_block,
)

STOPWORDS = {
    "the", "and", "for", "that", "this", "with", "what", "have", "you", "your",
    "are", "was", "were", "but", "not", "from", "should", "would", "could",
    "about", "into", "how", "why", "can", "did", "does", "get", "got", "just",
    "like", "today", "yesterday", "please", "there", "then", "than", "them",
    "they", "will", "shall", "some", "more", "most", "also", "when", "where",
}

WORD_RE = re.compile(r"[a-z0-9']+")


def _num(value: float, decimals: int = 0) -> str:
    if decimals:
        return f"{value:,.{decimals}f}"
    return f"{value:,.0f}"


def _ratio(done: float, goal: float) -> str:
    if not goal:
        return "0%"
    return f"{(done / goal) * 100:.0f}%"


# --------------------------------------------------------------------------- #
# per-day serialisation
# --------------------------------------------------------------------------- #
def habit_lines(state: dict[str, Any], day: str) -> tuple[list[str], list[str]]:
    """``(done_names, missing_names)`` for active habits on ``day``."""
    log = state.get("habit_log", {}).get(day, {})
    done: list[str] = []
    missing: list[str] = []
    for habit in state.get("habits", []):
        if not habit.get("active", True):
            continue
        (done if log.get(habit["id"]) else missing).append(habit["name"])
    return done, missing


def serialize_day(state: dict[str, Any], day: str | None = None, *,
                  include_diary: bool = True, diary_chars: int = 600) -> str:
    """One day of the user's life as compact, LLM-readable text."""
    if day is None:
        day = date.today().isoformat()
    day = day[:10]
    metrics = day_metrics(state, day)
    goals = state.get("settings", {}).get("goals", {})
    macros = metrics["macros"]
    lines = [f"DATE {day} — score {metrics['score']:.0f}/100"]

    done, missing = habit_lines(state, day)
    total = metrics["habits_total"]
    habit_line = f"  habits: {metrics['habits_done']}/{total} done"
    if done:
        habit_line += f" (done: {', '.join(done)})"
    if missing:
        shown = ", ".join(missing[:4])
        if len(missing) > 4:
            shown += f", +{len(missing) - 4} more"
        habit_line += f" (missing: {shown})"
    lines.append(habit_line)

    lines.append(
        f"  diet: {_num(macros['kcal'])} kcal (goal {_num(goals.get('kcal', 0))}, "
        f"{_ratio(macros['kcal'], goals.get('kcal', 0))}) | "
        f"P {_num(macros['protein'])}/{_num(goals.get('protein', 0))} "
        f"C {_num(macros['carbs'])}/{_num(goals.get('carbs', 0))} "
        f"F {_num(macros['fat'])}/{_num(goals.get('fat', 0))} | "
        f"{metrics['meals']} meals logged"
    )

    if metrics["sets"] > 0:
        session = metrics["session_name"] or "unnamed session"
        lines.append(
            f"  training: {session} — tonnage {_num(metrics['tonnage'])} kg "
            f"(goal {_num(goals.get('tonnage', 0))}, "
            f"{_ratio(metrics['tonnage'], goals.get('tonnage', 0))}), "
            f"{metrics['sets']} sets, {metrics['reps']} reps, "
            f"{metrics['exercises']} exercises"
        )
        top = sorted(metrics["per_exercise"].items(), key=lambda kv: -kv[1])[:4]
        if top:
            lines.append("    top lifts: " + ", ".join(
                f"{name} {_num(volume)} kg" for name, volume in top))
    else:
        lines.append("  training: rest day (nothing logged)")

    if include_diary:
        diary = state.get("diary", {}).get(day, {})
        text = str(diary.get("text", "")).strip()
        if text:
            clipped = text[:diary_chars].replace("\n", " ")
            if len(text) > diary_chars:
                clipped += " […]"
            lines.append(f"  diary ({metrics['diary_words']} words): {clipped}")
    return "\n".join(lines)


def serialize_recent(state: dict[str, Any], *, end: date | None = None,
                     days: int = 7) -> str:
    """Rolling picture over the trailing ``days`` window (not the calendar week).

    Every number here is derived from the same window so the model is never
    handed a "7 days" line that was actually computed from a calendar week.
    """
    end = end or date.today()
    metrics = [day_metrics(state, (end - timedelta(days=i)).isoformat())
               for i in range(days)]
    training_days = sum(1 for m in metrics if m["sets"] > 0)
    avg_score = sum(m["score"] for m in metrics) / max(1, len(metrics))
    avg_kcal = sum(m["macros"]["kcal"] for m in metrics) / max(1, len(metrics))
    total_tonnage = sum(m["tonnage"] for m in metrics)
    block = summary_block(state, end=end)
    goals = state.get("settings", {}).get("goals", {})
    return "\n".join([
        f"LAST {days} DAYS (rolling window ending {end.isoformat()})",
        f"  avg score {avg_score:.1f}/100 (today {block['today']['score']:.0f})",
        f"  avg intake {avg_kcal:,.0f} kcal/day "
        f"(goal {goals.get('kcal', 0):,})",
        f"  training days {training_days}/{days}, tonnage in window "
        f"{total_tonnage:,.0f} kg",
        f"  streak {block['streak']} day(s) above 40 score, "
        f"{block['logged_streak']} day(s) with any log",
    ])


def serialize_deltas(state: dict[str, Any], *, end: date | None = None) -> str:
    """Day-over-day deltas — the raw material for the proactive briefing.

    Two blocks on purpose: *yesterday vs the day before* is a closed comparison
    (this is what the briefing judges), while *today so far* is explicitly
    labelled as partial.  Comparing an in-progress day against a finished one
    would tell the model "tonnage -100%" at 09:00, which is a lie.
    """
    end = end or date.today()
    today = day_metrics(state, end.isoformat())
    yest = day_metrics(state, (end - timedelta(days=1)).isoformat())
    before = day_metrics(state, (end - timedelta(days=2)).isoformat())
    goals = state.get("settings", {}).get("goals", {})

    def delta_line(label: str, previous: float, current: float, unit: str) -> str:
        change = percent_change(previous, current)
        if change is None:
            return f"    {label} {current:,.0f} {unit} (no previous day to compare)"
        return (f"    {label} {current:,.0f} {unit} "
                f"({change:+.1f}% from {previous:,.0f})")

    lines = [
        "DELTAS",
        f"  yesterday ({yest['date']}) vs previous day",
        delta_line("tonnage", before["tonnage"], yest["tonnage"], "kg"),
        delta_line("intake", before["macros"]["kcal"], yest["macros"]["kcal"], "kcal"),
        delta_line("protein", before["macros"]["protein"],
                   yest["macros"]["protein"], "g"),
        f"    habits {yest['habits_done']}/{yest['habits_total']} "
        f"({yest['habits_done'] - before['habits_done']:+d})",
        f"  today so far ({today['date']}, partial — the day is not over)",
    ]
    kcal_goal = float(goals.get("kcal") or 0)
    headroom = (f", headroom {kcal_goal - today['macros']['kcal']:+,.0f} kcal"
                if kcal_goal else "")
    lines.append(f"    intake {today['macros']['kcal']:,.0f} kcal of "
                 f"{kcal_goal:,.0f} goal{headroom}")
    lines.append(f"    protein {today['macros']['protein']:,.0f} g, "
                 f"carbs {today['macros']['carbs']:,.0f} g, "
                 f"fat {today['macros']['fat']:,.0f} g")
    lines.append(f"    training {today['sets']} sets, {today['tonnage']:,.0f} kg")
    lines.append(f"    habits {today['habits_done']}/{today['habits_total']}")
    return "\n".join(lines)


def serialize_goals(state: dict[str, Any]) -> str:
    goals = state.get("settings", {}).get("goals", {})
    return (
        "GOALS\n"
        f"  kcal {goals.get('kcal', 0):,} | protein {goals.get('protein', 0)} g | "
        f"carbs {goals.get('carbs', 0)} g | fat {goals.get('fat', 0)} g | "
        f"session tonnage {goals.get('tonnage', 0):,.0f} kg | "
        f"habits/day {goals.get('habits', 0)}"
    )


def serialize_library(state: dict[str, Any], limit: int = 6) -> str:
    books = [b for b in state.get("library", []) if b.get("status") == "reading"] or \
            state.get("library", [])
    if not books:
        return ""
    lines = ["LIBRARY"]
    for book in books[:limit]:
        total = book.get("pages_total") or 0
        read = book.get("pages_read") or 0
        progress = f" {read}/{total}p ({_ratio(read, total)})" if total else ""
        lines.append(f"  {book.get('title', '?')} — {book.get('author', '?')} "
                     f"[{book.get('status', '?')}]{progress}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# retrieval
# --------------------------------------------------------------------------- #
def tokenize(text: str) -> list[str]:
    return [w for w in WORD_RE.findall(str(text).lower())
            if len(w) > 2 and w not in STOPWORDS]


def _passages(state: dict[str, Any]) -> list[dict[str, Any]]:
    """Retrievable corpus: diary entries + book notes, newest first."""
    corpus: list[dict[str, Any]] = []
    for day, entry in state.get("diary", {}).items():
        text = str(entry.get("text", "")).strip()
        if text:
            corpus.append({"kind": "diary", "date": day, "title": entry.get("title", ""),
                           "text": text})
    for book in state.get("library", []):
        notes = str(book.get("notes", "")).strip()
        if notes:
            corpus.append({"kind": "book", "date": book.get("started") or "",
                           "title": book.get("title", ""), "text": notes})
    corpus.sort(key=lambda item: item["date"], reverse=True)
    return corpus


def _recency_weight(day: str, anchor: date) -> float:
    if not day:
        return 0.6
    try:
        delta = abs((anchor - date.fromisoformat(day[:10])).days)
    except ValueError:
        return 0.6
    return max(0.35, 0.99 ** delta)


def retrieve_passages(state: dict[str, Any], query: str, *, top_k: int = 3,
                      end: date | None = None, max_chars: int = 450) -> list[dict[str, Any]]:
    """Keyword + recency retrieval over diary entries and book notes."""
    anchor = end or date.today()
    query_tokens = set(tokenize(query))
    if not query_tokens:
        return []
    scored: list[tuple[float, dict[str, Any]]] = []
    for passage in _passages(state):
        tokens = tokenize(passage["text"])
        if not tokens:
            continue
        counts = {t: tokens.count(t) for t in query_tokens if t in tokens}
        if not counts:
            continue
        score = sum(1.0 + math.log(1.0 + n) for n in counts.values())
        score *= _recency_weight(passage["date"], anchor)
        scored.append((score, passage))
    scored.sort(key=lambda pair: -pair[0])
    out = []
    for score, passage in scored[:top_k]:
        snippet = _best_window(passage["text"], query_tokens, max_chars)
        out.append({**passage, "score": round(score, 3), "snippet": snippet})
    return out


def _best_window(text: str, tokens: set[str], max_chars: int) -> str:
    """Extract the sentence cluster with the most query hits."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if s.strip()]
    if not sentences:
        return text[:max_chars]
    best: list[str] = []
    best_score = -1.0
    for index in range(len(sentences)):
        window: list[str] = []
        length = 0
        cursor = index
        while cursor < len(sentences) and length < max_chars:
            window.append(sentences[cursor])
            length += len(sentences[cursor]) + 1
            cursor += 1
        score = sum(1 for word in tokenize(" ".join(window)) if word in tokens)
        if score > best_score:
            best_score, best = score, window
    snippet = " ".join(best)
    return snippet[:max_chars] + (" […]" if len(snippet) > max_chars else "")


# --------------------------------------------------------------------------- #
# assembly
# --------------------------------------------------------------------------- #
def build_context(state: dict[str, Any], *, day: str | None = None,
                  query: str | None = None, max_chars: int = 2600,
                  end: date | None = None) -> str:
    """The full hidden context block: today, week, deltas, goals, retrieval."""
    day = (day or (end or date.today()).isoformat())[:10]
    sections = [
        serialize_goals(state),
        serialize_day(state, day),
        serialize_recent(state, end=end or date.fromisoformat(day)),
        serialize_deltas(state, end=end or date.fromisoformat(day)),
    ]
    library = serialize_library(state)
    if library:
        sections.append(library)

    passages = retrieve_passages(state, query or "", end=end or date.fromisoformat(day))
    if passages:
        retrieved = ["RETRIEVED FROM THE JOURNAL (most relevant to the question)"]
        for passage in passages:
            label = f"{passage['date']} {passage['title']}".strip()
            retrieved.append(f"  [{passage['kind']} {label}] {passage['snippet']}")
        sections.append("\n".join(retrieved))

    context = "\n\n".join(s for s in sections if s)
    if len(context) > max_chars:
        context = context[:max_chars].rstrip() + "\n[context truncated]"
    return context


def activity_digest(state: dict[str, Any], *, end: date | None = None,
                    days: int = 365) -> dict[str, Any]:
    """Aggregates used by the dashboard header and the 'how am I doing' prompt."""
    end = end or date.today()
    series = heatmap_series(state, end=end, days=days)
    logged = [m for m in series if m.get("logged")]
    trained = [m for m in series if m.get("sets", 0) > 0]
    totals = macro_totals(
        meal for day_key in (m["date"] for m in series)
        for meal in state.get("diet_log", {}).get(day_key, {}).get("meals", [])
    )
    return {
        "days_tracked": len(logged),
        "training_sessions": len(trained),
        "total_tonnage": round(sum(m.get("tonnage", 0.0) for m in trained), 1),
        "total_kcal": totals["kcal"],
        "best_score": max((m.get("score", 0.0) for m in series), default=0.0),
        "streak": streak(state, end=end),
    }


def days_with_entries(state: dict[str, Any]) -> Iterable[str]:
    return sorted({
        *state.get("habit_log", {}),
        *state.get("diet_log", {}),
        *state.get("workout_log", {}),
        *state.get("diary", {}),
    })
