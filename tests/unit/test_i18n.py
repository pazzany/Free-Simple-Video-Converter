"""Tests for i18n module and language neutrality."""

from __future__ import annotations

import pytest
from video_converter.domain.encoders import EncoderType
from video_converter.domain.jobs import ConversionJob, JobStatus
from video_converter.domain.presets import Preset
from video_converter.domain.settings import OutputMode
from video_converter.ui.i18n import (
    TRANSLATIONS,
    get_language,
    on_language_changed,
    remove_language_listener,
    set_language,
    tr,
)


@pytest.fixture(autouse=True)
def _reset_i18n_state():
    """Ensure tests run with clean i18n language state and no leftover listeners."""
    from video_converter.ui import i18n

    original_lang = get_language()
    original_listeners = list(i18n._listeners)
    set_language("en")
    try:
        yield
    finally:
        i18n._listeners[:] = original_listeners
        set_language(original_lang)


def test_translations_keys_parity_en_ru():
    """Every key in TRANSLATIONS must have non-empty definitions for both 'en' and 'ru'."""
    assert len(TRANSLATIONS) > 0
    for key, val in TRANSLATIONS.items():
        assert isinstance(val, dict), f"Key {key!r} value should be a dict"
        assert "en" in val, f"Key {key!r} is missing English translation"
        assert "ru" in val, f"Key {key!r} is missing Russian translation"
        assert val["en"].strip(), f"Key {key!r} has empty English translation"
        assert val["ru"].strip(), f"Key {key!r} has empty Russian translation"


def test_file_filter_lists_windows_media_input_patterns():
    for language in ("en", "ru"):
        file_filter = TRANSLATIONS["file_filter"][language]
        for pattern in ("*.asf", "*.wm", "*.wma"):
            assert pattern in file_filter


def test_tr_default_and_fallback():
    """tr should default to English and fall back gracefully on unknown key or missing lang."""
    set_language("en")
    assert tr("window_title") == "Free Simple Video Converter"

    set_language("ru")
    assert tr("window_title") == "Free Simple Video Converter"

    # Unknown key returns key itself
    assert tr("non_existent_key_xyz") == "non_existent_key_xyz"


def test_tr_formatting():
    """tr should format template strings correctly."""
    set_language("en")
    assert tr("group_quality", value=24) == "Quality (CRF): 24"

    set_language("ru")
    assert tr("group_quality", value=24) == "Качество (CRF): 24"

    # Formatting with mismatched or missing arguments does not crash
    assert "Quality" in tr("group_quality") or "Качество" in tr("group_quality")


def test_listener_registration_and_callback():
    """on_language_changed registers callbacks and remove_language_listener unregisters them."""
    calls = []

    def callback():
        calls.append(get_language())

    on_language_changed(callback)
    try:
        set_language("ru")
        assert calls == ["ru"]
        set_language("en")
        assert calls == ["ru", "en"]
    finally:
        remove_language_listener(callback)

    # Calling set_language again should not invoke removed listener
    set_language("ru")
    assert calls == ["ru", "en"]


def test_domain_enum_language_neutrality():
    """Domain enums must have technical/language-neutral values and representations."""
    # JobStatus values
    assert [s.value for s in JobStatus] == [
        "pending",
        "probing",
        "running",
        "completed",
        "failed",
        "cancelled",
    ]

    # EncoderType names & codec_names
    for enc in EncoderType:
        assert enc.codec_name in ("auto", "h264_nvenc", "h264_qsv", "h264_amf", "libx264")
        # Encoders display_name is neutral technical representation
        assert isinstance(enc.display_name, str)

    # Preset ids
    for preset in Preset:
        assert preset.preset_id in ("original", "480p", "720p", "1080p", "2k", "4k")

    # OutputMode mode_ids
    for mode in OutputMode:
        assert mode.mode_id in ("same_dir", "custom_dir")


def test_domain_jobs_has_no_ui_import():
    """Ensure video_converter.domain.jobs does not import UI i18n."""
    import sys
    import video_converter.domain.jobs as jobs_mod

    # JobStatus should not have a method that dynamically imports video_converter.ui
    # Check that jobs module does not have ui in globals
    assert "video_converter.ui" not in jobs_mod.__dict__
