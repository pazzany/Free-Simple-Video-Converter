from __future__ import annotations
import pytest
from video_converter.domain.presets import Preset
from video_converter.media.scaling import calculate_target_resolution, build_scale_filter


class TestPresets:
    def test_preset_properties(self):
        assert Preset.ORIGINAL.id == "original"
        assert Preset.ORIGINAL.limit is None
        assert Preset.P480.limit == 854
        assert Preset.P720.limit == 1280
        assert Preset.P1080.limit == 1920
        assert Preset.P2K.limit == 2560
        assert Preset.P4K.limit == 3840

    def test_from_id(self):
        assert Preset.from_id("1080p") == Preset.P1080
        assert Preset.from_id("4K") == Preset.P4K
        assert Preset.from_id("2k") == Preset.P2K
        assert Preset.from_id("720p") == Preset.P720
        assert Preset.from_id("480P") == Preset.P480
        assert Preset.from_id("original") == Preset.ORIGINAL
        assert Preset.from_id("unknown_value") == Preset.ORIGINAL


class TestScalingCalculation:
    @pytest.mark.parametrize(
        ("src_w", "src_h", "limit", "expected"),
        [
            # 4K downscales to 1080p
            (3840, 2160, 1920, (1920, 1080)),
            # 1920x1020 fits in 1920 limit -> keeps exact resolution
            (1920, 1020, 1920, (1920, 1020)),
            # 1280x720 is smaller than 1920 -> no upscaling!
            (1280, 720, 1920, (1280, 720)),
            # 840x480 is smaller than 1920 -> no upscaling!
            (840, 480, 1920, (840, 480)),
            # Vertical 4K (2160x3840) downscales by longest side (height) to 1080x1920
            (2160, 3840, 1920, (1080, 1920)),
            # Ultrawide 21:9 (2560x1080) downscales to (1920, 810)
            (2560, 1080, 1920, (1920, 810)),
            # Odd dimensions are truncated to even numbers (841x481 -> 840x480)
            (841, 481, 1920, (840, 480)),
            # Original preset (limit=None) preserves dimensions (even)
            (3840, 2160, None, (3840, 2160)),
            (1921, 1081, None, (1920, 1080)),
            # 4K preset limits
            (7680, 4320, 3840, (3840, 2160)),
        ],
    )
    def test_resolutions(self, src_w, src_h, limit, expected):
        target = calculate_target_resolution(src_w, src_h, limit)
        assert target == expected
        # Both must be even numbers
        assert target[0] % 2 == 0
        assert target[1] % 2 == 0

    def test_rotation_metadata(self):
        # Video is stored as 3840x2160 with 90 deg rotation (display is 2160x3840)
        target = calculate_target_resolution(3840, 2160, 1920, rotation=90)
        assert target == (1080, 1920)

    def test_build_scale_filter(self):
        filter_original = build_scale_filter(None)
        assert "scale=" in filter_original
        assert "trunc" in filter_original

        filter_1080 = build_scale_filter(1920)
        assert "min(iw,1920)" in filter_1080
        assert "min(ih,1920)" in filter_1080
        assert "force_original_aspect_ratio=decrease" in filter_1080
        assert "force_divisible_by=2" in filter_1080
