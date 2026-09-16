"""Tests for parsing strict FFmpeg acquisition reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from video_converter.ffmpeg_build.acquisition_report import (
    AcquisitionReport,
    Msys2DatabaseEvidence,
    Msys2InstallerEvidence,
    Msys2PackageEvidence,
    Msys2ReportEvidence,
    Msys2SignatureEvidence,
    PatchEvidence,
    SourceEvidence,
    parse_acquisition_report,
)


def sample_git_source_evidence() -> dict[str, Any]:
    return {
        "type": "commit_archive",
        "verified": True,
        "artifact_sha256": "1" * 64,
        "commit": "c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        "verifier": "git-rev-parse-and-archive",
        "remote_url": "https://code.videolan.org/videolan/x264.git",
        "archive_command": "git archive --format=tar.gz --prefix=x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497/ c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        "git_version": "git version 2.55.0",
        "git_bundle_sha256": "2" * 64,
        "bundle_retention_uri": "project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle",
        "canonical_archive_retention_uri": "project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
    }


def sample_valid_report_data() -> dict[str, Any]:
    git_evidence_builder = lambda commit, name: {
        "type": "commit_archive",
        "verified": True,
        "artifact_sha256": "2" * 64,
        "commit": commit,
        "verifier": "git-rev-parse-and-archive",
        "remote_url": f"https://example.com/{name}.git",
        "archive_command": f"git archive --format=tar.gz --prefix={name}-{commit}/ {commit}",
        "git_version": "git version 2.55.0",
        "git_bundle_sha256": "3" * 64,
        "bundle_retention_uri": f"project://ffmpeg-build/git/{name}/{commit}.bundle",
        "canonical_archive_retention_uri": f"project://ffmpeg-build/git/{name}/{commit}.tar.gz",
    }
    return {
        "recipe_sha256": "a" * 64,
        "source_evidence": {
            "ffmpeg": {
                "type": "pgp_signature",
                "verified": True,
                "artifact_sha256": "1" * 64,
                "signature_url": "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
                "signer": "ffmpeg-release-signing-key",
            },
            "x264": sample_git_source_evidence(),
            "x265": git_evidence_builder("f0c1022b6be121a753ff02853fbe33da71988656", "x265"),
            "libvpx": git_evidence_builder("10b9492dcf05b652e2e4b370e205bd605d421972", "libvpx"),
            "svt-av1": git_evidence_builder("59645eea34e2815b627b8293aa3af254eddd0d69", "svt-av1"),
            "libopus": {
                "type": "published_checksum",
                "algorithm": "sha256",
                "expected_digest": "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f",
                "verified": True,
                "artifact_sha256": "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f",
                "verifier": "sha256-verifier",
            },
            "nv-codec-headers": git_evidence_builder("1889e62e2d35ff7aa9baca2bceb14f053785e6f1", "nv-codec-headers"),
            "amf": git_evidence_builder("c48e50ad6c8723c006b2c145d8fa49ecc0651022", "amf"),
            "libvpl": git_evidence_builder("11a9bbda5b22ac1c544da59b4007bb57f737b487", "libvpl"),
        },
        "msys2": {
            "installer": {
                "url": "https://repo.msys2.org/distrib/msys2-x86_64-latest.tar.xz",
                "sha256": "b" * 64,
                "signature_filename": "msys2-x86_64-latest.tar.xz.sig",
                "signature_sha256": "f" * 64,
                "signature_retention_uri": "https://storage.example.com/msys2/installer.tar.xz.sig",
                "retention_uri": "https://storage.example.com/msys2/installer.tar.xz",
                "signature_verification": {
                    "verified": True,
                    "verifier": "gpgv",
                    "signer": "msys2-keyring",
                },
            },
            "databases": [
                {
                    "name": "ucrt64.db",
                    "sha256": "c" * 64,
                    "signature_filename": "ucrt64.db.sig",
                    "signature_sha256": "8" * 64,
                    "signature_retention_uri": "https://storage.example.com/msys2/ucrt64.db.sig",
                    "retention_uri": "https://storage.example.com/msys2/ucrt64.db",
                    "signature_verification": {
                        "verified": True,
                        "verifier": "gpgv",
                        "signer": "msys2-keyring",
                    },
                }
            ],
            "packages": [
                {
                    "name": "mingw-w64-ucrt-x86_64-gcc",
                    "version": "13.2.0-1",
                    "filename": "mingw-w64-ucrt-x86_64-gcc-13.2.0-1-any.pkg.tar.zst",
                    "sha256": "d" * 64,
                    "signature_filename": "mingw-w64-ucrt-x86_64-gcc-13.2.0-1-any.pkg.tar.zst.sig",
                    "signature_sha256": "e" * 64,
                    "signature_retention_uri": "https://storage.example.com/packages/mingw-w64-ucrt-x86_64-gcc-13.2.0-1-any.pkg.tar.zst.sig",
                    "retention_uri": "https://storage.example.com/packages/mingw-w64-ucrt-x86_64-gcc-13.2.0-1-any.pkg.tar.zst",
                    "dependencies": [],
                    "signature_verification": {
                        "verified": True,
                        "verifier": "gpgv",
                        "signer": "msys2-keyring",
                    },
                }
            ],
        },
        "patches": [
            {
                "name": "dummy-patch",
                "path": "packaging/ffmpeg-build/patches/dummy.patch",
                "sha256": "0" * 64,
            }
        ],
    }


def write_json(tmp_path: Path, data: dict[str, Any]) -> Path:
    target = tmp_path / "report.json"
    target.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return target


def test_parse_report_rejects_duplicate_json_object_member(tmp_path: Path):
    target = tmp_path / "duplicate.json"
    target.write_text('{"recipe_sha256":"a", "recipe_sha256":"b"}', encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate JSON object member: recipe_sha256"):
        parse_acquisition_report(target)


@pytest.fixture
def valid_report_data() -> dict[str, Any]:
    return sample_valid_report_data()


@pytest.fixture
def valid_report_path(tmp_path: Path, valid_report_data: dict[str, Any]) -> Path:
    return write_json(tmp_path, valid_report_data)


def test_parse_report_returns_immutable_typed_values(valid_report_path: Path):
    report = parse_acquisition_report(valid_report_path)
    assert isinstance(report, AcquisitionReport)
    assert report.recipe_sha256 == "a" * 64
    assert len(report.source_evidence) == 9
    assert "x264" in report.source_evidence

    x264_ev = report.source_evidence["x264"]
    assert isinstance(x264_ev, SourceEvidence)
    assert x264_ev.commit == "c24e06c2e184345ceb33eb20a15d1024d9fd3497"
    assert x264_ev.type == "commit_archive"
    assert x264_ev.verified is True
    assert x264_ev.artifact_sha256 == "1" * 64
    assert x264_ev.verifier == "git-rev-parse-and-archive"
    assert x264_ev.remote_url == "https://code.videolan.org/videolan/x264.git"
    assert (
        x264_ev.archive_command
        == "git archive --format=tar.gz --prefix=x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497/ c24e06c2e184345ceb33eb20a15d1024d9fd3497"
    )
    assert x264_ev.git_version == "git version 2.55.0"
    assert x264_ev.git_bundle_sha256 == "2" * 64
    assert (
        x264_ev.bundle_retention_uri
        == "project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle"
    )
    assert (
        x264_ev.canonical_archive_retention_uri
        == "project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz"
    )

    ffmpeg_ev = report.source_evidence["ffmpeg"]
    assert ffmpeg_ev.type == "pgp_signature"
    assert ffmpeg_ev.signer == "ffmpeg-release-signing-key"
    assert ffmpeg_ev.signature_url == "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc"

    opus_ev = report.source_evidence["libopus"]
    assert opus_ev.type == "published_checksum"
    assert opus_ev.algorithm == "sha256"
    assert opus_ev.expected_digest == "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f"

    assert isinstance(report.msys2, Msys2ReportEvidence)
    assert isinstance(report.msys2.installer, Msys2InstallerEvidence)
    assert report.msys2.installer.sha256 == "b" * 64
    assert report.msys2.installer.signature_sha256 == "f" * 64
    assert isinstance(report.msys2.installer.signature, Msys2SignatureEvidence)
    assert report.msys2.installer.signature.signature_filename == "msys2-x86_64-latest.tar.xz.sig"
    assert report.msys2.installer.signature.signature_sha256 == "f" * 64
    assert (
        report.msys2.installer.signature.signature_retention_uri
        == "https://storage.example.com/msys2/installer.tar.xz.sig"
    )
    assert report.msys2.installer.signature.verified is True
    assert report.msys2.installer.signature.verifier == "gpgv"
    assert report.msys2.installer.signature.signer == "msys2-keyring"

    assert isinstance(report.msys2.databases[0], Msys2DatabaseEvidence)
    assert report.msys2.databases[0].signature_sha256 == "8" * 64
    assert isinstance(report.msys2.databases[0].signature, Msys2SignatureEvidence)
    assert report.msys2.databases[0].signature.signature_sha256 == "8" * 64

    assert isinstance(report.msys2.packages[0], Msys2PackageEvidence)
    assert report.msys2.packages[0].dependencies == ()
    assert isinstance(report.msys2.packages[0].signature, Msys2SignatureEvidence)
    assert report.msys2.packages[0].signature.signature_sha256 == "e" * 64

    assert isinstance(report.patches[0], PatchEvidence)
    assert report.patches[0].sha256 == "0" * 64

    with pytest.raises(AttributeError):
        report.msys2.installer.signature.verified = False  # type: ignore[misc]

    with pytest.raises(AttributeError):
        report.recipe_sha256 = "b" * 64  # type: ignore[misc]

    # Immutability tests for source_evidence Mapping
    with pytest.raises(TypeError):
        report.source_evidence["x264"] = report.source_evidence["ffmpeg"]  # type: ignore[index]

    with pytest.raises(TypeError):
        del report.source_evidence["x264"]  # type: ignore[misc]

    with pytest.raises(AttributeError):
        report.source_evidence.clear()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.pop("msys2"),
        lambda data: data.pop("source_evidence"),
        lambda data: data.pop("recipe_sha256"),
        lambda data: data.pop("patches"),
        lambda data: data.__setitem__("extra_top_key", "value"),
        lambda data: data["source_evidence"].__setitem__("extra", {}),
        lambda data: data["source_evidence"].pop("x264"),
        lambda data: data.__setitem__("recipe_sha256", "not-a-sha"),
        lambda data: data.__setitem__("recipe_sha256", "A" * 64),
        lambda data: data["msys2"]["packages"][0].pop("signature_sha256"),
        lambda data: data["msys2"]["packages"][0].__setitem__("dependencies", [3]),
        lambda data: data["msys2"]["packages"][0].__setitem__("retention_uri", ""),
        lambda data: data["msys2"]["installer"].__setitem__("url", ""),
        lambda data: data["msys2"]["installer"].pop("signature_sha256"),
        lambda data: data["msys2"]["installer"].__setitem__("signature_sha256", "short"),
        lambda data: data["msys2"]["installer"].__setitem__("signature_sha256", "G" * 64),
        lambda data: data["msys2"]["databases"][0].__setitem__("sha256", "short"),
        lambda data: data["msys2"]["databases"][0].pop("signature_sha256"),
        lambda data: data["msys2"]["databases"][0].__setitem__("signature_sha256", "short"),
        lambda data: data["msys2"]["databases"][0].__setitem__("signature_sha256", "G" * 64),
        lambda data: data["patches"][0].__setitem__("path", ""),
        lambda data: data["source_evidence"]["x264"].pop("commit"),
        lambda data: data["source_evidence"]["x264"].__setitem__("unknown_key", "extra"),
        lambda data: data["source_evidence"]["x264"].pop("remote_url"),
        lambda data: data["source_evidence"]["x264"].__setitem__("remote_url", "http://code.videolan.org/videolan/x264.git"),
        lambda data: data["source_evidence"]["x264"].__setitem__("git_bundle_sha256", "bad-hash"),
        lambda data: data["source_evidence"]["x264"].__setitem__("git_bundle_sha256", "2" * 63),
        lambda data: data["source_evidence"]["x264"].__setitem__("bundle_retention_uri", "https://storage.example.com/bundle.bundle"),
        lambda data: data["source_evidence"]["x264"].__setitem__("canonical_archive_retention_uri", "https://storage.example.com/archive.tar.gz"),
        lambda data: data["source_evidence"]["x264"].__setitem__("archive_command", "git archive --format=tar.gz HEAD"),
        lambda data: data["source_evidence"]["ffmpeg"].__setitem__("remote_url", "https://example.com/ffmpeg.git"),
    ],
)
def test_parse_report_rejects_invalid_schema(
    tmp_path: Path, valid_report_data: dict[str, Any], mutation: Callable[[dict[str, Any]], None]
):
    mutation(valid_report_data)
    with pytest.raises(ValueError):
        parse_acquisition_report(write_json(tmp_path, valid_report_data))


def test_parse_report_rejects_signature_verified_false(
    tmp_path: Path, valid_report_data: dict[str, Any]
):
    valid_report_data["msys2"]["installer"]["signature_verification"]["verified"] = False
    with pytest.raises(ValueError):
        parse_acquisition_report(write_json(tmp_path, valid_report_data))


def test_parse_report_rejects_missing_signature_retention_uri(
    tmp_path: Path, valid_report_data: dict[str, Any]
):
    del valid_report_data["msys2"]["installer"]["signature_retention_uri"]
    with pytest.raises(ValueError):
        parse_acquisition_report(write_json(tmp_path, valid_report_data))


def test_parse_report_rejects_nonexact_git_verifier(
    tmp_path: Path, valid_report_data: dict[str, Any]
):
    valid_report_data["source_evidence"]["x264"]["verifier"] = "git-archive-verifier"
    with pytest.raises(ValueError, match="git-rev-parse-and-archive"):
        parse_acquisition_report(write_json(tmp_path, valid_report_data))


@pytest.mark.parametrize(
    "tampered_archive_command",
    [
        "git archive --format=tar --prefix=x264-{commit}/ {commit}",
        "git archive --format=tar.gz --prefix=x264-{commit}/ {commit}; evil",
        "git archive --format=tar.gz --prefix=x264-{commit}/ {commit} ",
    ],
)
def test_parse_report_rejects_nonexact_git_archive_command(
    tmp_path: Path, valid_report_data: dict[str, Any], tampered_archive_command: str
):
    commit = valid_report_data["source_evidence"]["x264"]["commit"]
    valid_report_data["source_evidence"]["x264"]["archive_command"] = (
        tampered_archive_command.format(commit=commit)
    )
    with pytest.raises(ValueError, match="archive_command"):
        parse_acquisition_report(write_json(tmp_path, valid_report_data))


def test_parse_report_rejects_swapped_git_retention_uris(
    tmp_path: Path, valid_report_data: dict[str, Any]
):
    valid_report_data["source_evidence"]["x264"]["bundle_retention_uri"] = (
        "project://ffmpeg-build/git/x265/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle"
    )
    with pytest.raises(ValueError, match="bundle_retention_uri"):
        parse_acquisition_report(write_json(tmp_path, valid_report_data))

    valid_report_data_2 = sample_valid_report_data()
    valid_report_data_2["source_evidence"]["x264"]["canonical_archive_retention_uri"] = (
        "project://ffmpeg-build/git/x264/f0c1022b6be121a753ff02853fbe33da71988656.tar.gz"
    )
    with pytest.raises(ValueError, match="canonical_archive_retention_uri"):
        parse_acquisition_report(write_json(tmp_path, valid_report_data_2))


