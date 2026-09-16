"""Download injection, real SHA-256 calculation, and verified source cache promotion."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import shutil
import tempfile
from typing import Any, Callable
from urllib.parse import urlparse

from video_converter.ffmpeg_build.acquisition_report import SourceEvidence

Download = Callable[[str, Path], None]


@dataclass(frozen=True)
class ResolvedSource:
    name: str
    artifact_url: str | None
    filename: str
    sha256: str
    verification_evidence: dict[str, str | bool]
    upstream_remote_url: str | None = None
    canonical_filename: str | None = None
    canonical_retention_uri: str | None = None


def _compute_file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _filename_from_url(url: str) -> str:
    parsed = urlparse(url)
    return Path(parsed.path).name


def _build_evidence_dict(evidence: SourceEvidence) -> dict[str, str | bool]:
    if evidence.type == "commit_archive":
        return {
            "type": "commit_archive",
            "verified": evidence.verified,
            "artifact_sha256": evidence.artifact_sha256,
            "commit": evidence.commit or "",
            "verifier": evidence.verifier or "",
            "remote_url": evidence.remote_url or "",
            "archive_command": evidence.archive_command or "",
            "git_version": evidence.git_version or "",
            "git_bundle_sha256": evidence.git_bundle_sha256 or "",
            "bundle_retention_uri": evidence.bundle_retention_uri or "",
            "canonical_archive_retention_uri": evidence.canonical_archive_retention_uri or "",
        }
    if evidence.type == "pgp_signature":
        return {
            "type": "pgp_signature",
            "verified": evidence.verified,
            "artifact_sha256": evidence.artifact_sha256,
            "signature_url": evidence.signature_url or "",
            "signer": evidence.signer or "",
        }
    if evidence.type == "published_checksum":
        return {
            "type": "published_checksum",
            "algorithm": evidence.algorithm or "",
            "expected_digest": evidence.expected_digest or "",
            "verified": evidence.verified,
            "artifact_sha256": evidence.artifact_sha256,
            "verifier": evidence.verifier or "",
        }
    raise ValueError(f"Unsupported evidence type: {evidence.type!r}")


def _validate_evidence_fields(evidence: SourceEvidence) -> None:
    # Ensure no unexpected or inconsistent fields for the evidence type
    if evidence.type == "commit_archive":
        if (
            evidence.signature_url is not None
            or evidence.signer is not None
            or evidence.algorithm is not None
            or evidence.expected_digest is not None
        ):
            raise ValueError(f"Extra fields present for commit_archive evidence: {evidence}")
    elif evidence.type == "pgp_signature":
        if (
            evidence.commit is not None
            or evidence.verifier is not None
            or evidence.algorithm is not None
            or evidence.expected_digest is not None
            or evidence.remote_url is not None
            or evidence.archive_command is not None
            or evidence.git_version is not None
            or evidence.git_bundle_sha256 is not None
            or evidence.bundle_retention_uri is not None
            or evidence.canonical_archive_retention_uri is not None
        ):
            raise ValueError(f"Extra fields present for pgp_signature evidence: {evidence}")
    elif evidence.type == "published_checksum":
        if (
            evidence.commit is not None
            or evidence.signature_url is not None
            or evidence.signer is not None
            or evidence.remote_url is not None
            or evidence.archive_command is not None
            or evidence.git_version is not None
            or evidence.git_bundle_sha256 is not None
            or evidence.bundle_retention_uri is not None
            or evidence.canonical_archive_retention_uri is not None
        ):
            raise ValueError(f"Extra fields present for published_checksum evidence: {evidence}")


def _bind_evidence_to_source(
    source: dict[str, Any],
    evidence: SourceEvidence,
    actual_sha256: str,
) -> dict[str, str | bool]:
    _validate_evidence_fields(evidence)
    name = source.get("name")
    if evidence.name != name:
        raise ValueError(
            f"Evidence name mismatch with source: {evidence.name!r} != {name!r}"
        )

    if not evidence.verified:
        raise ValueError(f"Source evidence for {name!r} has verified=False")

    if evidence.artifact_sha256 != actual_sha256:
        raise ValueError(
            f"Evidence artifact_sha256 does not match downloaded file sha256: "
            f"{evidence.artifact_sha256!r} != {actual_sha256!r}"
        )

    acq_type = source.get("acquisition_type")
    if acq_type == "commit_archive":
        if evidence.type != "commit_archive":
            raise ValueError(
                f"Source {name!r} verification evidence type must be commit_archive, got {evidence.type!r}"
            )
        expected_commit = source.get("commit")
        if evidence.commit != expected_commit:
            raise ValueError(
                f"Evidence commit mismatch for {name!r}: {evidence.commit!r} != {expected_commit!r}"
            )
        if evidence.verifier != "git-rev-parse-and-archive":
            raise ValueError(
                f"Evidence verifier for {name!r} must be 'git-rev-parse-and-archive', got {evidence.verifier!r}"
            )

        expected_remote = source.get("git_remote_url")
        if evidence.remote_url != expected_remote:
            raise ValueError(
                f"Evidence remote_url mismatch for {name!r}: {evidence.remote_url!r} != {expected_remote!r}"
            )
        expected_archive_command = (
            f"git archive --format=tar.gz --prefix={name}-{expected_commit}/ {expected_commit}"
        )
        if evidence.archive_command != expected_archive_command:
            raise ValueError(
                f"Evidence archive_command for {name!r} must be {expected_archive_command!r}, got {evidence.archive_command!r}"
            )
        if not evidence.git_bundle_sha256 or len(evidence.git_bundle_sha256) != 64:
            raise ValueError(f"Evidence git_bundle_sha256 for {name!r} must be a 64-hex SHA-256")
        expected_bundle_retention_uri = f"project://ffmpeg-build/git/{name}/{expected_commit}.bundle"
        if evidence.bundle_retention_uri != expected_bundle_retention_uri:
            raise ValueError(
                f"Evidence bundle_retention_uri for {name!r} must be {expected_bundle_retention_uri!r}, got {evidence.bundle_retention_uri!r}"
            )
        expected_canonical_archive_retention_uri = f"project://ffmpeg-build/git/{name}/{expected_commit}.tar.gz"
        if evidence.canonical_archive_retention_uri != expected_canonical_archive_retention_uri:
            raise ValueError(
                f"Evidence canonical_archive_retention_uri for {name!r} must be {expected_canonical_archive_retention_uri!r}, got {evidence.canonical_archive_retention_uri!r}"
            )

    elif name == "ffmpeg":
        if evidence.type != "pgp_signature":
            raise ValueError(
                f"Source {name!r} verification evidence type must be pgp_signature, got {evidence.type!r}"
            )
        expected_sig_url = source.get("verification", {}).get("signature_url")
        if evidence.signature_url != expected_sig_url:
            raise ValueError(
                f"Evidence signature_url mismatch for ffmpeg: "
                f"{evidence.signature_url!r} != {expected_sig_url!r}"
            )
        expected_signer = source.get("verification", {}).get("signer")
        if not expected_signer or not isinstance(expected_signer, str) or not expected_signer.strip():
            raise ValueError("FFmpeg source manifest must declare a non-empty verification.signer")
        if evidence.signer != expected_signer:
            raise ValueError(
                f"Evidence signer mismatch for ffmpeg: "
                f"{evidence.signer!r} != {expected_signer!r}"
            )
        if not evidence.signer or not evidence.signer.strip():
            raise ValueError(f"Evidence signer for ffmpeg must be non-empty")

    elif name == "libopus":
        if evidence.type != "published_checksum":
            raise ValueError(
                f"Source {name!r} verification evidence type must be published_checksum, got {evidence.type!r}"
            )
        expected_digest = source.get("verification", {}).get("expected_digest")
        if actual_sha256 != expected_digest:
            raise ValueError(
                f"libopus actual sha256 mismatch with expected_digest: "
                f"{actual_sha256!r} != {expected_digest!r}"
            )
        if evidence.expected_digest != expected_digest:
            raise ValueError(
                f"libopus evidence expected_digest mismatch: "
                f"{evidence.expected_digest!r} != {expected_digest!r}"
            )
        if evidence.algorithm != "sha256":
            raise ValueError(f"libopus algorithm must be sha256, got {evidence.algorithm!r}")
        if not evidence.verifier or not evidence.verifier.strip():
            raise ValueError(f"Evidence verifier for libopus must be non-empty")

    else:
        raise ValueError(f"Unknown source configuration for {name!r}")

    return _build_evidence_dict(evidence)


def resolve_source(
    source: dict[str, Any],
    evidence: SourceEvidence,
    cache_dir: Path,
    download: Download,
) -> ResolvedSource:
    """Consumes one validated manifest source and its report evidence.

    Downloads or validates cache bytes, verifies bindings, and content-addresses
    the artifact in cache_dir.
    """
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    name = source.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("Source must have a non-empty string 'name'")

    acq_type = source.get("acquisition_type")
    if acq_type == "commit_archive":
        expected_sha = evidence.artifact_sha256
        cached_path = cache_dir / expected_sha
        if not cached_path.is_file():
            raise FileNotFoundError(f"Cached archive missing for {name!r}: {cached_path}")

        actual_sha = _compute_file_sha256(cached_path)
        if actual_sha != expected_sha:
            raise ValueError(
                f"Cached archive sha256 mismatch for {name!r}: {actual_sha} != {expected_sha}"
            )

        evidence_dict = _bind_evidence_to_source(source, evidence, actual_sha)
        commit = source.get("commit")
        canonical_filename = f"{name}-{commit}.tar.gz"
        canonical_retention_uri = evidence.canonical_archive_retention_uri
        upstream_remote_url = source.get("git_remote_url")

        return ResolvedSource(
            name=name,
            artifact_url=None,
            filename=canonical_filename,
            sha256=actual_sha,
            verification_evidence=evidence_dict,
            upstream_remote_url=upstream_remote_url,
            canonical_filename=canonical_filename,
            canonical_retention_uri=canonical_retention_uri,
        )

    artifact_url = source.get("artifact_url")
    if not artifact_url or not isinstance(artifact_url, str):
        raise ValueError(f"Source {name!r} must have a non-empty string 'artifact_url'")

    filename = _filename_from_url(artifact_url)
    expected_sha = evidence.artifact_sha256
    cached_path = cache_dir / expected_sha

    # Check if valid cached artifact already exists
    if cached_path.is_file():
        actual_sha = _compute_file_sha256(cached_path)
        if actual_sha == expected_sha:
            evidence_dict = _bind_evidence_to_source(source, evidence, actual_sha)
            return ResolvedSource(
                name=name,
                artifact_url=artifact_url,
                filename=filename,
                sha256=actual_sha,
                verification_evidence=evidence_dict,
            )

    # Need to download into a unique private invocation directory
    invocation_dir = Path(tempfile.mkdtemp(dir=cache_dir, prefix="resolve-"))
    cleanup_exc: Exception | None = None
    primary_exc: BaseException | None = None
    try:
        try:
            temp_download_path = invocation_dir / filename
            download(artifact_url, temp_download_path)

            if not temp_download_path.is_file():
                raise ValueError(f"Downloaded file not found at {temp_download_path}")

            actual_sha = _compute_file_sha256(temp_download_path)
            evidence_dict = _bind_evidence_to_source(source, evidence, actual_sha)

            # Promote only after real bytes and evidence validation succeed
            promoted_target = cache_dir / actual_sha
            temp_download_path.replace(promoted_target)

            return ResolvedSource(
                name=name,
                artifact_url=artifact_url,
                filename=filename,
                sha256=actual_sha,
                verification_evidence=evidence_dict,
            )
        except BaseException as exc:
            primary_exc = exc
            raise
    finally:
        try:
            if invocation_dir.exists():
                shutil.rmtree(invocation_dir)
        except Exception as err:
            cleanup_exc = err

        if cleanup_exc is not None:
            cause = primary_exc if primary_exc is not None else cleanup_exc
            raise OSError(
                f"Failed to clean up invocation directory {invocation_dir}: {cleanup_exc}"
            ) from cause
