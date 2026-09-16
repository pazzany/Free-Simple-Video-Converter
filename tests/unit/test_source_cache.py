"""Tests for resolving verified source cache entries."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
import pytest

from video_converter.ffmpeg_build.acquisition_report import SourceEvidence
from video_converter.ffmpeg_build.source_cache import (
    Download,
    ResolvedSource,
    resolve_source,
)

FIXTURE_BYTES = b"real-test-binary-payload-for-source-artifact"
FIXTURE_SHA256 = hashlib.sha256(FIXTURE_BYTES).hexdigest()

OPUS_BYTES = b"opus-1.4-official-payload"
OPUS_SHA256 = hashlib.sha256(OPUS_BYTES).hexdigest()


def _make_downloader(content: bytes) -> Download:
    def _download(url: str, dest: Path) -> None:
        dest.write_bytes(content)

    return _download


@pytest.fixture
def downloader() -> Download:
    return _make_downloader(FIXTURE_BYTES)


@pytest.fixture
def fixture_source() -> dict[str, Any]:
    return {
        "name": "x264",
        "license": "GPL-2.0-or-later",
        "acquisition_type": "commit_archive",
        "commit": "c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        "git_remote_url": "https://code.videolan.org/videolan/x264.git",
    }


@pytest.fixture
def fixture_evidence() -> SourceEvidence:
    return SourceEvidence(
        name="x264",
        type="commit_archive",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        commit="c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        verifier="git-rev-parse-and-archive",
        remote_url="https://code.videolan.org/videolan/x264.git",
        archive_command="git archive --format=tar.gz --prefix=x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497/ c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        git_version="git version 2.43.0",
        git_bundle_sha256="b" * 64,
        bundle_retention_uri="project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle",
        canonical_archive_retention_uri="project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
    )


@pytest.fixture
def ffmpeg_source() -> dict[str, Any]:
    return {
        "name": "ffmpeg",
        "license": "GPL-3.0-or-later",
        "acquisition_type": "official_release",
        "version": "6.1.1",
        "source_commit": "e38092ef9395d7049f871ef4d5411eb410e283e0",
        "artifact_url": "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz",
        "verification": {
            "type": "pgp_signature",
            "signature_url": "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
            "signer": "ffmpeg-release-signing-key",
        },
    }


@pytest.fixture
def ffmpeg_evidence() -> SourceEvidence:
    return SourceEvidence(
        name="ffmpeg",
        type="pgp_signature",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        signature_url="https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
        signer="ffmpeg-release-signing-key",
    )


@pytest.fixture
def opus_source() -> dict[str, Any]:
    return {
        "name": "libopus",
        "license": "BSD-3-Clause",
        "acquisition_type": "official_release",
        "version": "1.4",
        "artifact_url": "https://github.com/xiph/opus/releases/download/v1.4/opus-1.4.tar.gz",
        "verification": {
            "type": "published_checksum",
            "algorithm": "sha256",
            "expected_digest": OPUS_SHA256,
        },
    }


@pytest.fixture
def opus_evidence() -> SourceEvidence:
    return SourceEvidence(
        name="libopus",
        type="published_checksum",
        verified=True,
        artifact_sha256=OPUS_SHA256,
        algorithm="sha256",
        expected_digest=OPUS_SHA256,
        verifier="sha256-verifier",
    )


def test_resolve_git_source_uses_existing_cache_and_never_downloads(tmp_path, fixture_source, fixture_evidence):
    cached_file = tmp_path / fixture_evidence.artifact_sha256
    cached_file.write_bytes(FIXTURE_BYTES)

    def failing_download(url: str, dest: Path) -> None:
        raise AssertionError("Downloader should never be called for commit_archive sources")

    resolved = resolve_source(fixture_source, fixture_evidence, tmp_path, failing_download)
    assert resolved.artifact_url is None
    assert resolved.upstream_remote_url == fixture_source["git_remote_url"]
    assert resolved.canonical_retention_uri == fixture_evidence.canonical_archive_retention_uri
    assert resolved.canonical_filename == f"x264-{fixture_source['commit']}.tar.gz"
    assert resolved.sha256 == fixture_evidence.artifact_sha256
    assert resolved.verification_evidence["archive_command"] == fixture_evidence.archive_command
    assert resolved.verification_evidence["git_bundle_sha256"] == fixture_evidence.git_bundle_sha256


def test_resolve_git_source_requires_existing_cache_file(tmp_path, fixture_source, fixture_evidence):
    def failing_download(url: str, dest: Path) -> None:
        raise AssertionError("Downloader should never be called")

    with pytest.raises(FileNotFoundError, match="Cached archive missing"):
        resolve_source(fixture_source, fixture_evidence, tmp_path, failing_download)


def test_resolve_git_source_verifies_rehashed_sha(tmp_path, fixture_source, fixture_evidence):
    cached_file = tmp_path / fixture_evidence.artifact_sha256
    cached_file.write_bytes(b"tampered content")

    def failing_download(url: str, dest: Path) -> None:
        raise AssertionError("Downloader should never be called")

    with pytest.raises(ValueError, match="sha256"):
        resolve_source(fixture_source, fixture_evidence, tmp_path, failing_download)


def test_resolve_official_release_caches_real_hashed_bytes(tmp_path, ffmpeg_source, ffmpeg_evidence, downloader):
    result = resolve_source(ffmpeg_source, ffmpeg_evidence, tmp_path, downloader)
    cached_file = tmp_path / result.sha256
    assert cached_file.read_bytes() == FIXTURE_BYTES
    assert result.sha256 == hashlib.sha256(FIXTURE_BYTES).hexdigest()
    assert result.name == "ffmpeg"
    assert result.filename == "ffmpeg-6.1.1.tar.xz"
    assert result.artifact_url == ffmpeg_source["artifact_url"]
    assert result.verification_evidence == {
        "type": "pgp_signature",
        "verified": True,
        "artifact_sha256": FIXTURE_SHA256,
        "signature_url": "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
        "signer": "ffmpeg-release-signing-key",
    }


def test_resolve_official_release_reuses_existing_valid_cache_without_downloading(
    tmp_path, ffmpeg_source, ffmpeg_evidence
):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)

    download_called = False

    def _failing_download(url: str, dest: Path) -> None:
        nonlocal download_called
        download_called = True
        raise AssertionError("Downloader should not be called when cache entry is valid")

    result = resolve_source(ffmpeg_source, ffmpeg_evidence, tmp_path, _failing_download)
    assert not download_called
    assert result.sha256 == FIXTURE_SHA256
    assert cached_file.read_bytes() == FIXTURE_BYTES


def test_existing_corrupt_cache_is_not_reused(tmp_path, ffmpeg_source, ffmpeg_evidence, downloader):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(b"corrupt-data-not-matching-sha")

    result = resolve_source(ffmpeg_source, ffmpeg_evidence, tmp_path, downloader)
    assert result.sha256 == FIXTURE_SHA256
    assert cached_file.read_bytes() == FIXTURE_BYTES


def test_evidence_failure_never_promotes_cache_bytes(tmp_path, fixture_source, downloader):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)
    wrong_commit_evidence = SourceEvidence(
        name="x264",
        type="commit_archive",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        commit="badcommit00000000000000000000000000000000",
        verifier="git-rev-parse-and-archive",
        remote_url="https://code.videolan.org/videolan/x264.git",
        archive_command="git archive --format=tar.gz --prefix=x264-badcommit00000000000000000000000000000000/ badcommit00000000000000000000000000000000",
        git_version="git version 2.43.0",
        git_bundle_sha256="b" * 64,
        bundle_retention_uri="project://ffmpeg-build/git/x264/badcommit00000000000000000000000000000000.bundle",
        canonical_archive_retention_uri="project://ffmpeg-build/git/x264/badcommit00000000000000000000000000000000.tar.gz",
    )
    with pytest.raises(ValueError, match="commit"):
        resolve_source(fixture_source, wrong_commit_evidence, tmp_path, downloader)


def test_evidence_unverified_never_promotes_cache(tmp_path, fixture_source, downloader):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)
    unverified_evidence = SourceEvidence(
        name="x264",
        type="commit_archive",
        verified=False,
        artifact_sha256=FIXTURE_SHA256,
        commit="c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        verifier="git-rev-parse-and-archive",
        remote_url="https://code.videolan.org/videolan/x264.git",
        archive_command="git archive --format=tar.gz --prefix=x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497/ c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        git_version="git version 2.43.0",
        git_bundle_sha256="b" * 64,
        bundle_retention_uri="project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle",
        canonical_archive_retention_uri="project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
    )
    with pytest.raises(ValueError, match="verified"):
        resolve_source(fixture_source, unverified_evidence, tmp_path, downloader)


def test_evidence_sha_mismatch_with_actual_bytes(tmp_path, fixture_source, downloader):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)
    mismatched_sha_evidence = SourceEvidence(
        name="x264",
        type="commit_archive",
        verified=True,
        artifact_sha256="0" * 64,
        commit="c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        verifier="git-rev-parse-and-archive",
        remote_url="https://code.videolan.org/videolan/x264.git",
        archive_command="git archive --format=tar.gz --prefix=x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497/ c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        git_version="git version 2.43.0",
        git_bundle_sha256="b" * 64,
        bundle_retention_uri="project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle",
        canonical_archive_retention_uri="project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
    )
    with pytest.raises(FileNotFoundError):
        resolve_source(fixture_source, mismatched_sha_evidence, tmp_path, downloader)


def test_commit_archive_wrong_evidence_type(tmp_path, fixture_source, downloader):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)
    wrong_type_evidence = SourceEvidence(
        name="x264",
        type="pgp_signature",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        signature_url="https://example.com/sig.asc",
        signer="someone",
    )
    with pytest.raises(ValueError, match="type"):
        resolve_source(fixture_source, wrong_type_evidence, tmp_path, downloader)


def test_commit_archive_extra_fields_rejected(tmp_path, fixture_source, downloader):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)
    extra_field_evidence = SourceEvidence(
        name="x264",
        type="commit_archive",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        commit="c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        verifier="git-rev-parse-and-archive",
        remote_url="https://code.videolan.org/videolan/x264.git",
        archive_command="git archive --format=tar.gz --prefix=x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497/ c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        git_version="git version 2.43.0",
        git_bundle_sha256="b" * 64,
        bundle_retention_uri="project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle",
        canonical_archive_retention_uri="project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
        signer="unexpected-signer",
    )
    with pytest.raises(ValueError, match="Extra fields"):
        resolve_source(fixture_source, extra_field_evidence, tmp_path, downloader)


def test_ffmpeg_pgp_extra_fields_rejected(tmp_path, ffmpeg_source):
    dl = _make_downloader(FIXTURE_BYTES)
    extra_field_evidence = SourceEvidence(
        name="ffmpeg",
        type="pgp_signature",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        signature_url="https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
        signer="ffmpeg-release-signing-key",
        commit="unexpected-commit",
    )
    with pytest.raises(ValueError, match="Extra fields"):
        resolve_source(ffmpeg_source, extra_field_evidence, tmp_path, dl)

    assert list(tmp_path.glob("*")) == []


def test_opus_checksum_extra_fields_rejected(tmp_path, opus_source):
    dl = _make_downloader(OPUS_BYTES)
    extra_field_evidence = SourceEvidence(
        name="libopus",
        type="published_checksum",
        verified=True,
        artifact_sha256=OPUS_SHA256,
        algorithm="sha256",
        expected_digest=OPUS_SHA256,
        verifier="sha256-verifier",
        commit="unexpected-commit",
    )
    with pytest.raises(ValueError, match="Extra fields"):
        resolve_source(opus_source, extra_field_evidence, tmp_path, dl)

    assert list(tmp_path.glob("*")) == []


def test_ffmpeg_pgp_success(tmp_path, ffmpeg_source, ffmpeg_evidence):
    dl = _make_downloader(FIXTURE_BYTES)
    result = resolve_source(ffmpeg_source, ffmpeg_evidence, tmp_path, dl)
    assert result.name == "ffmpeg"
    assert result.sha256 == FIXTURE_SHA256
    assert (tmp_path / FIXTURE_SHA256).read_bytes() == FIXTURE_BYTES
    assert result.verification_evidence == {
        "type": "pgp_signature",
        "verified": True,
        "artifact_sha256": FIXTURE_SHA256,
        "signature_url": "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
        "signer": "ffmpeg-release-signing-key",
    }


def test_ffmpeg_wrong_signature_url(tmp_path, ffmpeg_source):
    dl = _make_downloader(FIXTURE_BYTES)
    bad_sig_evidence = SourceEvidence(
        name="ffmpeg",
        type="pgp_signature",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        signature_url="https://ffmpeg.org/releases/wrong.asc",
        signer="ffmpeg-release-signing-key",
    )
    with pytest.raises(ValueError, match="signature_url"):
        resolve_source(ffmpeg_source, bad_sig_evidence, tmp_path, dl)

    assert list(tmp_path.glob("*")) == []


def test_ffmpeg_wrong_signer_when_specified_in_source(tmp_path, ffmpeg_source):
    dl = _make_downloader(FIXTURE_BYTES)
    source_with_signer = dict(ffmpeg_source)
    source_with_signer["verification"] = {
        "type": "pgp_signature",
        "signature_url": "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
        "signer": "ffmpeg-expected-key",
    }
    bad_signer_evidence = SourceEvidence(
        name="ffmpeg",
        type="pgp_signature",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        signature_url="https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
        signer="different-key",
    )
    with pytest.raises(ValueError, match="signer"):
        resolve_source(source_with_signer, bad_signer_evidence, tmp_path, dl)

    assert list(tmp_path.glob("*")) == []


def test_ffmpeg_empty_signer(tmp_path, ffmpeg_source):
    dl = _make_downloader(FIXTURE_BYTES)
    bad_signer_evidence = SourceEvidence(
        name="ffmpeg",
        type="pgp_signature",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        signature_url="https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
        signer="   ",
    )
    with pytest.raises(ValueError, match="signer"):
        resolve_source(ffmpeg_source, bad_signer_evidence, tmp_path, dl)

    assert list(tmp_path.glob("*")) == []


def test_ffmpeg_wrong_evidence_type(tmp_path, ffmpeg_source):
    dl = _make_downloader(FIXTURE_BYTES)
    bad_evidence = SourceEvidence(
        name="ffmpeg",
        type="commit_archive",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        commit="e38092ef9395d7049f871ef4d5411eb410e283e0",
        verifier="git-archive-verifier",
    )
    with pytest.raises(ValueError, match="type"):
        resolve_source(ffmpeg_source, bad_evidence, tmp_path, dl)

    assert list(tmp_path.glob("*")) == []


def test_opus_published_checksum_success(tmp_path, opus_source, opus_evidence):
    dl = _make_downloader(OPUS_BYTES)
    result = resolve_source(opus_source, opus_evidence, tmp_path, dl)
    assert result.name == "libopus"
    assert result.sha256 == OPUS_SHA256
    assert (tmp_path / OPUS_SHA256).read_bytes() == OPUS_BYTES
    assert result.verification_evidence == {
        "type": "published_checksum",
        "algorithm": "sha256",
        "expected_digest": OPUS_SHA256,
        "verified": True,
        "artifact_sha256": OPUS_SHA256,
        "verifier": "sha256-verifier",
    }


def test_opus_expected_digest_mismatch_with_source(tmp_path, opus_source):
    dl = _make_downloader(OPUS_BYTES)
    bad_opus_source = dict(opus_source)
    bad_opus_source["verification"] = {
        "type": "published_checksum",
        "algorithm": "sha256",
        "expected_digest": "e" * 64,
    }
    evidence = SourceEvidence(
        name="libopus",
        type="published_checksum",
        verified=True,
        artifact_sha256=OPUS_SHA256,
        algorithm="sha256",
        expected_digest="e" * 64,
        verifier="sha256-verifier",
    )
    with pytest.raises(ValueError, match="expected_digest"):
        resolve_source(bad_opus_source, evidence, tmp_path, dl)

    assert list(tmp_path.glob("*")) == []


def test_opus_wrong_evidence_type(tmp_path, opus_source):
    dl = _make_downloader(OPUS_BYTES)
    bad_evidence = SourceEvidence(
        name="libopus",
        type="pgp_signature",
        verified=True,
        artifact_sha256=OPUS_SHA256,
        signature_url="https://example.com/sig.asc",
        signer="someone",
    )
    with pytest.raises(ValueError, match="type"):
        resolve_source(opus_source, bad_evidence, tmp_path, dl)

    assert list(tmp_path.glob("*")) == []


def test_source_name_mismatch_with_evidence(tmp_path, fixture_source, downloader):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)
    evidence = SourceEvidence(
        name="ffmpeg",
        type="commit_archive",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        commit="c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        verifier="git-rev-parse-and-archive",
        remote_url="https://code.videolan.org/videolan/x264.git",
        archive_command="git archive --format=tar.gz --prefix=x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497/ c24e06c2e184345ceb33eb20a15d1024d9fd3497",
        git_version="git version 2.43.0",
        git_bundle_sha256="b" * 64,
        bundle_retention_uri="project://ffmpeg-build/git/libvpx/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle",
        canonical_archive_retention_uri="project://ffmpeg-build/git/libvpx/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
    )
    with pytest.raises(ValueError, match="name"):
        resolve_source(fixture_source, evidence, tmp_path, downloader)


def test_source_cache_rejects_nonexact_git_verifier(tmp_path, fixture_source, fixture_evidence, downloader):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)
    bad_verifier_evidence = SourceEvidence(
        name=fixture_evidence.name,
        type=fixture_evidence.type,
        verified=fixture_evidence.verified,
        artifact_sha256=fixture_evidence.artifact_sha256,
        commit=fixture_evidence.commit,
        verifier="git-archive-verifier",
        remote_url=fixture_evidence.remote_url,
        archive_command=fixture_evidence.archive_command,
        git_version=fixture_evidence.git_version,
        git_bundle_sha256=fixture_evidence.git_bundle_sha256,
        bundle_retention_uri=fixture_evidence.bundle_retention_uri,
        canonical_archive_retention_uri=fixture_evidence.canonical_archive_retention_uri,
    )
    with pytest.raises(ValueError, match="git-rev-parse-and-archive"):
        resolve_source(fixture_source, bad_verifier_evidence, tmp_path, downloader)


@pytest.mark.parametrize(
    "tampered_archive_command",
    [
        "git archive --format=tar --prefix={name}-{commit}/ {commit}",
        "git archive --format=tar.gz --prefix={name}-{commit}/ {commit}; evil",
        "git archive --format=tar.gz --prefix={name}-{commit}/ {commit} ",
    ],
)
def test_source_cache_rejects_nonexact_git_archive_command(
    tmp_path, fixture_source, fixture_evidence, downloader, tampered_archive_command
):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)
    bad_cmd_evidence = SourceEvidence(
        name=fixture_evidence.name,
        type=fixture_evidence.type,
        verified=fixture_evidence.verified,
        artifact_sha256=fixture_evidence.artifact_sha256,
        commit=fixture_evidence.commit,
        verifier=fixture_evidence.verifier,
        remote_url=fixture_evidence.remote_url,
        archive_command=tampered_archive_command.format(
            name=fixture_evidence.name, commit=fixture_evidence.commit
        ),
        git_version=fixture_evidence.git_version,
        git_bundle_sha256=fixture_evidence.git_bundle_sha256,
        bundle_retention_uri=fixture_evidence.bundle_retention_uri,
        canonical_archive_retention_uri=fixture_evidence.canonical_archive_retention_uri,
    )
    with pytest.raises(ValueError, match="archive_command"):
        resolve_source(fixture_source, bad_cmd_evidence, tmp_path, downloader)


def test_sentinel_partial_and_existing_files_untouched_on_failure(
    tmp_path, ffmpeg_source, downloader
):
    sentinel_file = tmp_path / "ffmpeg.partial"
    sentinel_file.write_bytes(b"external-sentinel-content")

    unrelated_file = tmp_path / "other-file.txt"
    unrelated_file.write_bytes(b"keep-me")

    wrong_evidence = SourceEvidence(
        name="ffmpeg",
        type="pgp_signature",
        verified=False,
        artifact_sha256=FIXTURE_SHA256,
        signature_url="https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
        signer="ffmpeg-release-signing-key",
    )

    with pytest.raises(ValueError):
        resolve_source(ffmpeg_source, wrong_evidence, tmp_path, downloader)

    assert sentinel_file.exists()
    assert sentinel_file.read_bytes() == b"external-sentinel-content"
    assert unrelated_file.exists()
    assert unrelated_file.read_bytes() == b"keep-me"
    # No resolve-* temp directories left behind
    assert [p.name for p in tmp_path.glob("resolve-*")] == []


def test_cleanup_failure_raises_chained_oserror(
    tmp_path, ffmpeg_source, ffmpeg_evidence, monkeypatch
):
    dl = _make_downloader(FIXTURE_BYTES)
    import shutil

    original_rmtree = shutil.rmtree

    def _failing_rmtree(path, *args, **kwargs):
        raise OSError("Permission denied cleaning tempdir")

    monkeypatch.setattr(shutil, "rmtree", _failing_rmtree)

    with pytest.raises(OSError, match="cleaning tempdir"):
        resolve_source(ffmpeg_source, ffmpeg_evidence, tmp_path, dl)


def test_real_manifest_ffmpeg_signer_differing_from_manifest_must_fail(tmp_path):
    import json

    manifest_path = (
        Path(__file__).resolve().parent.parent.parent
        / "packaging"
        / "ffmpeg-build"
        / "acquisition-manifest.json"
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    ffmpeg_source = next(s for s in manifest["sources"] if s["name"] == "ffmpeg")

    assert ffmpeg_source["verification"]["signer"] == "FCF986EA15E6E293A5644F10B4322F04D67658D8"

    dl = _make_downloader(FIXTURE_BYTES)
    wrong_signer_evidence = SourceEvidence(
        name="ffmpeg",
        type="pgp_signature",
        verified=True,
        artifact_sha256=FIXTURE_SHA256,
        signature_url=ffmpeg_source["verification"]["signature_url"],
        signer="DIFFERENT_SIGNER_KEY_12345",
    )

    with pytest.raises(ValueError, match="signer"):
        resolve_source(ffmpeg_source, wrong_signer_evidence, tmp_path, dl)


def test_primary_failure_with_cleanup_failure_chains_original_as_cause(
    tmp_path, ffmpeg_source, ffmpeg_evidence, monkeypatch
):
    import shutil

    def _failing_download(url: str, dest: Path) -> None:
        raise ValueError("Primary download failed: connection refused")

    def _failing_rmtree(path, *args, **kwargs):
        raise OSError("Permission denied cleaning tempdir")

    monkeypatch.setattr(shutil, "rmtree", _failing_rmtree)

    with pytest.raises(OSError, match="cleaning tempdir") as exc_info:
        resolve_source(ffmpeg_source, ffmpeg_evidence, tmp_path, _failing_download)

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert "Primary download failed: connection refused" in str(exc_info.value.__cause__)


def test_source_cache_rejects_swapped_git_retention_uris(tmp_path, fixture_source, fixture_evidence, downloader):
    cached_file = tmp_path / FIXTURE_SHA256
    cached_file.write_bytes(FIXTURE_BYTES)

    # Swap bundle retention URI to another valid git URI under same prefix
    bad_bundle_evidence = SourceEvidence(
        name=fixture_evidence.name,
        type=fixture_evidence.type,
        verified=fixture_evidence.verified,
        artifact_sha256=fixture_evidence.artifact_sha256,
        commit=fixture_evidence.commit,
        verifier=fixture_evidence.verifier,
        remote_url=fixture_evidence.remote_url,
        archive_command=fixture_evidence.archive_command,
        git_version=fixture_evidence.git_version,
        git_bundle_sha256=fixture_evidence.git_bundle_sha256,
        bundle_retention_uri="project://ffmpeg-build/git/x265/c24e06c2e184345ceb33eb20a15d1024d9fd3497.bundle",
        canonical_archive_retention_uri=fixture_evidence.canonical_archive_retention_uri,
    )
    with pytest.raises(ValueError, match="bundle_retention_uri"):
        resolve_source(fixture_source, bad_bundle_evidence, tmp_path, downloader)

    # Swap canonical archive retention URI to another commit under same prefix
    bad_archive_evidence = SourceEvidence(
        name=fixture_evidence.name,
        type=fixture_evidence.type,
        verified=fixture_evidence.verified,
        artifact_sha256=fixture_evidence.artifact_sha256,
        commit=fixture_evidence.commit,
        verifier=fixture_evidence.verifier,
        remote_url=fixture_evidence.remote_url,
        archive_command=fixture_evidence.archive_command,
        git_version=fixture_evidence.git_version,
        git_bundle_sha256=fixture_evidence.git_bundle_sha256,
        bundle_retention_uri=fixture_evidence.bundle_retention_uri,
        canonical_archive_retention_uri="project://ffmpeg-build/git/x264/f0c1022b6be121a753ff02853fbe33da71988656.tar.gz",
    )
    with pytest.raises(ValueError, match="canonical_archive_retention_uri"):
        resolve_source(fixture_source, bad_archive_evidence, tmp_path, downloader)

