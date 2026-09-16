"""Unit tests for FFmpeg build manifest and lifecycle contracts."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest

from video_converter.ffmpeg_build_manifest import (
    decode_json_without_duplicate_keys,
    load_json,
    validate_acquisition_manifest,
    validate_build_lock,
    validate_build_record,
    validate_cached_inputs,
    validate_release,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MANIFEST_PATH = (
    REPO_ROOT
    / "packaging"
    / "ffmpeg-build"
    / "acquisition-manifest.json"
)

ALL_9_SOURCES = [
    {
        "name": "ffmpeg",
        "acquisition_type": "official_release",
        "version": "6.1.1",
        "source_commit": "e38092ef9395d7049f871ef4d5411eb410e283e0",
        "artifact_url": "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz",
        "filename": "ffmpeg-6.1.1.tar.xz",
        "sha256": "1" * 64,
        "verification_evidence": {
            "type": "pgp_signature",
            "verified": True,
            "artifact_sha256": "1" * 64,
            "signature_url": "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
            "signer": "FCF986EA15E6E293A5644F10B4322F04D67658D8",
        },
    },
    {
        "name": "x264",
        "acquisition_type": "commit_archive",
        "commit": "c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        "upstream_remote_url": "https://code.videolan.org/videolan/x264.git",
        "canonical_artifact": {
            "origin": "git_archive",
            "filename": "x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
            "sha256": "2" * 64,
            "retention_uri": "project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
        },
        "verification_evidence": {
            "type": "commit_archive",
            "verified": True,
            "artifact_sha256": "2" * 64,
            "commit": "c24e06c2e184345ceb33eb20a15d1024d9fd3497",
            "verifier": "git-rev-parse-and-archive",
            "remote_url": "https://code.videolan.org/videolan/x264.git",
            "archive_command": "git archive --format=tar.gz --prefix=x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497/ c24e06c2e184345ceb33eb20a15d1024d9fd3497",
            "git_version": "git version 2.43.0",
            "git_bundle_sha256": "b" * 64,
            "bundle_retention_uri": "project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle",
            "canonical_archive_retention_uri": "project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
        },
    },
    {
        "name": "x265",
        "acquisition_type": "commit_archive",
        "commit": "f0c1022b6be121a753ff02853fbe33da71988656",
        "upstream_remote_url": "https://bitbucket.org/multicoreware/x265_git.git",
        "canonical_artifact": {
            "origin": "git_archive",
            "filename": "x265-f0c1022b6be121a753ff02853fbe33da71988656.tar.gz",
            "sha256": "3" * 64,
            "retention_uri": "project://ffmpeg-build/git/x265/f0c1022b6be121a753ff02853fbe33da71988656.tar.gz",
        },
        "verification_evidence": {
            "type": "commit_archive",
            "verified": True,
            "artifact_sha256": "3" * 64,
            "commit": "f0c1022b6be121a753ff02853fbe33da71988656",
            "verifier": "git-rev-parse-and-archive",
            "remote_url": "https://bitbucket.org/multicoreware/x265_git.git",
            "archive_command": "git archive --format=tar.gz --prefix=x265-f0c1022b6be121a753ff02853fbe33da71988656/ f0c1022b6be121a753ff02853fbe33da71988656",
            "git_version": "git version 2.43.0",
            "git_bundle_sha256": "b" * 64,
            "bundle_retention_uri": "project://ffmpeg-build/git/x265/f0c1022b6be121a753ff02853fbe33da71988656.bundle",
            "canonical_archive_retention_uri": "project://ffmpeg-build/git/x265/f0c1022b6be121a753ff02853fbe33da71988656.tar.gz",
        },
    },
    {
        "name": "libvpx",
        "acquisition_type": "commit_archive",
        "commit": "10b9492dcf05b652e2e4b370e205bd605d421972",
        "upstream_remote_url": "https://chromium.googlesource.com/webm/libvpx",
        "canonical_artifact": {
            "origin": "git_archive",
            "filename": "libvpx-10b9492dcf05b652e2e4b370e205bd605d421972.tar.gz",
            "sha256": "4" * 64,
            "retention_uri": "project://ffmpeg-build/git/libvpx/10b9492dcf05b652e2e4b370e205bd605d421972.tar.gz",
        },
        "verification_evidence": {
            "type": "commit_archive",
            "verified": True,
            "artifact_sha256": "4" * 64,
            "commit": "10b9492dcf05b652e2e4b370e205bd605d421972",
            "verifier": "git-rev-parse-and-archive",
            "remote_url": "https://chromium.googlesource.com/webm/libvpx",
            "archive_command": "git archive --format=tar.gz --prefix=libvpx-10b9492dcf05b652e2e4b370e205bd605d421972/ 10b9492dcf05b652e2e4b370e205bd605d421972",
            "git_version": "git version 2.43.0",
            "git_bundle_sha256": "b" * 64,
            "bundle_retention_uri": "project://ffmpeg-build/git/libvpx/10b9492dcf05b652e2e4b370e205bd605d421972.bundle",
            "canonical_archive_retention_uri": "project://ffmpeg-build/git/libvpx/10b9492dcf05b652e2e4b370e205bd605d421972.tar.gz",
        },
    },
    {
        "name": "svt-av1",
        "acquisition_type": "commit_archive",
        "commit": "59645eea34e2815b627b8293aa3af254eddd0d69",
        "upstream_remote_url": "https://gitlab.com/AOMediaCodec/SVT-AV1.git",
        "canonical_artifact": {
            "origin": "git_archive",
            "filename": "svt-av1-59645eea34e2815b627b8293aa3af254eddd0d69.tar.gz",
            "sha256": "5" * 64,
            "retention_uri": "project://ffmpeg-build/git/svt-av1/59645eea34e2815b627b8293aa3af254eddd0d69.tar.gz",
        },
        "verification_evidence": {
            "type": "commit_archive",
            "verified": True,
            "artifact_sha256": "5" * 64,
            "commit": "59645eea34e2815b627b8293aa3af254eddd0d69",
            "verifier": "git-rev-parse-and-archive",
            "remote_url": "https://gitlab.com/AOMediaCodec/SVT-AV1.git",
            "archive_command": "git archive --format=tar.gz --prefix=svt-av1-59645eea34e2815b627b8293aa3af254eddd0d69/ 59645eea34e2815b627b8293aa3af254eddd0d69",
            "git_version": "git version 2.43.0",
            "git_bundle_sha256": "b" * 64,
            "bundle_retention_uri": "project://ffmpeg-build/git/svt-av1/59645eea34e2815b627b8293aa3af254eddd0d69.bundle",
            "canonical_archive_retention_uri": "project://ffmpeg-build/git/svt-av1/59645eea34e2815b627b8293aa3af254eddd0d69.tar.gz",
        },
    },
    {
        "name": "libopus",
        "acquisition_type": "official_release",
        "version": "1.4",
        "artifact_url": "https://github.com/xiph/opus/releases/download/v1.4/opus-1.4.tar.gz",
        "filename": "opus-1.4.tar.gz",
        "sha256": "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f",
        "verification_evidence": {
            "type": "published_checksum",
            "algorithm": "sha256",
            "expected_digest": "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f",
            "verified": True,
            "artifact_sha256": "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f",
            "verifier": "sha256-verifier",
        },
    },
    {
        "name": "nv-codec-headers",
        "acquisition_type": "commit_archive",
        "commit": "1889e62e2d35ff7aa9baca2bceb14f053785e6f1",
        "upstream_remote_url": "https://github.com/FFmpeg/nv-codec-headers.git",
        "canonical_artifact": {
            "origin": "git_archive",
            "filename": "nv-codec-headers-1889e62e2d35ff7aa9baca2bceb14f053785e6f1.tar.gz",
            "sha256": "7" * 64,
            "retention_uri": "project://ffmpeg-build/git/nv-codec-headers/1889e62e2d35ff7aa9baca2bceb14f053785e6f1.tar.gz",
        },
        "verification_evidence": {
            "type": "commit_archive",
            "verified": True,
            "artifact_sha256": "7" * 64,
            "commit": "1889e62e2d35ff7aa9baca2bceb14f053785e6f1",
            "verifier": "git-rev-parse-and-archive",
            "remote_url": "https://github.com/FFmpeg/nv-codec-headers.git",
            "archive_command": "git archive --format=tar.gz --prefix=nv-codec-headers-1889e62e2d35ff7aa9baca2bceb14f053785e6f1/ 1889e62e2d35ff7aa9baca2bceb14f053785e6f1",
            "git_version": "git version 2.43.0",
            "git_bundle_sha256": "b" * 64,
            "bundle_retention_uri": "project://ffmpeg-build/git/nv-codec-headers/1889e62e2d35ff7aa9baca2bceb14f053785e6f1.bundle",
            "canonical_archive_retention_uri": "project://ffmpeg-build/git/nv-codec-headers/1889e62e2d35ff7aa9baca2bceb14f053785e6f1.tar.gz",
        },
    },
    {
        "name": "amf",
        "acquisition_type": "commit_archive",
        "commit": "c48e50ad6c8723c006b2c145d8fa49ecc0651022",
        "upstream_remote_url": "https://github.com/GPUOpen-LibrariesAndSDKs/AMF.git",
        "canonical_artifact": {
            "origin": "git_archive",
            "filename": "amf-c48e50ad6c8723c006b2c145d8fa49ecc0651022.tar.gz",
            "sha256": "8" * 64,
            "retention_uri": "project://ffmpeg-build/git/amf/c48e50ad6c8723c006b2c145d8fa49ecc0651022.tar.gz",
        },
        "verification_evidence": {
            "type": "commit_archive",
            "verified": True,
            "artifact_sha256": "8" * 64,
            "commit": "c48e50ad6c8723c006b2c145d8fa49ecc0651022",
            "verifier": "git-rev-parse-and-archive",
            "remote_url": "https://github.com/GPUOpen-LibrariesAndSDKs/AMF.git",
            "archive_command": "git archive --format=tar.gz --prefix=amf-c48e50ad6c8723c006b2c145d8fa49ecc0651022/ c48e50ad6c8723c006b2c145d8fa49ecc0651022",
            "git_version": "git version 2.43.0",
            "git_bundle_sha256": "b" * 64,
            "bundle_retention_uri": "project://ffmpeg-build/git/amf/c48e50ad6c8723c006b2c145d8fa49ecc0651022.bundle",
            "canonical_archive_retention_uri": "project://ffmpeg-build/git/amf/c48e50ad6c8723c006b2c145d8fa49ecc0651022.tar.gz",
        },
    },
    {
        "name": "libvpl",
        "acquisition_type": "commit_archive",
        "commit": "11a9bbda5b22ac1c544da59b4007bb57f737b487",
        "upstream_remote_url": "https://github.com/intel/libvpl.git",
        "canonical_artifact": {
            "origin": "git_archive",
            "filename": "libvpl-11a9bbda5b22ac1c544da59b4007bb57f737b487.tar.gz",
            "sha256": "9" * 64,
            "retention_uri": "project://ffmpeg-build/git/libvpl/11a9bbda5b22ac1c544da59b4007bb57f737b487.tar.gz",
        },
        "verification_evidence": {
            "type": "commit_archive",
            "verified": True,
            "artifact_sha256": "9" * 64,
            "commit": "11a9bbda5b22ac1c544da59b4007bb57f737b487",
            "verifier": "git-rev-parse-and-archive",
            "remote_url": "https://github.com/intel/libvpl.git",
            "archive_command": "git archive --format=tar.gz --prefix=libvpl-11a9bbda5b22ac1c544da59b4007bb57f737b487/ 11a9bbda5b22ac1c544da59b4007bb57f737b487",
            "git_version": "git version 2.43.0",
            "git_bundle_sha256": "b" * 64,
            "bundle_retention_uri": "project://ffmpeg-build/git/libvpl/11a9bbda5b22ac1c544da59b4007bb57f737b487.bundle",
            "canonical_archive_retention_uri": "project://ffmpeg-build/git/libvpl/11a9bbda5b22ac1c544da59b4007bb57f737b487.tar.gz",
        },
    },
]

EXPECTED_CONFIGURE_FLAGS = [
    "--target-os=mingw32",
    "--arch=x86_64",
    "--enable-gpl",
    "--enable-libx264",
    "--enable-libx265",
    "--enable-libvpx",
    "--enable-libsvtav1",
    "--enable-libopus",
    "--enable-nvenc",
    "--enable-libvpl",
    "--enable-amf",
    "--disable-ffplay",
    "--disable-doc",
]


ALL_8_REQUESTED_MSYS2_PACKAGES = [
    {
        "name": "mingw-w64-ucrt-x86_64-gcc",
        "version": "13.2.0-1",
        "filename": "mingw-w64-ucrt-x86_64-gcc-13.2.0-1-any.pkg.tar.zst",
        "sha256": "d" * 64,
        "signature_sha256": "e" * 64,
        "retention_uri": "project://ffmpeg-build/packages/mingw-w64-ucrt-x86_64-gcc-13.2.0-1-any.pkg.tar.zst",
        "dependencies": [],
    },
    {
        "name": "mingw-w64-ucrt-x86_64-nasm",
        "version": "2.16.01-1",
        "filename": "mingw-w64-ucrt-x86_64-nasm-2.16.01-1-any.pkg.tar.zst",
        "sha256": "d" * 64,
        "signature_sha256": "e" * 64,
        "retention_uri": "project://ffmpeg-build/packages/nasm.pkg.tar.zst",
        "dependencies": [],
    },
    {
        "name": "mingw-w64-ucrt-x86_64-ninja",
        "version": "1.11.1-1",
        "filename": "mingw-w64-ucrt-x86_64-ninja-1.11.1-1-any.pkg.tar.zst",
        "sha256": "d" * 64,
        "signature_sha256": "e" * 64,
        "retention_uri": "project://ffmpeg-build/packages/ninja.pkg.tar.zst",
        "dependencies": [],
    },
    {
        "name": "mingw-w64-ucrt-x86_64-cmake",
        "version": "3.28.1-1",
        "filename": "mingw-w64-ucrt-x86_64-cmake-3.28.1-1-any.pkg.tar.zst",
        "sha256": "d" * 64,
        "signature_sha256": "e" * 64,
        "retention_uri": "project://ffmpeg-build/packages/cmake.pkg.tar.zst",
        "dependencies": [],
    },
    {
        "name": "mingw-w64-ucrt-x86_64-meson",
        "version": "1.3.1-1",
        "filename": "mingw-w64-ucrt-x86_64-meson-1.3.1-1-any.pkg.tar.zst",
        "sha256": "d" * 64,
        "signature_sha256": "e" * 64,
        "retention_uri": "project://ffmpeg-build/packages/meson.pkg.tar.zst",
        "dependencies": [],
    },
    {
        "name": "mingw-w64-ucrt-x86_64-pkgconf",
        "version": "2.1.0-1",
        "filename": "mingw-w64-ucrt-x86_64-pkgconf-2.1.0-1-any.pkg.tar.zst",
        "sha256": "d" * 64,
        "signature_sha256": "e" * 64,
        "retention_uri": "project://ffmpeg-build/packages/pkgconf.pkg.tar.zst",
        "dependencies": [],
    },
    {
        "name": "make",
        "version": "4.4.1-1",
        "filename": "make-4.4.1-1-x86_64.pkg.tar.zst",
        "sha256": "d" * 64,
        "signature_sha256": "e" * 64,
        "retention_uri": "project://ffmpeg-build/packages/make.pkg.tar.zst",
        "dependencies": [],
    },
    {
        "name": "diffutils",
        "version": "3.10-1",
        "filename": "diffutils-3.10-1-x86_64.pkg.tar.zst",
        "sha256": "d" * 64,
        "signature_sha256": "e" * 64,
        "retention_uri": "project://ffmpeg-build/packages/diffutils.pkg.tar.zst",
        "dependencies": [],
    },
]


def sample_valid_build_lock() -> dict:
    def signature(name: str) -> dict:
        return {
            "filename": f"{name}.sig",
            "sha256": "e" * 64,
            "retention_uri": f"project://ffmpeg-build/signatures/{name}.sig",
            "verified": True,
            "verifier": "pacman-key",
            "signer": "MSYS2 package signing key",
        }

    packages = copy.deepcopy(ALL_8_REQUESTED_MSYS2_PACKAGES)
    for package in packages:
        package["signature"] = signature(package["name"])
    return {
        "schema_version": "1.0.0",
        "acquisition_manifest_sha256": "a" * 64,
        "recipe_sha256": "a" * 64,
        "toolchain": {
            "environment": "UCRT64",
            "target": "x86_64-w64-mingw32",
        },
        "msys2": {
            "installer": {
                "url": "https://repo.msys2.org/distrib/msys2-x86_64-latest.tar.xz",
                "sha256": "b" * 64,
                "signature_sha256": "e" * 64,
                "signature": signature("installer"),
                "retention_uri": "project://ffmpeg-build/msys2/installer.tar.xz",
            },
            "databases": [
                {
                    "name": "ucrt64.db",
                    "sha256": "c" * 64,
                    "signature_sha256": "e" * 64,
                    "signature": signature("ucrt64.db"),
                    "retention_uri": "project://ffmpeg-build/msys2/ucrt64.db",
                }
            ],
            "packages": packages,
        },
        "sources": copy.deepcopy(ALL_9_SOURCES),
        "patches": [
            {
                "name": "x265-cmake-4.4-compatibility",
                "path": "packaging/ffmpeg-build/patches/x265-cmake-4.4-compatibility.patch",
                "sha256": "a" * 64,
            },
            {
                "name": "x265-pkgconfig-libs-private-no-lgcc_s",
                "path": "packaging/ffmpeg-build/patches/x265-pkgconfig-libs-private-no-lgcc_s.patch",
                "sha256": "b" * 64,
            },
        ],
        "configure": {
            "flags": list(EXPECTED_CONFIGURE_FLAGS),
        },
        "outputs": [
            {
                "name": "ffmpeg",
                "path": "bin/ffmpeg.exe",
                "version_prefix": "ffmpeg version 6.1.1",
            },
            {
                "name": "ffprobe",
                "path": "bin/ffprobe.exe",
                "version_prefix": "ffprobe version 6.1.1",
            },
        ],
    }


def sample_valid_acquisition_manifest() -> dict:
    return load_json(MANIFEST_PATH)


def test_real_acquisition_manifest_loads_and_passes_validation():
    data = load_json(MANIFEST_PATH)
    validate_acquisition_manifest(data)


def test_acquisition_manifest_missing_or_extra_top_level_fields():
    data = load_json(MANIFEST_PATH)

    missing_data = copy.deepcopy(data)
    del missing_data["schema_version"]
    with pytest.raises(ValueError, match="Missing:.*schema_version"):
        validate_acquisition_manifest(missing_data)

    extra_data = copy.deepcopy(data)
    extra_data["extra_field"] = "unexpected"
    with pytest.raises(ValueError, match="Extra:.*extra_field"):
        validate_acquisition_manifest(extra_data)


def test_acquisition_manifest_toolchain_validation():
    data = load_json(MANIFEST_PATH)

    mutant1 = copy.deepcopy(data)
    mutant1["toolchain"]["environment"] = "CLANG64"
    with pytest.raises(ValueError, match="Invalid toolchain environment"):
        validate_acquisition_manifest(mutant1)

    mutant2 = copy.deepcopy(data)
    mutant2["toolchain"]["target"] = "x86_64-pc-linux-gnu"
    with pytest.raises(ValueError, match="Invalid toolchain target"):
        validate_acquisition_manifest(mutant2)

    mutant3 = copy.deepcopy(data)
    mutant3["toolchain"]["extra_opt"] = "forbidden"
    with pytest.raises(ValueError, match="Extra:.*extra_opt"):
        validate_acquisition_manifest(mutant3)


def test_acquisition_manifest_rejects_forbidden_checksum_in_sources():
    data = sample_valid_acquisition_manifest()
    for forbidden_key in ("sha256", "checksum", "hash", "md5", "sha1", "digest"):
        mutant = copy.deepcopy(data)
        mutant["sources"][0][forbidden_key] = "1" * 64
        with pytest.raises(ValueError, match=r"Forbidden hash/checksum key|Extra:"):
            validate_acquisition_manifest(mutant)


def test_acquisition_manifest_commit_archive_validations():
    data = load_json(MANIFEST_PATH)

    # Invalid commit length / hex
    mutant1 = copy.deepcopy(data)
    x264 = next(s for s in mutant1["sources"] if s["name"] == "x264")
    x264["commit"] = "not-a-40-hex-commit"
    with pytest.raises(ValueError, match="40-lowercase-hex"):
        validate_acquisition_manifest(mutant1)

    # Git entry with artifact_url is rejected
    mutant2 = copy.deepcopy(data)
    x264 = next(s for s in mutant2["sources"] if s["name"] == "x264")
    x264["artifact_url"] = "https://code.videolan.org/videolan/x264/-/archive/c24e06c2e184345ceb33eb20a15d1024d9fd3497/x264.tar.gz"
    with pytest.raises(ValueError, match=r"Extra:.*artifact_url"):
        validate_acquisition_manifest(mutant2)

    # Missing git_remote_url is rejected
    mutant3 = copy.deepcopy(data)
    x264 = next(s for s in mutant3["sources"] if s["name"] == "x264")
    del x264["git_remote_url"]
    with pytest.raises(ValueError, match=r"Missing:.*git_remote_url"):
        validate_acquisition_manifest(mutant3)

    # Non-HTTPS git_remote_url is rejected
    mutant4 = copy.deepcopy(data)
    x264 = next(s for s in mutant4["sources"] if s["name"] == "x264")
    x264["git_remote_url"] = "http://code.videolan.org/videolan/x264.git"
    with pytest.raises(ValueError, match="HTTPS"):
        validate_acquisition_manifest(mutant4)

    # Empty git_remote_url is rejected
    mutant5 = copy.deepcopy(data)
    x264 = next(s for s in mutant5["sources"] if s["name"] == "x264")
    x264["git_remote_url"] = ""
    with pytest.raises(ValueError):
        validate_acquisition_manifest(mutant5)

    # Unknown key in commit_archive source
    mutant6 = copy.deepcopy(data)
    x264 = next(s for s in mutant6["sources"] if s["name"] == "x264")
    x264["extra_field"] = "bad"
    with pytest.raises(ValueError, match="Extra:.*extra_field"):
        validate_acquisition_manifest(mutant6)


def test_acquisition_manifest_official_release_validations():
    data = load_json(MANIFEST_PATH)

    # Missing verification policy
    mutant1 = copy.deepcopy(data)
    ffmpeg = next(s for s in mutant1["sources"] if s["name"] == "ffmpeg")
    del ffmpeg["verification"]
    with pytest.raises(ValueError, match="Missing:.*verification"):
        validate_acquisition_manifest(mutant1)

    # Malformed published checksum policy (not 64 hex)
    mutant2 = copy.deepcopy(data)
    opus = next(s for s in mutant2["sources"] if s["name"] == "libopus")
    opus["verification"]["expected_digest"] = "bad-hash"
    with pytest.raises(ValueError, match="64-hex expected_digest"):
        validate_acquisition_manifest(mutant2)

    # Wrong Opus published checksum policy
    mutant3 = copy.deepcopy(data)
    opus = next(s for s in mutant3["sources"] if s["name"] == "libopus")
    opus["verification"]["expected_digest"] = "f" * 64
    with pytest.raises(ValueError, match="libopus source parameters mismatch"):
        validate_acquisition_manifest(mutant3)

    # Wrong FFmpeg URL or signature
    mutant4 = copy.deepcopy(data)
    ffmpeg = next(s for s in mutant4["sources"] if s["name"] == "ffmpeg")
    ffmpeg["verification"]["signature_url"] = "https://example.com/fake.asc"
    with pytest.raises(ValueError, match="ffmpeg source parameters mismatch"):
        validate_acquisition_manifest(mutant4)

    # Wrong FFmpeg source commit provenance
    mutant5 = copy.deepcopy(data)
    ffmpeg = next(s for s in mutant5["sources"] if s["name"] == "ffmpeg")
    ffmpeg["source_commit"] = "0" * 40
    with pytest.raises(ValueError, match="ffmpeg source parameters mismatch"):
        validate_acquisition_manifest(mutant5)

    # Malformed optional source_commit (not 40 lowercase hex)
    mutant6 = copy.deepcopy(data)
    opus = next(s for s in mutant6["sources"] if s["name"] == "libopus")
    opus["source_commit"] = "NOT-A-VALID-HEX-STRING"
    with pytest.raises(ValueError, match="optional source_commit must be a 40-lowercase-hex string"):
        validate_acquisition_manifest(mutant6)

    # Missing/blank license string in source
    mutant7 = copy.deepcopy(data)
    ffmpeg = next(s for s in mutant7["sources"] if s["name"] == "ffmpeg")
    ffmpeg["license"] = "   "
    with pytest.raises(ValueError, match="must have a non-empty license string"):
        validate_acquisition_manifest(mutant7)


def test_acquisition_manifest_requires_exact_9_sources():
    data = load_json(MANIFEST_PATH)

    # Remove one source
    mutant1 = copy.deepcopy(data)
    mutant1["sources"] = [s for s in mutant1["sources"] if s["name"] != "amf"]
    with pytest.raises(ValueError, match="Missing:.*'amf'"):
        validate_acquisition_manifest(mutant1)

    # Add an extra source
    mutant2 = copy.deepcopy(data)
    mutant2["sources"].append({
        "name": "extra-src",
        "license": "MIT",
        "acquisition_type": "commit_archive",
        "commit": "1" * 40,
        "artifact_url": f"https://example.com/{'1' * 40}.tar.gz",
    })
    with pytest.raises(ValueError, match="Extra:.*'extra-src'"):
        validate_acquisition_manifest(mutant2)


def test_acquisition_manifest_msys2_schema_and_policy():
    data = load_json(MANIFEST_PATH)

    # Extra key in msys2
    mutant1 = copy.deepcopy(data)
    mutant1["msys2"]["closure"] = []
    with pytest.raises(ValueError, match="Extra:.*closure"):
        validate_acquisition_manifest(mutant1)

    # Reject prose or string policy field
    mutant2 = copy.deepcopy(data)
    mutant2["msys2"]["policy"] = "Prose policy not allowed"
    with pytest.raises(ValueError, match="policy string/prose is forbidden"):
        validate_acquisition_manifest(mutant2)

    # Missing immutable_retention
    mutant3 = copy.deepcopy(data)
    del mutant3["msys2"]["immutable_retention"]
    with pytest.raises(ValueError, match="Missing:.*immutable_retention"):
        validate_acquisition_manifest(mutant3)

    # Invalid immutable_retention.location_kind
    mutant4 = copy.deepcopy(data)
    mutant4["msys2"]["immutable_retention"]["location_kind"] = "upstream-mirror"
    with pytest.raises(ValueError, match="location_kind must be 'project-controlled'"):
        validate_acquisition_manifest(mutant4)

    # The closure verifier requires a stable project-controlled URI prefix.
    mutant5 = copy.deepcopy(data)
    del mutant5["msys2"]["immutable_retention"]["uri_prefix"]
    with pytest.raises(ValueError, match="uri_prefix"):
        validate_acquisition_manifest(mutant5)

    # Missing offline_install
    mutant5 = copy.deepcopy(data)
    del mutant5["msys2"]["offline_install"]
    with pytest.raises(ValueError, match="Missing:.*offline_install"):
        validate_acquisition_manifest(mutant5)

    # Invalid offline command
    mutant6 = copy.deepcopy(data)
    mutant6["msys2"]["offline_install"]["command"] = "pacman -S"
    with pytest.raises(ValueError, match="offline_install.command must be 'pacman -U'"):
        validate_acquisition_manifest(mutant6)

    # Missing or bad forbidden_commands
    mutant7 = copy.deepcopy(data)
    mutant7["msys2"]["offline_install"]["forbidden_commands"] = ["pacman -S"]
    with pytest.raises(ValueError, match="forbidden_commands must exactly match"):
        validate_acquisition_manifest(mutant7)


def test_acquisition_manifest_configure_flags_validation():
    data = load_json(MANIFEST_PATH)

    # Forbidden --enable-nonfree
    mutant1 = copy.deepcopy(data)
    mutant1["configure"]["flags"].append("--enable-nonfree")
    with pytest.raises(ValueError, match="Forbidden flag: --enable-nonfree"):
        validate_acquisition_manifest(mutant1)

    # Missing required flag
    mutant2 = copy.deepcopy(data)
    mutant2["configure"]["flags"].remove("--enable-nvenc")
    with pytest.raises(ValueError, match="Configure flags must exactly match required baseline"):
        validate_acquisition_manifest(mutant2)

    # Extra configure flag
    mutant3 = copy.deepcopy(data)
    mutant3["configure"]["flags"].append("--enable-extra")
    with pytest.raises(ValueError, match="Configure flags must exactly match required baseline"):
        validate_acquisition_manifest(mutant3)


def test_acquisition_manifest_outputs_validation():
    data = load_json(MANIFEST_PATH)

    # Declaring hash in outputs is forbidden in acquisition manifest
    mutant1 = copy.deepcopy(data)
    mutant1["outputs"][0]["sha256"] = "a" * 64
    with pytest.raises(ValueError, match="Forbidden hash/checksum key|Extra:"):
        validate_acquisition_manifest(mutant1)

    # Output identity mismatch
    mutant2 = copy.deepcopy(data)
    mutant2["outputs"][0]["version_prefix"] = "ffmpeg version 7.0.0"
    with pytest.raises(ValueError, match="Output ffmpeg mismatch"):
        validate_acquisition_manifest(mutant2)

    # Extra field in output item
    mutant3 = copy.deepcopy(data)
    mutant3["outputs"][0]["extra_meta"] = "bad"
    with pytest.raises(ValueError, match="Extra:.*extra_meta"):
        validate_acquisition_manifest(mutant3)


def test_valid_build_lock_fixture():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    validate_build_lock(lock, manifest)


def test_build_lock_requires_recipe_hash_to_match_manifest_hash():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    lock["recipe_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="recipe_sha256 must match acquisition_manifest_sha256"):
        validate_build_lock(lock, manifest)


def test_build_lock_patches_must_exactly_match_manifest():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    lock["patches"] = [
        {
            "name": "undeclared-patch",
            "path": "patches/undeclared.patch",
            "sha256": "0" * 64,
        }
    ]
    with pytest.raises(ValueError, match="patches do not exactly match acquisition manifest"):
        validate_build_lock(lock, manifest)


def test_build_lock_requires_manifest_retention_prefix():
    manifest = sample_valid_acquisition_manifest()
    del manifest["msys2"]["immutable_retention"]["uri_prefix"]
    with pytest.raises(ValueError, match="retention uri_prefix"):
        validate_build_lock(sample_valid_build_lock(), manifest)


def test_build_lock_top_level_schema():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    del lock["acquisition_manifest_sha256"]
    with pytest.raises(ValueError, match="Missing:.*acquisition_manifest_sha256"):
        validate_build_lock(lock, manifest)

    lock = sample_valid_build_lock()
    lock["extra_lock_key"] = "forbidden"
    with pytest.raises(ValueError, match="Extra:.*extra_lock_key"):
        validate_build_lock(lock, manifest)


def test_build_lock_manifest_and_recipe_hashes():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    lock["acquisition_manifest_sha256"] = "not-64-hex"
    with pytest.raises(ValueError, match="valid 64-hex acquisition_manifest_sha256"):
        validate_build_lock(lock, manifest)

    lock = sample_valid_build_lock()
    lock["recipe_sha256"] = "not-64-hex"
    with pytest.raises(ValueError, match="valid 64-hex recipe_sha256"):
        validate_build_lock(lock, manifest)


def test_build_lock_patches_order_mismatch_rejected():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    # Reverse lock patches order relative to manifest
    assert len(lock["patches"]) >= 2
    lock["patches"] = list(reversed(lock["patches"]))
    with pytest.raises(ValueError, match="Build lock patches do not exactly match acquisition manifest"):
        validate_build_lock(lock, manifest)


def test_build_lock_closure_must_include_all_9_sources():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    lock["sources"] = [s for s in lock["sources"] if s["name"] != "libvpl"]
    with pytest.raises(ValueError, match="Missing:.*'libvpl'"):
        validate_build_lock(lock, manifest)


def test_build_lock_missing_source_artifact_sha256_or_evidence():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    lock["sources"][0]["sha256"] = "short"
    with pytest.raises(ValueError, match="Source sha256 malformed"):
        validate_build_lock(lock, manifest)

    # Removal of a source SHA
    lock_missing_src_sha = sample_valid_build_lock()
    del lock_missing_src_sha["sources"][0]["sha256"]
    with pytest.raises(ValueError, match="Missing:.*'sha256'"):
        validate_build_lock(lock_missing_src_sha, manifest)

    # Removal of verification_evidence object
    lock_missing_evidence = sample_valid_build_lock()
    del lock_missing_evidence["sources"][0]["verification_evidence"]
    with pytest.raises(ValueError, match="Missing:.*'verification_evidence'"):
        validate_build_lock(lock_missing_evidence, manifest)

    lock = sample_valid_build_lock()
    lock["sources"][0]["verification_evidence"]["verified"] = False
    with pytest.raises(ValueError, match="Source verification evidence not verified"):
        validate_build_lock(lock, manifest)


def test_build_lock_msys2_closure_validations():
    manifest = sample_valid_acquisition_manifest()
    # Missing retention URI
    lock = sample_valid_build_lock()
    lock["msys2"]["packages"][0]["retention_uri"] = ""
    with pytest.raises(ValueError, match="Package missing or blank retention_uri"):
        validate_build_lock(lock, manifest)

    # Removal of MSYS2 package SHA
    lock_missing_pkg_sha = sample_valid_build_lock()
    del lock_missing_pkg_sha["msys2"]["packages"][0]["sha256"]
    with pytest.raises(ValueError, match="Missing:.*'sha256'"):
        validate_build_lock(lock_missing_pkg_sha, manifest)

    # Missing package checksum
    lock = sample_valid_build_lock()
    lock["msys2"]["packages"][0]["sha256"] = "not-hex"
    with pytest.raises(ValueError, match="Package sha256 malformed"):
        validate_build_lock(lock, manifest)

    # Missing package signature checksum
    lock = sample_valid_build_lock()
    lock["msys2"]["packages"][0]["signature_sha256"] = "bad"
    with pytest.raises(ValueError, match="Package signature_sha256 malformed"):
        validate_build_lock(lock, manifest)


def test_build_lock_rejects_output_binary_sha256():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    lock["outputs"][0]["sha256"] = "1" * 64
    with pytest.raises(ValueError, match="Forbidden hash/checksum key|Extra:"):
        validate_build_lock(lock, manifest)


def test_acquisition_manifest_enforces_fixed_source_types():
    data = load_json(MANIFEST_PATH)

    # Change ffmpeg to commit_archive
    mutant1 = copy.deepcopy(data)
    ffmpeg = next(s for s in mutant1["sources"] if s["name"] == "ffmpeg")
    ffmpeg["acquisition_type"] = "commit_archive"
    ffmpeg["commit"] = "e38092ef9395d7049f871ef4d5411eb410e283e0"
    del ffmpeg["version"]
    del ffmpeg["verification"]
    with pytest.raises(ValueError, match="must have acquisition_type 'official_release'"):
        validate_acquisition_manifest(mutant1)

    # Change x264 to official_release
    mutant2 = copy.deepcopy(data)
    x264 = next(s for s in mutant2["sources"] if s["name"] == "x264")
    x264["acquisition_type"] = "official_release"
    x264["version"] = "1.0"
    x264["verification"] = {"type": "pgp_signature", "signature_url": "https://example.com/sig.asc"}
    del x264["commit"]
    with pytest.raises(ValueError, match="must have acquisition_type 'commit_archive'"):
        validate_acquisition_manifest(mutant2)


def test_acquisition_manifest_recursively_rejects_hashes_in_patches():
    data = load_json(MANIFEST_PATH)
    mutant = copy.deepcopy(data)
    mutant["patches"] = [{"name": "patch1", "sha256": "0" * 64}]
    with pytest.raises(ValueError, match="Forbidden hash/checksum key 'sha256'"):
        validate_acquisition_manifest(mutant)


def test_acquisition_manifest_msys2_policy_prohibitions_and_structured():
    data = load_json(MANIFEST_PATH)

    # String policy is rejected
    mutant1 = copy.deepcopy(data)
    mutant1["msys2"]["policy"] = "Prose policy not permitted"
    del mutant1["msys2"]["immutable_retention"]
    del mutant1["msys2"]["offline_install"]
    with pytest.raises(ValueError, match="policy string/prose is forbidden"):
        validate_acquisition_manifest(mutant1)

    # Incomplete structured immutable_retention
    invalid_structured = copy.deepcopy(data)
    invalid_structured["msys2"]["immutable_retention"]["required"] = False
    with pytest.raises(ValueError, match="manifest.msys2.immutable_retention.required must be True"):
        validate_acquisition_manifest(invalid_structured)

    # Incomplete structured offline_install
    invalid_offline = copy.deepcopy(data)
    invalid_offline["msys2"]["offline_install"]["forbidden_commands"] = ["pacman -S"]
    with pytest.raises(ValueError, match="forbidden_commands must exactly match"):
        validate_acquisition_manifest(invalid_offline)


def test_reject_duplicate_identities():
    # Acquisition manifest duplicate source
    data = load_json(MANIFEST_PATH)
    mutant_acq = copy.deepcopy(data)
    mutant_acq["sources"].append(copy.deepcopy(mutant_acq["sources"][0]))
    with pytest.raises(ValueError, match="Duplicate source name detected"):
        validate_acquisition_manifest(mutant_acq)

    # Acquisition manifest duplicate output
    mutant_out = copy.deepcopy(data)
    mutant_out["outputs"].append(copy.deepcopy(mutant_out["outputs"][0]))
    with pytest.raises(ValueError, match="Duplicate output name detected"):
        validate_acquisition_manifest(mutant_out)

    # Acquisition manifest duplicate requested package
    mutant_pkg = copy.deepcopy(data)
    mutant_pkg["msys2"]["requested_packages"].append(mutant_pkg["msys2"]["requested_packages"][0])
    with pytest.raises(ValueError, match="Duplicate requested package detected"):
        validate_acquisition_manifest(mutant_pkg)

    # Build lock duplicate source
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()
    lock_dup_src = copy.deepcopy(lock)
    lock_dup_src["sources"].append(copy.deepcopy(lock_dup_src["sources"][0]))
    with pytest.raises(ValueError, match="Duplicate source identity detected"):
        validate_build_lock(lock_dup_src, manifest)

    # Build lock duplicate package
    lock_dup_pkg = copy.deepcopy(lock)
    lock_dup_pkg["msys2"]["packages"].append(copy.deepcopy(lock_dup_pkg["msys2"]["packages"][0]))
    with pytest.raises(ValueError, match="Duplicate package identity detected"):
        validate_build_lock(lock_dup_pkg, manifest)

    # Build lock duplicate database
    lock_dup_db = copy.deepcopy(lock)
    lock_dup_db["msys2"]["databases"].append(copy.deepcopy(lock_dup_db["msys2"]["databases"][0]))
    with pytest.raises(ValueError, match="Duplicate database identity detected"):
        validate_build_lock(lock_dup_db, manifest)

    # Build lock duplicate output
    lock_dup_out = copy.deepcopy(lock)
    lock_dup_out["outputs"].append(copy.deepcopy(lock_dup_out["outputs"][0]))
    with pytest.raises(ValueError, match="Duplicate output identity detected"):
        validate_build_lock(lock_dup_out, manifest)


def test_build_lock_package_closure_and_transitive_dependencies():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()

    # Missing one requested package from closure
    mutant = copy.deepcopy(lock)
    mutant["msys2"]["packages"] = [p for p in mutant["msys2"]["packages"] if p["name"] != "diffutils"]
    with pytest.raises(ValueError, match="MSYS2 package closure missing requested packages.*'diffutils'"):
        validate_build_lock(mutant, manifest)

    # Non-string package dependency entry
    mutant_nonstr_dep = copy.deepcopy(lock)
    mutant_nonstr_dep["msys2"]["packages"][0]["dependencies"] = [12345]
    with pytest.raises(ValueError, match="Package .* contains invalid dependency"):
        validate_build_lock(mutant_nonstr_dep, manifest)

    # Missing dependencies key on package
    mutant_nodep = copy.deepcopy(lock)
    del mutant_nodep["msys2"]["packages"][0]["dependencies"]
    with pytest.raises(ValueError, match="Missing:.*'dependencies'"):
        validate_build_lock(mutant_nodep, manifest)

    # Duplicate dependency entry in dependencies list
    mutant_dupdep = copy.deepcopy(lock)
    mutant_dupdep["msys2"]["packages"][0]["dependencies"] = ["mingw-w64-ucrt-x86_64-nasm", "mingw-w64-ucrt-x86_64-nasm"]
    with pytest.raises(ValueError, match="duplicate dependency"):
        validate_build_lock(mutant_dupdep, manifest)

    # Dangling dependency not in package names
    mutant_dangling = copy.deepcopy(lock)
    mutant_dangling["msys2"]["packages"][0]["dependencies"] = ["non-existent-pkg"]
    with pytest.raises(ValueError, match="dangling dependency 'non-existent-pkg'"):
        validate_build_lock(mutant_dangling, manifest)

    # Adding extra transitive package with explicit dependencies edges and complete closure succeeds
    # gcc -> isl -> gmp (both isl and gmp added to satisfy reachability and dependencies)
    complete_pkg_lock = copy.deepcopy(lock)
    gcc_pkg = next(p for p in complete_pkg_lock["msys2"]["packages"] if p["name"] == "mingw-w64-ucrt-x86_64-gcc")
    gcc_pkg["dependencies"] = ["mingw-w64-ucrt-x86_64-isl"]

    complete_pkg_lock["msys2"]["packages"].append({
        "name": "mingw-w64-ucrt-x86_64-isl",
        "version": "0.26-1",
        "filename": "mingw-w64-ucrt-x86_64-isl-0.26-1-any.pkg.tar.zst",
        "sha256": "f" * 64,
        "signature_sha256": "0" * 64,
        "signature": {
            "filename": "isl.sig",
            "sha256": "0" * 64,
            "retention_uri": "project://ffmpeg-build/signatures/isl.sig",
            "verified": True,
            "verifier": "pacman-key",
            "signer": "MSYS2 package signing key",
        },
        "retention_uri": "project://ffmpeg-build/packages/isl.pkg.tar.zst",
        "dependencies": ["mingw-w64-ucrt-x86_64-gmp"],
    })
    complete_pkg_lock["msys2"]["packages"].append({
        "name": "mingw-w64-ucrt-x86_64-gmp",
        "version": "6.3.0-2",
        "filename": "mingw-w64-ucrt-x86_64-gmp-6.3.0-2-any.pkg.tar.zst",
        "sha256": "e" * 64,
        "signature_sha256": "1" * 64,
        "signature": {
            "filename": "gmp.sig",
            "sha256": "1" * 64,
            "retention_uri": "project://ffmpeg-build/signatures/gmp.sig",
            "verified": True,
            "verifier": "pacman-key",
            "signer": "MSYS2 package signing key",
        },
        "retention_uri": "project://ffmpeg-build/packages/gmp.pkg.tar.zst",
        "dependencies": [],
    })
    validate_build_lock(complete_pkg_lock, manifest)

    # Transitive package unreachable from requested packages rejected
    unreachable_lock = copy.deepcopy(lock)
    unreachable_lock["msys2"]["packages"].append({
        "name": "mingw-w64-ucrt-x86_64-isolated",
        "version": "1.0.0-1",
        "filename": "mingw-w64-ucrt-x86_64-isolated-1.0.0-1-any.pkg.tar.zst",
        "sha256": "a" * 64,
        "signature_sha256": "b" * 64,
        "signature": {
            "filename": "isolated.sig",
            "sha256": "b" * 64,
            "retention_uri": "project://ffmpeg-build/signatures/isolated.sig",
            "verified": True,
            "verifier": "pacman-key",
            "signer": "MSYS2 package signing key",
        },
        "retention_uri": "project://ffmpeg-build/packages/isolated.pkg.tar.zst",
        "dependencies": [],
    })
    with pytest.raises(ValueError, match="Transitive MSYS2 packages not reachable from requested packages"):
        validate_build_lock(unreachable_lock, manifest)


def test_build_lock_source_binding_and_evidence():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()

    # Commit archive source binding commit mismatch
    mutant1 = copy.deepcopy(lock)
    x264 = next(s for s in mutant1["sources"] if s["name"] == "x264")
    x264["commit"] = "0" * 40
    with pytest.raises(ValueError, match="commit mismatch"):
        validate_build_lock(mutant1, manifest)

    # Commit archive source must not have artifact_url
    mutant_art_url = copy.deepcopy(lock)
    x264 = next(s for s in mutant_art_url["sources"] if s["name"] == "x264")
    x264["artifact_url"] = "https://example.com/not-allowed.tar.gz"
    with pytest.raises(ValueError, match="Extra:.*artifact_url|forbidden"):
        validate_build_lock(mutant_art_url, manifest)

    # Commit archive remote mismatch
    mutant_remote = copy.deepcopy(lock)
    x264 = next(s for s in mutant_remote["sources"] if s["name"] == "x264")
    x264["upstream_remote_url"] = "https://example.com/other-remote.git"
    with pytest.raises(ValueError, match="upstream_remote_url mismatch"):
        validate_build_lock(mutant_remote, manifest)

    # Canonical origin other than git_archive
    mutant_origin = copy.deepcopy(lock)
    x264 = next(s for s in mutant_origin["sources"] if s["name"] == "x264")
    x264["canonical_artifact"]["origin"] = "http"
    with pytest.raises(ValueError, match="origin must be git_archive"):
        validate_build_lock(mutant_origin, manifest)

    # Canonical filename wrong or mismatched
    mutant_canon_fn_wrong = copy.deepcopy(lock)
    x264 = next(s for s in mutant_canon_fn_wrong["sources"] if s["name"] == "x264")
    x264["canonical_artifact"]["filename"] = "wrong-filename.tar.gz"
    with pytest.raises(ValueError, match="canonical_artifact filename must be"):
        validate_build_lock(mutant_canon_fn_wrong, manifest)

    # Canonical filename empty / non-string
    mutant_canon_fn_blank = copy.deepcopy(lock)
    x264 = next(s for s in mutant_canon_fn_blank["sources"] if s["name"] == "x264")
    x264["canonical_artifact"]["filename"] = ""
    with pytest.raises(ValueError, match="canonical_artifact filename must be"):
        validate_build_lock(mutant_canon_fn_blank, manifest)

    # Malformed canonical SHA
    mutant_canon_sha = copy.deepcopy(lock)
    x264 = next(s for s in mutant_canon_sha["sources"] if s["name"] == "x264")
    x264["canonical_artifact"]["sha256"] = "bad-sha"
    with pytest.raises(ValueError, match="sha256"):
        validate_build_lock(mutant_canon_sha, manifest)

    # Malformed canonical retention URI prefix
    mutant_canon_uri = copy.deepcopy(lock)
    x264 = next(s for s in mutant_canon_uri["sources"] if s["name"] == "x264")
    x264["canonical_artifact"]["retention_uri"] = "http://bad/uri"
    with pytest.raises(ValueError, match="retention_uri"):
        validate_build_lock(mutant_canon_uri, manifest)

    # Git bundle SHA mismatch
    mutant_bundle_sha = copy.deepcopy(lock)
    x264 = next(s for s in mutant_bundle_sha["sources"] if s["name"] == "x264")
    x264["verification_evidence"]["git_bundle_sha256"] = "bad-sha"
    with pytest.raises(ValueError, match="git_bundle_sha256"):
        validate_build_lock(mutant_bundle_sha, manifest)

    # Archive command omitting commit
    mutant_cmd = copy.deepcopy(lock)
    x264 = next(s for s in mutant_cmd["sources"] if s["name"] == "x264")
    x264["verification_evidence"]["archive_command"] = "git archive HEAD"
    with pytest.raises(ValueError, match="archive_command"):
        validate_build_lock(mutant_cmd, manifest)

    # Official release source binding version/url mismatch
    mutant3 = copy.deepcopy(lock)
    ffmpeg = next(s for s in mutant3["sources"] if s["name"] == "ffmpeg")
    ffmpeg["version"] = "6.1.0"
    with pytest.raises(ValueError, match="identity mismatch with official release"):
        validate_build_lock(mutant3, manifest)

    # Changing retention uri_prefix in manifest causes Git canonical/bundle URI to fail if using old prefix
    mutant_retention_prefix = copy.deepcopy(manifest)
    mutant_retention_prefix["msys2"]["immutable_retention"]["uri_prefix"] = "project://custom-prefix/"
    mutant_retention_lock = copy.deepcopy(lock)
    # Update MSYS2 URIs to match new prefix so it specifically tests Git source retention failure
    mutant_retention_lock["msys2"]["installer"]["retention_uri"] = "project://custom-prefix/msys2/installer.tar.xz"
    mutant_retention_lock["msys2"]["installer"]["signature"]["retention_uri"] = "project://custom-prefix/signatures/installer.sig"
    for db in mutant_retention_lock["msys2"]["databases"]:
        db["retention_uri"] = f"project://custom-prefix/msys2/{db['name']}"
        db["signature"]["retention_uri"] = f"project://custom-prefix/signatures/{db['name']}.sig"
    for pkg in mutant_retention_lock["msys2"]["packages"]:
        pkg["retention_uri"] = f"project://custom-prefix/packages/{pkg['filename']}"
        pkg["signature"]["retention_uri"] = f"project://custom-prefix/signatures/{pkg['filename']}.sig"
    with pytest.raises(ValueError, match="canonical_artifact retention_uri must be"):
        validate_build_lock(mutant_retention_lock, mutant_retention_prefix)

    # Mutate canonical_artifact.retention_uri to a different URI that still uses valid prefix
    mutant_diff_retention = copy.deepcopy(lock)
    x264 = next(s for s in mutant_diff_retention["sources"] if s["name"] == "x264")
    x264["canonical_artifact"]["retention_uri"] = "project://ffmpeg-build/git/x264/different.tar.gz"
    with pytest.raises(ValueError, match="canonical_artifact retention_uri must be"):
        validate_build_lock(mutant_diff_retention, manifest)

    # Commit archive evidence type mismatch
    mutant4 = copy.deepcopy(lock)
    x264 = next(s for s in mutant4["sources"] if s["name"] == "x264")
    x264["verification_evidence"]["type"] = "pgp_signature"
    with pytest.raises(ValueError, match="verification evidence type must be commit_archive"):
        validate_build_lock(mutant4, manifest)

    # Commit archive evidence artifact_sha256 mismatch
    mutant4b = copy.deepcopy(lock)
    x264 = next(s for s in mutant4b["sources"] if s["name"] == "x264")
    x264["verification_evidence"]["artifact_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="evidence artifact_sha256 must match entry sha256"):
        validate_build_lock(mutant4b, manifest)

    # Commit archive evidence commit mismatch
    mutant4c = copy.deepcopy(lock)
    x264 = next(s for s in mutant4c["sources"] if s["name"] == "x264")
    x264["verification_evidence"]["commit"] = "0" * 40
    with pytest.raises(ValueError, match="evidence commit must match entry commit"):
        validate_build_lock(mutant4c, manifest)

    # Commit archive evidence missing verifier
    mutant4d = copy.deepcopy(lock)
    x264 = next(s for s in mutant4d["sources"] if s["name"] == "x264")
    x264["verification_evidence"]["verifier"] = "  "
    with pytest.raises(ValueError, match="evidence verifier"):
        validate_build_lock(mutant4d, manifest)

    # Commit archive evidence invalid git_version
    for invalid_git_version in ("", "   ", None, 123):
        mutant_git_ver = copy.deepcopy(lock)
        x264 = next(s for s in mutant_git_ver["sources"] if s["name"] == "x264")
        x264["verification_evidence"]["git_version"] = invalid_git_version
        with pytest.raises(ValueError, match="git_version must be a non-empty string"):
            validate_build_lock(mutant_git_ver, manifest)

    # Commit archive evidence extra key
    mutant4e = copy.deepcopy(lock)
    x264 = next(s for s in mutant4e["sources"] if s["name"] == "x264")
    x264["verification_evidence"]["unexpected_key"] = "bad"
    with pytest.raises(ValueError, match="Extra:.*unexpected_key"):
        validate_build_lock(mutant4e, manifest)

    # FFmpeg official release evidence signer missing
    mutant4f = copy.deepcopy(lock)
    ffmpeg = next(s for s in mutant4f["sources"] if s["name"] == "ffmpeg")
    ffmpeg["verification_evidence"]["signer"] = ""
    with pytest.raises(ValueError, match="evidence signer must be non-empty string"):
        validate_build_lock(mutant4f, manifest)

    # FFmpeg official release evidence sha256 mismatch
    mutant4g = copy.deepcopy(lock)
    ffmpeg = next(s for s in mutant4g["sources"] if s["name"] == "ffmpeg")
    ffmpeg["verification_evidence"]["artifact_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="evidence artifact_sha256 must match entry sha256"):
        validate_build_lock(mutant4g, manifest)

    # FFmpeg official release signature URL mismatch
    mutant4h = copy.deepcopy(lock)
    ffmpeg = next(s for s in mutant4h["sources"] if s["name"] == "ffmpeg")
    ffmpeg["verification_evidence"]["signature_url"] = "https://example.com/other.asc"
    with pytest.raises(ValueError, match="evidence signature_url mismatch"):
        validate_build_lock(mutant4h, manifest)

    # Changing both libopus source SHA and evidence artifact SHA to the same wrong 64-hex
    # must make validate_build_lock fail because it must equal declared published expected_digest
    mutant_opus_sha = copy.deepcopy(lock)
    wrong_sha = "0" * 64
    opus = next(s for s in mutant_opus_sha["sources"] if s["name"] == "libopus")
    opus["sha256"] = wrong_sha
    opus["verification_evidence"]["artifact_sha256"] = wrong_sha
    with pytest.raises(ValueError, match="libopus entry sha256 mismatch with declared published expected_digest"):
        validate_build_lock(mutant_opus_sha, manifest)

    # Libopus official release evidence verifier missing
    mutant4i = copy.deepcopy(lock)
    opus = next(s for s in mutant4i["sources"] if s["name"] == "libopus")
    opus["verification_evidence"]["verifier"] = ""
    with pytest.raises(ValueError, match="evidence verifier must be non-empty string"):
        validate_build_lock(mutant4i, manifest)

    # Libopus official release evidence sha256 mismatch
    mutant4j = copy.deepcopy(lock)
    opus = next(s for s in mutant4j["sources"] if s["name"] == "libopus")
    opus["verification_evidence"]["artifact_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="evidence artifact_sha256 must match entry sha256"):
        validate_build_lock(mutant4j, manifest)

    # Evidence verified boolean not True
    mutant5 = copy.deepcopy(lock)
    ffmpeg = next(s for s in mutant5["sources"] if s["name"] == "ffmpeg")
    ffmpeg["verification_evidence"]["verified"] = "yes"
    with pytest.raises(ValueError, match="verification evidence not verified"):
        validate_build_lock(mutant5, manifest)


def test_validate_cached_inputs_success_missing_and_corrupted(tmp_path):
    import hashlib
    lock = sample_valid_build_lock()
    cache_dir = tmp_path / "source_cache"
    cache_dir.mkdir()

    # Create real files matching each source
    for idx, src in enumerate(lock["sources"]):
        data = f"payload-for-{src['name']}-{idx}".encode("utf-8")
        real_sha = hashlib.sha256(data).hexdigest()
        if src["acquisition_type"] == "commit_archive":
            src["canonical_artifact"]["sha256"] = real_sha
        else:
            src["sha256"] = real_sha
        src["verification_evidence"]["artifact_sha256"] = real_sha
        target_file = cache_dir / real_sha
        target_file.write_bytes(data)

    # Success case: all cached files exist, are regular files, and match sha256
    validate_cached_inputs(lock, cache_dir)

    # Missing file case
    first_src = lock["sources"][0]
    expected_first_sha = first_src["sha256"] if first_src["acquisition_type"] == "official_release" else first_src["canonical_artifact"]["sha256"]
    (cache_dir / expected_first_sha).unlink()
    with pytest.raises(ValueError, match=f"Cached artifact missing for source '{first_src['name']}'"):
        validate_cached_inputs(lock, cache_dir)

    # Not a regular file (directory instead of file)
    (cache_dir / expected_first_sha).mkdir()
    with pytest.raises(ValueError, match=f"Cached artifact for source '{first_src['name']}' is not a regular file"):
        validate_cached_inputs(lock, cache_dir)
    (cache_dir / expected_first_sha).rmdir()

    # Corrupt content case (sha256 mismatch)
    corrupted_data = b"corrupted-tampered-content"
    (cache_dir / expected_first_sha).write_bytes(corrupted_data)
    with pytest.raises(ValueError, match=f"Cached artifact digest mismatch for source '{first_src['name']}'"):
        validate_cached_inputs(lock, cache_dir)


def test_later_stage_validator_stubs_raise_not_implemented():
    lock = sample_valid_build_lock()
    with pytest.raises(NotImplementedError, match="Task 5"):
        validate_release(lock, {}, {}, Path("/tmp"))


def test_build_lock_rejects_nonexact_git_verifier():
    manifest = load_json(MANIFEST_PATH)
    lock = sample_valid_build_lock()
    x264 = next(s for s in lock["sources"] if s["name"] == "x264")
    x264["verification_evidence"]["verifier"] = "git-archive-verifier"
    with pytest.raises(ValueError, match="git-rev-parse-and-archive"):
        validate_build_lock(lock, manifest)


@pytest.mark.parametrize(
    "tampered_archive_command",
    [
        "git archive --format=tar --prefix=x264-{commit}/ {commit}",
        "git archive --format=tar.gz --prefix=x264-{commit}/ {commit}; evil",
        "git archive --format=tar.gz --prefix=x264-{commit}/ {commit} ",
    ],
)
def test_build_lock_rejects_nonexact_git_archive_command(tampered_archive_command: str):
    manifest = load_json(MANIFEST_PATH)
    lock = sample_valid_build_lock()
    x264 = next(s for s in lock["sources"] if s["name"] == "x264")
    commit = x264["commit"]
    x264["verification_evidence"]["archive_command"] = (
        tampered_archive_command.format(commit=commit)
    )
    with pytest.raises(ValueError, match="archive_command"):
        validate_build_lock(lock, manifest)


def test_load_json_rejects_duplicate_top_level_key(tmp_path: Path):
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text('{"schema_version": "1.0.0", "schema_version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON object member: schema_version"):
        load_json(manifest_file)


def test_load_json_rejects_duplicate_nested_source_key(tmp_path: Path):
    content = """{
        "schema_version": "1.0.0",
        "sources": [
            {
                "name": "ffmpeg",
                "name": "ffmpeg",
                "acquisition_type": "official_release"
            }
        ]
    }"""
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON object member: name"):
        load_json(manifest_file)


def test_decode_json_without_duplicate_keys_rejects_nested_key():
    content = '{"a": {"b": 1, "b": 2}}'
    with pytest.raises(ValueError, match="duplicate JSON object member: b"):
        decode_json_without_duplicate_keys(content)


def test_validate_build_lock_rejects_swapped_git_retention_uris():
    manifest = sample_valid_acquisition_manifest()
    lock = sample_valid_build_lock()

    # Swap bundle_retention_uri to another valid project git URI
    bad_bundle_lock = copy.deepcopy(lock)
    x264 = next(s for s in bad_bundle_lock["sources"] if s["name"] == "x264")
    x264["verification_evidence"]["bundle_retention_uri"] = (
        "project://ffmpeg-build/git/x265/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle"
    )
    with pytest.raises(ValueError, match="bundle_retention_uri"):
        validate_build_lock(bad_bundle_lock, manifest)

    # Swap canonical_archive_retention_uri and canonical_artifact.retention_uri to another valid git URI under same prefix
    bad_archive_lock = copy.deepcopy(lock)
    x264_arch = next(s for s in bad_archive_lock["sources"] if s["name"] == "x264")
    wrong_archive_uri = "project://ffmpeg-build/git/x264/f0c1022b6be121a753ff02853fbe33da71988656.tar.gz"
    x264_arch["canonical_artifact"]["retention_uri"] = wrong_archive_uri
    x264_arch["verification_evidence"]["canonical_archive_retention_uri"] = wrong_archive_uri
    with pytest.raises(ValueError, match="canonical_artifact retention_uri must be"):
        validate_build_lock(bad_archive_lock, manifest)


def test_manifest_declares_reviewable_x265_cmake_patch() -> None:
    manifest = load_json(MANIFEST_PATH)
    assert manifest["patches"] == [
        {
            "name": "x265-cmake-4.4-compatibility",
            "path": "packaging/ffmpeg-build/patches/x265-cmake-4.4-compatibility.patch",
        },
        {
            "name": "x265-pkgconfig-libs-private-no-lgcc_s",
            "path": "packaging/ffmpeg-build/patches/x265-pkgconfig-libs-private-no-lgcc_s.patch",
        },
    ]
    for patch in manifest["patches"]:
        assert (REPO_ROOT / patch["path"]).is_file()


def test_validate_build_record_accepts_avicap32_dll() -> None:
    import hashlib
    from test_build_ffmpeg_script import sample_valid_build_record

    lock = sample_valid_build_lock()
    record = sample_valid_build_record(lock)
    record["command_log_sha256"] = hashlib.sha256(
        ("\n".join(record["commands_executed"]) + "\n").encode("utf-8")
    ).hexdigest()
    record["pe_import_audit"]["ffmpeg.exe"]["imported_dlls"].append("AVICAP32.dll")
    record["pe_import_audit"]["ffprobe.exe"]["imported_dlls"].append("AVICAP32.dll")

    validate_build_record(lock, record)


def test_validate_build_record_requires_encoders_sha256() -> None:
    from test_build_ffmpeg_script import sample_valid_build_record

    lock = sample_valid_build_lock()
    record = sample_valid_build_record(lock)
    record["command_log_sha256"] = hashlib.sha256(
        ("\n".join(record["commands_executed"]) + "\n").encode("utf-8")
    ).hexdigest()
    record.pop("encoders_sha256", None)
    with pytest.raises(ValueError, match="encoders_sha256"):
        validate_build_record(lock, record)


def test_validate_build_record_rejects_noncanonical_encoders_sha256() -> None:
    from test_build_ffmpeg_script import sample_valid_build_record

    lock = sample_valid_build_lock()
    record = sample_valid_build_record(lock)
    record["command_log_sha256"] = hashlib.sha256(
        ("\n".join(record["commands_executed"]) + "\n").encode("utf-8")
    ).hexdigest()
    record["encoders_sha256"] = "A" * 64
    with pytest.raises(ValueError, match="encoders_sha256"):
        validate_build_record(lock, record)

