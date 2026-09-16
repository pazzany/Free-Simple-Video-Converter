"""Application settings and output mode domain representations."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path

from video_converter.domain.encoders import EncoderType
from video_converter.domain.presets import Preset


class OutputMode(Enum):
    """Output directory selection mode."""

    SAME_DIR = ("same_dir", "Same directory as source")
    CUSTOM_DIR = ("custom_dir", "Custom directory")

    def __init__(self, mode_id: str, display_name: str) -> None:
        self.mode_id = mode_id
        self.display_name = display_name

    @property
    def id(self) -> str:
        return self.mode_id

    @classmethod
    def from_id(cls, val: str) -> OutputMode:
        val_clean = val.strip().lower()
        for member in cls:
            if member.mode_id.lower() == val_clean or member.name.lower() == val_clean:
                return member
        return cls.SAME_DIR


@dataclass
class AppSettings:
    """User application settings dataclass."""

    language: str = "en"
    output_mode: OutputMode = OutputMode.SAME_DIR
    custom_output_dir: str = ""
    preset: Preset = Preset.P1080
    crf: int = 24
    encoder: EncoderType = EncoderType.AUTO
    target_fps: int | None = None
    audio_bitrate: str = "192k"

    def to_dict(self) -> dict:
        return {
            "language": self.language,
            "output_mode": self.output_mode.mode_id,
            "custom_output_dir": self.custom_output_dir,
            "preset": self.preset.preset_id,
            "crf": self.crf,
            "encoder": self.encoder.codec_name,
            "target_fps": self.target_fps,
            "audio_bitrate": self.audio_bitrate,
        }

    @classmethod
    def from_dict(cls, d: dict) -> AppSettings:
        language = d.get("language", "en")
        output_mode = OutputMode.from_id(d.get("output_mode", "same_dir"))
        custom_output_dir = d.get("custom_output_dir", "")
        preset = Preset.from_id(d.get("preset", "1080p"))
        crf_raw = d.get("crf", 24)
        try:
            crf = int(crf_raw)
        except (ValueError, TypeError):
            crf = 24

        encoder_raw = d.get("encoder", "auto")
        try:
            encoder = EncoderType.from_codec_name(encoder_raw)
        except ValueError:
            encoder = EncoderType.AUTO

        target_fps_raw = d.get("target_fps")
        try:
            target_fps = int(target_fps_raw) if target_fps_raw is not None else None
        except (ValueError, TypeError):
            target_fps = None
        audio_bitrate = str(d.get("audio_bitrate", "192k"))

        return cls(
            language=language,
            output_mode=output_mode,
            custom_output_dir=custom_output_dir,
            preset=preset,
            crf=crf,
            encoder=encoder,
            target_fps=target_fps,
            audio_bitrate=audio_bitrate,
        )

    def save_to_file(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)

    @classmethod
    def load_from_file(cls, path: str | Path) -> AppSettings:
        target = Path(path)
        if not target.is_file():
            return cls()
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return cls.from_dict(data)
        except Exception:
            pass
        return cls()
