"""Media information domain model."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class MediaInfo:
    """Detailed metadata about a media file."""

    file_path: str
    width: int = 0
    height: int = 0
    display_width: int = 0
    display_height: int = 0
    duration_sec: float = 0.0
    rotation: int = 0
    has_audio: bool = False
    codec_video: str = ""
    codec_audio: str = ""
    size_bytes: int = 0
    fps: float = 0.0

    @property
    def aspect_ratio_str(self) -> str:
        """Return human-readable aspect ratio based on display dimensions (e.g. '16:9')."""
        w, h = self.display_width, self.display_height
        if w <= 0 or h <= 0:
            return ""

        # Common standard aspect ratios
        ratio = w / h
        common_ratios = [
            (16 / 9, "16:9"),
            (9 / 16, "9:16"),
            (4 / 3, "4:3"),
            (3 / 4, "3:4"),
            (1 / 1, "1:1"),
            (21 / 9, "21:9"),
            (9 / 21, "9:21"),
            (3 / 2, "3:2"),
            (2 / 3, "2:3"),
            (5 / 4, "5:4"),
            (4 / 5, "4:5"),
        ]

        for std_val, std_str in common_ratios:
            if math.isclose(ratio, std_val, rel_tol=0.01):
                return std_str

        # Reduce using gcd
        g = math.gcd(w, h)
        if g > 1:
            rw, rh = w // g, h // g
            # If reduced numbers are small enough, use them
            if rw <= 100 and rh <= 100:
                return f"{rw}:{rh}"

        return f"{ratio:.2f}:1"

    def formatted_duration(self) -> str:
        """Format duration in HH:MM:SS or MM:SS."""
        if self.duration_sec <= 0:
            return "00:00"

        total_seconds = int(round(self.duration_sec))
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        return f"{minutes:02d}:{seconds:02d}"

    def formatted_size(self) -> str:
        """Format file size into human-readable bytes (B, KB, MB, GB)."""
        if self.size_bytes <= 0:
            return "0 B"

        size = float(self.size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0 or unit == "TB":
                if unit == "B":
                    return f"{int(size)} B"
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"
