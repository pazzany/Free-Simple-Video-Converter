"""Tests for validating manifest-bound MSYS2 closure."""

from __future__ import annotations

import copy
import json
from dataclasses import replace
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
)
from video_converter.ffmpeg_build.msys2_closure import (
    ResolvedMsys2Closure,
    resolve_msys2_closure,
)


def sample_manifest_msys2() -> dict[str, Any]:
    manifest_path = (
        Path(__file__).resolve().parent.parent.parent
        / "packaging"
        / "ffmpeg-build"
        / "acquisition-manifest.json"
    )
    return json.loads(manifest_path.read_text(encoding="utf-8"))["msys2"]


def signature_evidence(name: str) -> Msys2SignatureEvidence:
    return Msys2SignatureEvidence(
        signature_filename=f"{name}.sig",
        signature_sha256="f" * 64,
        signature_retention_uri=f"project://ffmpeg-build/signatures/{name}.sig",
        verified=True,
        verifier="pacman-key",
        signer="MSYS2 package signing key",
    )


def make_report(
    installer: Msys2InstallerEvidence | None = None,
    databases: tuple[Msys2DatabaseEvidence, ...] | None = None,
    packages: tuple[Msys2PackageEvidence, ...] | None = None,
) -> AcquisitionReport:
    inst = installer or Msys2InstallerEvidence(
        url="https://repo.msys2.org/distrib/msys2-x86_64-latest.tar.xz",
        sha256="b" * 64,
        signature_sha256="f" * 64,
        retention_uri="project://ffmpeg-build/msys2/installer.tar.xz",
        signature=signature_evidence("installer"),
    )
    dbs = (
        databases
        if databases is not None
        else (
            Msys2DatabaseEvidence(
                name="ucrt64.db",
                sha256="c" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/msys2/ucrt64.db",
                signature=signature_evidence("ucrt64.db"),
            ),
        )
    )
    pkgs = (
        packages
        if packages is not None
        else (
            Msys2PackageEvidence(
                name="mingw-w64-ucrt-x86_64-gcc",
                version="13.2.0-1",
                filename="mingw-w64-ucrt-x86_64-gcc-13.2.0-1-any.pkg.tar.zst",
                sha256="d" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/packages/gcc.pkg.tar.zst",
                dependencies=("mingw-w64-ucrt-x86_64-isl",),
                signature=signature_evidence("gcc"),
            ),
            Msys2PackageEvidence(
                name="mingw-w64-ucrt-x86_64-isl",
                version="0.26-1",
                filename="mingw-w64-ucrt-x86_64-isl-0.26-1-any.pkg.tar.zst",
                sha256="f" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/packages/isl.pkg.tar.zst",
                dependencies=(),
                signature=signature_evidence("isl"),
            ),
            Msys2PackageEvidence(
                name="mingw-w64-ucrt-x86_64-nasm",
                version="2.16.01-1",
                filename="nasm.pkg.tar.zst",
                sha256="1" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/packages/nasm.pkg.tar.zst",
                dependencies=(),
                signature=signature_evidence("nasm"),
            ),
            Msys2PackageEvidence(
                name="mingw-w64-ucrt-x86_64-ninja",
                version="1.11.1-1",
                filename="ninja.pkg.tar.zst",
                sha256="3" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/packages/ninja.pkg.tar.zst",
                dependencies=(),
                signature=signature_evidence("ninja"),
            ),
            Msys2PackageEvidence(
                name="mingw-w64-ucrt-x86_64-cmake",
                version="3.28.1-1",
                filename="cmake.pkg.tar.zst",
                sha256="5" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/packages/cmake.pkg.tar.zst",
                dependencies=(),
                signature=signature_evidence("cmake"),
            ),
            Msys2PackageEvidence(
                name="mingw-w64-ucrt-x86_64-meson",
                version="1.3.1-1",
                filename="meson.pkg.tar.zst",
                sha256="7" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/packages/meson.pkg.tar.zst",
                dependencies=(),
                signature=signature_evidence("meson"),
            ),
            Msys2PackageEvidence(
                name="mingw-w64-ucrt-x86_64-pkgconf",
                version="2.1.0-1",
                filename="pkgconf.pkg.tar.zst",
                sha256="9" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/packages/pkgconf.pkg.tar.zst",
                dependencies=(),
                signature=signature_evidence("pkgconf"),
            ),
            Msys2PackageEvidence(
                name="make",
                version="4.4.1-1",
                filename="make.pkg.tar.zst",
                sha256="b" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/packages/make.pkg.tar.zst",
                dependencies=(),
                signature=signature_evidence("make"),
            ),
            Msys2PackageEvidence(
                name="diffutils",
                version="3.10-1",
                filename="diffutils.pkg.tar.zst",
                sha256="d" * 64,
                signature_sha256="f" * 64,
                retention_uri="project://ffmpeg-build/packages/diffutils.pkg.tar.zst",
                dependencies=(),
                signature=signature_evidence("diffutils"),
            ),
        )
    )
    return AcquisitionReport(
        recipe_sha256="a" * 64,
        source_evidence={},
        msys2=Msys2ReportEvidence(
            installer=inst,
            databases=dbs,
            packages=pkgs,
        ),
        patches=(),
    )


