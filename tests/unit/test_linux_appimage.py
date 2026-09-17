"""Unit tests for the Linux AppImage stager/validator."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys

import pytest

CLI_PATH = Path(__file__).resolve().parents[2] / "packaging" / "build_linux_appimage.py"
spec = importlib.util.spec_from_file_location("build_linux_appimage", CLI_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load {CLI_PATH}")
bia = importlib.util.module_from_spec(spec)
sys.modules["build_linux_appimage"] = bia
spec.loader.exec_module(bia)


def _make_repo_and_bundle(tmp_path: Path) -> tuple[Path, Path]:
    repo_root = tmp_path / "repo"
    (repo_root / "assets").mkdir(parents=True)
    (repo_root / "assets" / "icon.png").write_bytes(b"\x89PNG-fake-icon")
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "FreeSimpleVideoConverter").write_bytes(b"fake-elf-binary")
    (bundle_dir / "lib").mkdir()
    (bundle_dir / "lib" / "libfoo.so").write_bytes(b"fake-so")
    return repo_root, bundle_dir


def test_stage_appdir_layout(tmp_path: Path) -> None:
    repo_root, bundle_dir = _make_repo_and_bundle(tmp_path)
    appdir = tmp_path / "AppDir"
    bia.stage_appdir(repo_root, bundle_dir, appdir)

    assert (appdir / "AppRun").is_file()
    assert os.access(appdir / "AppRun", os.X_OK)
    assert (appdir / "FreeSimpleVideoConverter.desktop").is_file()
    desktop = (appdir / "FreeSimpleVideoConverter.desktop").read_text(encoding="utf-8")
    assert "Exec=FreeSimpleVideoConverter" in desktop
    assert (appdir / ".DirIcon").read_bytes() == b"\x89PNG-fake-icon"
    assert (appdir / "FreeSimpleVideoConverter.png").read_bytes() == b"\x89PNG-fake-icon"
    assert (
        appdir / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    ).is_dir()
    assert (appdir / "usr" / "bin" / "FreeSimpleVideoConverter").is_file()
    assert (appdir / "usr" / "bin" / "lib" / "libfoo.so").is_file()


def test_stage_appdir_requires_icon(tmp_path: Path) -> None:
    repo_root, bundle_dir = _make_repo_and_bundle(tmp_path)
    (repo_root / "assets" / "icon.png").unlink()
    with pytest.raises(RuntimeError, match="icon missing"):
        bia.stage_appdir(repo_root, bundle_dir, tmp_path / "AppDir")


def test_validate_appimage_rejects_bad_magic(tmp_path: Path) -> None:
    bad = tmp_path / "bad.AppImage"
    bad.write_bytes(b"\x7fELF" + b"\x00" * 4 + b"XX" + b"\x00" * 20_000_000)
    bad.chmod(0o755)
    with pytest.raises(ValueError, match="magic"):
        bia.validate_appimage(bad)


def test_validate_appimage_rejects_tiny(tmp_path: Path) -> None:
    tiny = tmp_path / "tiny.AppImage"
    tiny.write_bytes(b"\x7fELF" + b"\x00" * 4 + b"AI" + b"\x00" * 100)
    tiny.chmod(0o755)
    with pytest.raises(ValueError, match="suspiciously small"):
        bia.validate_appimage(tiny)
