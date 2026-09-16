"""Unit tests for FFmpeg conversion command assembly."""

from __future__ import annotations

from video_converter.domain.encoders import EncoderType
from video_converter.domain.presets import Preset
from video_converter.media.command import build_ffmpeg_command


def test_build_ffmpeg_command_libx264_1080p():
    cmd = build_ffmpeg_command(
        input_path="input.mov",
        temp_output_path="out.part.mp4",
        preset=Preset.P1080,
        encoder=EncoderType.LIBX264,
        crf=23,
        ffmpeg_path="ffmpeg.exe",
    )
    assert cmd[0] == "ffmpeg.exe"
    assert "-i" in cmd
    assert cmd[cmd.index("-i") + 1] == "input.mov"
    assert "-vf" in cmd
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert "min(iw,1920)" in vf_arg
    assert "-pix_fmt" in cmd
    assert cmd[cmd.index("-pix_fmt") + 1] == "yuv420p"
    assert "-map" in cmd
    assert "0:v:0" in cmd
    assert "0:a?" in cmd
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "libx264"
    assert "-crf" in cmd
    assert cmd[cmd.index("-crf") + 1] == "23"
    assert "-c:a" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "aac"
    assert "-b:a" in cmd
    assert cmd[cmd.index("-b:a") + 1] == "192k"
    assert "-y" in cmd
    assert cmd[-1] == "out.part.mp4"


def test_build_ffmpeg_command_nvenc_original():
    cmd = build_ffmpeg_command(
        input_path="input.mp4",
        temp_output_path="out.part.mp4",
        preset=Preset.ORIGINAL,
        encoder=EncoderType.NVENC,
        crf=26,
        ffmpeg_path="C:\\tools\\ffmpeg.exe",
    )
    assert cmd[0] == "C:\\tools\\ffmpeg.exe"
    vf_arg = cmd[cmd.index("-vf") + 1]
    assert "trunc(iw/2)*2" in vf_arg
    assert cmd[cmd.index("-c:v") + 1] == "h264_nvenc"
    assert "-cq" in cmd
    assert cmd[cmd.index("-cq") + 1] == "26"
    assert "-preset" in cmd
    assert cmd[cmd.index("-preset") + 1] == "medium"


def test_build_ffmpeg_command_qsv_720p():
    cmd = build_ffmpeg_command(
        input_path="test.mkv",
        temp_output_path="temp.mp4",
        preset=Preset.P720,
        encoder=EncoderType.QSV,
        crf=18,
    )
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "h264_qsv"
    assert "-global_quality" in cmd
    assert cmd[cmd.index("-global_quality") + 1] == "18"


def test_build_ffmpeg_command_amf_4k():
    cmd = build_ffmpeg_command(
        input_path="test.avi",
        temp_output_path="temp.mp4",
        preset=Preset.P4K,
        encoder=EncoderType.AMF,
        crf=22,
    )
    assert "-c:v" in cmd
    assert cmd[cmd.index("-c:v") + 1] == "h264_amf"
    assert "-qp_p" in cmd
    assert cmd[cmd.index("-qp_p") + 1] == "22"
    assert "-qp_i" in cmd
    assert cmd[cmd.index("-qp_i") + 1] == "22"


def test_build_ffmpeg_command_custom_fps_30():
    """Verify -r 30 is inserted when fps=30 is specified."""
    cmd = build_ffmpeg_command(
        input_path="input.mp4",
        temp_output_path="out.part.mp4",
        preset=Preset.P1080,
        encoder=EncoderType.LIBX264,
        crf=24,
        ffmpeg_path="ffmpeg.exe",
        fps=30,
    )
    assert "-r" in cmd
    r_idx = cmd.index("-r")
    assert cmd[r_idx + 1] == "30"
    # -r must come before -y
    y_idx = cmd.index("-y")
    assert r_idx < y_idx
    # default audio bitrate still 192k
    assert cmd[cmd.index("-b:a") + 1] == "192k"


def test_build_ffmpeg_command_custom_fps_24():
    """Verify -r 24 is inserted when fps=24."""
    cmd = build_ffmpeg_command(
        input_path="input.mp4",
        temp_output_path="out.part.mp4",
        preset=Preset.P720,
        encoder=EncoderType.LIBX264,
        crf=20,
        ffmpeg_path="ffmpeg.exe",
        fps=24,
    )
    assert "-r" in cmd
    assert cmd[cmd.index("-r") + 1] == "24"


def test_build_ffmpeg_command_fps_original_no_r_flag():
    """Verify no -r flag when fps=None (original framerate)."""
    cmd = build_ffmpeg_command(
        input_path="input.mp4",
        temp_output_path="out.part.mp4",
        preset=Preset.P1080,
        encoder=EncoderType.LIBX264,
        crf=24,
        ffmpeg_path="ffmpeg.exe",
        fps=None,
    )
    assert "-r" not in cmd


def test_build_ffmpeg_command_custom_audio_bitrate_128k():
    """Verify custom audio bitrate replaces default 192k."""
    cmd = build_ffmpeg_command(
        input_path="input.mp4",
        temp_output_path="out.part.mp4",
        preset=Preset.P1080,
        encoder=EncoderType.LIBX264,
        crf=24,
        ffmpeg_path="ffmpeg.exe",
        audio_bitrate="128k",
    )
    assert cmd[cmd.index("-b:a") + 1] == "128k"
    assert "-r" not in cmd  # fps not specified


def test_build_ffmpeg_command_low_audio_bitrate_32k():
    """Verify 32k audio bitrate for voice-only content."""
    cmd = build_ffmpeg_command(
        input_path="input.mp4",
        temp_output_path="out.part.mp4",
        preset=Preset.P480,
        encoder=EncoderType.LIBX264,
        crf=28,
        ffmpeg_path="ffmpeg.exe",
        audio_bitrate="32k",
    )
    assert cmd[cmd.index("-b:a") + 1] == "32k"


def test_build_ffmpeg_command_high_audio_bitrate_320k():
    """Verify 320k audio bitrate."""
    cmd = build_ffmpeg_command(
        input_path="input.mp4",
        temp_output_path="out.part.mp4",
        preset=Preset.P4K,
        encoder=EncoderType.LIBX264,
        crf=18,
        ffmpeg_path="ffmpeg.exe",
        audio_bitrate="320k",
    )
    assert cmd[cmd.index("-b:a") + 1] == "320k"


def test_build_ffmpeg_command_fps_and_audio_bitrate_combined():
    """Verify both fps and audio_bitrate can be set together."""
    cmd = build_ffmpeg_command(
        input_path="input.mp4",
        temp_output_path="out.part.mp4",
        preset=Preset.P720,
        encoder=EncoderType.NVENC,
        crf=26,
        ffmpeg_path="ffmpeg.exe",
        fps=60,
        audio_bitrate="64k",
    )
    # FPS
    assert "-r" in cmd
    assert cmd[cmd.index("-r") + 1] == "60"
    # Audio bitrate
    assert cmd[cmd.index("-b:a") + 1] == "64k"
    # Encoder
    assert cmd[cmd.index("-c:v") + 1] == "h264_nvenc"
    # Order: -r before -y, -y before output
    r_idx = cmd.index("-r")
    y_idx = cmd.index("-y")
    assert r_idx < y_idx
    assert cmd[-1] == "out.part.mp4"
