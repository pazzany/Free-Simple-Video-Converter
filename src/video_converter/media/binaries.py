"""FFmpeg and FFprobe binary discovery and inspection."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class BinaryInfo:
    """Information about discovered media binaries."""

    ffmpeg_path: str
    ffprobe_path: str
    version: str = ""


def _candidate_directories(custom_dir: str | None = None) -> list[Path]:
    """Build an ordered list of directories to search for binaries."""
    candidates: list[Path] = []

    if custom_dir:
        candidates.append(Path(custom_dir))

    # Frozen PyInstaller bundle directory (sys._MEIPASS)
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass_dir = Path(getattr(sys, "_MEIPASS"))
        candidates.append(meipass_dir)
        candidates.append(meipass_dir / "bin")

    # Beside current running executable
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).parent
        candidates.append(exe_dir)
        candidates.append(exe_dir / "bin")

    # Beside current script / package location
    script_dir = Path(__file__).resolve().parent
    candidates.append(script_dir)
    # Walk up to find potential project roots / bin folders
    for parent in script_dir.parents:
        candidates.append(parent)
        candidates.append(parent / "bin")

    # Current working directory and its bin subdirectory
    cwd = Path.cwd()
    candidates.append(cwd)
    candidates.append(cwd / "bin")

    # Deduplicate while preserving order
    seen: set[Path] = set()
    unique_candidates: list[Path] = []
    for d in candidates:
        try:
            resolved = d.resolve()
        except Exception:
            resolved = d
        if resolved not in seen:
            seen.add(resolved)
            unique_candidates.append(d)

    return unique_candidates


def find_ffmpeg(custom_dir: str | None = None) -> str | None:
    """Find ffmpeg binary path.

    Searches in custom_dir, adjacent application directories, and system PATH.
    """
    exec_names = ["ffmpeg.exe", "ffmpeg"] if sys.platform == "win32" else ["ffmpeg", "ffmpeg.exe"]

    # 1. Search candidate directories
    for directory in _candidate_directories(custom_dir):
        for name in exec_names:
            candidate = directory / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())

    # 2. Search system PATH
    path_hit = shutil.which("ffmpeg")
    if path_hit:
        return str(Path(path_hit).resolve())

    return None


def find_ffprobe(custom_dir: str | None = None) -> str | None:
    """Find ffprobe binary path.

    Searches in custom_dir, adjacent application directories, and system PATH.
    """
    exec_names = ["ffprobe.exe", "ffprobe"] if sys.platform == "win32" else ["ffprobe", "ffprobe.exe"]

    # 1. Search candidate directories
    for directory in _candidate_directories(custom_dir):
        for name in exec_names:
            candidate = directory / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate.resolve())

    # 2. Search system PATH
    path_hit = shutil.which("ffprobe")
    if path_hit:
        return str(Path(path_hit).resolve())

    return None


def get_ffmpeg_version(ffmpeg_path: str) -> str:
    """Extract version string from ffmpeg binary."""
    try:
        startupinfo = None
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        result = subprocess.run(
            [ffmpeg_path, "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=5,
            startupinfo=startupinfo,
            check=False,
        )
        if result.returncode == 0 and result.stdout:
            # First line usually contains "ffmpeg version X.Y.Z ..."
            first_line = result.stdout.strip().splitlines()[0]
            return first_line.strip()
    except Exception:
        pass
    return ""


def get_binaries(custom_dir: str | None = None) -> BinaryInfo:
    """Discover ffmpeg and ffprobe and return BinaryInfo."""
    ffmpeg = find_ffmpeg(custom_dir) or ""
    ffprobe = find_ffprobe(custom_dir) or ""
    version = get_ffmpeg_version(ffmpeg) if ffmpeg else ""
    return BinaryInfo(ffmpeg_path=ffmpeg, ffprobe_path=ffprobe, version=version)
