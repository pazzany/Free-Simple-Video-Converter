from __future__ import annotations
import os
import subprocess
import pytest

from video_converter.domain.encoders import EncoderType
from video_converter.domain.jobs import JobStatus
from video_converter.domain.presets import Preset
from video_converter.domain.settings import OutputMode
from video_converter.media.binaries import find_ffmpeg, find_ffprobe
from video_converter.media.command import build_ffmpeg_command
from video_converter.media.paths import get_temp_output_path, resolve_output_path
from video_converter.media.probe import probe_file
from video_converter.queue.controller import QueueController


@pytest.fixture(scope="module")
def ffmpeg_binaries():
    ffmpeg = find_ffmpeg()
    ffprobe = find_ffprobe()
    if not ffmpeg or not ffprobe:
        pytest.skip("ffmpeg or ffprobe not available in environment")
    return ffmpeg, ffprobe


def create_synthetic_video(
    output_path: str,
    width: int,
    height: int,
    duration: float = 0.5,
    has_audio: bool = True,
    ffmpeg_path: str = "ffmpeg",
) -> str:
    """Helper to generate tiny test videos using FFmpeg lavfi."""
    args = [
        ffmpeg_path,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=size={width}x{height}:rate=10:duration={duration}",
    ]
    if has_audio:
        args.extend(["-f", "lavfi", "-i", f"sine=frequency=1000:duration={duration}"])
        args.extend(["-c:a", "aac"])
    else:
        args.extend(["-an"])

    args.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", output_path])

    res = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"Failed to create synthetic video: {res.stderr}")
    return output_path


class TestConversionE2E:
    def test_e2e_4k_to_1080p_fit(self, ffmpeg_binaries, tmp_path):
        ffmpeg, ffprobe = ffmpeg_binaries
        src = str(tmp_path / "sample_4k.mp4")
        create_synthetic_video(src, 3840, 2160, duration=0.3, has_audio=True, ffmpeg_path=ffmpeg)

        target = resolve_output_path(src, OutputMode.SAME_DIR)
        temp_out = get_temp_output_path(target)

        cmd = build_ffmpeg_command(
            input_path=src,
            temp_output_path=temp_out,
            preset=Preset.P1080,
            encoder=EncoderType.LIBX264,
            crf=24,
            ffmpeg_path=ffmpeg,
        )

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert res.returncode == 0
        assert os.path.exists(temp_out)

        os.replace(temp_out, target)
        assert os.path.exists(target)

        info = probe_file(target, ffprobe_path=ffprobe)
        assert info.display_width == 1920
        assert info.display_height == 1080
        assert info.codec_video in ("h264", "libx264")
        assert info.has_audio is True

    def test_e2e_nonstandard_1920x1020_fit(self, ffmpeg_binaries, tmp_path):
        ffmpeg, ffprobe = ffmpeg_binaries
        src = str(tmp_path / "sample_1920x1020.mp4")
        create_synthetic_video(src, 1920, 1020, duration=0.3, has_audio=True, ffmpeg_path=ffmpeg)

        target = resolve_output_path(src, OutputMode.SAME_DIR)
        temp_out = get_temp_output_path(target)

        cmd = build_ffmpeg_command(
            input_path=src,
            temp_output_path=temp_out,
            preset=Preset.P1080,
            encoder=EncoderType.LIBX264,
            crf=24,
            ffmpeg_path=ffmpeg,
        )

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert res.returncode == 0

        os.replace(temp_out, target)
        info = probe_file(target, ffprobe_path=ffprobe)
        # Should retain exactly 1920x1020 without deformation or stretch
        assert info.display_width == 1920
        assert info.display_height == 1020

    def test_e2e_no_upscale_840x480(self, ffmpeg_binaries, tmp_path):
        ffmpeg, ffprobe = ffmpeg_binaries
        src = str(tmp_path / "sample_840x480.mp4")
        create_synthetic_video(src, 840, 480, duration=0.3, has_audio=False, ffmpeg_path=ffmpeg)

        target = resolve_output_path(src, OutputMode.SAME_DIR)
        temp_out = get_temp_output_path(target)

        cmd = build_ffmpeg_command(
            input_path=src,
            temp_output_path=temp_out,
            preset=Preset.P1080,
            encoder=EncoderType.LIBX264,
            crf=24,
            ffmpeg_path=ffmpeg,
        )

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert res.returncode == 0

        os.replace(temp_out, target)
        info = probe_file(target, ffprobe_path=ffprobe)
        # No upscaling to 1080p! Must remain 840x480
        assert info.display_width == 840
        assert info.display_height == 480

    def test_e2e_video_without_audio(self, ffmpeg_binaries, tmp_path):
        ffmpeg, ffprobe = ffmpeg_binaries
        src = str(tmp_path / "sample_no_audio.mp4")
        create_synthetic_video(src, 640, 360, duration=0.3, has_audio=False, ffmpeg_path=ffmpeg)

        target = resolve_output_path(src, OutputMode.SAME_DIR)
        temp_out = get_temp_output_path(target)

        cmd = build_ffmpeg_command(
            input_path=src,
            temp_output_path=temp_out,
            preset=Preset.P480,
            encoder=EncoderType.LIBX264,
            crf=24,
            ffmpeg_path=ffmpeg,
        )

        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        assert res.returncode == 0
        os.replace(temp_out, target)

        info = probe_file(target, ffprobe_path=ffprobe)
        assert info.display_width == 640
        assert info.display_height == 360
        assert info.has_audio is False

    def test_e2e_collision_avoidance(self, ffmpeg_binaries, tmp_path):
        ffmpeg, _ = ffmpeg_binaries
        src = str(tmp_path / "video.mp4")
        create_synthetic_video(src, 640, 360, duration=0.2, has_audio=True, ffmpeg_path=ffmpeg)

        out1 = resolve_output_path(src, OutputMode.SAME_DIR)
        # Create out1 on disk
        with open(out1, "wb") as f:
            f.write(b"existing file 1")

        # Resolving again must give -2
        out2 = resolve_output_path(src, OutputMode.SAME_DIR)
        assert out2.endswith("video-converted-2.mp4")
        with open(out2, "wb") as f:
            f.write(b"existing file 2")

        # Resolving again must give -3
        out3 = resolve_output_path(src, OutputMode.SAME_DIR)
        assert out3.endswith("video-converted-3.mp4")

    def test_e2e_queue_controller_batch_execution(self, qapp, ffmpeg_binaries, tmp_path, qtbot):
        ffmpeg, ffprobe = ffmpeg_binaries
        f1 = str(tmp_path / "clip1.mp4")
        f2 = str(tmp_path / "clip2.mp4")
        create_synthetic_video(f1, 1280, 720, duration=0.2, has_audio=True, ffmpeg_path=ffmpeg)
        create_synthetic_video(f2, 840, 480, duration=0.2, has_audio=False, ffmpeg_path=ffmpeg)

        controller = QueueController()
        jobs = controller.add_files(
            paths=[f1, f2],
            preset=Preset.P1080,
            crf=26,
            encoder=EncoderType.LIBX264,
            output_mode=OutputMode.SAME_DIR,
        )
        assert len(jobs) == 2

        with qtbot.waitSignal(controller.queue_state_changed, timeout=15000):
            controller.start()

        # Wait until queue finishes all items
        qtbot.waitUntil(lambda: not controller.is_running, timeout=15000)

        for job in controller.jobs:
            assert job.status == JobStatus.COMPLETED
            assert os.path.exists(job.output_path)
            # Verify temp file is cleaned up
            assert not os.path.exists(job.temp_path)