@pytest.fixture
def manifest_msys2() -> dict[str, Any]:
    return sample_manifest_msys2()


@pytest.fixture
def valid_report() -> AcquisitionReport:
    return make_report()


def test_resolve_msys2_closure_returns_frozen_dataclass(manifest_msys2, valid_report):
    closure = resolve_msys2_closure(manifest_msys2, valid_report)
    assert isinstance(closure, ResolvedMsys2Closure)
    assert closure.installer == valid_report.msys2.installer
    assert closure.databases == valid_report.msys2.databases
    assert closure.packages == valid_report.msys2.packages
    with pytest.raises(AttributeError):
        closure.installer = None  # type: ignore[misc]


def test_closure_requires_manifest_requested_packages(manifest_msys2, valid_report):
    changed_policy = {
        **manifest_msys2,
        "requested_packages": [*manifest_msys2["requested_packages"], "extra-tool"],
    }
    with pytest.raises(ValueError, match="extra-tool"):
        resolve_msys2_closure(changed_policy, valid_report)


def test_closure_rejects_duplicate_requested_package(manifest_msys2, valid_report):
    changed_policy = {
        **manifest_msys2,
        "requested_packages": [
            *manifest_msys2["requested_packages"],
            "make",
        ],
    }
    with pytest.raises(ValueError, match="duplicate"):
        resolve_msys2_closure(changed_policy, valid_report)


