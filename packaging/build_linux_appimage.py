"""Build a portable Linux AppImage from a PyInstaller onedir tree.

Stages an AppDir (AppRun, .desktop entry, icons, onedir bundle with the
validated custom FFmpeg binaries) and packs it with a pinned appimagetool
release. Writes an appimage-build.json provenance record next to the output.

Never touches the Windows packaging path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
from pathlib import Path

APP_NAME = "FreeSimpleVideoConverter"
APPIMAGE_VERSION = "1.9.0"
APPIMAGETOOL_URL = (
    "https://github.com/AppImage/appimagetool/releases/download/"
    f"{APPIMAGE_VERSION}/appimagetool-x86_64.AppImage"
)
# Pinned by scripts/build tooling; verified before every use.
APPIMAGETOOL_SHA256 = "46fdd785094c7f6e545b61afcfb0f3d98d8eab243f644b4b17698c01d06083d1"

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_linux_app  # noqa: E402


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def ensure_appimagetool(tools_dir: Path) -> Path:
    """Fetch (once) and verify the pinned appimagetool, return extracted AppRun."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    image = tools_dir / "appimagetool-x86_64.AppImage"
    if not image.is_file() or _sha256_file(image) != APPIMAGETOOL_SHA256:
        print(f"Downloading appimagetool {APPIMAGE_VERSION} ...")
        subprocess.run(
            ["curl", "-sSL", "-o", str(image), APPIMAGETOOL_URL], check=True
        )
    actual = _sha256_file(image)
    if actual != APPIMAGETOOL_SHA256:
        raise RuntimeError(f"appimagetool sha256 mismatch: {actual}")
    extracted = tools_dir / "squashfs-root" / "AppRun"
    if not extracted.is_file():
        subprocess.run([str(image), "--appimage-extract"], cwd=tools_dir, check=True)
    if not extracted.is_file():
        raise RuntimeError("appimagetool extraction produced no AppRun")
    return extracted


def build_onedir(
    repo_root: Path, bin_dir: Path, dist_dir: Path, work_dir: Path
) -> Path:
    """Run PyInstaller in onedir mode, return the bundle directory."""
    src_dir = repo_root / "src"
    entry_point = src_dir / "video_converter" / "main.py"
    bundle_dir = dist_dir / APP_NAME
    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    args = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
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
        raise RuntimeError(f"PyInstaller onedir failed: {result.returncode}")
    executable = bundle_dir / APP_NAME
    if not executable.is_file():
        raise RuntimeError(f"Onedir executable missing: {executable}")
    return bundle_dir


DESKTOP_ENTRY = """[Desktop Entry]
Name=Free Simple Video Converter
Exec=FreeSimpleVideoConverter
Icon=FreeSimpleVideoConverter
Type=Application
Categories=AudioVideo;Video;
Comment=Simple GPU-accelerated batch video converter powered by FFmpeg
Terminal=false
StartupWMClass=FreeSimpleVideoConverter
"""

APPRUN_SCRIPT = """#!/usr/bin/env sh
HERE="$(dirname "$(readlink -f "$0")")"
export QT_QPA_PLATFORMTHEME=""
exec "$HERE/usr/bin/FreeSimpleVideoConverter" "$@"
"""


def stage_appdir(repo_root: Path, bundle_dir: Path, appdir: Path) -> None:
    """Assemble the AppDir from the onedir bundle and repo metadata."""
    if appdir.exists():
        shutil.rmtree(appdir)
    target_bin = appdir / "usr" / "bin"
    target_bin.mkdir(parents=True)
    for item in bundle_dir.iterdir():
        dest = target_bin / item.name
        if item.is_dir():
            shutil.copytree(item, dest, symlinks=True)
        else:
            shutil.copy2(item, dest)
    (appdir / f"{APP_NAME}.desktop").write_text(DESKTOP_ENTRY, encoding="utf-8")
    icon_src = repo_root / "assets" / "icon.png"
    if not icon_src.is_file():
        raise RuntimeError(f"AppImage icon missing: {icon_src}")
    icon_data = icon_src.read_bytes()
    (appdir / ".DirIcon").write_bytes(icon_data)
    (appdir / f"{APP_NAME}.png").write_bytes(icon_data)
    icon_dir = appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icon_dir.mkdir(parents=True)
    (icon_dir / f"{APP_NAME}.png").write_bytes(icon_data)
    apprun = appdir / "AppRun"
    apprun.write_text(APPRUN_SCRIPT, encoding="utf-8", newline="\n")
    apprun.chmod(apprun.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def pack_appimage(appimagetool: Path, appdir: Path, output: Path, work_dir: Path) -> Path:
    """Pack the AppDir with appimagetool, return the AppImage path."""
    if output.exists():
        output.unlink()
    env = dict(os.environ)
    env["ARCH"] = "x86_64"
    result = subprocess.run(
        [str(appimagetool), str(appdir), str(output)],
        cwd=work_dir,
        env=env,
        check=False,
    )
    if result.returncode != 0 or not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"appimagetool failed: {result.returncode}")
    output.chmod(output.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return output


def validate_appimage(path: Path) -> None:
    """Structural validation: ELF + AppImage magic, executable, sane size."""
    data = path.read_bytes()
    if data[:4] != b"\x7fELF":
        raise ValueError("AppImage is not an ELF binary")
    if data[8:10] != b"AI":
        raise ValueError("AppImage magic bytes missing")
    if not os.access(path, os.X_OK):
        raise ValueError("AppImage is not executable")
    if path.stat().st_size < 10_000_000:
        raise ValueError(f"AppImage suspiciously small: {path.stat().st_size}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build Linux AppImage.")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--bin-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--dist-dir", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--tools-dir", type=Path, required=True)
    parser.add_argument("--version", default="1.0.2")
    args = parser.parse_args(argv)

    try:
        build_linux_app.validate_binaries(args.bin_dir, args.manifest)
        args.dist_dir.mkdir(parents=True, exist_ok=True)
        args.work_dir.mkdir(parents=True, exist_ok=True)
        bundle_dir = build_onedir(args.repo_root, args.bin_dir, args.dist_dir, args.work_dir)
        appdir = args.work_dir / "AppDir"
        stage_appdir(args.repo_root, bundle_dir, appdir)
        appimagetool = ensure_appimagetool(args.tools_dir)
        output = args.dist_dir / f"{APP_NAME}-v{args.version}-linux-x86_64.AppImage"
        pack_appimage(appimagetool, appdir, output, args.work_dir)
        validate_appimage(output)
        provenance = {
            "appimage_tool": {
                "version": APPIMAGE_VERSION,
                "url": APPIMAGETOOL_URL,
                "sha256": APPIMAGETOOL_SHA256,
            },
            "output": {
                "name": output.name,
                "sha256": _sha256_file(output),
                "size_bytes": output.stat().st_size,
            },
        }
        (args.dist_dir / "appimage-build.json").write_text(
            json.dumps(provenance, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(provenance, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
