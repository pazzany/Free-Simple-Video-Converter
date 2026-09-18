"""Unit tests for settings domain model and paths module."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from video_converter.domain.encoders import EncoderType
from video_converter.domain.presets import Preset
from video_converter.domain.settings import AppSettings, OutputMode
from video_converter.media.paths import (
    SUPPORTED_VIDEO_EXTENSIONS,
    collect_video_files,
    get_temp_output_path,
    resolve_output_path,
)


def test_output_mode_enum():
    assert OutputMode.SAME_DIR.mode_id == "same_dir"
    assert OutputMode.CUSTOM_DIR.mode_id == "custom_dir"
    assert OutputMode.from_id("same_dir") == OutputMode.SAME_DIR
    assert OutputMode.from_id("custom_dir") == OutputMode.CUSTOM_DIR
    assert OutputMode.from_id("unknown") == OutputMode.SAME_DIR


def test_app_settings_serialization(tmp_path: Path):
    settings = AppSettings(
        language="en",
        output_mode=OutputMode.CUSTOM_DIR,
        custom_output_dir=str(tmp_path / "out"),
        preset=Preset.P720,
        crf=20,
        encoder=EncoderType.NVENC,
        target_fps=60,
        audio_bitrate="320k",
    )
    d = settings.to_dict()
    assert d["language"] == "en"
    assert d["output_mode"] == "custom_dir"
    assert d["custom_output_dir"] == str(tmp_path / "out")
    assert d["preset"] == "720p"
    assert d["crf"] == 20
    assert d["encoder"] == "h264_nvenc"
    assert d["target_fps"] == 60
    assert d["audio_bitrate"] == "320k"

    # From dict
    restored = AppSettings.from_dict(d)
    assert restored.language == "en"
    assert restored.output_mode == OutputMode.CUSTOM_DIR
    assert restored.preset == Preset.P720
    assert restored.crf == 20
    assert restored.encoder == EncoderType.NVENC
    assert restored.target_fps == 60
    assert restored.audio_bitrate == "320k"

    # Save to file and load
    file_path = tmp_path / "config.json"
    settings.save_to_file(file_path)
    assert file_path.is_file()

    loaded = AppSettings.load_from_file(file_path)
    assert loaded.language == "en"
    assert loaded.preset == Preset.P720
    assert loaded.encoder == EncoderType.NVENC
    assert loaded.target_fps == 60
    assert loaded.audio_bitrate == "320k"

    # Load non-existent file default
    default_loaded = AppSettings.load_from_file(tmp_path / "non_existent.json")
    assert default_loaded.language == "en"
    assert default_loaded.output_mode == OutputMode.SAME_DIR
    assert default_loaded.target_fps is None
    assert default_loaded.audio_bitrate == "192k"


def test_resolve_output_path_single_file(tmp_path: Path):
    input_file = tmp_path / "my_video.avi"
    input_file.write_text("dummy")

    resolved = resolve_output_path(str(input_file))
    expected = tmp_path / "my_video-converted.mp4"
    assert Path(resolved) == expected.resolve()


def test_resolve_output_path_collision_avoidance(tmp_path: Path):
    input_file = tmp_path / "video.mp4"
    input_file.write_text("dummy")

    # Create collision files
    (tmp_path / "video-converted.mp4").write_text("first")
    (tmp_path / "video-converted-2.mp4").write_text("second")

    resolved = resolve_output_path(str(input_file))
    expected = tmp_path / "video-converted-3.mp4"
    assert Path(resolved) == expected.resolve()


def test_resolve_output_path_custom_dir(tmp_path: Path):
    in_dir = tmp_path / "input"
    out_dir = tmp_path / "custom_out"
    in_dir.mkdir()
    out_dir.mkdir()

    input_file = in_dir / "sample.mkv"
    input_file.write_text("dummy")

    resolved = resolve_output_path(
        str(input_file), mode=OutputMode.CUSTOM_DIR, custom_dir=str(out_dir)
    )
    expected = out_dir / "sample-converted.mp4"
    assert Path(resolved) == expected.resolve()


def test_get_temp_output_path(tmp_path: Path):
    target = tmp_path / "final.mp4"
    temp = get_temp_output_path(str(target))
    assert Path(temp).parent == tmp_path
    assert Path(temp).name == ".final.mp4.part.mp4"


def test_collect_video_files(tmp_path: Path):
    # Setup test file tree
    v1 = tmp_path / "vid1.mp4"
    v2 = tmp_path / "vid2.MKV"
    txt = tmp_path / "notes.txt"
    sub = tmp_path / "nested"
    sub.mkdir()
    v3 = sub / "vid3.mov"
    img = sub / "cover.jpg"

    v1.write_text("1")
    v2.write_text("2")
    txt.write_text("txt")
    v3.write_text("3")
    img.write_text("img")

    # Test single files mixed with text
    files = collect_video_files([str(v1), str(txt), str(v2)])
    assert len(files) == 2
    assert str(v1.resolve()) in files
    assert str(v2.resolve()) in files
    assert str(txt.resolve()) not in files

    # Test recursive directory scanning
    dir_files = collect_video_files([str(tmp_path)], recursive=True)
    assert len(dir_files) == 3
    assert str(v1.resolve()) in dir_files
    assert str(v2.resolve()) in dir_files
    assert str(v3.resolve()) in dir_files

    # Test non-recursive directory scanning
    non_rec_files = collect_video_files([str(tmp_path)], recursive=False)
    assert len(non_rec_files) == 2
    assert str(v1.resolve()) in non_rec_files
    assert str(v2.resolve()) in non_rec_files
    assert str(v3.resolve()) not in non_rec_files

    # Test deduplication
    dup_files = collect_video_files([str(v1), str(v1), str(tmp_path)], recursive=True)
    assert len(dup_files) == 3
    assert dup_files[0] == str(v1.resolve())


@pytest.mark.parametrize(
    "extension",
    [".asf", ".wm", ".wma", ".ASF", ".WmA", ".mpg", ".mpeg", ".MPG", ".m2t", ".m2v"],
)
def test_collect_video_files_accepts_windows_media_inputs(tmp_path: Path, extension: str):
    source = tmp_path / f"source{extension}"
    source.write_bytes(b"fixture")

    assert collect_video_files([str(source)]) == [str(source.resolve())]


def test_collect_video_files_finds_windows_media_inputs_in_folder(tmp_path: Path):
    top_level = [tmp_path / "a.asf", tmp_path / "b.wm"]
    nested = tmp_path / "nested" / "c.wma"
    for path in [*top_level, nested]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")

    collected = collect_video_files([str(tmp_path)])

    assert set(collected) == {str(path.resolve()) for path in [*top_level, nested]}
