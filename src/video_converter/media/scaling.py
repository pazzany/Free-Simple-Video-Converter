from __future__ import annotations


def calculate_target_resolution(
    src_w: int,
    src_h: int,
    limit: int | None,
    rotation: int = 0,
) -> tuple[int, int]:
    """Calculate target dimensions preserving aspect ratio without upscaling.

    - If rotation is 90/270 (-90/-270), effective display orientation is swapped.
    - Longest side is compared against limit.
    - If limit is None or longest side <= limit: original resolution is kept (ensuring even dimensions).
    - If longest side > limit: scaled down to limit along the longest dimension.
    - Output dimensions are always even numbers >= 2.
    """
    if src_w <= 0 or src_h <= 0:
        return max(2, src_w - (src_w % 2)), max(2, src_h - (src_h % 2))

    is_rotated_90 = abs(rotation) % 180 in (90, 270)
    eff_w = src_h if is_rotated_90 else src_w
    eff_h = src_w if is_rotated_90 else src_h

    longest = max(eff_w, eff_h)

    if limit is None or longest <= limit:
        target_w = eff_w
        target_h = eff_h
    else:
        scale = limit / float(longest)
        target_w = int(round(eff_w * scale))
        target_h = int(round(eff_h * scale))

    # Ensure even dimensions (at least 2)
    target_w = max(2, target_w - (target_w % 2))
    target_h = max(2, target_h - (target_h % 2))

    return target_w, target_h


def build_scale_filter(limit: int | None) -> str:
    """Build FFmpeg scale video filter string.

    Ensures aspect ratio preservation, no upscaling beyond limit,
    and dimensions divisible by 2.
    """
    if limit is None:
        return "scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1"

    return (
        f"scale=w='min(iw,{limit})':h='min(ih,{limit})':"
        f"force_original_aspect_ratio=decrease:"
        f"force_divisible_by=2:flags=lanczos,setsar=1"
    )
