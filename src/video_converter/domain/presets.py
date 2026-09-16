from __future__ import annotations
from enum import Enum


class Preset(Enum):
    ORIGINAL = ("original", None, "Original")
    P480 = ("480p", 854, "480p (up to 854px)")
    P720 = ("720p", 1280, "720p (up to 1280px)")
    P1080 = ("1080p", 1920, "1080p (up to 1920px)")
    P2K = ("2k", 2560, "2K (up to 2560px)")
    P4K = ("4k", 3840, "4K (up to 3840px)")

    def __init__(self, preset_id: str, limit: int | None, display_name: str) -> None:
        self.preset_id = preset_id
        self.limit = limit
        self.display_name = display_name

    @property
    def id(self) -> str:
        return self.preset_id

    @classmethod
    def from_id(cls, preset_id: str) -> Preset:
        normalized = preset_id.strip().lower()
        for member in cls:
            if member.preset_id.lower() == normalized or member.name.lower() == normalized:
                return member
        return cls.ORIGINAL

    @classmethod
    def all_presets(cls) -> list[Preset]:
        return [cls.ORIGINAL, cls.P1080, cls.P2K, cls.P4K, cls.P720, cls.P480]
