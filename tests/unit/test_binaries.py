"""Unit tests for media binary discovery."""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_converter.media.binaries import (
    BinaryInfo,
    find_ffmpeg,
    find_ffprobe,
    get_binaries,
    get_ffmpeg_version,
)


class TestBinariesDiscovery:
    """Test suite for ffmpeg/ffprobe binary lookup."""

    def test_find_ffmpeg_in_custom_dir(self, tmp_path: Path):
        fake_ffmpeg = tmp_path / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        fake_ffmpeg.write_text("mock binary")
        fake_ffmpeg.chmod(0o755)

        found = find_ffmpeg(custom_dir=str(tmp_path))
        assert found is not None
        assert Path(found).resolve() == fake_ffmpeg.resolve()

    def test_find_ffprobe_in_custom_dir(self, tmp_path: Path):
        fake_ffprobe = tmp_path / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        fake_ffprobe.write_text("mock binary")
        fake_ffprobe.chmod(0o755)

        found = find_ffprobe(custom_dir=str(tmp_path))
        assert found is not None
        assert Path(found).resolve() == fake_ffprobe.resolve()

    def test_find_ffmpeg_from_path(self, monkeypatch):
        # Ensure candidate directory checks fail
        with patch("video_converter.media.binaries._candidate_directories", return_value=[]):
            with patch("shutil.which", return_value=r"C:\fake\bin\ffmpeg.exe"):
                found = find_ffmpeg()
                assert found == str(Path(r"C:\fake\bin\ffmpeg.exe").resolve())

    def test_find_ffmpeg_not_found(self):
        with patch("video_converter.media.binaries._candidate_directories", return_value=[]):
            with patch("shutil.which", return_value=None):
                assert find_ffmpeg() is None
                assert find_ffprobe() is None

    def test_find_ffmpeg_in_frozen_meipass(self, tmp_path: Path, monkeypatch):
        fake_ffmpeg = tmp_path / ("ffmpeg.exe" if os.name == "nt" else "ffmpeg")
        fake_ffmpeg.write_text("mock binary")
        fake_ffmpeg.chmod(0o755)

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

        found = find_ffmpeg()
        assert found is not None
        assert Path(found).resolve() == fake_ffmpeg.resolve()

    def test_find_ffprobe_in_frozen_meipass(self, tmp_path: Path, monkeypatch):
        fake_ffprobe = tmp_path / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
        fake_ffprobe.write_text("mock binary")
        fake_ffprobe.chmod(0o755)

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

        found = find_ffprobe()
        assert found is not None
        assert Path(found).resolve() == fake_ffprobe.resolve()

    def test_get_ffmpeg_version_success(self):
        mock_output = "ffmpeg version 6.0-full_build Copyright (c) 2000-2023\nbuilt with gcc..."
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout=mock_output, stderr="")
            version = get_ffmpeg_version(r"C:\fake\ffmpeg.exe")
            assert version == "ffmpeg version 6.0-full_build Copyright (c) 2000-2023"

    def test_get_ffmpeg_version_failure(self):
        with patch("subprocess.run", side_effect=subprocess.SubprocessError("Failed")):
            version = get_ffmpeg_version(r"C:\fake\ffmpeg.exe")
            assert version == ""

    def test_get_binaries_structure(self):
        with patch("video_converter.media.binaries.find_ffmpeg", return_value=r"C:\bin\ffmpeg.exe"), \
             patch("video_converter.media.binaries.find_ffprobe", return_value=r"C:\bin\ffprobe.exe"), \
             patch("video_converter.media.binaries.get_ffmpeg_version", return_value="ffmpeg version 6.0"):
            info = get_binaries()
            assert isinstance(info, BinaryInfo)
            assert info.ffmpeg_path == r"C:\bin\ffmpeg.exe"
            assert info.ffprobe_path == r"C:\bin\ffprobe.exe"
            assert info.version == "ffmpeg version 6.0"

    def test_bundled_bin_discovery_real(self):
        # Test finding real bundled bin/ffmpeg.exe in repository if present
        bin_dir = Path(__file__).resolve().parents[2] / "bin"
        if (bin_dir / "ffmpeg.exe").exists():
            ffmpeg_path = find_ffmpeg()
            assert ffmpeg_path is not None
            assert Path(ffmpeg_path).exists()
            assert Path(ffmpeg_path).name.lower().startswith("ffmpeg")
