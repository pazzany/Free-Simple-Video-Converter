"""Strict acquisition report parser and immutable dataclasses."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType
from typing import Any, Mapping

HEX_64_PATTERN = re.compile(r"^[0-9a-f]{64}$")

REQUIRED_SOURCE_NAMES = {
    "ffmpeg",
    "x264",
    "x265",
    "libvpx",
    "svt-av1",
    "libopus",
    "nv-codec-headers",
    "amf",
    "libvpl",
}

REPORT_TOP_LEVEL_KEYS = {"source_evidence", "msys2", "recipe_sha256", "patches"}


def _reject_duplicate_json_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object member: {key}")
        result[key] = value
    return result


def _assert_exact_keys(actual: set[str], expected: set[str], context: str) -> None:
    missing = expected - actual
    extra = actual - expected
    if missing or extra:
        errors = []
        if missing:
            errors.append(f"Missing keys: {sorted(missing)}")
        if extra:
            errors.append(f"Extra keys: {sorted(extra)}")
        raise ValueError(f"Schema violation in {context}: {'; '.join(errors)}")


def _validate_hex_64(value: Any, context: str) -> str:
    if not isinstance(value, str) or not HEX_64_PATTERN.match(value):
        raise ValueError(f"Expected 64 lowercase hex characters for {context}, got {value!r}")
    return value


def _validate_nonempty_str(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Expected non-empty string for {context}, got {value!r}")
    return value


def _validate_bool(value: Any, context: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"Expected boolean for {context}, got {value!r}")
    return value


@dataclass(frozen=True)
class SourceEvidence:
    name: str
    type: str
    verified: bool
    artifact_sha256: str
    commit: str | None = None
    verifier: str | None = None
    signature_url: str | None = None
    signer: str | None = None
    algorithm: str | None = None
    expected_digest: str | None = None
    remote_url: str | None = None
    archive_command: str | None = None
    git_version: str | None = None
    git_bundle_sha256: str | None = None
    bundle_retention_uri: str | None = None
    canonical_archive_retention_uri: str | None = None


@dataclass(frozen=True)
class Msys2SignatureEvidence:
    signature_filename: str
    signature_sha256: str
    signature_retention_uri: str
    verified: bool
    verifier: str
    signer: str

    @property
    def filename(self) -> str:
        return self.signature_filename

    @property
    def sha256(self) -> str:
        return self.signature_sha256

    @property
    def retention_uri(self) -> str:
        return self.signature_retention_uri


@dataclass(frozen=True)
class Msys2InstallerEvidence:
    url: str
    sha256: str
    signature_sha256: str
    retention_uri: str
    signature: Msys2SignatureEvidence | None = None


@dataclass(frozen=True)
class Msys2DatabaseEvidence:
    name: str
    sha256: str
    signature_sha256: str
    retention_uri: str
    signature: Msys2SignatureEvidence | None = None


@dataclass(frozen=True)
class Msys2PackageEvidence:
    name: str
    version: str
    filename: str
    sha256: str
    signature_sha256: str
    retention_uri: str
    dependencies: tuple[str, ...]
    signature: Msys2SignatureEvidence | None = None


@dataclass(frozen=True)
class Msys2ReportEvidence:
    installer: Msys2InstallerEvidence
    databases: tuple[Msys2DatabaseEvidence, ...]
    packages: tuple[Msys2PackageEvidence, ...]


@dataclass(frozen=True)
class PatchEvidence:
    name: str
    path: str
    sha256: str


@dataclass(frozen=True)
class AcquisitionReport:
    recipe_sha256: str
    source_evidence: Mapping[str, SourceEvidence]
    msys2: Msys2ReportEvidence
    patches: tuple[PatchEvidence, ...]


def _parse_source_evidence_item(name: str, data: Any) -> SourceEvidence:
    if not isinstance(data, dict):
        raise ValueError(f"source_evidence[{name!r}] must be a dict")

    ev_type = _validate_nonempty_str(data.get("type"), f"source_evidence[{name}].type")
    verified = _validate_bool(data.get("verified"), f"source_evidence[{name}].verified")
    artifact_sha256 = _validate_hex_64(
        data.get("artifact_sha256"), f"source_evidence[{name}].artifact_sha256"
    )

    if ev_type == "commit_archive":
        _assert_exact_keys(
            set(data.keys()),
            {
                "type",
                "verified",
                "artifact_sha256",
                "commit",
                "verifier",
                "remote_url",
                "archive_command",
                "git_version",
                "git_bundle_sha256",
                "bundle_retention_uri",
                "canonical_archive_retention_uri",
            },
            f"source_evidence[{name}]",
        )
        commit = _validate_nonempty_str(data.get("commit"), f"source_evidence[{name}].commit")
        verifier = _validate_nonempty_str(
            data.get("verifier"), f"source_evidence[{name}].verifier"
        )
        if verifier != "git-rev-parse-and-archive":
            raise ValueError(
                f"source_evidence[{name}].verifier must be 'git-rev-parse-and-archive', got {verifier!r}"
            )
        remote_url = _validate_nonempty_str(
            data.get("remote_url"), f"source_evidence[{name}].remote_url"
        )
        if not remote_url.startswith("https://"):
            raise ValueError(f"source_evidence[{name}].remote_url must start with https://")

        archive_command = _validate_nonempty_str(
            data.get("archive_command"), f"source_evidence[{name}].archive_command"
        )
        expected_archive_command = f"git archive --format=tar.gz --prefix={name}-{commit}/ {commit}"
        if archive_command != expected_archive_command:
            raise ValueError(
                f"source_evidence[{name}].archive_command must be {expected_archive_command!r}, got {archive_command!r}"
            )

        git_version = _validate_nonempty_str(
            data.get("git_version"), f"source_evidence[{name}].git_version"
        )
        git_bundle_sha256 = _validate_hex_64(
            data.get("git_bundle_sha256"), f"source_evidence[{name}].git_bundle_sha256"
        )

        expected_bundle_retention_uri = f"project://ffmpeg-build/git/{name}/{commit}.bundle"
        bundle_retention_uri = _validate_nonempty_str(
            data.get("bundle_retention_uri"), f"source_evidence[{name}].bundle_retention_uri"
        )
        if bundle_retention_uri != expected_bundle_retention_uri:
            raise ValueError(
                f"source_evidence[{name}].bundle_retention_uri must be {expected_bundle_retention_uri!r}, got {bundle_retention_uri!r}"
            )

        expected_canonical_archive_retention_uri = f"project://ffmpeg-build/git/{name}/{commit}.tar.gz"
        canonical_archive_retention_uri = _validate_nonempty_str(
            data.get("canonical_archive_retention_uri"),
            f"source_evidence[{name}].canonical_archive_retention_uri",
        )
        if canonical_archive_retention_uri != expected_canonical_archive_retention_uri:
            raise ValueError(
                f"source_evidence[{name}].canonical_archive_retention_uri must be {expected_canonical_archive_retention_uri!r}, got {canonical_archive_retention_uri!r}"
            )

        return SourceEvidence(
            name=name,
            type=ev_type,
            verified=verified,
            artifact_sha256=artifact_sha256,
            commit=commit,
            verifier=verifier,
            remote_url=remote_url,
            archive_command=archive_command,
            git_version=git_version,
            git_bundle_sha256=git_bundle_sha256,
            bundle_retention_uri=bundle_retention_uri,
            canonical_archive_retention_uri=canonical_archive_retention_uri,
        )

    if ev_type == "pgp_signature":
        _assert_exact_keys(
            set(data.keys()),
            {"type", "verified", "artifact_sha256", "signature_url", "signer"},
            f"source_evidence[{name}]",
        )
        signature_url = _validate_nonempty_str(
            data.get("signature_url"), f"source_evidence[{name}].signature_url"
        )
        signer = _validate_nonempty_str(data.get("signer"), f"source_evidence[{name}].signer")
        return SourceEvidence(
            name=name,
            type=ev_type,
            verified=verified,
            artifact_sha256=artifact_sha256,
            signature_url=signature_url,
            signer=signer,
        )

    if ev_type == "published_checksum":
        _assert_exact_keys(
            set(data.keys()),
            {
                "type",
                "verified",
                "artifact_sha256",
                "algorithm",
                "expected_digest",
                "verifier",
            },
            f"source_evidence[{name}]",
        )
        algorithm = _validate_nonempty_str(
            data.get("algorithm"), f"source_evidence[{name}].algorithm"
        )
        expected_digest = _validate_hex_64(
            data.get("expected_digest"), f"source_evidence[{name}].expected_digest"
        )
        verifier = _validate_nonempty_str(
            data.get("verifier"), f"source_evidence[{name}].verifier"
        )
        return SourceEvidence(
            name=name,
            type=ev_type,
            verified=verified,
            artifact_sha256=artifact_sha256,
            algorithm=algorithm,
            expected_digest=expected_digest,
            verifier=verifier,
        )

    raise ValueError(f"Unknown verification evidence type {ev_type!r} for source {name!r}")


def _parse_source_evidence(data: Any) -> Mapping[str, SourceEvidence]:
    if not isinstance(data, dict):
        raise ValueError("source_evidence must be a dict")
    _assert_exact_keys(set(data.keys()), REQUIRED_SOURCE_NAMES, "source_evidence")

    result = {}
    for name in sorted(REQUIRED_SOURCE_NAMES):
        result[name] = _parse_source_evidence_item(name, data[name])
    return MappingProxyType(result)


def _parse_msys2_signature(data: Mapping[str, Any], context: str) -> Msys2SignatureEvidence:
    sig_filename = _validate_nonempty_str(
        data.get("signature_filename"), f"{context}.signature_filename"
    )
    sig_sha256 = _validate_hex_64(
        data.get("signature_sha256"), f"{context}.signature_sha256"
    )
    sig_retention_uri = _validate_nonempty_str(
        data.get("signature_retention_uri"), f"{context}.signature_retention_uri"
    )
    sig_ver = data.get("signature_verification")
    if not isinstance(sig_ver, dict):
        raise ValueError(f"{context}.signature_verification must be a dict")
    _assert_exact_keys(
        set(sig_ver.keys()),
        {"verified", "verifier", "signer"},
        f"{context}.signature_verification",
    )
    verified = _validate_bool(sig_ver.get("verified"), f"{context}.signature_verification.verified")
    if not verified:
        raise ValueError(f"{context}.signature_verification.verified must be True, got {verified!r}")
    verifier = _validate_nonempty_str(
        sig_ver.get("verifier"), f"{context}.signature_verification.verifier"
    )
    signer = _validate_nonempty_str(
        sig_ver.get("signer"), f"{context}.signature_verification.signer"
    )

    return Msys2SignatureEvidence(
        signature_filename=sig_filename,
        signature_sha256=sig_sha256,
        signature_retention_uri=sig_retention_uri,
        verified=verified,
        verifier=verifier,
        signer=signer,
    )


def _parse_msys2(data: Any) -> Msys2ReportEvidence:
    if not isinstance(data, dict):
        raise ValueError("msys2 must be a dict")
    _assert_exact_keys(set(data.keys()), {"installer", "databases", "packages"}, "msys2")

    # Installer
    inst = data["installer"]
    if not isinstance(inst, dict):
        raise ValueError("msys2.installer must be a dict")
    _assert_exact_keys(
        set(inst.keys()),
        {
            "url",
            "sha256",
            "retention_uri",
            "signature_filename",
            "signature_sha256",
            "signature_retention_uri",
            "signature_verification",
        },
        "msys2.installer",
    )
    inst_sig = _parse_msys2_signature(inst, "msys2.installer")
    installer = Msys2InstallerEvidence(
        url=_validate_nonempty_str(inst["url"], "msys2.installer.url"),
        sha256=_validate_hex_64(inst["sha256"], "msys2.installer.sha256"),
        retention_uri=_validate_nonempty_str(
            inst["retention_uri"], "msys2.installer.retention_uri"
        ),
        signature_sha256=inst_sig.signature_sha256,
        signature=inst_sig,
    )

    # Databases
    dbs_raw = data["databases"]
    if not isinstance(dbs_raw, list):
        raise ValueError("msys2.databases must be a list")
    databases: list[Msys2DatabaseEvidence] = []
    for idx, db in enumerate(dbs_raw):
        if not isinstance(db, dict):
            raise ValueError(f"msys2.databases[{idx}] must be a dict")
        _assert_exact_keys(
            set(db.keys()),
            {
                "name",
                "sha256",
                "retention_uri",
                "signature_filename",
                "signature_sha256",
                "signature_retention_uri",
                "signature_verification",
            },
            f"msys2.databases[{idx}]",
        )
        db_sig = _parse_msys2_signature(db, f"msys2.databases[{idx}]")
        databases.append(
            Msys2DatabaseEvidence(
                name=_validate_nonempty_str(db["name"], f"msys2.databases[{idx}].name"),
                sha256=_validate_hex_64(db["sha256"], f"msys2.databases[{idx}].sha256"),
                retention_uri=_validate_nonempty_str(
                    db["retention_uri"], f"msys2.databases[{idx}].retention_uri"
                ),
                signature_sha256=db_sig.signature_sha256,
                signature=db_sig,
            )
        )

    # Packages
    pkgs_raw = data["packages"]
    if not isinstance(pkgs_raw, list):
        raise ValueError("msys2.packages must be a list")
    packages: list[Msys2PackageEvidence] = []
    for idx, pkg in enumerate(pkgs_raw):
        if not isinstance(pkg, dict):
            raise ValueError(f"msys2.packages[{idx}] must be a dict")
        _assert_exact_keys(
            set(pkg.keys()),
            {
                "name",
                "version",
                "filename",
                "sha256",
                "retention_uri",
                "dependencies",
                "signature_filename",
                "signature_sha256",
                "signature_retention_uri",
                "signature_verification",
            },
            f"msys2.packages[{idx}]",
        )
        pkg_sig = _parse_msys2_signature(pkg, f"msys2.packages[{idx}]")
        deps_raw = pkg["dependencies"]
        if not isinstance(deps_raw, list):
            raise ValueError(f"msys2.packages[{idx}].dependencies must be a list")
        deps: list[str] = []
        for d_idx, dep in enumerate(deps_raw):
            if not isinstance(dep, str) or not dep.strip():
                raise ValueError(
                    f"msys2.packages[{idx}].dependencies[{d_idx}] must be non-empty string"
                )
            deps.append(dep)

        packages.append(
            Msys2PackageEvidence(
                name=_validate_nonempty_str(pkg["name"], f"msys2.packages[{idx}].name"),
                version=_validate_nonempty_str(pkg["version"], f"msys2.packages[{idx}].version"),
                filename=_validate_nonempty_str(
                    pkg["filename"], f"msys2.packages[{idx}].filename"
                ),
                sha256=_validate_hex_64(pkg["sha256"], f"msys2.packages[{idx}].sha256"),
                retention_uri=_validate_nonempty_str(
                    pkg["retention_uri"], f"msys2.packages[{idx}].retention_uri"
                ),
                signature_sha256=pkg_sig.signature_sha256,
                dependencies=tuple(deps),
                signature=pkg_sig,
            )
        )

    return Msys2ReportEvidence(
        installer=installer,
        databases=tuple(databases),
        packages=tuple(packages),
    )


def _parse_patches(data: Any) -> tuple[PatchEvidence, ...]:
    if not isinstance(data, list):
        raise ValueError("patches must be a list")
    patches: list[PatchEvidence] = []
    for idx, patch in enumerate(data):
        if not isinstance(patch, dict):
            raise ValueError(f"patches[{idx}] must be a dict")
        _assert_exact_keys(
            set(patch.keys()), {"name", "path", "sha256"}, f"patches[{idx}]"
        )
        patches.append(
            PatchEvidence(
                name=_validate_nonempty_str(patch["name"], f"patches[{idx}].name"),
                path=_validate_nonempty_str(patch["path"], f"patches[{idx}].path"),
                sha256=_validate_hex_64(patch["sha256"], f"patches[{idx}].sha256"),
            )
        )
    return tuple(patches)


def parse_acquisition_report(path: Path) -> AcquisitionReport:
    """Parse and schema-validate an acquisition report from JSON."""
    if not isinstance(path, Path):
        path = Path(path)

    if not path.is_file():
        raise ValueError(f"Acquisition report file not found: {path}")

    try:
        raw_text = path.read_text(encoding="utf-8")
        data = json.loads(raw_text, object_pairs_hook=_reject_duplicate_json_members)
    except Exception as err:
        raise ValueError(f"Failed to read/decode JSON from {path}: {err}") from err

    if not isinstance(data, dict):
        raise ValueError("Acquisition report top level must be a JSON object")

    _assert_exact_keys(set(data.keys()), REPORT_TOP_LEVEL_KEYS, "acquisition_report")

    recipe_sha256 = _validate_hex_64(data["recipe_sha256"], "recipe_sha256")
    source_evidence = _parse_source_evidence(data["source_evidence"])
    msys2 = _parse_msys2(data["msys2"])
    patches = _parse_patches(data["patches"])

    return AcquisitionReport(
        recipe_sha256=recipe_sha256,
        source_evidence=source_evidence,
        msys2=msys2,
        patches=patches,
    )
