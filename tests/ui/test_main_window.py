"""Tests for PySide6 MainWindow and UI interactions using pytest-qt."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog

from video_converter.domain.encoders import EncoderType
from video_converter.domain.jobs import ConversionJob, JobStatus
from video_converter.domain.presets import Preset
from video_converter.domain.settings import AppSettings, OutputMode
from video_converter.queue.controller import QueueController
from video_converter.ui.i18n import tr
from video_converter.ui.main_window import MainWindow
from video_converter.ui.settings_panel import SettingsPanel


@pytest.fixture
def temp_config_file(tmp_path: Path) -> Path:
    return tmp_path / "test_config.json"


@pytest.fixture
def window(qtbot, temp_config_file: Path) -> MainWindow:
    controller = QueueController()
    win = MainWindow(controller=controller, config_path=temp_config_file)
    qtbot.addWidget(win)
    win.show()
    return win


def test_main_window_creation(window: MainWindow) -> None:
    """Verify window title, central widget and default UI setup."""
    assert "Video Converter" in window.windowTitle()
    assert window.centralWidget() is not None
    assert window.job_table.table.rowCount() == 0
    # Disabled by default when queue has no pending jobs
    assert window.btn_start.isEnabled() is False
    assert window.btn_stop.isEnabled() is False
    # Check updated column headers
    headers = window.job_table._get_headers()
    assert headers[1] == tr("col_file")
    assert headers[6] == tr("col_preset")
    assert headers[7] == tr("col_progress")


def test_first_run_creates_default_config(qtbot, temp_config_file: Path) -> None:
    assert not temp_config_file.exists()

    win = MainWindow(config_path=temp_config_file)
    qtbot.addWidget(win)

    assert temp_config_file.is_file()
    loaded = AppSettings.load_from_file(temp_config_file)
    assert loaded.language == "en"
    assert loaded.target_fps is None
    assert loaded.audio_bitrate == "192k"


def test_adding_mock_files_updates_table(window: MainWindow, qtbot, tmp_path: Path) -> None:
    """Verify adding files updates the job table rows and enables start button."""
    file1 = tmp_path / "sample1.mp4"
    file1.touch()
    file2 = tmp_path / "sample2.mkv"
    file2.touch()

    with patch("video_converter.queue.controller.probe_file") as mock_probe:
        mock_probe.return_value = None

        with patch.object(
            QFileDialog, "getOpenFileNames", return_value=([str(file1), str(file2)], "")
        ):
            qtbot.mouseClick(window.btn_add_files, Qt.MouseButton.LeftButton)

    assert window.job_table.table.rowCount() == 2
    assert window.job_table.table.item(0, window.job_table.COL_NAME).text() == "sample1.mp4"
    assert window.job_table.table.item(1, window.job_table.COL_NAME).text() == "sample2.mkv"
    assert window.btn_start.isEnabled() is True


def test_settings_ui_changes_saved_and_passed(
    window: MainWindow, qtbot, temp_config_file: Path, tmp_path: Path
) -> None:
    """Verify modifying settings updates configuration and is passed to controller."""
    # Set preset to 720p
    idx = window.settings_panel.preset_combo.findData(Preset.P720)
    assert idx >= 0
    window.settings_panel.preset_combo.setCurrentIndex(idx)

    # Set CRF to 28
    window.settings_panel.crf_slider.setValue(28)
    assert "28" in window.settings_panel.crf_group.title()

    # Check saved settings file
    loaded_settings = AppSettings.load_from_file(temp_config_file)
    assert loaded_settings.preset == Preset.P720
    assert loaded_settings.crf == 28

    # Enqueue a file and verify parameters match UI
    test_video = tmp_path / "test.mp4"
    test_video.touch()

    with patch("video_converter.queue.controller.probe_file", return_value=None):
        window._enqueue_paths([str(test_video)])

    jobs = window.controller.jobs
    assert len(jobs) == 1
    assert jobs[0].preset == Preset.P720
    assert jobs[0].crf == 28


def test_start_stop_button_state_toggling(window: MainWindow, qtbot, tmp_path: Path) -> None:
    """Verify start and stop buttons enable/disable correctly during queue state changes."""
    test_video = tmp_path / "test.mp4"
    test_video.touch()

    with patch("video_converter.queue.controller.probe_file", return_value=None):
        window._enqueue_paths([str(test_video)])

    assert window.btn_start.isEnabled() is True

    # Mock worker start_job to avoid executing actual ffmpeg
    with patch.object(window.controller._worker, "start_job") as mock_start:
        qtbot.mouseClick(window.btn_start, Qt.MouseButton.LeftButton)

        assert window.controller.is_running is True
        assert window.btn_start.isEnabled() is False
        assert window.btn_stop.isEnabled() is True
        assert window.settings_panel.preset_combo.isEnabled() is False

        # Now click stop
        qtbot.mouseClick(window.btn_stop, Qt.MouseButton.LeftButton)

        assert window.controller.is_running is False
        assert window.btn_start.isEnabled() is True
        assert window.btn_stop.isEnabled() is False
        assert window.settings_panel.preset_combo.isEnabled() is True


def test_remove_job_action(window: MainWindow, tmp_path: Path) -> None:
    """Verify removing a job from the table disables start button when queue becomes empty."""
    test_video = tmp_path / "test.mp4"
    test_video.touch()

    with patch("video_converter.queue.controller.probe_file", return_value=None):
        window._enqueue_paths([str(test_video)])

    assert window.job_table.table.rowCount() == 1
    assert window.btn_start.isEnabled() is True
    job_id = window.controller.jobs[0].id

    window.job_table.remove_job_requested.emit(job_id)
    assert len(window.controller.jobs) == 0
    assert window.job_table.table.rowCount() == 0
    assert window.btn_start.isEnabled() is False


def test_individual_job_settings_update_on_selection(window: MainWindow, qtbot, tmp_path: Path) -> None:
    """Verify that selecting a job and changing panel settings modifies only the selected job."""
    f1 = tmp_path / "vid1.mp4"
    f2 = tmp_path / "vid2.mp4"
    f1.touch()
    f2.touch()

    with patch("video_converter.queue.controller.probe_file", return_value=None):
        window._enqueue_paths([str(f1), str(f2)])

    assert len(window.controller.jobs) == 2
    job1 = window.controller.jobs[0]
    job2 = window.controller.jobs[1]

    # Default preset is 1080p, CRF 24
    assert job1.preset == Preset.P1080
    assert job2.preset == Preset.P1080

    # Select row 0 (job 1)
    window.job_table.table.selectRow(0)

    # Change settings to 720p, CRF 30, FPS 60, Audio 320k
    idx_720 = window.settings_panel.preset_combo.findData(Preset.P720)
    window.settings_panel.preset_combo.setCurrentIndex(idx_720)
    window.settings_panel.crf_slider.setValue(30)
    idx_fps_60 = window.settings_panel.fps_combo.findData(60)
    window.settings_panel.fps_combo.setCurrentIndex(idx_fps_60)
    idx_audio_320 = window.settings_panel.audio_bitrate_combo.findData("320k")
    window.settings_panel.audio_bitrate_combo.setCurrentIndex(idx_audio_320)

    # Job 1 should have new settings, Job 2 remains 1080p / 24 / None / 192k
    assert job1.preset == Preset.P720
    assert job1.crf == 30
    assert job1.target_fps == 60
    assert job1.audio_bitrate == "320k"
    assert job2.preset == Preset.P1080
    assert job2.crf == 24
    assert job2.target_fps is None
    assert job2.audio_bitrate == "192k"

    # Selecting Job 2 should restore Job 2's settings to panel without overwriting Job 2
    window.job_table.table.selectRow(1)
    assert window.settings_panel.selected_preset == Preset.P1080
    assert window.settings_panel.selected_crf == 24
    assert window.settings_panel.selected_fps is None
    assert window.settings_panel.selected_audio_bitrate == "192k"
    assert job2.preset == Preset.P1080
    assert job2.target_fps is None

    # Selecting Job 1 again should restore Job 1's settings to panel
    window.job_table.table.selectRow(0)
    assert window.settings_panel.selected_preset == Preset.P720
    assert window.settings_panel.selected_crf == 30
    assert window.settings_panel.selected_fps == 60
    assert window.settings_panel.selected_audio_bitrate == "320k"

    # Verify table column "Пресет" reflects the update in row 0
    settings_item_row0 = window.job_table.table.item(0, window.job_table.COL_SETTINGS)
    assert settings_item_row0 is not None
    assert "720P" in settings_item_row0.text()
    assert "CRF 30" in settings_item_row0.text()


def test_settings_panel_get_apply_settings(qtbot) -> None:
    panel = SettingsPanel()
    qtbot.addWidget(panel)

    settings = AppSettings(
        preset=Preset.P4K,
        crf=18,
        encoder=EncoderType.QSV,
        output_mode=OutputMode.CUSTOM_DIR,
        custom_output_dir="/custom/path",
        target_fps=30,
        audio_bitrate="128k",
    )
    panel.apply_settings(settings)

    retrieved = panel.get_settings()
    assert retrieved.preset == Preset.P4K
    assert retrieved.crf == 18
    assert retrieved.encoder == EncoderType.QSV
    assert retrieved.output_mode == OutputMode.CUSTOM_DIR
    assert retrieved.custom_output_dir == "/custom/path"
    assert retrieved.target_fps == 30
    assert retrieved.audio_bitrate == "128k"


def test_app_settings_from_dict_robustness() -> None:
    """Verify AppSettings.from_dict handles invalid crf and target_fps gracefully."""
    invalid_data = {
        "crf": "invalid",
        "target_fps": "not_an_int",
    }
    settings = AppSettings.from_dict(invalid_data)
    assert settings.crf == 24
    assert settings.target_fps is None


def test_theme_toggle_and_persistence(window: MainWindow, qtbot, temp_config_file: Path) -> None:
    """Verify theme toggle button flips theme state, updates icon, and persists in config."""
    assert window._dark_theme is True
    assert window.btn_theme_toggle.text() == "🌙"

    # Click toggle button -> Light Theme
    qtbot.mouseClick(window.btn_theme_toggle, Qt.MouseButton.LeftButton)
    assert window._dark_theme is False
    assert window.btn_theme_toggle.text() == "☀️"

    # Verify saved in config file
    import json
    with open(temp_config_file, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data.get("dark_theme") is False

    # Create new window instance using same config to verify loading
    win2 = MainWindow(config_path=temp_config_file)
    qtbot.addWidget(win2)
    assert win2._dark_theme is False
    assert win2.btn_theme_toggle.text() == "☀️"

    # Toggle back to dark
    qtbot.mouseClick(win2.btn_theme_toggle, Qt.MouseButton.LeftButton)
    assert win2._dark_theme is True
    assert win2.btn_theme_toggle.text() == "🌙"
