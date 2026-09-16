"""Manifest and provenance lifecycle contracts for custom reproducible FFmpeg builds."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

HEX_40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
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

REQUIRED_SOURCE_TYPES = {
    "ffmpeg": "official_release",
    "libopus": "official_release",
    "x264": "commit_archive",
    "x265": "commit_archive",
    "libvpx": "commit_archive",
    "svt-av1": "commit_archive",
    "nv-codec-headers": "commit_archive",
    "amf": "commit_archive",
    "libvpl": "commit_archive",
}

COMMIT_ARCHIVE_SOURCES = {
    "x264": "c24e06c2e184345ceb33eb20a15d1024d9fd3497",
    "x265": "f0c1022b6be121a753ff02853fbe33da71988656",
    "libvpx": "10b9492dcf05b652e2e4b370e205bd605d421972",
    "svt-av1": "59645eea34e2815b627b8293aa3af254eddd0d69",
    "nv-codec-headers": "1889e62e2d35ff7aa9baca2bceb14f053785e6f1",
    "amf": "c48e50ad6c8723c006b2c145d8fa49ecc0651022",
    "libvpl": "11a9bbda5b22ac1c544da59b4007bb57f737b487",
}

REQUIRED_CONFIGURE_FLAGS = [
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

EXPECTED_OUTPUTS = {
    "ffmpeg": {
        "name": "ffmpeg",
        "path": "bin/ffmpeg.exe",
        "version_prefix": "ffmpeg version 6.1.1",
    },
    "ffprobe": {
        "name": "ffprobe",
        "path": "bin/ffprobe.exe",
        "version_prefix": "ffprobe version 6.1.1",
    },
}

HASH_KEY_NAMES = {
    "sha256",
    "checksum",
    "hash",
    "md5",
    "sha1",
    "sha512",
    "sha384",
    "sha224",
    "digest",
}


def _assert_no_hash_fields(obj: Any, context: str = "") -> None:
    """Recursively reject every hash or checksum field anywhere in acquisition manifest including patches.

    Permits the declared verification policy in official_release (which declares verification type/policy).
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_lower = k.lower()
            if any(h in k_lower for h in ("sha", "checksum", "hash", "md5")) or k_lower == "digest":
                raise ValueError(f"Forbidden hash/checksum key '{k}' found in {context}")
            # Do not recurse into verification subdict if it's the declared verification policy
            if k == "verification" and isinstance(v, dict) and v.get("type") == "published_checksum":
                continue
            _assert_no_hash_fields(v, f"{context}.{k}" if context else k)
    elif isinstance(obj, list):
        for idx, item in enumerate(obj):
            _assert_no_hash_fields(item, f"{context}[{idx}]")


