"""Unit tests for the Linux release asset packager."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

CLI_PATH = Path(__file__).resolve().parents[2] / "packaging" / "package_linux_release_assets.py"
spec = importlib.util.spec_from_file_location("package_linux_release_assets", CLI_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load {CLI_PATH}")
plra = importlib.util.module_from_spec(spec)
sys.modules["package_linux_release_assets"] = plra
spec.loader.exec_module(plra)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_fixture(tmp_path: Path) -> dict:
    repo_root = tmp_path / "repo"
    recipe_dir = repo_root / "packaging" / "ffmpeg-build"
    recipe_dir.mkdir(parents=True)
    (repo_root / "LICENSE").write_text("license", encoding="utf-8")
    (repo_root / "THIRD_PARTY_NOTICES.md").write_text("notices", encoding="utf-8")

    builder_bytes = b"#!/usr/bin/env bash\n# linux builder\n"
    (recipe_dir / "build_ffmpeg_linux.sh").write_bytes(builder_bytes)
    artifact_manifest = {"expected_binaries": {"ffmpeg": {}, "ffprobe": {}}}
    (repo_root / "packaging" / "ffmpeg_artifact_manifest_linux.json").write_text(
        json.dumps(artifact_manifest), encoding="utf-8"
    )

    fake_sources = [
        {
            "name": "ffmpeg",
            "acquisition_type": "official_release",
            "version": "6.1.1",
            "content": b"fake ffmpeg tarball",
            "filename": "ffmpeg-6.1.1.tar.xz",
        },
        {
            "name": "x264",
            "acquisition_type": "commit_archive",
            "commit": "c" * 40,
            "content": b"fake x264 tarball",
            "filename": "x264-test.tar.gz",
        },
    ]
    lock_sources = []
    manifest_sources = []
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    for src in fake_sources:
        digest = _sha256(src["content"])
        (cache_dir / digest).write_bytes(src["content"])
        if src["acquisition_type"] == "official_release":
            lock_sources.append(
                {
                    "name": src["name"],
                    "acquisition_type": src["acquisition_type"],
                    "version": src["version"],
                    "sha256": digest,
                    "filename": src["filename"],
                }
            )
        else:
            lock_sources.append(
                {
                    "name": src["name"],
                    "acquisition_type": src["acquisition_type"],
                    "commit": src["commit"],
                    "canonical_artifact": {"sha256": digest, "filename": src["filename"]},
                }
            )
        manifest_sources.append(
            {k: v for k, v in src.items() if k in ("name", "acquisition_type", "version", "commit")}
        )

    flags = ["--enable-test"]
    outputs = [
        {"name": "ffmpeg", "path": "bin/ffmpeg", "version_prefix": "ffmpeg version 6.1.1"},
        {"name": "ffprobe", "path": "bin/ffprobe", "version_prefix": "ffprobe version 6.1.1"},
    ]
    lock = {
        "sources": lock_sources,
        "configure": {"flags": flags},
        "outputs": outputs,
        "patches": [],
    }
    manifest = {
        "sources": manifest_sources,
        "configure": {"flags": flags},
        "outputs": outputs,
        "patches": [],
    }
    (recipe_dir / "build-linux.lock.json").write_text(json.dumps(lock), encoding="utf-8")
    (recipe_dir / "acquisition-manifest-linux.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )

    output_dir = tmp_path / "output"
    bin_dir = output_dir / "bin"
    bin_dir.mkdir(parents=True)
    ffmpeg_bytes = b"fake-ffmpeg-elf"
    ffprobe_bytes = b"fake-ffprobe-elf"
    (bin_dir / "ffmpeg").write_bytes(ffmpeg_bytes)
    (bin_dir / "ffprobe").write_bytes(ffprobe_bytes)
    recon = {
        "build-record.json": None,
        "commands.log": b"cmds\n",
        "config.log": b"config\n",
        "encoders.txt": (
            b" V..... libx264 libx264\n V..... libx265 libx265\n"
            b" V..... libvpx-vp9 libvpx\n V..... libsvtav1 svt\n"
            b" A..... libopus opus\n V..... h264_nvenc nvenc\n"
            b" V..... h264_qsv qsv\n V..... h264_vaapi vaapi\n"
        ),
        "ffmpeg-buildconf.txt": b"ffmpeg conf\n",
        "ffprobe-buildconf.txt": b"ffprobe conf\n",
        "ffmpeg-deps.txt": b"linux-vdso\n",
        "ffprobe-deps.txt": b"linux-vdso\n",
        "hwaccels.txt": b"vaapi\n",
    }
    record = {
        "configure_flags": flags,
        "builder_script_sha256": _sha256(builder_bytes),
        "config_log": {"sha256": _sha256(recon["config.log"])},
        "command_log_sha256": _sha256(recon["commands.log"]),
        "encoders_sha256": _sha256(recon["encoders.txt"]),
        "outputs": {
            "binaries": {
                "ffmpeg": {"sha256": _sha256(ffmpeg_bytes), "size_bytes": len(ffmpeg_bytes)},
                "ffprobe": {"sha256": _sha256(ffprobe_bytes), "size_bytes": len(ffprobe_bytes)},
            }
        },
    }
    recon["build-record.json"] = (json.dumps(record) + "\n").encode("utf-8")
    for name, data in recon.items():
        (output_dir / name).write_bytes(data)

    app_tarball = tmp_path / "FreeSimpleVideoConverter-v1.0.1-linux-x86_64.tar.gz"
    app_tarball.write_bytes(b"fake-tarball")

    return {
        "repo_root": repo_root,
        "cache_dir": cache_dir,
        "output_dir": output_dir,
        "app_tarball": app_tarball,
        "lock": lock,
        "manifest": manifest,
    }


def _mock_versions(monkeypatch: pytest.MonkeyPatch) -> None:
    class Result:
        returncode = 0

        def __init__(self, cmd: list[str]) -> None:
            if "ffprobe" in str(cmd[0]):
                self.stdout = "ffprobe version 6.1.1\n"
            else:
                self.stdout = "ffmpeg version 6.1.1\n"

    monkeypatch.setattr(
        plra.subprocess, "run", lambda cmd, **kwargs: Result(cmd)
    )


def test_manifest_lock_match_and_mismatch(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    plra.check_manifest_against_lock(fixture["manifest"], fixture["lock"])
    bad = copy.deepcopy(fixture["manifest"])
    bad["configure"]["flags"] = ["--enable-other"]
    with pytest.raises(ValueError, match="configure flags"):
        plra.check_manifest_against_lock(bad, fixture["lock"])


def test_cached_sources_and_record_validation(tmp_path: Path) -> None:
    fixture = _make_fixture(tmp_path)
    plra.validate_cached_sources(fixture["lock"], fixture["cache_dir"])
    record = json.loads((fixture["output_dir"] / "build-record.json").read_text())
    plra.validate_build_record(record, fixture["lock"], fixture["repo_root"], fixture["output_dir"])
    (fixture["output_dir"] / "encoders.txt").write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="encoders.txt sha256"):
        plra.validate_build_record(
            record, fixture["lock"], fixture["repo_root"], fixture["output_dir"]
        )


def test_source_zip_roundtrip_and_tamper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import zipfile

    fixture = _make_fixture(tmp_path)
    _mock_versions(monkeypatch)
    release_dir = tmp_path / "release"
    report = plra.package_linux_release(
        fixture["repo_root"],
        fixture["output_dir"],
        fixture["cache_dir"],
        fixture["app_tarball"],
        release_dir,
    )
    assert report["status"] == "success"
    assert set(report["checksums"]) == {
        "FreeSimpleVideoConverter-v1.0.1-linux-x86_64.tar.gz",
        plra.SOURCE_ZIP_NAME,
    }
    sums = (release_dir / "SHA256SUMS.txt").read_text(encoding="utf-8")
    assert plra.SOURCE_ZIP_NAME in sums

    tampered = tmp_path / "tampered.zip"
    tampered.write_bytes((release_dir / plra.SOURCE_ZIP_NAME).read_bytes())
    with zipfile.ZipFile(tampered, "a") as zf:
        zf.writestr("extra.txt", b"extra")
    with pytest.raises(
        ValueError, match="entry mismatch|Extra|Non-unix entry|Bad mode"
    ):
        plra.validate_linux_source_zip(tampered, fixture["repo_root"], fixture["lock"])
