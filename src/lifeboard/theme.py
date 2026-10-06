"""Palette + stylesheet generation.

The whole look of LifeBoard is derived from **one** number: a base hue in
degrees.  :func:`build_palette` turns that hue into every colour the app needs
(backgrounds, borders, text ramp, accent, semantic colours and the five
heatmap intensity levels), and :func:`render_stylesheet` injects them into the
QSS template shipped in ``assets/theme.qss``.

This module is deliberately Qt-free: it only produces hex strings, so the
colour maths can be unit-tested on a machine without a display.
"""

from __future__ import annotations

import colorsys
import re
from pathlib import Path
from typing import Any

from . import paths

#: Fixed anchor colour from the design brief.
BASE_BG = "#0B0E15"

#: Monospace stack, first available family wins.  Applied as QFont families in
#: code *and* referenced by the QSS so widgets cannot fall back to a serif.
FONT_FAMILIES = (
    "Cascadia Mono",
    "JetBrains Mono",
    "Fira Code",
    "Consolas",
    "DejaVu Sans Mono",
    "Liberation Mono",
    "monospace",
)

TOKEN_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")


# --------------------------------------------------------------------------- #
# colour maths
# --------------------------------------------------------------------------- #
def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def hsl_hex(hue: float, saturation: float, lightness: float, alpha: float | None = None) -> str:
    """HSL (h in degrees, s/l in 0..1) -> ``#RRGGBB`` or ``#AARRGGBB`` for QSS."""
    hue = (hue % 360.0) / 360.0
    r, g, b = colorsys.hls_to_rgb(hue, clamp(lightness), clamp(saturation))
    out = "#{:02X}{:02X}{:02X}".format(round(r * 255), round(g * 255), round(b * 255))
    if alpha is not None:
        return "#{:02X}{}".format(round(clamp(alpha) * 255), out[1:])
    return out


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    if len(value) == 8:          # #AARRGGBB
        value = value[2:]
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def mix(a: str, b: str, t: float) -> str:
    """Linear RGB blend of two hex colours (``t=0`` -> ``a``)."""
    ra, ga, ba = hex_to_rgb(a)
    rb, gb, bb = hex_to_rgb(b)
    t = clamp(t)
    return "#{:02X}{:02X}{:02X}".format(
        round(ra + (rb - ra) * t),
        round(ga + (gb - ga) * t),
        round(ba + (bb - ba) * t),
    )


def with_alpha(hex_color: str, alpha: float) -> str:
    """QSS ``#AARRGGBB`` (note: alpha first, unlike CSS)."""
    r, g, b = hex_to_rgb(hex_color)
    return "#{:02X}{:02X}{:02X}{:02X}".format(round(clamp(alpha) * 255), r, g, b)


def readable_text_for(hex_color: str) -> str:
    """Black or near-white, whichever contrasts better with ``hex_color``."""
    r, g, b = hex_to_rgb(hex_color)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return BASE_BG if luminance > 0.62 else "#F2F4FA"


