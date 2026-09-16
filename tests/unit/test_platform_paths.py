"""Unit tests for platform paths and bundled resource resolution."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import QStandardPaths

from video_converter.platform_paths import (
    APP_DIR_NAME,
    get_app_config_dir,
    get_bundled_resource,
    get_config_path,
)


class TestPlatformPaths:
    """Test suite for platform paths resolution."""

    def test_get_app_config_dir_generic_returned_dir(self, tmp_path: Path, monkeypatch):
        mock_config_dir = tmp_path / "mock_config_dir"
        monkeypatch.setattr(
            QStandardPaths,
            "writableLocation",
            lambda loc: str(mock_config_dir) if loc == QStandardPaths.StandardLocation.AppConfigLocation else "",
        )

        config_dir = get_app_config_dir()
        assert config_dir == mock_config_dir / APP_DIR_NAME
        assert config_dir.exists()

    def test_get_app_config_dir_already_namespaced(self, tmp_path: Path, monkeypatch):
        mock_config_dir = tmp_path / "mock_config_dir" / APP_DIR_NAME
        monkeypatch.setattr(
            QStandardPaths,
            "writableLocation",
            lambda loc: str(mock_config_dir) if loc == QStandardPaths.StandardLocation.AppConfigLocation else "",
        )

        config_dir = get_app_config_dir()
        assert config_dir == mock_config_dir
        assert config_dir.exists()

    def test_get_app_config_dir_accepts_qt_display_name_namespace(self, tmp_path: Path, monkeypatch):
        qt_namespaced_dir = tmp_path / "Free Simple Video Converter"
        monkeypatch.setattr(
            QStandardPaths,
            "writableLocation",
            lambda _location: str(qt_namespaced_dir),
        )

        assert get_app_config_dir() == qt_namespaced_dir

    @pytest.mark.parametrize("empty_val", ["", "   ", "\t\n"])
    def test_get_app_config_dir_empty_or_whitespace_fallback(self, empty_val: str, monkeypatch, tmp_path: Path):
        fake_home = tmp_path / "fake_home"
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: fake_home))
        monkeypatch.setattr(
            QStandardPaths,
            "writableLocation",
            lambda loc: empty_val if loc == QStandardPaths.StandardLocation.AppConfigLocation else "",
        )

        config_dir = get_app_config_dir()
        expected = fake_home / ".config" / APP_DIR_NAME
        assert config_dir == expected
        assert config_dir.exists()

    def test_get_config_path_returns_config_json_in_app_config_dir(self, tmp_path: Path, monkeypatch):
        mock_config_dir = tmp_path / "mock_config_dir"
        monkeypatch.setattr(
            QStandardPaths,
            "writableLocation",
            lambda loc: str(mock_config_dir) if loc == QStandardPaths.StandardLocation.AppConfigLocation else "",
        )

        config_path = get_config_path()
        assert config_path == mock_config_dir / APP_DIR_NAME / "config.json"
        assert config_path.parent.exists()

    def test_get_bundled_resource_in_frozen_mode(self, tmp_path: Path, monkeypatch):
        fake_meipass = tmp_path / "fake_meipass"
        fake_meipass.mkdir()
        fake_icon = fake_meipass / "icon.ico"
        fake_icon.write_text("dummy icon")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)

        res = get_bundled_resource("icon.ico")
        assert res is not None
        assert res.resolve() == fake_icon.resolve()

    def test_get_bundled_resource_frozen_relative_path_wins_over_basename_collision(self, tmp_path: Path, monkeypatch):
        fake_meipass = tmp_path / "fake_meipass"
        nested_dir = fake_meipass / "assets" / "icons"
        nested_dir.mkdir(parents=True)

        target_file = nested_dir / "item.txt"
        target_file.write_text("correct nested content")

        colliding_root_file = fake_meipass / "item.txt"
        colliding_root_file.write_text("incorrect flat content")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(fake_meipass), raising=False)

        res = get_bundled_resource("assets/icons/item.txt")
        assert res is not None
        assert res.resolve() == target_file.resolve()
        assert res.read_text() == "correct nested content"

    def test_get_bundled_resource_in_development_mode(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

        # In dev mode, bundled application assets should resolve from the repository.
        res = get_bundled_resource("assets/icon.ico")
        assert res is not None
        assert res.exists()

    def test_get_bundled_resource_non_existent(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)

        res = get_bundled_resource("non_existent_file_xyz_123.tmp")
        assert res is None
