"""Tests for theme stylesheets and styling palette tokens."""

from __future__ import annotations

import re

from video_converter.ui.styles import (
    DARK_PALETTE,
    LIGHT_PALETTE,
    LIGHT_THEME_QSS,
    THEME_QSS,
    get_theme,
)


def _extract_block_properties(qss: str, selector: str) -> dict[str, str]:
    """Extract key-value CSS properties for a given selector."""
    pattern = rf"{re.escape(selector)}\s*\{{([^}}]+)\}}"
    match = re.search(pattern, qss)
    assert match is not None, f"Selector '{selector}' not found in QSS"
    props = {}
    for line in match.group(1).strip().split(";"):
        line = line.strip()
        if not line or ":" not in line:
            continue
        key, val = line.split(":", 1)
        props[key.strip()] = val.strip()
    return props


def test_tooltip_contrast_dark_and_light():
    """QToolTip text and background colors must have distinct, readable contrast."""
    for qss, palette in [(THEME_QSS, DARK_PALETTE), (LIGHT_THEME_QSS, LIGHT_PALETTE)]:
        props = _extract_block_properties(qss, "QToolTip")
        assert props["background-color"] == palette.tooltip_bg
        assert props["color"] == palette.tooltip_text
        assert props["border"] == f"1px solid {palette.tooltip_border}"
        assert props["background-color"] != props["color"], "Tooltip background and text color must differ"


def test_theme_qss_contains_semantic_palette_colors():
    """Dark and light theme stylesheets should render corresponding semantic tokens without unresolved ternaries."""
    assert DARK_PALETTE.tooltip_bg == "#24283b"
    assert DARK_PALETTE.tooltip_text == "#c0caf5"
    assert LIGHT_PALETTE.tooltip_bg == "#ffffff"
    assert LIGHT_PALETTE.tooltip_text == "#1e293b"

    dark_props = _extract_block_properties(THEME_QSS, "QToolTip")
    assert dark_props["background-color"] == "#24283b"
    assert dark_props["color"] == "#c0caf5"

    light_props = _extract_block_properties(LIGHT_THEME_QSS, "QToolTip")
    assert light_props["background-color"] == "#ffffff"
    assert light_props["color"] == "#1e293b"

    # Verify get_theme helper
    assert get_theme(True) == THEME_QSS
    assert get_theme(False) == LIGHT_THEME_QSS
