"""Candidate output qualification CLI and verification logic for FFmpeg build outputs.

Validates that a built FFmpeg candidate output directory strictly matches the
lock, build script provenance, reconstruction evidence, required encoders,
version prefixes, binary hashes/sizes, and positive PE import policy.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

# Ensure workspace root and src are in sys.path when invoked directly
_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent
_SRC_DIR = _REPO_ROOT / "src"
_PACKAGING_DIR = _REPO_ROOT / "packaging"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
if str(_PACKAGING_DIR) not in sys.path:
    sys.path.insert(0, str(_PACKAGING_DIR))

from video_converter.ffmpeg_build_manifest import (
    decode_json_without_duplicate_keys,
    load_json,
    validate_build_record,
)
from video_converter.ffmpeg_build.source_bundle import (
    STANDARD_RECONSTRUCTION_FILES,
    parse_pe_imports,
    validate_encoder_inventory,
)
from package_release_assets import (
    validate_binary_size_and_sha,
    verify_binary_versions,
)


def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def qualify_output(output_dir: Path, workspace_root: Path) -> dict[str, Any]:
    """Qualify candidate output directory against workspace builder and lock.

    Returns qualification report dictionary only on success; raises ValueError
    or FileNotFoundError on any discrepancy or missing artifact.
    """
    output_dir = output_dir.resolve()
    workspace_root = workspace_root.resolve()

    if not output_dir.is_dir():
        raise FileNotFoundError(f"Output directory does not exist: {output_dir}")
    if not workspace_root.is_dir():
        raise FileNotFoundError(f"Workspace root does not exist: {workspace_root}")

    # 1. Verify build.lock.json in workspace
    lock_path = workspace_root / "packaging" / "ffmpeg-build" / "build.lock.json"
    if not lock_path.is_file():
        raise FileNotFoundError(f"Build lock file not found: {lock_path}")
    lock_bytes = lock_path.read_bytes()
    lock = decode_json_without_duplicate_keys(lock_bytes.decode("utf-8"))

    # 2. Verify build_ffmpeg.sh in workspace
    builder_script_path = workspace_root / "packaging" / "ffmpeg-build" / "build_ffmpeg.sh"
    if not builder_script_path.is_file():
        raise FileNotFoundError(f"Builder script not found: {builder_script_path}")
    current_builder_sha = _compute_sha256(builder_script_path.read_bytes())

    # 3. Verify all standard reconstruction files exist in output_dir
    for rf in STANDARD_RECONSTRUCTION_FILES:
        rf_path = output_dir / rf
        if not rf_path.is_file():
            raise FileNotFoundError(f"Required reconstruction file missing in candidate output: {rf_path}")

    # 4. Load candidate build-record.json
    record_path = output_dir / "build-record.json"
    record = load_json(record_path)

    # 5. Validate build record against lock using existing canonical validator (also validates PE allowlist positive policy)
    validate_build_record(lock, record, lock_raw_bytes=lock_bytes)

    # 6. Verify record builder_script_sha256 matches current packaging/ffmpeg-build/build_ffmpeg.sh
    record_builder_sha = record.get("builder_script_sha256")
    if record_builder_sha != current_builder_sha:
        raise ValueError(
            f"Build record builder_script_sha256 '{record_builder_sha}' "
            f"does not match current workspace builder sha256 '{current_builder_sha}'"
        )

    # 7. Bind reconstruction evidence against record
    # 7a. config.log SHA equals record config_log.sha256
    config_log_path = output_dir / "config.log"
    actual_config_log_sha = _compute_sha256(config_log_path.read_bytes())
    expected_config_log_sha = record.get("config_log", {}).get("sha256")
    if actual_config_log_sha != expected_config_log_sha:
        raise ValueError(
            f"config.log sha256 mismatch: expected {expected_config_log_sha}, got {actual_config_log_sha}"
        )

    # 7b. commands.log SHA equals record command_log_sha256
    commands_log_path = output_dir / "commands.log"
    actual_commands_log_sha = _compute_sha256(commands_log_path.read_bytes())
    expected_command_log_sha = record.get("command_log_sha256")
    if actual_commands_log_sha != expected_command_log_sha:
        raise ValueError(
            f"commands.log sha256 mismatch: expected {expected_command_log_sha}, got {actual_commands_log_sha}"
        )

    # 7c. ffmpeg-buildconf.txt and ffprobe-buildconf.txt exact normalized equality to record buildconf
    for tool_name in ("ffmpeg", "ffprobe"):
        bconf_file = output_dir / f"{tool_name}-buildconf.txt"
        file_text = bconf_file.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()
        rec_text = record.get("buildconf", {}).get(tool_name, "").replace("\r\n", "\n").strip()
        if file_text != rec_text:
            raise ValueError(
                f"{tool_name}-buildconf.txt content does not match build record buildconf.{tool_name}"
            )

    # 7d. Imports dump exact parsed equality to record pe_import_audit
    pe_audit = record.get("pe_import_audit", {})
    ffmpeg_imports_file = output_dir / "ffmpeg-imports.txt"
    ffprobe_imports_file = output_dir / "ffprobe-imports.txt"
    parsed_ffmpeg_imports = parse_pe_imports(ffmpeg_imports_file.read_text(encoding="utf-8", errors="replace"))
    parsed_ffprobe_imports = parse_pe_imports(ffprobe_imports_file.read_text(encoding="utf-8", errors="replace"))
    rec_ffmpeg_imports = {dll.lower() for dll in pe_audit.get("ffmpeg.exe", {}).get("imported_dlls", [])}
    rec_ffprobe_imports = {dll.lower() for dll in pe_audit.get("ffprobe.exe", {}).get("imported_dlls", [])}
    if parsed_ffmpeg_imports != rec_ffmpeg_imports:
        raise ValueError("ffmpeg-imports.txt parsed DLLs do not match build record pe_import_audit")
    if parsed_ffprobe_imports != rec_ffprobe_imports:
        raise ValueError("ffprobe-imports.txt parsed DLLs do not match build record pe_import_audit")

    # 7e. libvpl-imports.txt check if libvpl.dll in record outputs or pe_import_audit
    rec_binaries = record.get("outputs", {}).get("binaries", {})
    if "libvpl.dll" in rec_binaries or "libvpl.dll" in pe_audit:
        libvpl_imports_file = output_dir / "libvpl-imports.txt"
        if not libvpl_imports_file.is_file():
            raise FileNotFoundError(f"Required reconstruction file missing for libvpl: {libvpl_imports_file}")
        parsed_vpl_imports = parse_pe_imports(libvpl_imports_file.read_text(encoding="utf-8", errors="replace"))
        rec_vpl_imports = {dll.lower() for dll in pe_audit.get("libvpl.dll", {}).get("imported_dlls", [])}
        if parsed_vpl_imports != rec_vpl_imports:
            raise ValueError("libvpl-imports.txt parsed DLLs do not match build record pe_import_audit")

    # 8. Raw encoders.txt digest & semantic encoders verification via shared source_bundle validator
    encoders_path = output_dir / "encoders.txt"
    validate_encoder_inventory(encoders_path.read_bytes(), record, context="encoders.txt")

    # 9. Validate sha256 and size for EVERY record outputs.binaries entry
    bin_dir = output_dir / "bin"
    for bin_name, b_info in rec_binaries.items():
        bin_path = bin_dir / bin_name
        expected_sha = b_info.get("sha256")
        expected_size = b_info.get("size_bytes")
        if not expected_sha or expected_size is None:
            raise ValueError(f"Build record outputs.binaries['{bin_name}'] missing sha256 or size_bytes")
        validate_binary_size_and_sha(bin_path, expected_sha, expected_size, f"Candidate {bin_name}")

    # 10. Verify binary version prefixes via project verifier and locked manifest expected prefixes
    lock_outputs = {out["name"]: out for out in lock.get("outputs", []) if isinstance(out, dict)}
    ffmpeg_lock = lock_outputs.get("ffmpeg")
    ffprobe_lock = lock_outputs.get("ffprobe")
    if not isinstance(ffmpeg_lock, dict) or not isinstance(ffmpeg_lock.get("version_prefix"), str) or not ffmpeg_lock["version_prefix"].strip():
        raise ValueError("build.lock.json missing or invalid nonempty version_prefix for outputs['ffmpeg']")
    if not isinstance(ffprobe_lock, dict) or not isinstance(ffprobe_lock.get("version_prefix"), str) or not ffprobe_lock["version_prefix"].strip():
        raise ValueError("build.lock.json missing or invalid nonempty version_prefix for outputs['ffprobe']")
    expected_ffmpeg_ver = ffmpeg_lock["version_prefix"]
    expected_ffprobe_ver = ffprobe_lock["version_prefix"]

    ffmpeg_bin = bin_dir / "ffmpeg.exe"
    ffprobe_bin = bin_dir / "ffprobe.exe"
    verify_binary_versions(
        ffmpeg_bin,
        ffprobe_bin,
        expected_ffmpeg_version=expected_ffmpeg_ver,
        expected_ffprobe_version=expected_ffprobe_ver,
    )

    return {
        "status": "qualified",
        "output_dir": str(output_dir),
        "workspace_root": str(workspace_root),
        "builder_script_sha256": current_builder_sha,
        "encoders_sha256": record["encoders_sha256"],
        "binaries": {
            k: {"sha256": v["sha256"], "size_bytes": v["size_bytes"]}
            for k, v in rec_binaries.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Qualify candidate FFmpeg build output directory.")
    parser.add_argument("--output-dir", required=True, type=Path, help="Path to candidate output directory")
    parser.add_argument("--workspace-root", required=True, type=Path, help="Path to workspace root")

    args = parser.parse_args(argv)
    try:
        report = qualify_output(output_dir=args.output_dir, workspace_root=args.workspace_root)
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        sys.stderr.write(f"Qualification failed: {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
