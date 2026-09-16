"""Build script to create a single-file standalone Windows executable using PyInstaller."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
BIN_DIR = ROOT_DIR / "bin"
DIST_DIR = ROOT_DIR / "dist"
BUILD_DIR = ROOT_DIR / "build"
PACKAGING_DIR = ROOT_DIR / "packaging"
MANIFEST_PATH = PACKAGING_DIR / "ffmpeg_artifact_manifest.json"
ENTRY_POINT = SRC_DIR / "video_converter" / "main.py"
ICON_PATH = ROOT_DIR / "assets" / "icon.ico"
FFMPEG_PATH = BIN_DIR / "ffmpeg.exe"
FFPROBE_PATH = BIN_DIR / "ffprobe.exe"
APP_NAME = "FreeSimpleVideoConverter"

SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_BINARIES = ("ffmpeg.exe", "ffprobe.exe")


class ArtifactValidationError(RuntimeError):
    """Raised when bundled media binaries fail identity verification."""


def load_artifact_manifest(manifest_path: Path) -> dict[str, Any]:
    """Load canonical artifact manifest from disk."""
    if not manifest_path.is_file():
        raise ArtifactValidationError(f"Packaging manifest not found: {manifest_path}")
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        raise ArtifactValidationError(f"Failed to read packaging manifest: {exc}") from exc


def compute_sha256(file_path: Path) -> str:
    """Compute lowercase SHA-256 hash for a given file."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def get_binary_version(binary_path: Path) -> str:
    """Extract first line of version output for ffmpeg/ffprobe executable."""
    try:
        cmd = [str(binary_path), "-version"]
        flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            creationflags=flags,
            timeout=10,
        )
        if result.returncode == 0 and result.stdout:
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return ""


def validate_binary_artifacts(bin_dir: Path, manifest_path: Path) -> None:
    """Validate that binaries in bin_dir match the identity manifest by hash and version."""
    manifest = load_artifact_manifest(manifest_path)
    expected_binaries = manifest.get("expected_binaries")
    if not isinstance(expected_binaries, dict):
        raise ArtifactValidationError("Manifest missing or invalid 'expected_binaries' mapping")

    # Manifest schema must require exactly {ffmpeg.exe, ffprobe.exe}
    if set(expected_binaries.keys()) != set(REQUIRED_BINARIES):
        raise ArtifactValidationError(
            f"Manifest 'expected_binaries' must contain exactly {set(REQUIRED_BINARIES)}, got {set(expected_binaries.keys())}"
        )

    # Validate each entry in manifest schema first
    for binary_name in REQUIRED_BINARIES:
        info = expected_binaries[binary_name]
        if not isinstance(info, dict):
            raise ArtifactValidationError(
                f"Manifest entry for '{binary_name}' must be an object"
            )
        sha = info.get("sha256", "")
        if not isinstance(sha, str) or not SHA256_HEX_PATTERN.match(sha.strip()):
            raise ArtifactValidationError(
                f"Manifest entry '{binary_name}' has invalid sha256: expected 64 lowercase hex characters"
            )
        version_prefix = info.get("version_prefix", "")
        if not isinstance(version_prefix, str) or not version_prefix.strip():
            raise ArtifactValidationError(
                f"Manifest entry '{binary_name}' missing or empty 'version_prefix'"
            )

    for binary_name in REQUIRED_BINARIES:
        expected_info = expected_binaries[binary_name]
        binary_file = bin_dir / binary_name
        if not binary_file.is_file():
            raise ArtifactValidationError(
                f"Required binary '{binary_name}' not found at {binary_file}. "
                f"Approved archive source: {manifest.get('archive_url')}"
            )

        expected_hash = expected_info["sha256"].strip().lower()
        actual_hash = compute_sha256(binary_file)
        if actual_hash != expected_hash:
            raise ArtifactValidationError(
                f"SHA-256 mismatch for {binary_name} at {binary_file}.\n"
                f"  Expected: {expected_hash}\n"
                f"  Actual:   {actual_hash}\n"
                f"  Approved source: {manifest.get('archive_url')}"
            )

        expected_version_prefix = expected_info["version_prefix"].strip()
        actual_version = get_binary_version(binary_file)
        if not actual_version.startswith(expected_version_prefix):
            raise ArtifactValidationError(
                f"Version prefix mismatch for {binary_name} at {binary_file}.\n"
                f"  Expected prefix: {expected_version_prefix}\n"
                f"  Actual version:  {actual_version}"
            )


def build(dist_dir: Path | None = None) -> None:
    print(f"Building {APP_NAME}...")

    # Validate binary artifact identity prior to packaging
    print("Validating bundled FFmpeg/ffprobe binary identity...")
    try:
        validate_binary_artifacts(bin_dir=BIN_DIR, manifest_path=MANIFEST_PATH)
    except ArtifactValidationError as err:
        print(f"Error: Binary identity validation failed:\n{err}", file=sys.stderr)
        print("Packaging aborted. Ensure approved binaries are placed in bin/.", file=sys.stderr)
        sys.exit(1)

    # PyInstaller command arguments
    actual_dist_dir = dist_dir.resolve() if dist_dir else DIST_DIR
    exe_suffix = ".exe" if sys.platform == "win32" else ""
    output_file = actual_dist_dir / f"{APP_NAME}{exe_suffix}"

    # Safely remove/reject stale preexisting output prior to invoking PyInstaller
    if output_file.is_dir():
        print(f"Build output path is a directory, not a regular file: {output_file}", file=sys.stderr)
        sys.exit(1)
    elif output_file.exists():
        output_file.unlink()

    # PyInstaller syntax for --add-binary is "source;dest" on Windows or "source:dest" on Linux
    separator = ";" if sys.platform == "win32" else ":"
    ffmpeg_add_binary = f"{FFMPEG_PATH}{separator}."
    ffprobe_add_binary = f"{FFPROBE_PATH}{separator}."

    pyinstaller_args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onefile",
        "--windowed",
        "--name",
        APP_NAME,
        "--paths",
        str(SRC_DIR),
        "--distpath",
        str(actual_dist_dir),
        "--workpath",
        str(BUILD_DIR),
        "--add-binary",
        ffmpeg_add_binary,
        "--add-binary",
        ffprobe_add_binary,
    ]

    if ICON_PATH.is_file():
        pyinstaller_args.extend(["--icon", str(ICON_PATH)])
        # Also bundle icon into the executable resources for window icon lookup
        pyinstaller_args.extend(["--add-data", f"{ICON_PATH}{separator}assets"])

    pyinstaller_args.append(str(ENTRY_POINT))

    print(f"Running PyInstaller: {' '.join(pyinstaller_args)}")
    result = subprocess.run(pyinstaller_args, check=False)
    if result.returncode != 0:
        print(f"PyInstaller build failed with exit code {result.returncode}", file=sys.stderr)
        sys.exit(result.returncode)

    if not output_file.exists():
        print(f"Build output executable does not exist: {output_file}", file=sys.stderr)
        sys.exit(1)

    if not output_file.is_file():
        print(f"Build output executable is not a regular file: {output_file}", file=sys.stderr)
        sys.exit(1)

    if output_file.stat().st_size == 0:
        print(f"Build output executable is empty (0 bytes): {output_file}", file=sys.stderr)
        sys.exit(1)

    print(f"\nSuccessfully built single-file standalone executable: {output_file}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build FreeSimpleVideoConverter executable.")
    parser.add_argument("--dist-dir", type=Path, default=None, help="Custom output directory.")
    cli_args = parser.parse_args()
    build(dist_dir=cli_args.dist_dir)
