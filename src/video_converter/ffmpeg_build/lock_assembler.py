"""Canonical build lock assembly and atomic publication."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Any, Sequence

from video_converter.ffmpeg_build.acquisition_report import AcquisitionReport
from video_converter.ffmpeg_build.msys2_closure import ResolvedMsys2Closure
from video_converter.ffmpeg_build.source_cache import ResolvedSource


def _lock_signature(signature: Any) -> dict[str, Any]:
    return {
        "filename": signature.signature_filename,
        "sha256": signature.signature_sha256,
        "retention_uri": signature.signature_retention_uri,
        "verified": signature.verified,
        "verifier": signature.verifier,
        "signer": signature.signer,
    }


def assemble_build_lock(
    manifest: dict[str, Any],
    manifest_sha256: str,
    sources: Sequence[ResolvedSource],
    msys2: ResolvedMsys2Closure,
    report: AcquisitionReport,
) -> dict[str, Any]:
    """Assemble a complete, canonical build lock dictionary bound to the manifest."""
    declared_patches = manifest.get("patches", [])
    if not isinstance(declared_patches, list):
        raise ValueError("manifest patches must be a list")
    try:
        expected_patch_identities = [(patch["name"], patch["path"]) for patch in declared_patches]
    except (KeyError, TypeError) as exc:
        raise ValueError("manifest patches must declare name and path") from exc
    report_patch_identities = [(patch.name, patch.path) for patch in report.patches]
    if (
        len(set(expected_patch_identities)) != len(declared_patches)
        or len(set(report_patch_identities)) != len(report.patches)
        or report_patch_identities != expected_patch_identities
    ):
        raise ValueError("report patch evidence does not exactly match manifest patches")

    sources_by_name = {s.name: s for s in sources}
    lock_sources = []
    for src in manifest.get("sources", []):
        name = src["name"]
        resolved = sources_by_name[name]
        acq_type = src["acquisition_type"]

        if acq_type == "commit_archive":
            item = {
                "name": resolved.name,
                "acquisition_type": "commit_archive",
                "commit": src["commit"],
                "upstream_remote_url": src["git_remote_url"],
                "canonical_artifact": {
                    "origin": "git_archive",
                    "filename": resolved.canonical_filename,
                    "sha256": resolved.sha256,
                    "retention_uri": resolved.canonical_retention_uri,
                },
                "verification_evidence": dict(resolved.verification_evidence),
            }
        else:
            item = {
                "name": resolved.name,
                "acquisition_type": src["acquisition_type"],
                "artifact_url": resolved.artifact_url,
                "filename": resolved.filename,
                "sha256": resolved.sha256,
                "verification_evidence": dict(resolved.verification_evidence),
            }
            if "version" in src:
                item["version"] = src["version"]
            if "source_commit" in src:
                item["source_commit"] = src["source_commit"]

        lock_sources.append(item)

    lock_packages = [
        {
            "name": pkg.name,
            "version": pkg.version,
            "filename": pkg.filename,
            "sha256": pkg.sha256,
            "signature_sha256": pkg.signature_sha256,
            "signature": _lock_signature(pkg.signature),
            "retention_uri": pkg.retention_uri,
            "dependencies": list(pkg.dependencies),
        }
        for pkg in msys2.packages
    ]

    lock_databases = [
        {
            "name": db.name,
            "sha256": db.sha256,
            "signature_sha256": db.signature_sha256,
            "signature": _lock_signature(db.signature),
            "retention_uri": db.retention_uri,
        }
        for db in msys2.databases
    ]

    lock_patches = [
        {
            "name": patch.name,
            "path": patch.path,
            "sha256": patch.sha256,
        }
        for patch in report.patches
    ]

    lock_outputs = [
        {
            "name": out["name"],
            "path": out["path"],
            "version_prefix": out["version_prefix"],
        }
        for out in manifest.get("outputs", [])
    ]

    lock: dict[str, Any] = {
        "schema_version": "1.0.0",
        "acquisition_manifest_sha256": manifest_sha256,
        "recipe_sha256": report.recipe_sha256,
        "toolchain": {
            "environment": manifest["toolchain"]["environment"],
            "target": manifest["toolchain"]["target"],
        },
        "msys2": {
            "installer": {
                "url": msys2.installer.url,
                "sha256": msys2.installer.sha256,
                "signature_sha256": msys2.installer.signature_sha256,
                "signature": _lock_signature(msys2.installer.signature),
                "retention_uri": msys2.installer.retention_uri,
            },
            "databases": lock_databases,
            "packages": lock_packages,
        },
        "sources": lock_sources,
        "patches": lock_patches,
        "configure": {
            "flags": list(manifest["configure"]["flags"]),
        },
        "outputs": lock_outputs,
    }

    return lock


def publish_build_lock(lock: dict[str, Any], output_path: Path) -> Path:
    """Atomically publish build lock to output_path using sorted UTF-8 JSON.

    Serializes sorted UTF-8 JSON with indent=2 and trailing newline into an output-sibling
    temporary file and atomically replaces output_path.
    If writing or replacement fails, an existing output is preserved and the temporary
    file owned by this invocation is removed.
    """
    output_path = Path(output_path).resolve()
    parent_dir = output_path.parent
    parent_dir.mkdir(parents=True, exist_ok=True)

    temp_file = tempfile.NamedTemporaryFile(
        dir=parent_dir,
        prefix=f".{output_path.stem}.",
        suffix=".tmp",
        delete=False,
        mode="w",
        encoding="utf-8",
        newline="\n",
    )
    temp_path = Path(temp_file.name)

    try:
        content = json.dumps(lock, sort_keys=True, indent=2) + "\n"
        temp_file.write(content)
        temp_file.flush()
        temp_file.close()

        temp_path.replace(output_path)
        return output_path
    except BaseException as err:
        try:
            temp_file.close()
        except Exception:
            pass
        if temp_path.exists():
            try:
                temp_path.unlink()
            except OSError as cleanup_err:
                raise cleanup_err from err
            except Exception:
                pass
        raise
