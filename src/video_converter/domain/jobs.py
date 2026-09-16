from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import os
import uuid

from video_converter.domain.encoders import EncoderType
from video_converter.domain.media_info import MediaInfo
from video_converter.domain.presets import Preset


class JobStatus(Enum):
    PENDING = "pending"
    PROBING = "probing"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class ConversionJob:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    source_path: str = ""
    output_path: str = ""
    temp_path: str = ""
    media_info: MediaInfo | None = None
    target_width: int = 0
    target_height: int = 0
    preset: Preset = Preset.P1080
    crf: int = 24
    encoder: EncoderType = EncoderType.AUTO
    target_fps: int | None = None        # None means "original" (no -r flag)
    audio_bitrate: str = "192k"          # e.g. "128k", "96k", "64k", "32k", "256k", "320k"
    actual_encoder: EncoderType = EncoderType.LIBX264
    status: JobStatus = JobStatus.PENDING
    progress: float = 0.0
    speed: str = ""
    fps: float = 0.0
    eta_str: str = ""
    error_message: str = ""
    output_size_bytes: int = 0
    log_lines: list[str] = field(default_factory=list)
    fallback_attempted: bool = False

    @property
    def source_filename(self) -> str:
        return os.path.basename(self.source_path)

    @property
    def source_resolution_str(self) -> str:
        if not self.media_info or self.media_info.width == 0:
            return "—"
        return f"{self.media_info.display_width}x{self.media_info.display_height}"

    @property
    def target_resolution_str(self) -> str:
        if self.target_width == 0 or self.target_height == 0:
            return "—"
        return f"{self.target_width}x{self.target_height}"

    @property
    def duration_str(self) -> str:
        if not self.media_info:
            return "—"
        return self.media_info.formatted_duration()

    @property
    def size_str(self) -> str:
        if not self.media_info:
            return "—"
        return self.media_info.formatted_size()

    @property
    def output_size_str(self) -> str:
        if self.output_size_bytes <= 0:
            return ""
        size = float(self.output_size_bytes)
        for unit in ["B", "KB", "MB", "GB", "TB"]:
            if size < 1024.0 or unit == "TB":
                if unit == "B":
                    return f"{int(size)} B"
                return f"{size:.2f} {unit}"
            size /= 1024.0
        return f"{size:.2f} TB"

    @property
    def is_active(self) -> bool:
        return self.status in (JobStatus.PROBING, JobStatus.RUNNING)

    @property
    def is_finished(self) -> bool:
        return self.status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED)
