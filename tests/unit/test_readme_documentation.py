"""Contract tests for the bilingual GitHub landing pages."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
INPUT_EXTENSIONS = (
    ".mp4",
    ".mkv",
    ".avi",
    ".mov",
    ".wmv",
    ".asf",
    ".wm",
    ".wma",
    ".flv",
    ".webm",
    ".m4v",
    ".ts",
    ".mts",
    ".m2ts",
    ".3gp",
    ".vob",
    ".ogv",
)
EN_HEADINGS = (
    "## Features",
    "## Supported input files",
    "## Download and quick start",
    "## Run from source",
    "## Build the standalone executable",
    "## Conversion behavior",
    "## License and notices",
)
RU_HEADINGS = (
    "## Возможности",
    "## Поддерживаемые входные файлы",
    "## Загрузка и быстрый старт",
    "## Запуск из исходников",
    "## Сборка автономного приложения",
    "## Поведение конвертации",
    "## Лицензия и уведомления",
)


def _read(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def _heading_positions(text: str, headings: tuple[str, ...]) -> list[int]:
    return [text.index(heading) for heading in headings]


def test_readmes_have_reciprocal_language_links_and_screenshots():
    english = _read("README.md")
    russian = _read("README_RU.md")

    assert "[Русская версия](README_RU.md)" in english
    assert "[English version](README.md)" in russian
    assert "docs/images/en.jpg" in english
    assert "docs/images/ru.jpg" in russian
    assert (ROOT / "docs/images/en.jpg").is_file()
    assert (ROOT / "docs/images/ru.jpg").is_file()


def test_readmes_document_same_supported_input_extensions_and_notices():
    for name in ("README.md", "README_RU.md"):
        text = _read(name).lower()
        assert all(extension in text for extension in INPUT_EXTENSIONS)
        assert "gyan" not in text
        assert "third_party_notices.md" in text
        assert "packaging/ffmpeg_source_release_checklist.md" in text
        assert "custom ffmpeg 6.1.1 ucrt64" in text


def test_readmes_have_mirrored_heading_order_and_feature_bullet_count():
    english = _read("README.md")
    russian = _read("README_RU.md")

    assert _heading_positions(english, EN_HEADINGS) == sorted(
        _heading_positions(english, EN_HEADINGS)
    )
    assert _heading_positions(russian, RU_HEADINGS) == sorted(
        _heading_positions(russian, RU_HEADINGS)
    )

    english_features = english.split("## Supported input files", 1)[0].split("## Features", 1)[1]
    russian_features = russian.split("## Поддерживаемые входные файлы", 1)[0].split("## Возможности", 1)[1]
    assert sum(line.startswith("-") for line in english_features.splitlines()) == sum(
        line.startswith("-") for line in russian_features.splitlines()
    )
