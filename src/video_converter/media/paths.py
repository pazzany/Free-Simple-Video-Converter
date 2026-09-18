"""File paths and output collision resolution logic."""

from __future__ import annotations

import os
from pathlib import Path

from video_converter.domain.settings import OutputMode

SUPPORTED_VIDEO_EXTENSIONS: frozenset[str] = frozenset(
    [
        ".mp4",
        ".mpg",
        ".mpeg",
        ".mkv",
        ".avi",
        ".mov",
        ".wmv",
        ".asf",
        ".wm",
        ".wma",
        ".flv",
        ".webm",
        ".m4v",
        ".ts",
        ".mts",
        ".m2ts",
        ".m2t",
        ".m2v",
        ".3gp",
        ".vob",
        ".ogv",
    ]
)


def resolve_output_path(
    input_path: str,
    mode: OutputMode = OutputMode.SAME_DIR,
    custom_dir: str | None = None,
    suffix: str = "-converted",
    ext: str = ".mp4",
) -> str:
    """Determine final non-colliding output path for video conversion.

    Args:
        input_path: Source video path.
        mode: OutputMode (SAME_DIR or CUSTOM_DIR).
        custom_dir: Target directory when CUSTOM_DIR mode is selected.
        suffix: Suffix appended to the stem.
        ext: Output file extension (including leading dot).

    Returns:
        Guaranteed non-colliding absolute file path.
    """
    abs_input = os.path.abspath(input_path)
    if mode == OutputMode.CUSTOM_DIR and custom_dir:
        target_dir = os.path.abspath(custom_dir)
    else:
        target_dir = os.path.dirname(abs_input)

    stem = Path(abs_input).stem
    if not ext.startswith("."):
        ext = f".{ext}"

    candidate_name = f"{stem}{suffix}{ext}"
    candidate_path = os.path.join(target_dir, candidate_name)

    if not os.path.exists(candidate_path):
        return candidate_path

    # Collision loop: -2, -3, ...
    i = 2
    while True:
        candidate_name = f"{stem}{suffix}-{i}{ext}"
        candidate_path = os.path.join(target_dir, candidate_name)
        if not os.path.exists(candidate_path):
            return candidate_path
        i += 1


def get_temp_output_path(target_path: str) -> str:
    """Return temporary output file path located in the same directory."""
    abs_path = os.path.abspath(target_path)
    dirname = os.path.dirname(abs_path)
    basename = os.path.basename(abs_path)
    return os.path.join(dirname, f".{basename}.part.mp4")


def collect_video_files(paths: list[str], recursive: bool = True) -> list[str]:
    """Scan and collect valid video files from a list of paths (files or directories).

    Args:
        paths: List of input paths (files or folders).
        recursive: Whether to recursively scan subdirectories.

    Returns:
        List of unique absolute paths to video files, preserving discovery order.
    """
    collected: list[str] = []
    seen: set[str] = set()

    def add_file(f_path: str) -> None:
        p = Path(f_path).resolve()
        if p.is_file() and p.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
            str_path = str(p)
            if str_path not in seen:
                seen.add(str_path)
                collected.append(str_path)

    for item in paths:
        path_obj = Path(item)
        if not path_obj.exists():
            continue

        if path_obj.is_file():
            add_file(str(path_obj))
        elif path_obj.is_dir():
            if recursive:
                for root, _, files in os.walk(str(path_obj)):
                    for fname in sorted(files):
                        add_file(os.path.join(root, fname))
            else:
                for child in sorted(path_obj.iterdir()):
                    if child.is_file():
                        add_file(str(child))

    return collected
