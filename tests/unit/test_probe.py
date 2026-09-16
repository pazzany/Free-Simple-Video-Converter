"""Unit tests for media probe and MediaInfo model."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from video_converter.domain.media_info import MediaInfo
from video_converter.media.probe import _parse_fps, probe_file


def test_media_info_properties_and_formatting():
    """Test MediaInfo aspect ratio calculations and formatted strings."""
    info = MediaInfo(
        file_path="video.mp4",
        width=1920,
        height=1080,
        display_width=1920,
        display_height=1080,
        duration_sec=3665.5,
        size_bytes=1024 * 1024 * 50,  # 50 MB
        fps=30.0,
    )
    assert info.aspect_ratio_str == "16:9"
    assert info.formatted_duration() == "01:01:06"
    assert info.formatted_size() == "50.00 MB"

    # Test short duration
    info.duration_sec = 45.0
    assert info.formatted_duration() == "00:45"

    # Test zero duration and size
    info.duration_sec = 0.0
    info.size_bytes = 0
    assert info.formatted_duration() == "00:00"
    assert info.formatted_size() == "0 B"

    # Test small byte size
    info.size_bytes = 500
    assert info.formatted_size() == "500 B"

    # Test custom aspect ratios
    info.display_width = 1080
    info.display_height = 1920
    assert info.aspect_ratio_str == "9:16"

    info.display_width = 1000
    info.display_height = 1000
    assert info.aspect_ratio_str == "1:1"

    info.display_width = 0
    info.display_height = 0
    assert info.aspect_ratio_str == ""


def test_parse_fps():
    """Test parsing fraction and float fps strings."""
    assert _parse_fps("30/1") == 30.0
    assert pytest.approx(_parse_fps("24000/1001"), 0.001) == 23.976
    assert _parse_fps("60") == 60.0
    assert _parse_fps("0/0") == 0.0
    assert _parse_fps(None) == 0.0
    assert _parse_fps("invalid") == 0.0
    assert _parse_fps("10/0") == 0.0


@patch("os.path.isfile", return_value=True)
@patch("video_converter.media.probe.subprocess.run")
def test_probe_file_standard_1080p(mock_run, mock_isfile):
    """Test probing a standard 1080p video with audio."""
    sample_json = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "duration": "120.5",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
            },
        ],
        "format": {
            "duration": "120.5",
            "size": "10485760",
        },
    }

    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(sample_json),
        stderr="",
    )

    info = probe_file("test.mp4", ffprobe_path="/usr/bin/ffprobe")

    assert info.file_path == "test.mp4"
    assert info.width == 1920
    assert info.height == 1080
    assert info.display_width == 1920
    assert info.display_height == 1080
    assert info.rotation == 0
    assert info.codec_video == "h264"
    assert info.codec_audio == "aac"
    assert info.has_audio is True
    assert info.duration_sec == 120.5
    assert info.size_bytes == 10485760
    assert info.fps == 30.0


@patch("os.path.isfile", return_value=True)
@patch("video_converter.media.probe.subprocess.run")
def test_probe_file_rotated_90(mock_run, mock_isfile):
    """Test probing a video with 90 degree rotation in side_data_list."""
    sample_json = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "60/1",
                "side_data_list": [
                    {"rotation": -90}
                ],
            }
        ],
        "format": {
            "duration": "15.0",
            "size": "5000000",
        },
    }

    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(sample_json),
        stderr="",
    )

    info = probe_file("rotated.mp4", ffprobe_path="ffprobe")

    assert info.width == 1920
    assert info.height == 1080
    assert info.rotation == 270
    assert info.display_width == 1080
    assert info.display_height == 1920
    assert info.has_audio is False
    assert info.codec_audio == ""
    assert info.codec_video == "hevc"
    assert info.fps == 60.0


@patch("os.path.isfile", return_value=True)
@patch("video_converter.media.probe.subprocess.run")
def test_probe_file_tag_rotation(mock_run, mock_isfile):
    """Test probing a video with rotation in stream tags."""
    sample_json = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "tags": {"rotate": "90"},
            }
        ],
        "format": {"duration": "10.0"},
    }

    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(sample_json),
        stderr="",
    )

    info = probe_file("rotated_tag.mp4", ffprobe_path="ffprobe")
    assert info.rotation == 90
    assert info.display_width == 1080
    assert info.display_height == 1920


@patch("os.path.isfile", return_value=True)
@patch("os.path.getsize", return_value=2048)
@patch("video_converter.media.probe.subprocess.run")
def test_probe_file_missing_size_fallback(mock_run, mock_getsize, mock_isfile):
    """Test fallback to os.path.getsize when format size is absent."""
    sample_json = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "vp9",
                "width": 1280,
                "height": 720,
            }
        ],
        "format": {},
    }

    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(sample_json),
        stderr="",
    )

    info = probe_file("nofmt.webm", ffprobe_path="ffprobe")
    assert info.size_bytes == 2048
    assert info.codec_video == "vp9"


@patch("os.path.isfile", return_value=True)
@patch("video_converter.media.probe.subprocess.run")
def test_probe_file_ignore_attached_pictures(mock_run, mock_isfile):
    """Test that attached pictures (cover art / posters) are ignored when picking primary video stream."""
    sample_json = {
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "mjpeg",
                "width": 500,
                "height": 500,
                "disposition": {
                    "attached_pic": 1,
                },
            },
            {
                "index": 1,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "avg_frame_rate": "30/1",
                "duration": "60.0",
                "disposition": {
                    "attached_pic": 0,
                },
            },
            {
                "index": 2,
                "codec_type": "audio",
                "codec_name": "aac",
            },
        ],
        "format": {
            "duration": "60.0",
            "size": "5242880",
        },
    }

    mock_run.return_value = MagicMock(
        returncode=0,
        stdout=json.dumps(sample_json),
        stderr="",
    )

    info = probe_file("with_cover.mp4", ffprobe_path="/usr/bin/ffprobe")

    assert info.width == 1920
    assert info.height == 1080
    assert info.codec_video == "h264"
    assert info.codec_audio == "aac"
    assert info.has_audio is True


def test_probe_file_not_found():
    """Test probe_file raises FileNotFoundError for non-existent file."""
    with pytest.raises(FileNotFoundError, match="Media file not found"):
        probe_file("non_existent_file_xyz_123.mp4")


@patch("os.path.isfile", return_value=True)
@patch("video_converter.media.probe.find_ffprobe", return_value=None)
def test_probe_file_no_ffprobe(mock_find, mock_isfile):
    """Test probe_file raises FileNotFoundError if ffprobe binary is missing."""
    with pytest.raises(FileNotFoundError, match="ffprobe executable not found"):
        probe_file("video.mp4", ffprobe_path=None)


@patch("os.path.isfile", return_value=True)
@patch("video_converter.media.probe.subprocess.run")
def test_probe_file_execution_error(mock_run, mock_isfile):
    """Test ffprobe returning non-zero returncode."""
    mock_run.return_value = MagicMock(
        returncode=1,
        stdout="",
        stderr="Invalid data found when processing input",
    )

    with pytest.raises(RuntimeError, match="ffprobe failed"):
        probe_file("corrupt.mp4", ffprobe_path="ffprobe")


@patch("os.path.isfile", return_value=True)
@patch("video_converter.media.probe.subprocess.run")
def test_probe_file_invalid_json(mock_run, mock_isfile):
    """Test ffprobe returning invalid JSON string."""
    mock_run.return_value = MagicMock(
        returncode=0,
        stdout="not a json",
        stderr="",
    )

    with pytest.raises(ValueError, match="Failed to parse ffprobe JSON output"):
        probe_file("test.mp4", ffprobe_path="ffprobe")
