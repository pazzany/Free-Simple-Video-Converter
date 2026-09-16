"""Update acquisition report patches and recipe_sha256 deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
from typing import Sequence


def _find_repo_root(start_path: Path) -> Path:
    current = start_path.resolve()
    for parent in [current, *current.parents]:
        if (parent / ".git").exists():
            return parent
    return current


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def update_report_patches(
    manifest_path: Path,
    report_path: Path,
    patch_args: Sequence[str],
    repo_root: Path | None = None,
) -> None:
    manifest_path = manifest_path.resolve()
    report_path = report_path.resolve()

    if not manifest_path.is_file():
        raise ValueError(f"Manifest file not found: {manifest_path}")
    if not report_path.is_file():
        raise ValueError(f"Report file not found: {report_path}")

    if repo_root is None:
        repo_root = _find_repo_root(manifest_path.parent)
    else:
        repo_root = repo_root.resolve()

    # Load raw manifest bytes and compute sha256
    manifest_raw_bytes = manifest_path.read_bytes()
    recipe_sha256 = _compute_sha256(manifest_raw_bytes)

    try:
        manifest_data = json.loads(manifest_raw_bytes.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Failed to parse manifest JSON: {exc}") from exc

    manifest_patches = manifest_data.get("patches", [])
    if not isinstance(manifest_patches, list):
        raise ValueError("Manifest 'patches' must be a list")

    manifest_patch_map: dict[str, str] = {}
    for idx, p in enumerate(manifest_patches):
        if not isinstance(p, dict):
            raise ValueError(f"Manifest patch at index {idx} must be a dict")
        name = p.get("name")
        path_str = p.get("path")
        if not name or not isinstance(name, str):
            raise ValueError(f"Manifest patch at index {idx} missing valid 'name'")
        if not path_str or not isinstance(path_str, str):
            raise ValueError(f"Manifest patch at index {idx} missing valid 'path'")
        if name in manifest_patch_map:
            raise ValueError(f"Duplicate patch name in manifest: {name}")
        manifest_patch_map[name] = path_str

    parsed_patch_cli: dict[str, str] = {}
    for arg in patch_args:
        if "=" not in arg:
            raise ValueError(f"Invalid patch argument format (must be name=path): {arg}")
        name, rel_path = arg.split("=", 1)
        if not name or not rel_path:
            raise ValueError(f"Invalid patch argument (empty name or path): {arg}")
        if name in parsed_patch_cli:
            raise ValueError(f"Duplicate patch specified in arguments: {name}")
        if name not in manifest_patch_map:
            raise ValueError(f"Patch '{name}' not declared in manifest")
        if manifest_patch_map[name] != rel_path:
            raise ValueError(
                f"Patch path mismatch for '{name}': manifest declares '{manifest_patch_map[name]}', got '{rel_path}'"
            )
        parsed_patch_cli[name] = rel_path

    # Check for missing patches
    missing_patches = set(manifest_patch_map.keys()) - set(parsed_patch_cli.keys())
    if missing_patches:
        raise ValueError(f"Missing patch definitions for: {sorted(missing_patches)}")

    # Resolve patch files below repo root, reject traversal/absolute, compute sha256
    computed_patches: list[dict[str, str]] = []
    for p in manifest_patches:
        name = p["name"]
        rel_path_str = parsed_patch_cli[name]

        rel_path = Path(rel_path_str)
        if rel_path.is_absolute():
            raise ValueError(f"Patch path must be relative to repository root: {rel_path_str}")

        # Check for traversal before resolving
        parts = rel_path.parts
        if ".." in parts:
            raise ValueError(f"Path traversal detected in patch path: {rel_path_str}")

        unresolved_patch_path = repo_root / rel_path
        if unresolved_patch_path.is_symlink():
            raise ValueError(f"Patch file must not be a symbolic link: {rel_path_str}")
        full_patch_path = unresolved_patch_path.resolve()
        try:
            full_patch_path.relative_to(repo_root)
        except ValueError:
            raise ValueError(f"Patch path escapes repository root: {rel_path_str}")

        if not full_patch_path.is_file():
            raise ValueError(f"Patch file does not exist or is not a regular file: {rel_path_str}")

        patch_bytes = full_patch_path.read_bytes()
        patch_sha256 = _compute_sha256(patch_bytes)

        computed_patches.append(
            {
                "name": name,
                "path": rel_path_str,
                "sha256": patch_sha256,
            }
        )

    # Load report
    try:
        report_text = report_path.read_text(encoding="utf-8")
        report_data = json.loads(report_text)
    except Exception as exc:
        raise ValueError(f"Failed to read/parse report JSON: {exc}") from exc

    if not isinstance(report_data, dict):
        raise ValueError("Report top-level must be a JSON object")

    report_data["recipe_sha256"] = recipe_sha256
    report_data["patches"] = computed_patches

    # Write sorted indent=2 UTF-8 JSON trailing newline atomically
    report_dir = report_path.parent
    report_dir.mkdir(parents=True, exist_ok=True)
    temp_file = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(report_dir),
            delete=False,
            newline="\n",
        ) as tf:
            temp_file = Path(tf.name)
            json.dump(report_data, tf, indent=2, sort_keys=True)
            tf.write("\n")
        temp_file.replace(report_path)
    finally:
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
            except OSError:
                pass


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Deterministically update acquisition report patches and recipe_sha256."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to acquisition-manifest.json",
    )
    parser.add_argument(
        "--report",
        required=True,
        type=Path,
        help="Path to acquisition-report.json",
    )
    parser.add_argument(
        "--patch",
        action="append",
        dest="patches",
        default=[],
        help="Patch in name=repository-relative-path format",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Optional override for repository root",
    )

    args = parser.parse_args(argv)

    try:
        update_report_patches(
            manifest_path=args.manifest,
            report_path=args.report,
            patch_args=args.patches,
            repo_root=args.repo_root,
        )
    except Exception as err:
        sys.stderr.write(f"Error: {err}\n")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
