"""Context serialisation + retrieval (the RAG half of the pipeline)."""

from __future__ import annotations

from datetime import date, timedelta

from lifeboard.ai.context import (
    activity_digest,
    build_context,
    days_with_entries,
    retrieve_passages,
    serialize_day,
    serialize_deltas,
    serialize_goals,
    serialize_recent,
    tokenize,
)
from lifeboard.ai.prompts import system_prompt, trim_history


def test_serialize_day_contains_the_real_numbers(week_of_logs):
    logged, end = week_of_logs
    day = (end - timedelta(days=1)).isoformat()
    text = serialize_day(logged, day)
    assert f"DATE {day}" in text
    assert "habits: 3/4 done" in text
    assert "1,800 kcal" in text           # 700 + 1100
    assert "P 115/180" in text
    assert "tonnage 2,250 kg" in text
    assert "Bench Press 2,250 kg" in text
    assert "Slept badly" in text          # diary excerpt


def test_serialize_day_rest_day_says_so(state):
    text = serialize_day(state, "2026-01-01")
    assert "training: rest day (nothing logged)" in text


def test_serialize_goals_lists_every_target(state):
    text = serialize_goals(state)
    assert "kcal 2,600" in text
    assert "protein 180 g" in text
    assert "session tonnage 6,000 kg" in text


def test_serialize_deltas_compares_two_closed_days(week_of_logs):
    logged, end = week_of_logs
    text = serialize_deltas(logged, end=end)
    # Yesterday 2,250 kg against 2,500 kg the day before.
    assert "tonnage 2,250 kg (-10.0% from 2,500)" in text
    assert "habits 3/4 (+0)" in text
    # Today is explicitly flagged as partial, never as a -100% collapse.
    assert "today so far" in text
    assert "the day is not over" in text
    assert "-100.0%" not in text


def test_serialize_recent_reports_averages(week_of_logs):
    logged, end = week_of_logs
    text = serialize_recent(logged, end=end, days=7)
    assert "LAST 7 DAYS (rolling window" in text
    assert "training days 2/7" in text
    # 2,500 + 2,250 both fall inside the trailing 7-day window.
    assert "tonnage in window 4,750 kg" in text
    # 6 logged days x 1,800 kcal, averaged over all 7 window days (today is 0).
    assert "avg intake 1,543 kcal/day" in text


def test_build_context_assembles_every_section(week_of_logs):
    logged, end = week_of_logs
    day = (end - timedelta(days=1)).isoformat()
    context = build_context(logged, day=day, query="why did my bench stall",
                            max_chars=4000)
    assert "GOALS" in context
    assert f"DATE {day}" in context
    assert "LAST 7 DAYS" in context
    assert "DELTAS" in context
    assert "today so far" in context
    assert "RETRIEVED FROM THE JOURNAL" in context


def test_build_context_truncates_to_budget(week_of_logs):
    logged, end = week_of_logs
    context = build_context(logged, day=(end - timedelta(days=1)).isoformat(),
                            max_chars=200)
    assert len(context) <= 200 + len("\n[context truncated]")
    assert context.endswith("[context truncated]")


def test_retrieval_finds_the_relevant_entry(week_of_logs):
    logged, end = week_of_logs
    logged["diary"][(end - timedelta(days=9)).isoformat()] = {
        "html": "", "text": "Visited the coast. Ate oysters. Read a novel.",
        "title": "Coast", "updated": ""}
    hits = retrieve_passages(logged, "bench shoulders heavy sleep",
                             end=end, top_k=3)
    assert hits, "expected at least one retrieval hit"
    assert hits[0]["kind"] == "diary"
    assert hits[0]["title"] == "Heavy bench"
    assert "Bench" in hits[0]["snippet"] or "bench" in hits[0]["snippet"].lower()


def test_retrieval_prefers_recency_on_a_tie(week_of_logs):
    logged, end = week_of_logs
    same = "Slept badly and everything ached."
    logged["diary"][(end - timedelta(days=30)).isoformat()] = {
        "html": "", "text": same, "title": "Old", "updated": ""}
    logged["diary"][(end - timedelta(days=1)).isoformat()] = {
        "html": "", "text": same, "title": "New", "updated": ""}
    hits = retrieve_passages(logged, "slept badly ached", end=end, top_k=2)
    assert hits[0]["title"] == "New"


def test_retrieval_returns_nothing_for_a_blank_query(state):
    assert retrieve_passages(state, "   ") == []
    assert retrieve_passages(state, "the and for") == []


def test_tokenize_drops_stopwords_and_short_tokens():
    assert tokenize("The Bench Press feels HEAVY today!") == ["bench", "press",
                                                             "feels", "heavy"]


def test_activity_digest_counts_tracked_days(week_of_logs):
    logged, end = week_of_logs
    digest = activity_digest(logged, end=end, days=365)
    assert digest["days_tracked"] == 7
    assert digest["training_sessions"] == 2
    assert digest["total_tonnage"] == 4750.0
    assert digest["total_kcal"] == 7 * 1800.0
    assert digest["best_score"] > 0


def test_days_with_entries_is_sorted_and_unique(week_of_logs):
    logged, _ = week_of_logs
    days = list(days_with_entries(logged))
    assert days == sorted(days)
    assert len(days) == len(set(days))


def test_system_prompt_hides_the_data_behind_the_persona():
    prompt = system_prompt("Be terse.", "GOALS\n  kcal 2600")
    assert prompt.startswith("Be terse.")
    assert "CURRENT USER DATA (authoritative, read-only):" in prompt
    assert "Never invent workouts" in prompt


def test_trim_history_respects_turn_and_char_budgets():
    history = [{"role": "user", "content": f"question {i}" * 40} for i in range(20)]
    history += [{"role": "assistant", "content": f"answer {i}" * 40} for i in range(20)]
    trimmed = trim_history(history, max_turns=8, max_chars=400)
    assert len(trimmed) <= 8
    assert sum(len(m["content"]) for m in trimmed) <= 400 + 1
    assert all(m["role"] in ("user", "assistant") for m in trimmed)
