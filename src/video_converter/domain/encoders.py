"""Video encoder types and domain representations."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class EncoderProbeResult:
    """Structured result of probing an encoder candidate."""

    encoder: EncoderType
    available: bool
    stderr: str = ""
    reason: str = ""


@dataclass(frozen=True)
class EncoderSelectionResult:
    """Structured outcome of encoder selection containing candidate probe attempts."""

    selected_encoder: EncoderType | None
    attempts: tuple[EncoderProbeResult, ...] = ()


class EncoderType(Enum):
    """Supported video encoder types with codec and display names."""

    AUTO = ("auto", "Auto (GPU / CPU)")
    NVENC = ("h264_nvenc", "NVIDIA NVENC")
    QSV = ("h264_qsv", "Intel QuickSync")
    AMF = ("h264_amf", "AMD AMF")
    LIBX264 = ("libx264", "CPU (libx264)")

    def __init__(self, codec_name: str, display_name: str) -> None:
        self.codec_name = codec_name
        self.display_name = display_name

    @property
    def is_hardware(self) -> bool:
        """Return True if this encoder is hardware-accelerated."""
        return self in (EncoderType.NVENC, EncoderType.QSV, EncoderType.AMF)

    @classmethod
    def from_codec_name(cls, val: str) -> EncoderType:
        """Resolve EncoderType from codec string or enum name."""
        val_clean = val.strip().lower()
        for item in cls:
            if item.codec_name.lower() == val_clean or item.name.lower() == val_clean:
                return item
        raise ValueError(f"Unknown encoder codec name: {val!r}")

    @classmethod
    def all_options(cls) -> list[EncoderType]:
        """Return all available EncoderType options."""
        return list(cls)
