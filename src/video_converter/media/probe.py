"""Media probing and metadata extraction using ffprobe."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from video_converter.domain.media_info import MediaInfo
from video_converter.media.binaries import find_ffprobe


def _parse_fps(rate_str: str | None) -> float:
    """Parse frame rate string like '30/1' or '29.97' or '24000/1001'."""
    if not rate_str or rate_str == "0/0":
        return 0.0
    try:
        if "/" in rate_str:
            num, den = rate_str.split("/", 1)
            denominator = float(den)
            if denominator == 0:
                return 0.0
            return float(num) / denominator
        return float(rate_str)
    except Exception:
        return 0.0


def probe_file(file_path: str, ffprobe_path: str | None = None) -> MediaInfo:
    """Probe a video/media file using ffprobe and return MediaInfo."""
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"Media file not found: {file_path}")

    probe_exe = ffprobe_path or find_ffprobe()
    if not probe_exe:
        raise FileNotFoundError("ffprobe executable not found")

    args = [
        probe_exe,
        "-v",
        "error",
        "-show_entries",
        "stream=index,codec_type,codec_name,width,height,duration,r_frame_rate,avg_frame_rate:stream_tags=rotate,creation_time:stream_disposition=:stream_side_data=rotation",
        "-show_entries",
        "format=duration,size,bit_rate",
        "-of",
        "json",
        file_path,
    ]

    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    result = subprocess.run(
        args,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        startupinfo=startupinfo,
    )

    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed with exit code {result.returncode}: {result.stderr}")

    try:
        data = json.loads(result.stdout)
    except Exception as err:
        raise ValueError(f"Failed to parse ffprobe JSON output: {err}") from err

    streams = data.get("streams", [])
    format_info = data.get("format", {})

    # Extract Video Stream Info
    width = 0
    height = 0
    codec_video = ""
    fps = 0.0
    rotation = 0
    video_stream_duration = 0.0

    # Extract Audio Stream Info
    has_audio = False
    codec_audio = ""

    for stream in streams:
        codec_type = stream.get("codec_type")
        disposition = stream.get("disposition", {})
        is_attached_pic = bool(disposition.get("attached_pic", 0))

        if codec_type == "video" and not is_attached_pic and width == 0 and height == 0:
            width = int(stream.get("width") or 0)
            height = int(stream.get("height") or 0)
            codec_video = stream.get("codec_name") or ""

            # Check FPS
            fps_r = _parse_fps(stream.get("r_frame_rate"))
            fps_avg = _parse_fps(stream.get("avg_frame_rate"))
            fps = fps_avg if fps_avg > 0 else fps_r

            # Check Rotation
            # 1. From side_data_list
            side_data_list = stream.get("side_data_list", [])
            for side_data in side_data_list:
                if "rotation" in side_data:
                    try:
                        rotation = int(float(side_data["rotation"]))
                    except Exception:
                        pass

            # 2. From stream tags rotate if rotation not yet set
            if rotation == 0:
                tags = stream.get("tags", {})
                if "rotate" in tags:
                    try:
                        rotation = int(float(tags["rotate"]))
                    except Exception:
                        pass

            if "duration" in stream:
                try:
                    video_stream_duration = float(stream["duration"])
                except Exception:
                    pass

        elif codec_type == "audio":
            has_audio = True
            if not codec_audio:
                codec_audio = stream.get("codec_name") or ""

    # Normalize rotation: positive modulo 360 (e.g. -90 -> 270)
    rotation = (rotation % 360 + 360) % 360

    # Compute display dimensions based on rotation
    if rotation in (90, 270):
        display_width = height
        display_height = width
    else:
        display_width = width
        display_height = height

    # Extract Duration
    duration_sec = 0.0
    if "duration" in format_info:
        try:
            duration_sec = float(format_info["duration"])
        except Exception:
            pass
    if duration_sec <= 0.0:
        duration_sec = video_stream_duration

    # Extract File Size
    size_bytes = 0
    if "size" in format_info:
        try:
            size_bytes = int(format_info["size"])
        except Exception:
            pass

    if size_bytes <= 0:
        try:
            size_bytes = os.path.getsize(file_path)
        except Exception:
            size_bytes = 0

    return MediaInfo(
        file_path=file_path,
        width=width,
        height=height,
        display_width=display_width,
        display_height=display_height,
        duration_sec=duration_sec,
        rotation=rotation,
        has_audio=has_audio,
        codec_video=codec_video,
        codec_audio=codec_audio,
        size_bytes=size_bytes,
        fps=fps,
    )
