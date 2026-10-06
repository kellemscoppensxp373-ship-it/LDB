"""Palette maths and QSS rendering."""

from __future__ import annotations

import pytest

from lifeboard import theme
from lifeboard.theme import (
    BASE_BG,
    build_palette,
    build_stylesheet,
    hex_to_rgb,
    hsl_hex,
    load_template,
    mix,
    readable_text_for,
    render_stylesheet,
    unresolved_tokens,
    with_alpha,
)

REQUIRED_KEYS = (
    "BG0", "BG1", "BG2", "BG3", "BG4", "BORDER", "BORDER_STRONG", "TEXT",
    "TEXT_DIM", "TEXT_FAINT", "ACCENT", "ACCENT_BRIGHT", "ACCENT_DIM",
    "ACCENT_DARK", "GOOD", "WARN", "DANGER", "HEAT0", "HEAT1", "HEAT2",
    "HEAT3", "HEAT4",
)


@pytest.mark.parametrize("hue", [0, 45, 120, 190, 265, 350])
def test_palette_is_complete_and_hex_shaped(hue):
    palette = build_palette(hue)
    for key in REQUIRED_KEYS:
        assert key in palette, key
        value = palette[key]
        assert value.startswith("#") and len(value) == 7, (key, value)
        hex_to_rgb(value)


def test_base_background_is_the_specified_colour():
    assert build_palette(265)["BG0"] == BASE_BG == "#0B0E15"


def test_hue_actually_drives_the_accent():
    assert build_palette(265)["ACCENT"] != build_palette(30)["ACCENT"]
    assert build_palette(0)["ACCENT"] == build_palette(360)["ACCENT"]


def test_hue_wraps_and_accepts_floats():
    assert build_palette(-95)["ACCENT"] == build_palette(265)["ACCENT"]
    assert build_palette(265.0)["ACCENT"] == build_palette(265)["ACCENT"]


def test_heat_levels_ramp_upwards_in_lightness():
    palette = build_palette(265)
    levels = [sum(hex_to_rgb(palette[f"HEAT{i}"])) / 3.0 for i in range(5)]
    assert levels == sorted(levels), levels
    assert levels[0] < levels[-1]


def test_with_alpha_puts_alpha_first_for_qss():
    assert with_alpha("#FF8800", 1.0) == "#FFFF8800"
    assert with_alpha("#FF8800", 0.0) == "#00FF8800"


def test_mix_and_readable_text():
    assert mix("#000000", "#FFFFFF", 0.0) == "#000000"
    assert mix("#000000", "#FFFFFF", 1.0) == "#FFFFFF"
    assert readable_text_for("#FFFFFF") == BASE_BG
    assert readable_text_for("#0B0E15") == "#F2F4FA"


def test_hsl_hex_basics():
    assert hsl_hex(0, 1.0, 0.5) == "#FF0000"
    assert hsl_hex(120, 1.0, 0.5) == "#00FF00"
    assert hsl_hex(240, 1.0, 0.5) == "#0000FF"
    assert hsl_hex(0, 0.0, 0.0) == "#000000"


def test_shipped_stylesheet_has_no_unresolved_tokens():
    """Guards against renaming a palette key without updating theme.qss."""
    stylesheet, _palette = build_stylesheet(265, load_template())
    assert unresolved_tokens(stylesheet) == []
    assert "{{" not in stylesheet
    assert "0B0E15" in stylesheet


def test_stylesheet_restyles_with_the_hue():
    violet, _ = build_stylesheet(265)
    ember, _ = build_stylesheet(25)
    assert violet != ember


def test_render_leaves_unknown_tokens_visible():
    out = render_stylesheet({"ACCENT": "#123456"}, "color: {{ACCENT}}; {{NOPE}};")
    assert out == "color: #123456; {{NOPE}};"


def test_palette_for_widgets_subset():
    subset = theme.palette_for_widgets(build_palette(200))
    assert "ACCENT" in subset and "HEAT4" in subset
    assert "ACCENT_A18" not in subset