def _assert_exact_keys(d: dict, expected_keys: set[str], context: str) -> None:
    actual = set(d.keys())
    if actual != expected_keys:
        missing = expected_keys - actual
        extra = actual - expected_keys
        raise ValueError(
            f"Invalid keys in {context}. Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        )


def _reject_duplicate_json_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object member: {key}")
        result[key] = value
    return result


def decode_json_without_duplicate_keys(content: str | bytes) -> Any:
    """Parse JSON string or bytes, rejecting duplicate object keys at any nesting level."""
    return json.loads(content, object_pairs_hook=_reject_duplicate_json_members)


def load_json(path: Path) -> dict:
    """Load and parse JSON file from path, rejecting duplicate object keys."""
    raw = path.read_bytes()
    data = decode_json_without_duplicate_keys(raw.decode("utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Root JSON element in {path} must be an object/dict")
    return data


def validate_acquisition_manifest(manifest: dict) -> None:
    """Validate declarative acquisition manifest policy.

    acquisition-manifest.json is a tracked declarative policy input.
    It includes no sha256 fields, no blank checksum fields, no output hashes,
    and no partial MSYS2 package closure. Rejects unknown keys across all schemas.
    """
    if not isinstance(manifest, dict):
        raise ValueError("Acquisition manifest must be a dictionary")

    expected_top_keys = {
        "schema_version",
        "sources",
        "toolchain",
        "msys2",
        "configure",
        "patches",
        "outputs",
    }
    _assert_exact_keys(manifest, expected_top_keys, "acquisition manifest root")

    if manifest["schema_version"] != "1.0.0":
        raise ValueError(f"Unsupported schema_version: {manifest['schema_version']}")

    # Recursively check entire acquisition manifest for any hash/checksum fields
    _assert_no_hash_fields(manifest, "acquisition manifest")

    if not isinstance(manifest["patches"], list):
        raise ValueError("patches must be a list")

    # Toolchain validation
    toolchain = manifest["toolchain"]
    if not isinstance(toolchain, dict):
        raise ValueError("Toolchain must be an object")
    _assert_exact_keys(toolchain, {"environment", "target"}, "manifest.toolchain")
    if toolchain.get("environment") != "UCRT64":
        raise ValueError(f"Invalid toolchain environment: {toolchain.get('environment')}")
    if toolchain.get("target") != "x86_64-w64-mingw32":
        raise ValueError(f"Invalid toolchain target: {toolchain.get('target')}")

    # MSYS2 policy validation
    msys2 = manifest["msys2"]
    if not isinstance(msys2, dict):
        raise ValueError("MSYS2 must be an object")
    if "policy" in msys2:
        raise ValueError("MSYS2 policy string/prose is forbidden; use structured fields")
    _assert_exact_keys(
        msys2,
        {"requested_packages", "immutable_retention", "offline_install"},
        "manifest.msys2",
    )
    if not isinstance(msys2["requested_packages"], list) or not msys2["requested_packages"]:
        raise ValueError("MSYS2 must specify nonempty requested_packages list")

    seen_requested_pkgs = []
    for pkg_name in msys2["requested_packages"]:
        if not isinstance(pkg_name, str) or not pkg_name.strip():
            raise ValueError(f"Invalid requested package name: {pkg_name}")
        if pkg_name in seen_requested_pkgs:
            raise ValueError(f"Duplicate requested package detected: '{pkg_name}'")
        seen_requested_pkgs.append(pkg_name)

    immutable_retention = msys2["immutable_retention"]
    if not isinstance(immutable_retention, dict):
        raise ValueError("manifest.msys2.immutable_retention must be an object")
    _assert_exact_keys(
        immutable_retention,
        {"required", "location_kind", "uri_prefix"},
        "manifest.msys2.immutable_retention",
    )
    if immutable_retention.get("required") is not True:
        raise ValueError("manifest.msys2.immutable_retention.required must be True")
    if immutable_retention.get("location_kind") != "project-controlled":
        raise ValueError("manifest.msys2.immutable_retention.location_kind must be 'project-controlled'")
    uri_prefix = immutable_retention.get("uri_prefix")
    if (
        not isinstance(uri_prefix, str)
        or not uri_prefix.startswith("project://")
        or not uri_prefix.endswith("/")
    ):
        raise ValueError(
            "manifest.msys2.immutable_retention.uri_prefix must be a project:// URI ending in '/'"
        )

    offline_install = msys2["offline_install"]
    if not isinstance(offline_install, dict):
        raise ValueError("manifest.msys2.offline_install must be an object")
    _assert_exact_keys(
        offline_install,
        {"command", "forbidden_commands"},
        "manifest.msys2.offline_install",
    )
    if offline_install.get("command") != "pacman -U":
        raise ValueError("manifest.msys2.offline_install.command must be 'pacman -U'")
    forbidden_cmds = offline_install.get("forbidden_commands")
    if forbidden_cmds != ["pacman -S", "pacman -Sy", "pacman -Syu"]:
        raise ValueError(
            "manifest.msys2.offline_install.forbidden_commands must exactly match "
            "['pacman -S', 'pacman -Sy', 'pacman -Syu']"
        )

    # Configure flags validation
    configure = manifest["configure"]
    if not isinstance(configure, dict):
        raise ValueError("Configure section must be an object")
    _assert_exact_keys(configure, {"flags"}, "manifest.configure")
    if not isinstance(configure["flags"], list):
        raise ValueError("manifest.configure.flags must be a list")
    flags = configure["flags"]
    if "--enable-nonfree" in flags:
        raise ValueError("Forbidden flag: --enable-nonfree")
    if flags != REQUIRED_CONFIGURE_FLAGS:
        raise ValueError(
            f"Configure flags must exactly match required baseline. Expected: {REQUIRED_CONFIGURE_FLAGS}, Got: {flags}"
        )

    # Outputs validation
    outputs = manifest["outputs"]
    if not isinstance(outputs, list):
        raise ValueError("Outputs must be a list")
    seen_output_names = []
    outputs_by_name = {}
    for item in outputs:
        if not isinstance(item, dict):
            raise ValueError("Output item must be an object")
        _assert_exact_keys(item, {"name", "path", "version_prefix"}, f"manifest.outputs[{item.get('name')}]")
        _assert_no_hash_fields(item, f"manifest.outputs[{item.get('name')}]")
        name = item.get("name")
        if not name:
            raise ValueError("Output item missing name")
        if name in seen_output_names:
            raise ValueError(f"Duplicate output name detected: '{name}'")
        seen_output_names.append(name)
        outputs_by_name[name] = item

    if set(outputs_by_name.keys()) != set(EXPECTED_OUTPUTS.keys()):
        raise ValueError(f"Outputs must be exactly {set(EXPECTED_OUTPUTS.keys())}")
    for name, expected in EXPECTED_OUTPUTS.items():
        actual = outputs_by_name[name]
        for k, v in expected.items():
            if actual.get(k) != v:
                raise ValueError(f"Output {name} mismatch on {k}: expected {v}, got {actual.get(k)}")

    # Sources validation
    sources = manifest["sources"]
    if not isinstance(sources, list):
        raise ValueError("Sources must be a list")

    source_names_seen = []
    for src in sources:
        if not isinstance(src, dict):
            raise ValueError("Source item must be an object")

        name = src.get("name")
        if not name or not isinstance(name, str):
            raise ValueError("Source must have a non-empty name string")
        if name in source_names_seen:
            raise ValueError(f"Duplicate source name detected: '{name}'")
        source_names_seen.append(name)

    if set(source_names_seen) != REQUIRED_SOURCE_NAMES:
        missing = REQUIRED_SOURCE_NAMES - set(source_names_seen)
        extra = set(source_names_seen) - REQUIRED_SOURCE_NAMES
        raise ValueError(
            f"Sources list must match all 9 required sources. Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        )

    for src in sources:
        name = src["name"]
        expected_type = REQUIRED_SOURCE_TYPES[name]
        acq_type = src.get("acquisition_type")
        if acq_type != expected_type:
            raise ValueError(
                f"Source '{name}' must have acquisition_type '{expected_type}', got '{acq_type}'"
            )

        # Validate license string
        license_val = src.get("license")
        if not license_val or not isinstance(license_val, str) or not license_val.strip():
            raise ValueError(f"Source {name} must have a non-empty license string")

        if acq_type == "commit_archive":
            _assert_exact_keys(
                src,
                {"name", "license", "acquisition_type", "commit", "git_remote_url"},
                f"manifest.sources[{name}]",
            )
            _assert_no_hash_fields(src, f"manifest.sources[{name}]")

            commit = src.get("commit")
            if not commit or not isinstance(commit, str) or not HEX_40_PATTERN.match(commit):
                raise ValueError(
                    f"Source {name} with commit_archive must have a 40-lowercase-hex commit"
                )
            git_remote_url = src.get("git_remote_url")
            if not git_remote_url or not isinstance(git_remote_url, str) or not git_remote_url.startswith("https://"):
                raise ValueError(f"Source {name} must have a valid non-empty HTTPS git_remote_url")

            if commit != COMMIT_ARCHIVE_SOURCES[name]:
                raise ValueError(
                    f"Source {name} commit mismatch: expected {COMMIT_ARCHIVE_SOURCES[name]}, got {commit}"
                )

        elif acq_type == "official_release":
            expected_keys = {"name", "license", "acquisition_type", "version", "artifact_url", "verification"}
            if "source_commit" in src:
                expected_keys.add("source_commit")
                src_commit = src.get("source_commit")
                if not isinstance(src_commit, str) or not HEX_40_PATTERN.match(src_commit):
                    raise ValueError(
                        f"Source {name} optional source_commit must be a 40-lowercase-hex string: {src_commit}"
                    )
            _assert_exact_keys(src, expected_keys, f"manifest.sources[{name}]")

            version = src.get("version")
            if not version or not isinstance(version, str):
                raise ValueError(f"Source {name} with official_release must declare version")

            artifact_url = src.get("artifact_url")
            if not artifact_url or not isinstance(artifact_url, str):
                raise ValueError(f"Source {name} must have a valid artifact_url")

            verification = src.get("verification")
            if not isinstance(verification, dict) or not verification:
                raise ValueError(f"Source {name} must declare nonempty verification policy")

            vtype = verification.get("type")
            if vtype == "pgp_signature":
                if name == "ffmpeg":
                    _assert_exact_keys(verification, {"type", "signature_url", "signer"}, f"manifest.sources[{name}].verification")
                    signer = verification.get("signer")
                    if not signer or not isinstance(signer, str) or not signer.strip():
                        raise ValueError(f"Source {name} pgp_signature must declare non-empty signer")
                else:
                    _assert_exact_keys(verification, {"type", "signature_url"}, f"manifest.sources[{name}].verification")
                sig_url = verification.get("signature_url")
                if not sig_url or not isinstance(sig_url, str):
                    raise ValueError(f"Source {name} pgp_signature must declare signature_url")
            elif vtype == "published_checksum":
                _assert_exact_keys(verification, {"type", "algorithm", "expected_digest"}, f"manifest.sources[{name}].verification")
                algo = verification.get("algorithm")
                digest = verification.get("expected_digest")
                if algo != "sha256" or not digest or not HEX_64_PATTERN.match(digest):
                    raise ValueError(
                        f"Source {name} published_checksum requires sha256 algorithm and 64-hex expected_digest"
                    )
            else:
                raise ValueError(f"Source {name} has unsupported verification type: {vtype}")
        else:
            raise ValueError(f"Unknown acquisition_type: {acq_type} for source {name}")

    if set(source_names_seen) != REQUIRED_SOURCE_NAMES:
        missing = REQUIRED_SOURCE_NAMES - set(source_names_seen)
        extra = set(source_names_seen) - REQUIRED_SOURCE_NAMES
        raise ValueError(
            f"Sources list must match all 9 required sources. Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        )

    # Specific official release provenance checks
    ffmpeg_src = next(s for s in sources if s["name"] == "ffmpeg")
    if (
        ffmpeg_src.get("version") != "6.1.1"
        or ffmpeg_src.get("source_commit") != "e38092ef9395d7049f871ef4d5411eb410e283e0"
        or ffmpeg_src.get("artifact_url") != "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz"
        or ffmpeg_src.get("verification", {}).get("signature_url")
        != "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc"
    ):
        raise ValueError("ffmpeg source parameters mismatch specification")

    opus_src = next(s for s in sources if s["name"] == "libopus")
    if (
        opus_src.get("version") != "1.4"
        or opus_src.get("artifact_url")
        != "https://github.com/xiph/opus/releases/download/v1.4/opus-1.4.tar.gz"
        or opus_src.get("verification", {}).get("expected_digest")
        != "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f"
    ):
        raise ValueError("libopus source parameters mismatch specification")


def validate_build_lock(lock: dict, acquisition_manifest: dict) -> None:
    """Validate complete build lock structure.

    Requires a complete fixture closure of ALL 9 sources, exact toolchain/configure/outputs,
    acquisition manifest SHA-256 digest, patch hashes and recipe hash, source URL/filename/sha256/positive
    verification evidence, and MSYS2 installer/database/package closure with hashes, retention URIs, and
    package signatures. Rejects any missing/blank checksum, incomplete closure, unknown fields, or output
    binary hashes (which belong exclusively to build-record.json).
    """
    if not isinstance(acquisition_manifest, dict):
        raise ValueError("validate_build_lock requires a valid acquisition_manifest dictionary")
    if not isinstance(lock, dict):
        raise ValueError("Build lock must be a dictionary")

    expected_top_keys = {
        "schema_version",
        "acquisition_manifest_sha256",
        "recipe_sha256",
        "toolchain",
        "msys2",
        "sources",
        "patches",
        "configure",
        "outputs",
    }
    _assert_exact_keys(lock, expected_top_keys, "build lock root")

    if lock["schema_version"] != "1.0.0":
        raise ValueError(f"Unsupported schema_version: {lock['schema_version']}")

    manifest_sha = lock.get("acquisition_manifest_sha256")
    if not manifest_sha or not isinstance(manifest_sha, str) or not HEX_64_PATTERN.match(manifest_sha):
        raise ValueError("Build lock must have a valid 64-hex acquisition_manifest_sha256")

    recipe_sha = lock.get("recipe_sha256")
    if not recipe_sha or not isinstance(recipe_sha, str) or not HEX_64_PATTERN.match(recipe_sha):
        raise ValueError("Build lock must have a valid 64-hex recipe_sha256")
    if recipe_sha != manifest_sha:
        raise ValueError("Build lock recipe_sha256 must match acquisition_manifest_sha256")

    # Toolchain validation
    toolchain = lock.get("toolchain")
    if not isinstance(toolchain, dict):
        raise ValueError("Build lock toolchain must be an object")
    _assert_exact_keys(toolchain, {"environment", "target"}, "lock.toolchain")
    if toolchain.get("environment") != "UCRT64":
        raise ValueError(f"Invalid toolchain environment: {toolchain.get('environment')}")
    if toolchain.get("target") != "x86_64-w64-mingw32":
        raise ValueError(f"Invalid toolchain target: {toolchain.get('target')}")

    # Patches validation
    patches = lock.get("patches")
    if not isinstance(patches, list):
        raise ValueError("Build lock patches must be a list")
    seen_patch_names = []
    for patch in patches:
        if not isinstance(patch, dict):
            raise ValueError("Patch item must be an object")
        _assert_exact_keys(patch, {"name", "path", "sha256"}, "lock.patches")
        name = patch.get("name")
        if not name:
            raise ValueError("Patch item missing name")
        if name in seen_patch_names:
            raise ValueError(f"Duplicate patch identity detected in lock: '{name}'")
        seen_patch_names.append(name)
        if not HEX_64_PATTERN.match(patch.get("sha256", "")):
            raise ValueError(f"Patch sha256 malformed: {patch.get('sha256')}")
    manifest_patches = acquisition_manifest.get("patches")
    if not isinstance(manifest_patches, list):
        raise ValueError("acquisition manifest patches must be a list")
    try:
        manifest_patch_identities = [
            (patch["name"], patch["path"]) for patch in manifest_patches
        ]
    except (KeyError, TypeError) as exc:
        raise ValueError("acquisition manifest patches must declare name and path") from exc
    lock_patch_identities = [(patch["name"], patch["path"]) for patch in patches]
    if (
        len(set(manifest_patch_identities)) != len(manifest_patches)
        or len(set(lock_patch_identities)) != len(patches)
        or lock_patch_identities != manifest_patch_identities
    ):
        raise ValueError("Build lock patches do not exactly match acquisition manifest")

    # Configure validation
    configure = lock.get("configure")
    if not isinstance(configure, dict):
        raise ValueError("Build lock configure must be an object")
    _assert_exact_keys(configure, {"flags"}, "lock.configure")
    if configure.get("flags") != REQUIRED_CONFIGURE_FLAGS:
        raise ValueError("Build lock configure flags mismatch required baseline")

    # MSYS2 closure validation
    msys2 = lock.get("msys2")
    if not isinstance(msys2, dict):
        raise ValueError("Build lock msys2 must be an object")
    _assert_exact_keys(msys2, {"installer", "databases", "packages"}, "lock.msys2")

    def validate_signature(signature: Any, context: str) -> None:
        if not isinstance(signature, dict):
            raise ValueError(f"{context}.signature must be an object")
        _assert_exact_keys(
            signature,
            {"filename", "sha256", "retention_uri", "verified", "verifier", "signer"},
            f"{context}.signature",
        )
        if not isinstance(signature.get("filename"), str) or not signature["filename"].strip():
            raise ValueError(f"{context}.signature filename must be non-empty")
        if not HEX_64_PATTERN.match(signature.get("sha256", "")):
            raise ValueError(f"{context}.signature sha256 must be 64-hex")
        if signature.get("verified") is not True:
            raise ValueError(f"{context}.signature verified must be True")
        for field in ("verifier", "signer", "retention_uri"):
            if not isinstance(signature.get(field), str) or not signature[field].strip():
                raise ValueError(f"{context}.signature {field} must be non-empty")

    installer = msys2.get("installer")
    if not isinstance(installer, dict):
        raise ValueError("msys2.installer must be an object")
    _assert_exact_keys(
        installer,
        {"url", "sha256", "signature_sha256", "signature", "retention_uri"},
        "lock.msys2.installer",
    )
    if not installer.get("url") or not HEX_64_PATTERN.match(installer.get("sha256", "")):
        raise ValueError("msys2.installer must contain valid url and sha256")
    if not installer.get("retention_uri") or not isinstance(installer.get("retention_uri"), str):
        raise ValueError("msys2.installer must declare retention_uri")
    if not HEX_64_PATTERN.match(installer.get("signature_sha256", "")):
        raise ValueError("msys2.installer must contain valid signature_sha256")
    validate_signature(installer.get("signature"), "msys2.installer")
    if installer["signature"]["sha256"] != installer["signature_sha256"]:
        raise ValueError("msys2.installer signature sha256 must match signature_sha256")

    databases = msys2.get("databases")
    if not isinstance(databases, list) or not databases:
        raise ValueError("msys2.databases must be a nonempty list")
    seen_database_names = []
    for db in databases:
        if not isinstance(db, dict):
            raise ValueError("Each msys2 database must be an object")
        _assert_exact_keys(
            db,
            {"name", "sha256", "signature_sha256", "signature", "retention_uri"},
            "lock.msys2.databases",
        )
        name = db.get("name")
        if not name or not HEX_64_PATTERN.match(db.get("sha256", "")):
            raise ValueError("Each msys2 database must have name and 64-hex sha256")
        if name in seen_database_names:
            raise ValueError(f"Duplicate database identity detected in lock: '{name}'")
        seen_database_names.append(name)
        if not db.get("retention_uri") or not isinstance(db.get("retention_uri"), str):
            raise ValueError("Each msys2 database must have retention_uri")
        if not HEX_64_PATTERN.match(db.get("signature_sha256", "")):
            raise ValueError("Each msys2 database must have 64-hex signature_sha256")
        validate_signature(db.get("signature"), f"msys2.database[{name}]")
        if db["signature"]["sha256"] != db["signature_sha256"]:
            raise ValueError(f"msys2 database {name} signature sha256 must match signature_sha256")

    packages = msys2.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("msys2.packages must be a nonempty list")
    seen_package_names = []
    packages_by_name = {}
    for pkg in packages:
        if not isinstance(pkg, dict):
            raise ValueError("Each package in closure must be an object")

        _assert_exact_keys(
            pkg,
            {"name", "version", "filename", "sha256", "signature_sha256", "signature", "retention_uri", "dependencies"},
            f"lock.msys2.packages[{pkg.get('name')}]",
        )

        for field in ("name", "version", "filename", "sha256", "signature_sha256", "retention_uri"):
            val = pkg.get(field)
            if not val or not isinstance(val, str):
                raise ValueError(f"Package missing or blank {field}: {pkg}")
        if not HEX_64_PATTERN.match(pkg["sha256"]):
            raise ValueError(f"Package sha256 malformed: {pkg.get('sha256')}")
        if not HEX_64_PATTERN.match(pkg["signature_sha256"]):
            raise ValueError(f"Package signature_sha256 malformed: {pkg.get('signature_sha256')}")
        validate_signature(pkg.get("signature"), f"msys2.package[{pkg.get('name')}]")
        if pkg["signature"]["sha256"] != pkg["signature_sha256"]:
            raise ValueError(
                f"Package signature sha256 must match signature_sha256: {pkg.get('name')}"
            )

        deps = pkg.get("dependencies")
        if not isinstance(deps, list):
            raise ValueError(f"Package dependencies must be a list of strings: {pkg.get('name')}")
        seen_deps = set()
        for dep in deps:
            if not isinstance(dep, str) or not dep.strip():
                raise ValueError(f"Package {pkg.get('name')} contains invalid dependency: {dep}")
            if dep in seen_deps:
                raise ValueError(f"Package {pkg.get('name')} contains duplicate dependency: '{dep}'")
            seen_deps.add(dep)

        name = pkg.get("name")
        if name in seen_package_names:
            raise ValueError(f"Duplicate package identity detected in lock closure: '{name}'")
        seen_package_names.append(name)
        packages_by_name[name] = pkg

    all_pkg_names = set(seen_package_names)

    # Every listed dependency in dependencies must be present in package names
    for name, pkg in packages_by_name.items():
        for dep in pkg["dependencies"]:
            if dep not in all_pkg_names:
                raise ValueError(
                    f"Package '{name}' has dangling dependency '{dep}' not found in MSYS2 package closure"
                )

    requested_packages = set(acquisition_manifest.get("msys2", {}).get("requested_packages", []))
    retention_prefix = acquisition_manifest.get("msys2", {}).get("immutable_retention", {}).get("uri_prefix")

    if not isinstance(retention_prefix, str) or not retention_prefix.strip():
        raise ValueError("acquisition manifest retention uri_prefix must be a non-empty string")
    if not installer["retention_uri"].startswith(retention_prefix):
            raise ValueError(
                f"msys2.installer retention_uri {installer['retention_uri']!r} does not start with prefix {retention_prefix!r}"
            )
    if not installer["signature"]["retention_uri"].startswith(retention_prefix):
        raise ValueError("msys2.installer signature retention_uri does not start with manifest prefix")
    for db in databases:
        if not db["retention_uri"].startswith(retention_prefix):
            raise ValueError(
                f"msys2 database {db.get('name')} retention_uri does not start with prefix {retention_prefix!r}"
            )
        if not db["signature"]["retention_uri"].startswith(retention_prefix):
            raise ValueError(
                f"msys2 database {db.get('name')} signature retention_uri does not start with prefix {retention_prefix!r}"
            )
    for pkg in packages:
        if not pkg["retention_uri"].startswith(retention_prefix):
            raise ValueError(
                f"msys2 package {pkg.get('name')} retention_uri does not start with prefix {retention_prefix!r}"
            )
        if not pkg["signature"]["retention_uri"].startswith(retention_prefix):
            raise ValueError(
                f"msys2 package {pkg.get('name')} signature retention_uri does not start with prefix {retention_prefix!r}"
            )

    # Final lock MSYS2 package closure must include every requested package
    missing_pkgs = requested_packages - all_pkg_names
    if missing_pkgs:
        raise ValueError(
            f"MSYS2 package closure missing requested packages: {sorted(missing_pkgs)}"
        )

    # Every non-requested transitive package must be reachable from at least one requested package
    # via dependencies edges (directed reachability from requested -> transitive dependencies).
    # Forward edges: if pkg A depends on B, we trace reachability from requested packages.
    # Note: package A depends on B means A -> B edge.
    reachable = set(requested_packages)
    queue = list(requested_packages)
    while queue:
        curr = queue.pop(0)
        curr_deps = packages_by_name[curr]["dependencies"]
        for dep in curr_deps:
            if dep not in reachable:
                reachable.add(dep)
                queue.append(dep)

    unreachable_pkgs = all_pkg_names - reachable
    if unreachable_pkgs:
        raise ValueError(
            f"Transitive MSYS2 packages not reachable from requested packages: {sorted(unreachable_pkgs)}"
        )

    # Sources closure validation (MUST contain ALL 9 sources)
    sources = lock.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("Build lock sources must be a nonempty list")
    lock_source_names = []

    # Map manifest sources by name for validation
    manifest_sources_by_name = {
        s["name"]: s for s in acquisition_manifest.get("sources", []) if isinstance(s, dict) and "name" in s
    }

    for src in sources:
        if not isinstance(src, dict):
            raise ValueError("Source in build lock must be an object")

        name = src.get("name")
        if not name or not isinstance(name, str):
            raise ValueError("Source in lock missing name")
        if name in lock_source_names:
            raise ValueError(f"Duplicate source identity detected in lock: '{name}'")
        lock_source_names.append(name)

        if name not in REQUIRED_SOURCE_TYPES:
            raise ValueError(f"Unknown source name in lock: {name}")

        expected_type = REQUIRED_SOURCE_TYPES[name]
        manifest_src = manifest_sources_by_name.get(name, {})

        if expected_type == "commit_archive":
            allowed_keys = {
                "name",
                "acquisition_type",
                "commit",
                "upstream_remote_url",
                "canonical_artifact",
                "verification_evidence",
            }
            _assert_exact_keys(src, allowed_keys, f"lock.sources[{name}]")

            if src.get("acquisition_type") != expected_type:
                raise ValueError(
                    f"Source in lock '{name}' acquisition_type mismatch: expected {expected_type}, got {src.get('acquisition_type')}"
                )

            expected_commit = COMMIT_ARCHIVE_SOURCES[name]
            if src.get("commit") != expected_commit:
                raise ValueError(
                    f"Source in lock '{name}' commit mismatch: expected {expected_commit}, got {src.get('commit')}"
                )

            expected_remote = manifest_src.get("git_remote_url")
            if src.get("upstream_remote_url") != expected_remote:
                raise ValueError(
                    f"Source in lock '{name}' upstream_remote_url mismatch: expected {expected_remote}, got {src.get('upstream_remote_url')}"
                )

            canonical = src.get("canonical_artifact")
            if not isinstance(canonical, dict):
                raise ValueError(f"Source in lock '{name}' missing canonical_artifact dict")

            _assert_exact_keys(
                canonical,
                {"origin", "filename", "sha256", "retention_uri"},
                f"lock.sources[{name}].canonical_artifact",
            )
            if canonical.get("origin") != "git_archive":
                raise ValueError(f"Source '{name}' canonical_artifact origin must be git_archive")
            expected_canonical_filename = f"{name}-{expected_commit}.tar.gz"
            if canonical.get("filename") != expected_canonical_filename:
                raise ValueError(
                    f"Source '{name}' canonical_artifact filename must be {expected_canonical_filename!r}, "
                    f"got {canonical.get('filename')!r}"
                )
            if not HEX_64_PATTERN.match(canonical.get("sha256", "")):
                raise ValueError(f"Source '{name}' canonical_artifact sha256 malformed")
            expected_canonical_archive_retention_uri = f"{retention_prefix}git/{name}/{expected_commit}.tar.gz"
            if canonical.get("retention_uri") != expected_canonical_archive_retention_uri:
                raise ValueError(
                    f"Source '{name}' canonical_artifact retention_uri must be {expected_canonical_archive_retention_uri!r}, "
                    f"got {canonical.get('retention_uri')!r}"
                )

            evidence = src.get("verification_evidence")
            if not isinstance(evidence, dict) or not evidence:
                raise ValueError(f"Source missing verification evidence: {name}")

            _assert_exact_keys(
                evidence,
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
                f"lock.sources[{name}].verification_evidence",
            )
            if evidence.get("type") != "commit_archive":
                raise ValueError(f"Source '{name}' verification evidence type must be commit_archive")
            if evidence.get("artifact_sha256") != canonical.get("sha256"):
                raise ValueError(
                    f"Source '{name}' evidence artifact_sha256 must match entry sha256: "
                    f"{evidence.get('artifact_sha256')} != {canonical.get('sha256')}"
                )
            if evidence.get("commit") != src.get("commit"):
                raise ValueError(
                    f"Source '{name}' evidence commit must match entry commit: "
                    f"{evidence.get('commit')} != {src.get('commit')}"
                )
            if canonical.get("retention_uri") != evidence.get("canonical_archive_retention_uri"):
                raise ValueError(
                    f"Source '{name}' canonical_artifact retention_uri must match evidence canonical_archive_retention_uri: "
                    f"{canonical.get('retention_uri')!r} != {evidence.get('canonical_archive_retention_uri')!r}"
                )
            verifier = evidence.get("verifier")
            if verifier != "git-rev-parse-and-archive":
                raise ValueError(
                    f"Source '{name}' evidence verifier must be 'git-rev-parse-and-archive', got {verifier!r}"
                )
            git_version = evidence.get("git_version")
            if not isinstance(git_version, str) or not git_version.strip():
                raise ValueError(f"Source '{name}' evidence git_version must be a non-empty string")
            if evidence.get("remote_url") != expected_remote:
                raise ValueError(f"Source '{name}' evidence remote_url mismatch")
            expected_archive_cmd = (
                f"git archive --format=tar.gz --prefix={name}-{expected_commit}/ {expected_commit}"
            )
            archive_cmd = evidence.get("archive_command")
            if archive_cmd != expected_archive_cmd:
                raise ValueError(
                    f"Source '{name}' evidence archive_command must be {expected_archive_cmd!r}, got {archive_cmd!r}"
                )
            if not HEX_64_PATTERN.match(evidence.get("git_bundle_sha256", "")):
                raise ValueError(f"Source '{name}' evidence git_bundle_sha256 malformed")
            expected_bundle_retention_uri = f"{retention_prefix}git/{name}/{expected_commit}.bundle"
            if evidence.get("bundle_retention_uri") != expected_bundle_retention_uri:
                raise ValueError(
                    f"Source '{name}' evidence bundle_retention_uri must be {expected_bundle_retention_uri!r}, "
                    f"got {evidence.get('bundle_retention_uri')!r}"
                )
            if evidence.get("canonical_archive_retention_uri") != expected_canonical_archive_retention_uri:
                raise ValueError(
                    f"Source '{name}' evidence canonical_archive_retention_uri must be {expected_canonical_archive_retention_uri!r}, "
                    f"got {evidence.get('canonical_archive_retention_uri')!r}"
                )

        elif expected_type == "official_release":
            allowed_keys = {
                "name",
                "acquisition_type",
                "version",
                "artifact_url",
                "filename",
                "sha256",
                "verification_evidence",
            }
            if name == "ffmpeg":
                allowed_keys.add("source_commit")

            _assert_exact_keys(src, allowed_keys, f"lock.sources[{name}]")
            evidence = src["verification_evidence"]

            if src.get("acquisition_type") != expected_type:
                raise ValueError(
                    f"Source in lock '{name}' acquisition_type mismatch: expected {expected_type}, got {src.get('acquisition_type')}"
                )

            if name == "ffmpeg":
                if (
                    src.get("version") != "6.1.1"
                    or src.get("source_commit") != "e38092ef9395d7049f871ef4d5411eb410e283e0"
                    or src.get("artifact_url") != "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz"
                ):
                    raise ValueError(f"Source in lock '{name}' identity mismatch with official release")
            elif name == "libopus":
                if (
                    src.get("version") != "1.4"
                    or src.get("artifact_url") != "https://github.com/xiph/opus/releases/download/v1.4/opus-1.4.tar.gz"
                ):
                    raise ValueError(f"Source in lock '{name}' identity mismatch with official release")
                if src.get("sha256") != "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f":
                    raise ValueError(
                        "libopus entry sha256 mismatch with declared published expected_digest: "
                        f"{src.get('sha256')}"
                    )

            for field in ("name", "artifact_url", "filename", "sha256", "verification_evidence"):
                val = src.get(field)
                if not val:
                    raise ValueError(f"Source missing or blank {field}: {name}")
            if not HEX_64_PATTERN.match(src["sha256"]):
                raise ValueError(f"Source sha256 malformed for {name}")

            evidence = src["verification_evidence"]
            if not isinstance(evidence, dict) or not evidence:
                raise ValueError(f"Source missing verification evidence: {name}")

            vtype = evidence.get("type")
            if name == "ffmpeg":
                if vtype != "pgp_signature":
                    raise ValueError(f"Source 'ffmpeg' verification evidence type must be pgp_signature")
                _assert_exact_keys(
                    evidence,
                    {"type", "verified", "artifact_sha256", "signature_url", "signer"},
                    f"lock.sources[{name}].verification_evidence",
                )
                if evidence.get("artifact_sha256") != src.get("sha256"):
                    raise ValueError(
                        f"Source 'ffmpeg' evidence artifact_sha256 must match entry sha256: "
                        f"{evidence.get('artifact_sha256')} != {src.get('sha256')}"
                    )
                if evidence.get("signature_url") != "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc":
                    raise ValueError("Source 'ffmpeg' evidence signature_url mismatch")
                signer = evidence.get("signer")
                if not signer or not isinstance(signer, str) or not signer.strip():
                    raise ValueError("Source 'ffmpeg' evidence signer must be non-empty string")
            elif name == "libopus":
                if vtype != "published_checksum":
                    raise ValueError(f"Source 'libopus' verification evidence type must be published_checksum")
                _assert_exact_keys(
                    evidence,
                    {"type", "algorithm", "expected_digest", "verified", "artifact_sha256", "verifier"},
                    f"lock.sources[{name}].verification_evidence",
                )
                if evidence.get("algorithm") != "sha256":
                    raise ValueError("libopus evidence algorithm must be sha256")
                if evidence.get("expected_digest") != "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f":
                    raise ValueError("libopus evidence digest mismatch")
                if evidence.get("artifact_sha256") != src.get("sha256"):
                    raise ValueError(
                        f"Source 'libopus' evidence artifact_sha256 must match entry sha256: "
                        f"{evidence.get('artifact_sha256')} != {src.get('sha256')}"
                    )
                verifier = evidence.get("verifier")
                if not verifier or not isinstance(verifier, str) or not verifier.strip():
                    raise ValueError("Source 'libopus' evidence verifier must be non-empty string")

        else:
            raise ValueError(f"Unknown acquisition type {expected_type}")

        if evidence.get("verified") is not True:
            raise ValueError(f"Source verification evidence not verified (must be True): {name}")

    if set(lock_source_names) != REQUIRED_SOURCE_NAMES:
        missing = REQUIRED_SOURCE_NAMES - set(lock_source_names)
        extra = set(lock_source_names) - REQUIRED_SOURCE_NAMES
        raise ValueError(
            f"Build lock sources closure must contain exactly all 9 sources. Missing: {sorted(missing)}, Extra: {sorted(extra)}"
        )

    # Outputs validation (declarative only, MUST NOT contain output hashes)
    outputs = lock.get("outputs")
    if not isinstance(outputs, list) or not outputs:
        raise ValueError("Build lock outputs must be a nonempty list")
    seen_output_names = []
    outputs_by_name = {}
    for out in outputs:
        if not isinstance(out, dict):
            raise ValueError("Output item must be an object")
        _assert_exact_keys(out, {"name", "path", "version_prefix"}, f"lock.outputs[{out.get('name')}]")
        _assert_no_hash_fields(out, f"lock.outputs[{out.get('name')}]")
        name = out.get("name")
        if not name or not out.get("path") or not out.get("version_prefix"):
            raise ValueError(f"Output item incomplete: {out}")
        if name in seen_output_names:
            raise ValueError(f"Duplicate output identity detected in lock: '{name}'")
        seen_output_names.append(name)
        outputs_by_name[name] = out

    if set(outputs_by_name.keys()) != set(EXPECTED_OUTPUTS.keys()):
        raise ValueError(f"Outputs in lock must be exactly {set(EXPECTED_OUTPUTS.keys())}")
    for name, expected in EXPECTED_OUTPUTS.items():
        actual = outputs_by_name[name]
        for k, v in expected.items():
            if actual.get(k) != v:
                raise ValueError(f"Output {name} in lock mismatch on {k}: expected {v}, got {actual.get(k)}")


def validate_cached_inputs(lock: dict, cache_dir: Path) -> None:
    """Validate cached input files against build lock hashes and verification policies.

    Verifies every locked source cache object exists at <cache_dir>/<sha256>,
    is a regular file, and its real hashlib SHA-256 equals lock source sha256.
    Rejects missing or mismatched artifacts.
    """
    import hashlib

    sources = lock.get("sources", [])
    for src in sources:
        name = src.get("name", "<unknown>")
        acq_type = src.get("acquisition_type")
        if acq_type == "commit_archive":
            canonical = src.get("canonical_artifact", {})
            expected_sha = canonical.get("sha256")
        else:
            expected_sha = src.get("sha256")

        if not expected_sha:
            raise ValueError(f"Lock source '{name}' missing sha256")

        cached_file = cache_dir / expected_sha
        if not cached_file.exists():
            raise ValueError(
                f"Cached artifact missing for source '{name}': expected at {cached_file}"
            )
        if not cached_file.is_file():
            raise ValueError(
                f"Cached artifact for source '{name}' is not a regular file: {cached_file}"
            )

        hasher = hashlib.sha256()
        with cached_file.open("rb") as f:
            while chunk := f.read(65536):
                hasher.update(chunk)
        actual_sha = hasher.hexdigest()

        if actual_sha != expected_sha:
            raise ValueError(
                f"Cached artifact digest mismatch for source '{name}': "
                f"expected {expected_sha}, got {actual_sha}"
            )


def validate_build_record(lock: dict, record: dict, lock_raw_bytes: bytes | None = None) -> None:
    """Validate build record containing binary hashes and compilation evidence against lock."""
    import hashlib

    if not isinstance(lock, dict):
        raise ValueError("Build lock must be a dictionary")
    if not isinstance(record, dict):
        raise ValueError("Build record must be a dictionary")

    expected_keys = {
        "schema_version",
        "build_lock_sha256",
        "recipe_sha256",
        "builder_script_sha256",
        "command_log_sha256",
        "source_identity",
        "configure",
        "commands_executed",
        "host_inventory",
        "outputs",
        "encoders_sha256",
        "encoders",
        "pe_import_audit",
        "buildconf",
        "config_log",
        "versions",
    }
    _assert_exact_keys(record, expected_keys, "build record root")

    if record["schema_version"] != "1.0.0":
        raise ValueError(f"Unsupported schema_version: {record['schema_version']}")

    lock_sha = record["build_lock_sha256"]
    if not isinstance(lock_sha, str) or not HEX_64_PATTERN.match(lock_sha):
        raise ValueError(f"Invalid build_lock_sha256 in build record: {lock_sha}")

    if lock_raw_bytes is not None:
        actual_lock_sha = hashlib.sha256(lock_raw_bytes).hexdigest()
    else:
        actual_lock_sha = hashlib.sha256(
            json.dumps(lock, sort_keys=True, indent=2).encode("utf-8") + b"\n"
        ).hexdigest()
    if lock_sha != actual_lock_sha:
        raise ValueError(
            f"Build record build_lock_sha256 '{lock_sha}' does not match actual lock sha256 '{actual_lock_sha}'"
        )

    recipe_sha = record["recipe_sha256"]
    if not isinstance(recipe_sha, str) or not HEX_64_PATTERN.match(recipe_sha):
        raise ValueError(f"Invalid recipe_sha256 in build record: {recipe_sha}")

    if lock.get("recipe_sha256") and recipe_sha != lock["recipe_sha256"]:
        raise ValueError("Build record recipe_sha256 does not match lock recipe_sha256")

    builder_script_sha = record["builder_script_sha256"]
    if not isinstance(builder_script_sha, str) or not HEX_64_PATTERN.match(builder_script_sha):
        raise ValueError(f"Invalid builder_script_sha256 in build record: {builder_script_sha}")

    command_log_sha = record["command_log_sha256"]
    if not isinstance(command_log_sha, str) or not HEX_64_PATTERN.match(command_log_sha):
        raise ValueError(f"Invalid command_log_sha256 in build record: {command_log_sha}")

    # Source identity validation
    source_identity = record["source_identity"]
    if not isinstance(source_identity, dict):
        raise ValueError("source_identity must be an object")
    _assert_exact_keys(source_identity, {"sources"}, "build record source_identity")
    if not isinstance(source_identity["sources"], list):
        raise ValueError("source_identity.sources must be a list")

    lock_sources = lock.get("sources", [])
    expected_source_map = {}
    for s in lock_sources:
        s_name = s.get("name")
        if s.get("acquisition_type") == "commit_archive":
            expected_source_map[s_name] = s.get("canonical_artifact", {}).get("sha256")
        else:
            expected_source_map[s_name] = s.get("sha256")

    rec_source_map = {}
    for s in source_identity["sources"]:
        if not isinstance(s, dict):
            raise ValueError("source entry in build record must be an object")
        _assert_exact_keys(s, {"name", "sha256"}, "build record source item")
        if not HEX_64_PATTERN.match(s["sha256"]):
            raise ValueError(f"Invalid sha256 for source {s['name']} in build record")
        rec_source_map[s["name"]] = s["sha256"]

    if set(rec_source_map.keys()) != set(expected_source_map.keys()):
        raise ValueError("Build record sources do not match lock sources")
    for name, expected_sha in expected_source_map.items():
        if rec_source_map[name] != expected_sha:
            raise ValueError(
                f"Source '{name}' sha256 mismatch: expected {expected_sha}, got {rec_source_map[name]}"
            )

    # Configure validation
    rec_cfg = record["configure"]
    if not isinstance(rec_cfg, dict):
        raise ValueError("configure must be an object")
    _assert_exact_keys(rec_cfg, {"flags"}, "build record configure")
    if not isinstance(rec_cfg["flags"], list):
        raise ValueError("configure.flags must be a list")
    if rec_cfg["flags"] != lock.get("configure", {}).get("flags", []):
        raise ValueError("Build record configure flags do not match lock configure flags")

    # Commands executed (actual command strings)
    commands = record["commands_executed"]
    if not isinstance(commands, list) or not commands:
        raise ValueError("commands_executed must be a non-empty list")
    for cmd in commands:
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError("commands_executed must contain non-empty command strings")
        # Ensure commands are actual command lines and not just function labels
        if cmd.startswith("build_") or cmd.startswith("stage_"):
            raise ValueError(
                f"commands_executed contains bare function name '{cmd}'; must record actual invoked commands"
            )
    computed_command_log_sha = hashlib.sha256(
        ("\n".join(commands) + "\n").encode("utf-8")
    ).hexdigest()
    if command_log_sha != computed_command_log_sha:
        raise ValueError("command_log_sha256 does not match commands_executed")

    # Host inventory
    host_inv = record["host_inventory"]
    if not isinstance(host_inv, dict):
        raise ValueError("host_inventory must be an object")
    _assert_exact_keys(host_inv, {"toolchain", "msys2_packages", "tool_versions"}, "build record host_inventory")
    tc = host_inv["toolchain"]
    if not isinstance(tc, dict):
        raise ValueError("host_inventory.toolchain must be an object")
    _assert_exact_keys(tc, {"environment", "target", "gcc_dumpmachine", "gcc_path", "gxx_path"}, "host_inventory.toolchain")
    if tc["environment"] != "UCRT64":
        raise ValueError("host_inventory toolchain environment must be UCRT64")
    if tc["target"] != "x86_64-w64-mingw32" or tc["gcc_dumpmachine"] != "x86_64-w64-mingw32":
        raise ValueError("host_inventory toolchain target mismatch")

    if not isinstance(host_inv["msys2_packages"], list) or not host_inv["msys2_packages"]:
        raise ValueError("host_inventory.msys2_packages must be a non-empty list")
    for pkg in host_inv["msys2_packages"]:
        if not isinstance(pkg, dict):
            raise ValueError("msys2_packages entry must be an object")
        _assert_exact_keys(
            pkg,
            {"package", "locked_version", "version_installed", "matches_lock"},
            "msys2_packages entry",
        )

    if not isinstance(host_inv["tool_versions"], dict):
        raise ValueError("host_inventory.tool_versions must be an object")
    for tool in ("gcc", "nasm", "cmake", "ninja", "meson", "pkgconf"):
        if tool not in host_inv["tool_versions"]:
            raise ValueError(f"Missing tool version in host_inventory: {tool}")

    # Outputs
    outputs = record["outputs"]
    if not isinstance(outputs, dict):
        raise ValueError("outputs must be an object")
    _assert_exact_keys(outputs, {"binaries"}, "build record outputs")
    binaries = outputs["binaries"]
    if not isinstance(binaries, dict):
        raise ValueError("outputs.binaries must be an object")

    for binary_name in ("ffmpeg.exe", "ffprobe.exe"):
        if binary_name not in binaries:
            raise ValueError(f"Missing binary in build record outputs: {binary_name}")
        b_info = binaries[binary_name]
        if not isinstance(b_info, dict):
            raise ValueError(f"Binary info for {binary_name} must be an object")
        _assert_exact_keys(b_info, {"sha256", "size_bytes"}, f"outputs.binaries.{binary_name}")
        if not HEX_64_PATTERN.match(b_info["sha256"]):
            raise ValueError(f"Invalid sha256 for {binary_name} in build record")
        if not isinstance(b_info["size_bytes"], int) or b_info["size_bytes"] <= 0:
            raise ValueError(f"Invalid size_bytes for {binary_name} in build record")

    # Optional libvpl.dll in binaries
    extra_binaries = set(binaries.keys()) - {"ffmpeg.exe", "ffprobe.exe"}
    if extra_binaries and extra_binaries != {"libvpl.dll"}:
        raise ValueError(f"Unexpected extra binaries in build record: {extra_binaries}")
    if "libvpl.dll" in binaries:
        vpl_info = binaries["libvpl.dll"]
        if not isinstance(vpl_info, dict):
            raise ValueError("libvpl.dll info must be an object")
        _assert_exact_keys(vpl_info, {"sha256", "size_bytes"}, "outputs.binaries.libvpl.dll")
        if not HEX_64_PATTERN.match(vpl_info["sha256"]):
            raise ValueError("Invalid sha256 for libvpl.dll in build record")

    # Encoders
    encoders_sha = record["encoders_sha256"]
    if not isinstance(encoders_sha, str) or not HEX_64_PATTERN.match(encoders_sha):
        raise ValueError(f"Invalid encoders_sha256 in build record: {encoders_sha}")

    encoders = record["encoders"]
    if not isinstance(encoders, list):
        raise ValueError("encoders must be a list")
    required_encoders = {
        "libx264",
        "libx265",
        "libvpx-vp9",
        "libsvtav1",
        "libopus",
        "h264_nvenc",
        "hevc_nvenc",
        "av1_nvenc",
        "h264_qsv",
        "hevc_qsv",
        "av1_qsv",
        "h264_amf",
        "hevc_amf",
        "av1_amf",
    }
    found_encoders = set()
    for enc_line in encoders:
        if not isinstance(enc_line, str):
            raise ValueError("encoder entry must be a string")
        for req in required_encoders:
            if req in enc_line:
                found_encoders.add(req)
    missing_encoders = required_encoders - found_encoders
    if missing_encoders:
        raise ValueError(f"Missing required encoder lines in build record: {sorted(missing_encoders)}")

    # PE import audit
    # Policy: standard Windows system DLLs allowed (+ optional libvpl.dll if staged/present);
    # Reject GPU driver DLLs, MinGW runtimes, and other non-system third-party DLLs.
    SYSTEM_DLLS = {
        "advapi32.dll", "avicap32.dll", "bcrypt.dll", "crypt32.dll", "d3d11.dll", "dxgi.dll",
        "gdi32.dll", "kernel32.dll", "mf.dll", "mfplat.dll", "mfreadwrite.dll",
        "msvcrt.dll", "ntdll.dll", "ole32.dll", "oleaut32.dll", "psapi.dll",
        "secur32.dll", "shell32.dll", "shlwapi.dll", "user32.dll", "userenv.dll",
        "version.dll", "ws2_32.dll", "wsock32.dll",
    }
    FORBIDDEN_DLL_SUBSTRINGS = (
        "nvencodeapi",
        "nvcuda",
        "amfrt",
        "igfx",
        "libmfx",
        "libgcc_s",
        "libstdc++",
        "libwinpthread",
    )

    def is_allowed_dll(dll_name: str, allow_vpl: bool) -> bool:
        lower = dll_name.lower()
        if any(bad in lower for bad in FORBIDDEN_DLL_SUBSTRINGS):
            return False
        if allow_vpl and lower == "libvpl.dll":
            return True
        return (
            lower in SYSTEM_DLLS
            or lower.startswith("api-ms-win-")
            or lower.startswith("ext-ms-win-")
        )

    pe_audit = record["pe_import_audit"]
    if not isinstance(pe_audit, dict):
        raise ValueError("pe_import_audit must be an object")

    has_vpl_binary = "libvpl.dll" in binaries
    for binary_name in ("ffmpeg.exe", "ffprobe.exe"):
        if binary_name not in pe_audit:
            raise ValueError(f"Missing {binary_name} in pe_import_audit")
        b_audit = pe_audit[binary_name]
        if not isinstance(b_audit, dict):
            raise ValueError(f"pe_import_audit[{binary_name}] must be an object")
        _assert_exact_keys(b_audit, {"imported_dlls", "forbidden_dlls_detected"}, f"pe_import_audit.{binary_name}")
        if not isinstance(b_audit["imported_dlls"], list):
            raise ValueError("imported_dlls must be a list")
        if not isinstance(b_audit["forbidden_dlls_detected"], list):
            raise ValueError("forbidden_dlls_detected must be a list")
        if b_audit["forbidden_dlls_detected"]:
            raise ValueError(f"Forbidden DLL imports detected in {binary_name}: {b_audit['forbidden_dlls_detected']}")

        # Validate that every imported DLL is allowed by the positive policy
        for dll in b_audit["imported_dlls"]:
            if not is_allowed_dll(dll, allow_vpl=has_vpl_binary):
                raise ValueError(
                    f"Illegal non-system/unauthorized DLL import detected in {binary_name}: '{dll}'"
                )

    if "libvpl.dll" in pe_audit:
        vpl_audit = pe_audit["libvpl.dll"]
        if not isinstance(vpl_audit, dict):
            raise ValueError("pe_import_audit['libvpl.dll'] must be an object")
        _assert_exact_keys(vpl_audit, {"imported_dlls", "forbidden_dlls_detected"}, "pe_import_audit.libvpl.dll")
        if vpl_audit["forbidden_dlls_detected"]:
            raise ValueError(f"Forbidden DLL imports detected in libvpl.dll: {vpl_audit['forbidden_dlls_detected']}")
        for dll in vpl_audit["imported_dlls"]:
            if not is_allowed_dll(dll, allow_vpl=False):
                raise ValueError(
                    f"Illegal non-system DLL import detected in libvpl.dll: '{dll}'"
                )

    # Buildconf
    bconf = record["buildconf"]
    if not isinstance(bconf, dict):
        raise ValueError("buildconf must be an object")
    _assert_exact_keys(bconf, {"ffmpeg", "ffprobe"}, "buildconf")
    for tool_name in ("ffmpeg", "ffprobe"):
        if not isinstance(bconf[tool_name], str) or not bconf[tool_name].strip():
            raise ValueError(f"buildconf.{tool_name} must be a non-empty string")

    # Config log
    cfg_log = record["config_log"]
    if not isinstance(cfg_log, dict):
        raise ValueError("config_log must be an object")
    _assert_exact_keys(cfg_log, {"path", "sha256"}, "config_log")
    if not isinstance(cfg_log["path"], str) or not cfg_log["path"].endswith("config.log"):
        raise ValueError("config_log.path must end with config.log")
    if not HEX_64_PATTERN.match(cfg_log["sha256"]):
        raise ValueError("config_log.sha256 must be a valid 64-hex digest")

    # Versions
    versions = record["versions"]
    if not isinstance(versions, dict):
        raise ValueError("versions must be an object")
    _assert_exact_keys(versions, {"ffmpeg", "ffprobe"}, "versions")
    if not versions["ffmpeg"].startswith("ffmpeg version 6.1.1"):
        raise ValueError("ffmpeg version prefix mismatch in build record")
    if not versions["ffprobe"].startswith("ffprobe version 6.1.1"):
        raise ValueError("ffprobe version prefix mismatch in build record")


def validate_release(lock: dict, record: dict, binary_manifest: dict, source_bundle: Path) -> None:
    """Validate release packaging, source bundle completeness, and binary provenance.

    Owned by Task 5 (Packaging and Provenance Verification).
    """
    raise NotImplementedError("validate_release is implemented in Task 5")