# --------------------------------------------------------------------------- #
# palette
# --------------------------------------------------------------------------- #
def build_palette(hue: float = 265.0) -> dict[str, str]:
    """Every colour the app uses, derived from a single base hue."""
    hue = float(hue) % 360.0

    bg0 = BASE_BG
    bg1 = hsl_hex(hue, 0.20, 0.072)       # window
    bg2 = hsl_hex(hue, 0.19, 0.098)       # panels / cards
    bg3 = hsl_hex(hue, 0.17, 0.135)       # inputs, table rows
    bg4 = hsl_hex(hue, 0.15, 0.175)       # hover / selected row

    border = hsl_hex(hue, 0.18, 0.205)
    border_strong = hsl_hex(hue, 0.26, 0.30)
    border_glow = hsl_hex(hue, 0.55, 0.42)

    text = hsl_hex(hue, 0.10, 0.93)
    text_dim = hsl_hex(hue, 0.09, 0.66)
    text_faint = hsl_hex(hue, 0.08, 0.44)

    accent = hsl_hex(hue, 0.78, 0.62)
    accent_bright = hsl_hex(hue, 0.86, 0.72)
    accent_dim = hsl_hex(hue, 0.62, 0.40)
    accent_dark = hsl_hex(hue, 0.55, 0.22)
    accent_wash = hsl_hex(hue, 0.45, 0.15)
    on_accent = readable_text_for(accent)

    # Complementary triad for semantic states.
    good = hsl_hex(hue + 140.0, 0.58, 0.55)
    warn = hsl_hex(hue + 55.0, 0.72, 0.58)
    danger = hsl_hex(hue + 100.0, 0.68, 0.58)
    info = hsl_hex(hue + 200.0, 0.55, 0.60)

    # Five heatmap intensity levels: dead -> blazing.
    heat = [
        mix(bg2, hsl_hex(hue, 0.35, 0.20), 0.35),
        hsl_hex(hue, 0.45, 0.26),
        hsl_hex(hue, 0.62, 0.38),
        hsl_hex(hue, 0.74, 0.50),
        accent_bright,
    ]

    palette = {
        "HUE": f"{hue:.0f}",
        "BG0": bg0,
        "BG1": bg1,
        "BG2": bg2,
        "BG3": bg3,
        "BG4": bg4,
        "BORDER": border,
        "BORDER_STRONG": border_strong,
        "BORDER_GLOW": border_glow,
        "TEXT": text,
        "TEXT_DIM": text_dim,
        "TEXT_FAINT": text_faint,
        "ACCENT": accent,
        "ACCENT_BRIGHT": accent_bright,
        "ACCENT_DIM": accent_dim,
        "ACCENT_DARK": accent_dark,
        "ACCENT_WASH": accent_wash,
        "ON_ACCENT": on_accent,
        "GOOD": good,
        "WARN": warn,
        "DANGER": danger,
        "INFO": info,
        "HEAT0": heat[0],
        "HEAT1": heat[1],
        "HEAT2": heat[2],
        "HEAT3": heat[3],
        "HEAT4": heat[4],
        "FONT": FONT_FAMILIES[0],
        # QSS helpers
        "ACCENT_A18": with_alpha(accent, 0.18),
        "ACCENT_A35": with_alpha(accent, 0.35),
        "BG3_A80": with_alpha(bg3, 0.80),
        "BG0_E8": with_alpha(bg0, 0.91),
        "SHADOW": with_alpha("#000000", 0.55),
    }
    return palette


def heat_levels(palette: dict[str, str]) -> list[str]:
    """The five heatmap colours, ordered from no activity to maximum."""
    return [palette[f"HEAT{i}"] for i in range(5)]


# --------------------------------------------------------------------------- #
# stylesheet rendering
# --------------------------------------------------------------------------- #
def load_template(path: Path | str | None = None) -> str:
    """Read the QSS template (bundled copy first, repo copy as fallback)."""
    candidate = Path(path) if path else paths.theme_path()
    if not candidate.is_file():
        raise FileNotFoundError(f"theme.qss not found at {candidate}")
    return candidate.read_text(encoding="utf-8")


def render_stylesheet(palette: dict[str, str], template: str | None = None) -> str:
    """Substitute ``{{TOKEN}}`` placeholders.  Unknown tokens are left visible."""
    if template is None:
        template = load_template()

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(palette.get(key, match.group(0)))

    return TOKEN_RE.sub(replace, template)


def unresolved_tokens(stylesheet: str) -> list[str]:
    """Tokens the template asked for but the palette did not provide."""
    return sorted(set(TOKEN_RE.findall(stylesheet)))


def build_stylesheet(hue: float = 265.0, template: str | None = None) -> tuple[str, dict[str, str]]:
    """Convenience wrapper used by the app and by the settings live-preview."""
    palette = build_palette(hue)
    return render_stylesheet(palette, template), palette


def palette_for_widgets(palette: dict[str, str]) -> dict[str, Any]:
    """Subset of the palette handed to custom-painted widgets."""
    keys = ("BG0", "BG1", "BG2", "BG3", "BG4", "BORDER", "BORDER_STRONG",
            "TEXT", "TEXT_DIM", "TEXT_FAINT", "ACCENT", "ACCENT_BRIGHT",
            "ACCENT_DIM", "ACCENT_DARK", "GOOD", "WARN", "DANGER", "INFO",
            "HEAT0", "HEAT1", "HEAT2", "HEAT3", "HEAT4", "ON_ACCENT")
    return {key: palette[key] for key in keys}
