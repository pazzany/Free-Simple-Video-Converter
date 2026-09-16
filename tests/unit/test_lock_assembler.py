"""Tests for assembling and publishing immutable FFmpeg build locks."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any
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
)
from video_converter.ffmpeg_build.lock_assembler import (
    assemble_build_lock,
    publish_build_lock,
)
from video_converter.ffmpeg_build.msys2_closure import ResolvedMsys2Closure
from video_converter.ffmpeg_build.source_cache import ResolvedSource
from video_converter.ffmpeg_build_manifest import validate_build_lock


MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "packaging"
    / "ffmpeg-build"
    / "acquisition-manifest.json"
)


@pytest.fixture
def valid_manifest() -> dict[str, Any]:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def resolved_sources(valid_manifest: dict[str, Any]) -> list[ResolvedSource]:
    sources: list[ResolvedSource] = []
    for src in valid_manifest["sources"]:
        name = src["name"]
        acq_type = src["acquisition_type"]
        sha = "1" * 64
        if acq_type == "commit_archive":
            commit = src["commit"]
            ev = {
                "type": "commit_archive",
                "verified": True,
                "artifact_sha256": sha,
                "commit": commit,
                "verifier": "git-rev-parse-and-archive",
                "remote_url": src["git_remote_url"],
                "archive_command": f"git archive --format=tar.gz --prefix={name}-{commit}/ {commit}",
                "git_version": "git version 2.43.0",
                "git_bundle_sha256": "b" * 64,
                "bundle_retention_uri": f"project://ffmpeg-build/git/{name}/{commit}.bundle",
                "canonical_archive_retention_uri": f"project://ffmpeg-build/git/{name}/{commit}.tar.gz",
            }
            sources.append(
                ResolvedSource(
                    name=name,
                    artifact_url=None,
                    filename=f"{name}-{commit}.tar.gz",
                    sha256=sha,
                    verification_evidence=ev,
                    upstream_remote_url=src["git_remote_url"],
                    canonical_filename=f"{name}-{commit}.tar.gz",
                    canonical_retention_uri=f"project://ffmpeg-build/git/{name}/{commit}.tar.gz",
                )
            )
        elif acq_type == "official_release":
            if name == "ffmpeg":
                ev = {
                    "type": "pgp_signature",
                    "verified": True,
                    "artifact_sha256": sha,
                    "signature_url": src["verification"]["signature_url"],
                    "signer": "FCF986EA15E6E293A5644F10B4322F04D67658D8",
                }
            elif name == "libopus":
                sha = "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f"
                ev = {
                    "type": "published_checksum",
                    "algorithm": "sha256",
                    "expected_digest": sha,
                    "verified": True,
                    "artifact_sha256": sha,
                    "verifier": "checksum_verifier",
                }
            else:
                raise ValueError(f"Unknown official release source {name}")

            sources.append(
                ResolvedSource(
                    name=name,
                    artifact_url=src["artifact_url"],
                    filename=Path(src["artifact_url"]).name,
                    sha256=sha,
                    verification_evidence=ev,
                )
            )
        else:
            raise ValueError(f"Unknown type {acq_type}")
    return sources


@pytest.fixture
def resolved_msys2(valid_manifest: dict[str, Any]) -> ResolvedMsys2Closure:
    prefix = valid_manifest["msys2"]["immutable_retention"]["uri_prefix"]
    def signature(name: str) -> Msys2SignatureEvidence:
        return Msys2SignatureEvidence(
            signature_filename=f"{name}.sig",
            signature_sha256="e" * 64,
            signature_retention_uri=f"{prefix}signatures/{name}.sig",
            verified=True,
            verifier="pacman-key",
            signer="MSYS2 package signing key",
        )

    installer = Msys2InstallerEvidence(
        url="https://repo.msys2.org/distrib/msys2-x86_64-latest.tar.xz",
        sha256="b" * 64,
        signature_sha256="e" * 64,
        retention_uri=f"{prefix}msys2/installer.tar.xz",
        signature=signature("installer"),
    )
    databases = (
        Msys2DatabaseEvidence(
            name="ucrt64.db",
            sha256="c" * 64,
            signature_sha256="e" * 64,
            retention_uri=f"{prefix}msys2/ucrt64.db",
            signature=signature("ucrt64.db"),
        ),
    )
    packages: list[Msys2PackageEvidence] = []
    for pkg_name in valid_manifest["msys2"]["requested_packages"]:
        packages.append(
            Msys2PackageEvidence(
                name=pkg_name,
                version="1.0.0-1",
                filename=f"{pkg_name}-1.0.0-1-any.pkg.tar.zst",
                sha256="d" * 64,
                signature_sha256="e" * 64,
                retention_uri=f"{prefix}packages/{pkg_name}.pkg.tar.zst",
                dependencies=(),
                signature=signature(pkg_name),
            )
        )
    return ResolvedMsys2Closure(
        installer=installer,
        databases=databases,
        packages=tuple(packages),
    )


@pytest.fixture
def report(
    valid_manifest: dict[str, Any],
    resolved_sources: list[ResolvedSource],
    resolved_msys2: ResolvedMsys2Closure,
) -> AcquisitionReport:
    source_ev: dict[str, SourceEvidence] = {}
    for s in resolved_sources:
        ev = s.verification_evidence
        source_ev[s.name] = SourceEvidence(
            name=s.name,
            type=str(ev["type"]),
            verified=bool(ev["verified"]),
            artifact_sha256=str(ev["artifact_sha256"]),
            commit=str(ev["commit"]) if "commit" in ev else None,
            verifier=str(ev["verifier"]) if "verifier" in ev else None,
            signature_url=str(ev["signature_url"]) if "signature_url" in ev else None,
            signer=str(ev["signer"]) if "signer" in ev else None,
            algorithm=str(ev["algorithm"]) if "algorithm" in ev else None,
            expected_digest=str(ev["expected_digest"]) if "expected_digest" in ev else None,
            remote_url=str(ev["remote_url"]) if "remote_url" in ev else None,
            archive_command=str(ev["archive_command"]) if "archive_command" in ev else None,
            git_version=str(ev["git_version"]) if "git_version" in ev else None,
            git_bundle_sha256=str(ev["git_bundle_sha256"]) if "git_bundle_sha256" in ev else None,
            bundle_retention_uri=str(ev["bundle_retention_uri"]) if "bundle_retention_uri" in ev else None,
            canonical_archive_retention_uri=str(ev["canonical_archive_retention_uri"]) if "canonical_archive_retention_uri" in ev else None,
        )
    msys2_report = Msys2ReportEvidence(
        installer=resolved_msys2.installer,
        databases=resolved_msys2.databases,
        packages=resolved_msys2.packages,
    )
    return AcquisitionReport(
        recipe_sha256="a" * 64,
        source_evidence=source_ev,
        msys2=msys2_report,
        patches=(
            PatchEvidence(
                name="x265-cmake-4.4-compatibility",
                path="packaging/ffmpeg-build/patches/x265-cmake-4.4-compatibility.patch",
                sha256="a" * 64,
            ),
            PatchEvidence(
                name="x265-pkgconfig-libs-private-no-lgcc_s",
                path="packaging/ffmpeg-build/patches/x265-pkgconfig-libs-private-no-lgcc_s.patch",
                sha256="b" * 64,
            ),
        ),
    )


@pytest.fixture
def valid_lock(
    valid_manifest: dict[str, Any],
    resolved_sources: list[ResolvedSource],
    resolved_msys2: ResolvedMsys2Closure,
    report: AcquisitionReport,
) -> dict[str, Any]:
    return assemble_build_lock(
        valid_manifest,
        "a" * 64,
        resolved_sources,
        resolved_msys2,
        report,
    )


def test_assemble_build_lock_rejects_patches_order_mismatch(
    valid_manifest: dict[str, Any],
    resolved_sources: list[ResolvedSource],
    resolved_msys2: ResolvedMsys2Closure,
    report: AcquisitionReport,
):
    reordered_patches = tuple(reversed(report.patches))
    reordered_report = AcquisitionReport(
        recipe_sha256=report.recipe_sha256,
        msys2=report.msys2,
        source_evidence=report.source_evidence,
        patches=reordered_patches,
    )
    with pytest.raises(ValueError, match="report patch evidence does not exactly match manifest patches"):
        assemble_build_lock(
            valid_manifest,
            "a" * 64,
            resolved_sources,
            resolved_msys2,
            reordered_report,
        )


def test_assembled_lock_emits_canonical_git_records_without_artifact_url(valid_lock, valid_manifest):
    x264_lock = next(s for s in valid_lock["sources"] if s["name"] == "x264")
    assert "artifact_url" not in x264_lock
    assert set(x264_lock.keys()) == {
        "name",
        "acquisition_type",
        "commit",
        "upstream_remote_url",
        "canonical_artifact",
        "verification_evidence",
    }
    assert x264_lock["upstream_remote_url"] == "https://code.videolan.org/videolan/x264.git"
    assert x264_lock["canonical_artifact"] == {
        "origin": "git_archive",
        "filename": "x264-c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
        "sha256": "1" * 64,
        "retention_uri": "project://ffmpeg-build/git/x264/c24e06c2e184345ceb33eb20a15d1024d9fd3497.tar.gz",
    }
    assert valid_lock["patches"] == [
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
    ]
    validate_build_lock(valid_lock, valid_manifest)


def test_assembled_lock_retains_complete_msys2_signature_evidence(valid_lock):
    signature = valid_lock["msys2"]["installer"]["signature"]
    assert signature == {
        "filename": "installer.sig",
        "sha256": "e" * 64,
        "retention_uri": "project://ffmpeg-build/signatures/installer.sig",
        "verified": True,
        "verifier": "pacman-key",
        "signer": "MSYS2 package signing key",
    }
    assert valid_lock["msys2"]["databases"][0]["signature"]["filename"] == "ucrt64.db.sig"
    assert valid_lock["msys2"]["packages"][0]["signature"]["verified"] is True


def test_assembler_rejects_report_patch_not_declared_by_manifest(
    valid_manifest, resolved_sources, resolved_msys2, report
):
    report_with_patch = AcquisitionReport(
        recipe_sha256=report.recipe_sha256,
        source_evidence=report.source_evidence,
        msys2=report.msys2,
        patches=(
            PatchEvidence(
                name="unreviewed-patch",
                path="patches/unreviewed.patch",
                sha256="0" * 64,
            ),
        ),
    )
    with pytest.raises(ValueError, match="patch evidence does not exactly match manifest patches"):
        assemble_build_lock(
            valid_manifest, "a" * 64, resolved_sources, resolved_msys2, report_with_patch
        )


def test_assembler_binds_manifest_digest(
    valid_manifest: dict[str, Any],
    resolved_sources: list[ResolvedSource],
    resolved_msys2: ResolvedMsys2Closure,
    report: AcquisitionReport,
):
    manifest_digest = "a" * 64
    lock = assemble_build_lock(
        valid_manifest,
        manifest_digest,
        resolved_sources,
        resolved_msys2,
        report,
    )
    assert lock["acquisition_manifest_sha256"] == manifest_digest
    validate_build_lock(lock, valid_manifest)


def test_assembler_deterministic_output(
    valid_manifest: dict[str, Any],
    resolved_sources: list[ResolvedSource],
    resolved_msys2: ResolvedMsys2Closure,
    report: AcquisitionReport,
):
    lock1 = assemble_build_lock(valid_manifest, "a" * 64, resolved_sources, resolved_msys2, report)
    lock2 = assemble_build_lock(valid_manifest, "a" * 64, resolved_sources, resolved_msys2, report)
    assert lock1 == lock2


def test_publish_creates_sorted_utf8_json_with_trailing_newline(
    tmp_path: Path, valid_lock: dict[str, Any]
):
    out_file = tmp_path / "build.lock.json"
    published = publish_build_lock(valid_lock, out_file)
    assert published == out_file
    raw_bytes = out_file.read_bytes()
    assert raw_bytes.endswith(b"\n")
    # Verify sorted keys formatting
    expected_text = json.dumps(valid_lock, sort_keys=True, indent=2) + "\n"
    assert raw_bytes.decode("utf-8") == expected_text


def test_publish_replace_failure_preserves_existing_output(
    tmp_path: Path, valid_lock: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    output = tmp_path / "build.lock.json"
    output.write_text("old", encoding="utf-8")

    def raise_os_error(self: Path, target: Path) -> Path:
        raise OSError("Atomic replace failed simulation")

    monkeypatch.setattr(Path, "replace", raise_os_error)
    with pytest.raises(OSError, match="Atomic replace failed"):
        publish_build_lock(valid_lock, output)
    assert output.read_text(encoding="utf-8") == "old"
    assert not list(tmp_path.glob(f".{output.stem}.*.tmp"))


def test_publish_failure_removes_only_own_temp_file(
    tmp_path: Path, valid_lock: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    output = tmp_path / "build.lock.json"
    other_temp = tmp_path / f".{output.stem}.other.tmp"
    other_temp.write_text("someone-elses-temp", encoding="utf-8")

    def raise_os_error(self: Path, target: Path) -> Path:
        raise OSError("Atomic replace failed simulation")

    monkeypatch.setattr(Path, "replace", raise_os_error)
    with pytest.raises(OSError, match="Atomic replace failed"):
        publish_build_lock(valid_lock, output)

    assert other_temp.exists()
    assert other_temp.read_text(encoding="utf-8") == "someone-elses-temp"
    remaining = list(tmp_path.glob(f".{output.stem}.*.tmp"))
    assert remaining == [other_temp]


def test_publish_cleanup_failure_retains_primary_cause(
    tmp_path: Path, valid_lock: dict[str, Any], monkeypatch: pytest.MonkeyPatch
):
    output = tmp_path / "build.lock.json"
    output.write_text("old", encoding="utf-8")

    def raise_replace_error(self: Path, target: Path) -> Path:
        raise OSError("Replace failed simulation")

    def raise_unlink_error(self: Path, missing_ok: bool = False) -> None:
        raise OSError("Unlink failed simulation")

    monkeypatch.setattr(Path, "replace", raise_replace_error)
    monkeypatch.setattr(Path, "unlink", raise_unlink_error)

    with pytest.raises(OSError, match="Unlink failed simulation") as exc_info:
        publish_build_lock(valid_lock, output)

    assert exc_info.value.__cause__ is not None
    assert "Replace failed simulation" in str(exc_info.value.__cause__)
    assert output.read_text(encoding="utf-8") == "old"


def test_validate_build_lock_requires_non_optional_manifest(
    valid_lock: dict[str, Any]
):
    with pytest.raises(TypeError):
        validate_build_lock(valid_lock)  # type: ignore[call-arg]
    with pytest.raises(ValueError, match="acquisition_manifest"):
        validate_build_lock(valid_lock, None)  # type: ignore[arg-type]


def test_validate_build_lock_rejects_changed_manifest_requested_packages(
    valid_lock: dict[str, Any], valid_manifest: dict[str, Any]
):
    changed_manifest = copy.deepcopy(valid_manifest)
    changed_manifest["msys2"]["requested_packages"].append("extra-pkg")
    with pytest.raises(ValueError, match="missing requested packages"):
        validate_build_lock(valid_lock, changed_manifest)


def test_validate_build_lock_rejects_external_retention_uri_policy(
    valid_lock: dict[str, Any], valid_manifest: dict[str, Any]
):
    changed_manifest = copy.deepcopy(valid_manifest)
    changed_manifest["msys2"]["immutable_retention"]["uri_prefix"] = "project://other-prefix/"
    with pytest.raises(ValueError, match="retention"):
        validate_build_lock(valid_lock, changed_manifest)


def test_validate_build_lock_prohibits_output_binary_hashes(
    valid_lock: dict[str, Any], valid_manifest: dict[str, Any]
):
    mutant = copy.deepcopy(valid_lock)
    mutant["outputs"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="Forbidden hash/checksum key|Extra:"):
        validate_build_lock(mutant, valid_manifest)