def test_closure_rejects_missing_requested_package_in_report(manifest_msys2, valid_report):
    pkgs = tuple(p for p in valid_report.msys2.packages if p.name != "make")
    report = make_report(packages=pkgs)
    with pytest.raises(ValueError, match="make"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_external_retention_uri_on_package(manifest_msys2, valid_report):
    bad_pkgs = []
    for p in valid_report.msys2.packages:
        if p.name == "make":
            bad_pkgs.append(
                Msys2PackageEvidence(
                    name=p.name,
                    version=p.version,
                    filename=p.filename,
                    sha256=p.sha256,
                    signature_sha256=p.signature_sha256,
                    retention_uri="https://external.invalid/make.pkg.tar.zst",
                    dependencies=p.dependencies,
                )
            )
        else:
            bad_pkgs.append(p)
    report = make_report(packages=tuple(bad_pkgs))
    with pytest.raises(ValueError, match="retention"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_external_retention_uri_on_installer(manifest_msys2, valid_report):
    bad_inst = Msys2InstallerEvidence(
        url=valid_report.msys2.installer.url,
        sha256=valid_report.msys2.installer.sha256,
        signature_sha256="c" * 64,
        retention_uri="https://attacker.org/installer.tar.xz",
    )
    report = make_report(installer=bad_inst)
    with pytest.raises(ValueError, match="retention"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_external_retention_uri_on_database(manifest_msys2, valid_report):
    bad_db = Msys2DatabaseEvidence(
        name="ucrt64.db",
        sha256="c" * 64,
        signature_sha256="d" * 64,
        retention_uri="https://external.com/ucrt64.db",
    )
    report = make_report(databases=(bad_db,))
    with pytest.raises(ValueError, match="retention"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_dangling_dependency(manifest_msys2, valid_report):
    pkgs = []
    for p in valid_report.msys2.packages:
        if p.name == "mingw-w64-ucrt-x86_64-isl":
            pkgs.append(
                Msys2PackageEvidence(
                    name=p.name,
                    version=p.version,
                    filename=p.filename,
                    sha256=p.sha256,
                    signature_sha256=p.signature_sha256,
                    retention_uri=p.retention_uri,
                    dependencies=("missing-gmp",),
                    signature=p.signature,
                )
            )
        else:
            pkgs.append(p)
    report = make_report(packages=tuple(pkgs))
    with pytest.raises(ValueError, match="dangling dependency 'missing-gmp'"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_duplicate_package_in_report(manifest_msys2, valid_report):
    pkgs = list(valid_report.msys2.packages)
    pkgs.append(pkgs[0])
    report = make_report(packages=tuple(pkgs))
    with pytest.raises(ValueError, match="Duplicate package"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_duplicate_database_in_report(manifest_msys2, valid_report):
    dbs = list(valid_report.msys2.databases)
    dbs.append(dbs[0])
    report = make_report(databases=tuple(dbs))
    with pytest.raises(ValueError, match="Duplicate database"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_duplicate_dependency_edge(manifest_msys2, valid_report):
    pkgs = []
    for p in valid_report.msys2.packages:
        if p.name == "mingw-w64-ucrt-x86_64-gcc":
            pkgs.append(
                Msys2PackageEvidence(
                    name=p.name,
                    version=p.version,
                    filename=p.filename,
                    sha256=p.sha256,
                    signature_sha256=p.signature_sha256,
                    retention_uri=p.retention_uri,
                    dependencies=("mingw-w64-ucrt-x86_64-isl", "mingw-w64-ucrt-x86_64-isl"),
                    signature=p.signature,
                )
            )
        else:
            pkgs.append(p)
    report = make_report(packages=tuple(pkgs))
    with pytest.raises(ValueError, match="duplicate dependency"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_unreachable_transitive_package(manifest_msys2, valid_report):
    pkgs = list(valid_report.msys2.packages)
    pkgs.append(
        Msys2PackageEvidence(
            name="isolated-lib",
            version="1.0.0-1",
            filename="isolated-lib.pkg.tar.zst",
            sha256="2" * 64,
            signature_sha256="f" * 64,
            retention_uri="project://ffmpeg-build/packages/isolated-lib.pkg.tar.zst",
            dependencies=(),
            signature=signature_evidence("isolated-lib"),
        )
    )
    report = make_report(packages=tuple(pkgs))
    with pytest.raises(ValueError, match="not reachable from requested packages.*isolated-lib"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_empty_databases(manifest_msys2, valid_report):
    report = make_report(databases=())
    with pytest.raises(ValueError, match="databases must be nonempty"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_empty_packages(manifest_msys2, valid_report):
    report = make_report(packages=())
    with pytest.raises(ValueError, match="packages must be nonempty"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_non_dict_manifest_policy(valid_report):
    with pytest.raises(ValueError, match="manifest_policy must be a dict"):
        resolve_msys2_closure(None, valid_report)  # type: ignore[arg-type]


def test_closure_rejects_missing_immutable_retention_in_manifest(manifest_msys2, valid_report):
    policy = copy.deepcopy(manifest_msys2)
    del policy["immutable_retention"]
    with pytest.raises(ValueError, match="immutable_retention"):
        resolve_msys2_closure(policy, valid_report)


def test_closure_rejects_missing_uri_prefix_in_manifest(manifest_msys2, valid_report):
    policy = copy.deepcopy(manifest_msys2)
    del policy["immutable_retention"]["uri_prefix"]
    with pytest.raises(ValueError, match="uri_prefix"):
        resolve_msys2_closure(policy, valid_report)


def test_closure_rejects_non_string_dependency_item(manifest_msys2, valid_report):
    # Construct an invalid package bypass
    p = Msys2PackageEvidence(
        name="make",
        version="4.4.1",
        filename="make.pkg.tar.zst",
        sha256="b" * 64,
        signature_sha256="f" * 64,
        retention_uri="project://ffmpeg-build/packages/make.pkg.tar.zst",
        dependencies=(123,),  # type: ignore[arg-type]
        signature=signature_evidence("make"),
    )
    pkgs = [pkg for pkg in valid_report.msys2.packages if pkg.name != "make"] + [p]
    report = make_report(packages=tuple(pkgs))
    with pytest.raises(ValueError, match="dependency item must be a non-empty string"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_dependency_string_collection(manifest_msys2, valid_report):
    package = next(
        package
        for package in valid_report.msys2.packages
        if package.name == "make"
    )
    malformed = Msys2PackageEvidence(
        name=package.name,
        version=package.version,
        filename=package.filename,
        sha256=package.sha256,
        signature_sha256=package.signature_sha256,
        retention_uri=package.retention_uri,
        dependencies="not-a-list",  # type: ignore[arg-type]
        signature=package.signature,
    )
    packages = [
        candidate
        for candidate in valid_report.msys2.packages
        if candidate.name != malformed.name
    ] + [malformed]
    report = make_report(packages=tuple(packages))
    with pytest.raises(ValueError, match="dependencies"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_missing_msys2_section_in_report(manifest_msys2, valid_report):
    # Construct report without msys2 section
    report = AcquisitionReport(
        recipe_sha256="a" * 64,
        source_evidence={},
        msys2=None,  # type: ignore[arg-type]
        patches=(),
    )
    with pytest.raises(ValueError, match="Acquisition report missing MSYS2 section"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_missing_installer_sha(manifest_msys2, valid_report):
    bad_inst = Msys2InstallerEvidence(
        url="https://repo.msys2.org/distrib/msys2.tar.xz",
        sha256="short-sha",
        signature_sha256="c" * 64,
        retention_uri="project://ffmpeg-build/msys2/installer.tar.xz",
    )
    report = make_report(installer=bad_inst)
    with pytest.raises(ValueError, match="installer.sha256 must be a valid 64-hex"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_unverified_retained_signature(manifest_msys2, valid_report):
    installer = replace(
        valid_report.msys2.installer,
        signature=replace(valid_report.msys2.installer.signature, verified=False),
    )
    with pytest.raises(ValueError, match="signature verification"):
        resolve_msys2_closure(manifest_msys2, make_report(installer=installer))


def test_closure_rejects_external_signature_retention_uri(manifest_msys2, valid_report):
    installer = replace(
        valid_report.msys2.installer,
        signature=replace(
            valid_report.msys2.installer.signature,
            signature_retention_uri="https://example.invalid/installer.sig",
        ),
    )
    with pytest.raises(ValueError, match="signature retention"):
        resolve_msys2_closure(manifest_msys2, make_report(installer=installer))


def test_closure_rejects_signature_digest_mismatch(manifest_msys2, valid_report):
    installer = replace(
        valid_report.msys2.installer,
        signature_sha256="0" * 64,
    )
    with pytest.raises(ValueError, match="signature sha256 must match"):
        resolve_msys2_closure(manifest_msys2, make_report(installer=installer))


def test_closure_rejects_invalid_installer_signature(manifest_msys2, valid_report):
    installer = Msys2InstallerEvidence(
        url=valid_report.msys2.installer.url,
        sha256=valid_report.msys2.installer.sha256,
        signature_sha256="invalid",
        retention_uri=valid_report.msys2.installer.retention_uri,
    )
    with pytest.raises(ValueError, match="installer.signature_sha256"):
        resolve_msys2_closure(manifest_msys2, make_report(installer=installer))


def test_closure_rejects_missing_database_sha(manifest_msys2, valid_report):
    bad_db = Msys2DatabaseEvidence(
        name="ucrt64.db",
        sha256="",
        signature_sha256="d" * 64,
        retention_uri="project://ffmpeg-build/msys2/ucrt64.db",
    )
    report = make_report(databases=(bad_db,))
    with pytest.raises(ValueError, match="database\\[ucrt64.db\\].sha256 must be a valid 64-hex"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_invalid_database_signature(manifest_msys2, valid_report):
    database = Msys2DatabaseEvidence(
        name="ucrt64.db",
        sha256="c" * 64,
        signature_sha256="invalid",
        retention_uri="project://ffmpeg-build/msys2/ucrt64.db",
    )
    with pytest.raises(ValueError, match="database\[ucrt64.db\].signature_sha256"):
        resolve_msys2_closure(manifest_msys2, make_report(databases=(database,)))


def test_closure_rejects_missing_package_signature_sha(manifest_msys2, valid_report):
    p = Msys2PackageEvidence(
        name="make",
        version="4.4.1",
        filename="make.pkg.tar.zst",
        sha256="b" * 64,
        signature_sha256="bad-sig",
        retention_uri="https://storage.example.com/packages/make.pkg.tar.zst",
        dependencies=(),
    )
    pkgs = [pkg for pkg in valid_report.msys2.packages if pkg.name != "make"] + [p]
    report = make_report(packages=tuple(pkgs))
    with pytest.raises(ValueError, match="package\\[make\\].signature_sha256 must be a valid 64-hex"):
        resolve_msys2_closure(manifest_msys2, report)


def test_closure_rejects_missing_integrity_values(manifest_msys2, valid_report):
    p = Msys2PackageEvidence(
        name="make",
        version="4.4.1",
        filename="make.pkg.tar.zst",
        sha256="",
        signature_sha256="c" * 64,
        retention_uri="https://storage.example.com/packages/make.pkg.tar.zst",
        dependencies=(),
    )
    pkgs = [pkg for pkg in valid_report.msys2.packages if pkg.name != "make"] + [p]
    report = make_report(packages=tuple(pkgs))
    with pytest.raises(ValueError, match="sha256"):
        resolve_msys2_closure(manifest_msys2, report)
