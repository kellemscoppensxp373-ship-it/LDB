"""Hidden system prompts and instruction wrappers for the local model.

The user never sees these; they are the "system" turn injected before the
serialised life data so the model has grounding it cannot invent.
"""

from __future__ import annotations

DEFAULT_PERSONA = (
    "You are the LifeBoard Advisor: a terse, direct, slightly gothic coaching "
    "intelligence embedded in a local desktop app. You speak in short "
    "imperative sentences, you never apologise, you never mention that you are "
    "a language model, and you always ground your advice in the numbers from "
    "the user's own logs."
)

RULES = (
    "RULES:\n"
    "- Answer in at most 6 short lines unless the user asks for more.\n"
    "- Plain text only. No markdown headings, no bullet glyphs, no emojis.\n"
    "- Cite the user's own numbers when you give advice (kcal, tonnage, "
    "habits done, streak).\n"
    "- If the data does not support a claim, say the log is empty instead of "
    "guessing.\n"
    "- Never invent workouts, meals or habits that are not in the log.\n"
    "- You are running offline on the user's own machine; there is no network."
)

EDITOR_INSTRUCTIONS = {
    "summarize": (
        "Summarise the following diary entry in at most 4 plain-text lines. "
        "Keep concrete details (numbers, names, decisions). Do not add "
        "commentary or advice.\n\nENTRY:\n"
    ),
    "improve": (
        "Rewrite the following diary entry so the prose is tighter and more "
        "vivid. Preserve every factual detail and the first-person voice. "
        "Output only the rewritten entry, no preamble.\n\nENTRY:\n"
    ),
    "ideas": (
        "Based on the following diary entry, propose 5 concrete follow-up "
        "prompts or actions for the writer, one per line, numbered 1-5. Each "
        "must connect to something actually in the entry.\n\nENTRY:\n"
    ),
    "briefing": (
        "Write a morning briefing for the user based on the metrics below. "
        "At most 5 short lines: one line on training load, one on nutrition, "
        "one on habits, one on the single highest-leverage action for today. "
        "Be concrete, quote the numbers, no filler.\n\n"
    ),
}


def system_prompt(persona: str = "", context: str = "") -> str:
    """Assemble the hidden system turn: persona + rules + serialised life data."""
    persona = (persona or DEFAULT_PERSONA).strip()
    parts = [persona, "", RULES]
    if context:
        parts += [
            "",
            "CURRENT USER DATA (authoritative, read-only):",
            context.strip(),
        ]
    return "\n".join(parts)


def editor_prompt(kind: str, body: str, context: str = "") -> str:
    """User-turn prompt for the diary context-menu actions."""
    instruction = EDITOR_INSTRUCTIONS.get(kind, EDITOR_INSTRUCTIONS["summarize"])
    body = body.strip() or "(the entry is empty)"
    if kind == "briefing":
        return f"{instruction}{body}"
    if context:
        return f"{instruction}{body}\n\n(RECENT CONTEXT)\n{context.strip()}"
    return f"{instruction}{body}"


def trim_history(history: list[dict[str, str]], *, max_turns: int = 8,
                 max_chars: int = 6000) -> list[dict[str, str]]:
    """Keep the conversation inside the context window budget."""
    recent = [m for m in history if m.get("role") in ("user", "assistant")][-max_turns:]
    out: list[dict[str, str]] = []
    budget = max_chars
    for message in reversed(recent):
        content = str(message.get("content", ""))
        if len(content) > budget:
            content = content[-budget:]
        out.append({"role": message["role"], "content": content})
        budget -= len(content)
        if budget <= 0:
            break
    out.reverse()
    return out
