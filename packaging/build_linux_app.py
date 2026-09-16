"""Build a single-file standalone Linux executable with PyInstaller and tar.gz it.

Uses the Linux FFmpeg artifact manifest (bin/ffmpeg, bin/ffprobe) and never
touches the Windows packaging path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
from pathlib import Path

APP_NAME = "FreeSimpleVideoConverter"


def compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def binary_version(binary_path: Path) -> str:
    result = subprocess.run(
        [str(binary_path), "-version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        timeout=10,
    )
    if result.returncode == 0 and result.stdout:
        return result.stdout.strip().splitlines()[0]
    return ""


def validate_binaries(bin_dir: Path, manifest_path: Path) -> None:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest.get("expected_binaries", {})
    for name, info in expected.items():
        binary = bin_dir / name
        if not binary.is_file():
            raise RuntimeError(f"Required binary missing: {binary}")
        actual_sha = compute_sha256(binary)
        if actual_sha != info["sha256"].strip().lower():
            raise RuntimeError(
                f"SHA-256 mismatch for {name}: expected {info['sha256']}, got {actual_sha}"
            )
        actual_version = binary_version(binary)
        if not actual_version.startswith(info["version_prefix"].strip()):
            raise RuntimeError(
                f"Version prefix mismatch for {name}: {actual_version!r}"
            )
        print(f"OK {name} {actual_sha[:16]}… {actual_version}")


def build(repo_root: Path, bin_dir: Path, dist_dir: Path, work_dir: Path) -> Path:
    src_dir = repo_root / "src"
    entry_point = src_dir / "video_converter" / "main.py"
    output_file = dist_dir / APP_NAME
    if output_file.is_dir():
        raise RuntimeError(f"Build output path is a directory: {output_file}")
    if output_file.exists():
        output_file.unlink()

    args = [
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
        str(src_dir),
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--add-binary",
        f"{bin_dir / 'ffmpeg'}:.",
        "--add-binary",
        f"{bin_dir / 'ffprobe'}:.",
        "--add-data",
        f"{repo_root / 'assets' / 'icon.ico'}:assets",
        "--add-data",
        f"{repo_root / 'assets' / 'fonts'}:assets/fonts",
        str(entry_point),
    ]
    print("Running PyInstaller:", " ".join(args))
    result = subprocess.run(args, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"PyInstaller failed with exit code {result.returncode}")
    if not output_file.is_file() or output_file.stat().st_size == 0:
        raise RuntimeError(f"Build output missing or empty: {output_file}")
    print(f"Built: {output_file} ({output_file.stat().st_size} bytes)")
    return output_file


def make_tarball(repo_root: Path, dist_dir: Path, version: str) -> Path:
    binary = dist_dir / APP_NAME
    tarball = dist_dir / f"{APP_NAME}-v{version}-linux-x86_64.tar.gz"
    if tarball.exists():
        tarball.unlink()
    with tarfile.open(tarball, "w:gz", compresslevel=9) as tf:
        tf.add(binary, arcname=APP_NAME)
        for doc in ("LICENSE", "README.md", "THIRD_PARTY_NOTICES.md"):
            tf.add(repo_root / doc, arcname=doc)
    print(f"Tarball: {tarball} ({tarball.stat().st_size} bytes)")
    return tarball


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Linux application tarball.")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--version", default="1.0.1")
    args = parser.parse_args(argv)

    try:
        validate_binaries(args.bin_dir, args.manifest)
        args.dist_dir.mkdir(parents=True, exist_ok=True)
        args.work_dir.mkdir(parents=True, exist_ok=True)
        build(args.repo_root, args.bin_dir, args.dist_dir, args.work_dir)
        make_tarball(args.repo_root, args.dist_dir, args.version)
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
