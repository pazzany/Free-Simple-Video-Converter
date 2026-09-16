"""MSYS2 closure verification against acquisition manifest policy."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from video_converter.ffmpeg_build.acquisition_report import (
    AcquisitionReport,
    Msys2DatabaseEvidence,
    Msys2InstallerEvidence,
    Msys2PackageEvidence,
)

HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class ResolvedMsys2Closure:
    installer: Msys2InstallerEvidence
    databases: tuple[Msys2DatabaseEvidence, ...]
    packages: tuple[Msys2PackageEvidence, ...]


def _validate_hex_64(val: Any, field_name: str) -> None:
    if not isinstance(val, str) or not HEX_64_PATTERN.match(val):
        raise ValueError(f"{field_name} must be a valid 64-hex SHA-256 string, got {val!r}")


def _validate_retention_uri(uri: Any, uri_prefix: str, context: str) -> None:
    if not isinstance(uri, str) or not uri.strip():
        raise ValueError(f"{context} missing or empty retention URI")
    if not uri.startswith(uri_prefix):
        raise ValueError(
            f"{context} retention URI {uri!r} does not start with project prefix {uri_prefix!r}"
        )


def _validate_signature(signature: Any, uri_prefix: str, context: str) -> None:
    if signature is None:
        raise ValueError(f"{context} missing signature evidence")
    if signature.verified is not True:
        raise ValueError(f"{context} signature verification must be True")
    if not isinstance(signature.signature_filename, str) or not signature.signature_filename.strip():
        raise ValueError(f"{context} signature filename must be non-empty")
    _validate_hex_64(signature.signature_sha256, f"{context}.signature_sha256")
    if not isinstance(signature.verifier, str) or not signature.verifier.strip():
        raise ValueError(f"{context} signature verifier must be non-empty")
    if not isinstance(signature.signer, str) or not signature.signer.strip():
        raise ValueError(f"{context} signature signer must be non-empty")
    _validate_retention_uri(
        signature.signature_retention_uri,
        uri_prefix,
        f"{context} signature",
    )


def resolve_msys2_closure(
    manifest_policy: dict[str, Any], report: AcquisitionReport
) -> ResolvedMsys2Closure:
    """Validate MSYS2 closure against manifest MSYS2 policy.

    Consumes `manifest["msys2"]` policy dictionary and parsed `AcquisitionReport`.
    Validates that:
    - manifest_policy contains requested_packages list and immutable_retention with uri_prefix
    - report contains MSYS2 installer, databases, and packages
    - installer, databases, and packages all have valid SHA-256 digests and retention URIs starting with uri_prefix
    - package SHA-256 and signature SHA-256 are valid 64-hex strings
    - databases and packages have no duplicate names
    - all requested packages are present in report packages
    - package dependencies are lists/tuples of non-empty strings with no duplicate edges
    - no package has dangling dependencies (all dependencies must exist in the closure)
    - all transitive packages (non-requested) are reachable from at least one requested package
    """
    if not isinstance(manifest_policy, dict):
        raise ValueError("manifest_policy must be a dict")

    if not isinstance(report, AcquisitionReport):
        raise ValueError("report must be an AcquisitionReport instance")

    if not hasattr(report, "msys2") or report.msys2 is None:
        raise ValueError("Acquisition report missing MSYS2 section")

    # Validate manifest policy
    requested_packages_raw = manifest_policy.get("requested_packages")
    if not isinstance(requested_packages_raw, list) or not requested_packages_raw:
        raise ValueError("manifest_policy['requested_packages'] must be a nonempty list")
    for req in requested_packages_raw:
        if not isinstance(req, str) or not req.strip():
            raise ValueError(f"Invalid requested package in manifest policy: {req!r}")
    if len(set(requested_packages_raw)) != len(requested_packages_raw):
        raise ValueError("manifest_policy['requested_packages'] contains duplicate package names")
    requested_packages = set(requested_packages_raw)

    immutable_retention = manifest_policy.get("immutable_retention")
    if not isinstance(immutable_retention, dict):
        raise ValueError("manifest_policy['immutable_retention'] must be a dict")

    uri_prefix = immutable_retention.get("uri_prefix")
    if not isinstance(uri_prefix, str) or not uri_prefix.strip():
        raise ValueError("manifest_policy['immutable_retention'] missing or empty uri_prefix")

    msys2_ev = report.msys2
    installer = msys2_ev.installer
    if not installer:
        raise ValueError("MSYS2 installer evidence missing")
    _validate_hex_64(installer.sha256, "installer.sha256")
    _validate_hex_64(installer.signature_sha256, "installer.signature_sha256")
    _validate_retention_uri(installer.retention_uri, uri_prefix, "installer")
    _validate_signature(installer.signature, uri_prefix, "installer")
    if installer.signature_sha256 != installer.signature.signature_sha256:
        raise ValueError("installer signature sha256 must match retained signature evidence")

    databases = msys2_ev.databases
    if not databases:
        raise ValueError("MSYS2 databases must be nonempty")
    seen_db_names: set[str] = set()
    for db in databases:
        if not db.name or not isinstance(db.name, str):
            raise ValueError(f"MSYS2 database missing or invalid name: {db}")
        if db.name in seen_db_names:
            raise ValueError(f"Duplicate database name detected in MSYS2 report: {db.name!r}")
        seen_db_names.add(db.name)
        _validate_hex_64(db.sha256, f"database[{db.name}].sha256")
        _validate_hex_64(
            db.signature_sha256,
            f"database[{db.name}].signature_sha256",
        )
        _validate_retention_uri(db.retention_uri, uri_prefix, f"database[{db.name}]")
        _validate_signature(db.signature, uri_prefix, f"database[{db.name}]")
        if db.signature_sha256 != db.signature.signature_sha256:
            raise ValueError(
                f"database[{db.name}] signature sha256 must match retained signature evidence"
            )

    packages = msys2_ev.packages
    if not packages:
        raise ValueError("MSYS2 packages must be nonempty")

    seen_pkg_names: set[str] = set()
    packages_by_name: dict[str, Msys2PackageEvidence] = {}

    for pkg in packages:
        if not pkg.name or not isinstance(pkg.name, str):
            raise ValueError(f"MSYS2 package missing or invalid name: {pkg}")
        if pkg.name in seen_pkg_names:
            raise ValueError(f"Duplicate package name detected in MSYS2 report: {pkg.name!r}")
        seen_pkg_names.add(pkg.name)
        packages_by_name[pkg.name] = pkg

        _validate_hex_64(pkg.sha256, f"package[{pkg.name}].sha256")
        _validate_hex_64(pkg.signature_sha256, f"package[{pkg.name}].signature_sha256")
        _validate_retention_uri(pkg.retention_uri, uri_prefix, f"package[{pkg.name}]")
        _validate_signature(pkg.signature, uri_prefix, f"package[{pkg.name}]")
        if pkg.signature_sha256 != pkg.signature.signature_sha256:
            raise ValueError(
                f"package[{pkg.name}] signature sha256 must match retained signature evidence"
            )

        if not isinstance(pkg.dependencies, (tuple, list)):
            raise ValueError(
                f"package[{pkg.name}].dependencies must be a tuple or list of strings"
            )
        seen_deps: set[str] = set()
        for dep in pkg.dependencies:
            if not isinstance(dep, str) or not dep.strip():
                raise ValueError(
                    f"package[{pkg.name}] dependency item must be a non-empty string, got {dep!r}"
                )
            if dep in seen_deps:
                raise ValueError(
                    f"package[{pkg.name}] contains duplicate dependency edge to {dep!r}"
                )
            seen_deps.add(dep)

    # Verify all manifest requested packages are present in the report
    missing_requested = requested_packages - seen_pkg_names
    if missing_requested:
        raise ValueError(
            f"MSYS2 package closure missing requested packages: {sorted(missing_requested)}"
        )

    # Verify no dangling dependencies
    for name, pkg in packages_by_name.items():
        for dep in pkg.dependencies:
            if dep not in seen_pkg_names:
                raise ValueError(
                    f"package[{name}] has dangling dependency {dep!r} not found in MSYS2 closure"
                )

    # Traverse directed dependency edges from requested packages to verify reachability
    reachable: set[str] = set(requested_packages)
    queue: list[str] = list(requested_packages)
    while queue:
        curr = queue.pop(0)
        curr_deps = packages_by_name[curr].dependencies
        for dep in curr_deps:
            if dep not in reachable:
                reachable.add(dep)
                queue.append(dep)

    unreachable = seen_pkg_names - reachable
    if unreachable:
        raise ValueError(
            f"Transitive MSYS2 packages not reachable from requested packages: {sorted(unreachable)}"
        )

    return ResolvedMsys2Closure(
        installer=installer,
        databases=databases,
        packages=packages,
    )
