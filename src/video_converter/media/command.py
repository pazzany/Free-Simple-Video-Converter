"""FFmpeg conversion command construction."""

from __future__ import annotations

from video_converter.domain.encoders import EncoderType
from video_converter.domain.presets import Preset
from video_converter.media.binaries import find_ffmpeg
from video_converter.media.encoders import get_encoder_args
from video_converter.media.scaling import build_scale_filter


def build_ffmpeg_command(
    input_path: str,
    temp_output_path: str,
    preset: Preset,
    encoder: EncoderType,
    crf: int = 24,
    ffmpeg_path: str | None = None,
    fps: int | None = None,
    audio_bitrate: str = "192k",
) -> list[str]:
    """Build command argument list for FFmpeg transcoding.

    Args:
        input_path: Input media file path.
        temp_output_path: Destination temporary file path.
        preset: Selected resolution preset.
        encoder: Selected video encoder.
        crf: Quality parameter value.
        ffmpeg_path: Explicit path to ffmpeg executable, or None to auto-find.
        fps: Target frame rate, or None to keep original frame rate.
        audio_bitrate: Target audio bitrate string (e.g., '192k').

    Returns:
        List of command strings ready for subprocess execution.
    """
    binary = ffmpeg_path or find_ffmpeg() or "ffmpeg"
    scale_filter = build_scale_filter(preset.limit)
    enc_args = get_encoder_args(encoder, crf=crf)

    cmd = [
        binary,
        "-v",
        "warning",
        "-stats_period",
        "0.5",
        "-progress",
        "pipe:1",
        "-nostats",
        "-i",
        input_path,
        "-vf",
        scale_filter,
        "-pix_fmt",
        "yuv420p",
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
        *enc_args,
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-y",
        temp_output_path,
    ]

    # Insert FPS limit if specified
    if fps is not None:
        # Insert -r <fps> before -y
        y_idx = cmd.index("-y")
        cmd[y_idx:y_idx] = ["-r", str(fps)]

    return cmd
