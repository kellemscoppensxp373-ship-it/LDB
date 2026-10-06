"""Minimal two-language i18n (English / Russian).

The shipped default is **Russian**.  Set the environment variable
``LIFEBOARD_LANG=en`` to get the English strings (the test-suite does exactly
that so the English assertions keep working).

Usage::

    from .i18n import tr
    label = tr("Load model", "Загрузить модель")

``tr`` reads the environment on every call so tests can flip the language at
runtime without rebuilding the app.
"""

from __future__ import annotations

import os

DEFAULT_LANG = "ru"


def lang() -> str:
    """Active language code (``ru`` by default)."""
    return (os.environ.get("LIFEBOARD_LANG") or DEFAULT_LANG).strip().lower()


def is_ru() -> bool:
    return lang().startswith("ru")


def tr(en: str, ru: str) -> str:
    """Return the string for the active language."""
    return ru if is_ru() else en


def fmt_int(value: float) -> str:
    """Locale-aware thousands separator: ``1 234`` (ru) vs ``1,234`` (en)."""
    text = f"{int(round(float(value))):,}"
    if is_ru():
        return text.replace(",", " ")
    return text


def fmt_num(value: float, decimals: int = 0) -> str:
    text = f"{float(value):,.{decimals}f}"
    if is_ru():
        return text.replace(",", " ")
    return text


_WEEKDAY_RU = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")
_MONTH_RU = ("янв", "фев", "мар", "апр", "май", "июн",
             "июл", "авг", "сен", "окт", "ноя", "дек")


def fmt_date(value) -> str:
    """``Tue 06 Oct 2026`` (en) vs ``вт 06 окт 2026`` (ru) without locales."""
    from datetime import date as _date

    day = value if isinstance(value, _date) else _date.fromisoformat(str(value)[:10])
    if is_ru():
        return (f"{_WEEKDAY_RU[day.weekday()]} {day.day:02d} "
                f"{_MONTH_RU[day.month - 1]} {day.year}")
    return day.strftime("%a %d %b %Y")


def fmt_day_month(value) -> str:
    """``06 Oct`` (en) vs ``06 окт`` (ru)."""
    from datetime import date as _date

    day = value if isinstance(value, _date) else _date.fromisoformat(str(value)[:10])
    if is_ru():
        return f"{day.day:02d} {_MONTH_RU[day.month - 1]}"
    return day.strftime("%d %b")
