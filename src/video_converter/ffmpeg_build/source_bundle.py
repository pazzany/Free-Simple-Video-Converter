"""Corresponding source bundle creation and validation engine."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any
import zipfile

from video_converter.ffmpeg_build_manifest import (
    REQUIRED_SOURCE_NAMES,
    decode_json_without_duplicate_keys,
    load_json,
    validate_build_lock,
    validate_build_record,
    validate_cached_inputs,
)

# Deterministic ZIP timestamp: 1980-01-01 00:00:00
DETERMINISTIC_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
DETERMINISTIC_FILE_MODE = 0o644
ZIP_UNIX_SYSTEM = 3

STANDARD_RECONSTRUCTION_FILES = [
    "build-record.json",
    "config.log",
    "commands.log",
    "encoders.txt",
    "ffmpeg-imports.txt",
    "ffprobe-imports.txt",
    "ffmpeg-buildconf.txt",
    "ffprobe-buildconf.txt",
]

STANDARD_RECIPE_FILES = [
    ("packaging/ffmpeg-build/acquisition-manifest.json", "recipe/acquisition-manifest.json"),
    ("packaging/ffmpeg-build/build.lock.json", "recipe/build.lock.json"),
    ("packaging/ffmpeg-build/build_ffmpeg.sh", "recipe/build_ffmpeg.sh"),
    ("packaging/ffmpeg-build/update_report_patches.py", "recipe/update_report_patches.py"),
    ("packaging/ffmpeg-build/resolve_lock.py", "recipe/resolve_lock.py"),
    ("packaging/ffmpeg-build/artifacts/acquisition-report.json", "recipe/acquisition-report.json"),
]

STANDARD_PATCH_FILES = [
    (
        "packaging/ffmpeg-build/patches/x265-cmake-4.4-compatibility.patch",
        "patches/x265-cmake-4.4-compatibility.patch",
    ),
    (
        "packaging/ffmpeg-build/patches/x265-pkgconfig-libs-private-no-lgcc_s.patch",
        "patches/x265-pkgconfig-libs-private-no-lgcc_s.patch",
    ),
]

STANDARD_LICENSE_FILES = [
    ("LICENSE", "licenses/LICENSE"),
    ("THIRD_PARTY_NOTICES.md", "licenses/THIRD_PARTY_NOTICES.md"),
]

STANDARD_BUILD_WORKSPACE_PYTHON_FILES = [
    (
        "src/video_converter/__init__.py",
        "build_workspace/src/video_converter/__init__.py",
    ),
    (
        "src/video_converter/ffmpeg_build_manifest.py",
        "build_workspace/src/video_converter/ffmpeg_build_manifest.py",
    ),
]

REQUIRED_ENCODER_TOKENS = (
    "libx264",
    "libx265",
    "libvpx-vp9",
    "libsvtav1",
    "libopus",
    "_nvenc",
    "_qsv",
    "_amf",
)


def validate_encoder_inventory(raw_bytes: bytes, record: dict[str, Any], context: str = "encoders.txt") -> None:
    """Validate exact raw SHA-256 digest and filtered semantic encoder subset against build record."""
    expected_sha = record.get("encoders_sha256")
    if not expected_sha:
        raise ValueError(f"Missing encoders_sha256 in build record for {context}")
    actual_sha = _compute_sha256(raw_bytes)
    if actual_sha != expected_sha:
        raise ValueError(
            f"{context} sha256 mismatch: {actual_sha} != {expected_sha} (encoders_sha256)"
        )

    encoders_text = raw_bytes.decode("utf-8")
    actual_encoders = [line for line in encoders_text.splitlines() if line.strip()]
    record_encoders = [line for line in record.get("encoders", []) if line.strip()]
    if actual_encoders != record_encoders:
        filtered_actual = [
            line for line in actual_encoders
            if any(name in line for name in REQUIRED_ENCODER_TOKENS)
        ]
        if filtered_actual != record_encoders:
            raise ValueError(f"{context} does not match build record encoders")


# Backward compatibility alias
_validate_encoders_inventory = validate_encoder_inventory




def _compute_sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonicalize_locked_patch_bytes(data: bytes) -> bytes:
    """Return the LF form used by immutable locked patch digests."""
    return data.replace(b"\r\n", b"\n")


def _assert_not_symlink(path: Path, context: str) -> None:
    if path.is_symlink():
        raise ValueError(f"Symlink input rejected for {context}: {path}")


def _assert_no_symlinks_in_path_and_parents(path: Path, context: str) -> None:
    """Verify path itself and none of its ancestors are symlinks."""
    _assert_not_symlink(path, context)
    curr = path
    while curr != curr.parent:
        if curr.is_symlink():
            raise ValueError(f"Symlink rejected in path or ancestor for {context}: {curr}")
        curr = curr.parent


def _assert_path_under_root_and_no_symlinks(path: Path, root: Path, context: str) -> None:


    """Verify that path is within resolved root and no symlinks exist in path or beneath root."""
    _assert_not_symlink(path, context)
    resolved_root = root.resolve()
    resolved_path = path.resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError:
        raise ValueError(f"Path escapes allowed root {resolved_root} for {context}: {resolved_path}")

    # Ensure no component from root down to path is a symlink
    curr = path
    while curr != root and curr != curr.parent:
        if curr.is_symlink():
            raise ValueError(f"Symlink component rejected in path for {context}: {curr}")
        curr = curr.parent




def parse_pe_imports(text: str) -> set[str]:
    """Parse DLL Name: lines from dumpbin/objdump style import text."""
    dlls = set()
    for line in text.splitlines():
        line = line.strip()
        if line.lower().startswith("dll name:"):
            dll = line.split(":", 1)[1].strip()
            if dll:
                dlls.add(dll.lower())
    return dlls


# Backward compatibility alias
_parse_pe_imports = parse_pe_imports


def _validate_archive_rel_path(path_str: str) -> PurePosixPath:
    """Validate that path_str is a safe, relative, non-traversing POSIX path."""


    if "\\" in path_str:
        raise ValueError(f"Backslashes forbidden in ZIP entry path: {path_str}")
    if ":" in path_str:
        raise ValueError(f"Drive or colon forbidden in ZIP entry path: {path_str}")
    if path_str.startswith(("//", "\\\\")):
        raise ValueError(f"UNC path forbidden in ZIP entry path: {path_str}")
    posix_path = PurePosixPath(path_str)
    if posix_path.is_absolute():
        raise ValueError(f"Absolute path forbidden in ZIP entry: {path_str}")
    if posix_path.drive:
        raise ValueError(f"Drive path forbidden in ZIP entry: {path_str}")
    parts = posix_path.parts
    if not parts or any(p in ("", ".", "..") for p in parts):
        raise ValueError(f"Unsafe path elements or traversal in ZIP entry: {path_str}")
    return posix_path



def extract_source_entry_info(src: dict[str, Any]) -> tuple[str, str, str]:
    """Extract (name, filename, sha256) from a locked source dictionary."""
    name = src.get("name")
    if not name or not isinstance(name, str):
        raise ValueError(f"Source entry missing valid name: {src}")
    if src.get("acquisition_type") == "commit_archive":
        canonical = src.get("canonical_artifact", {})
        if not isinstance(canonical, dict):
            raise ValueError(f"Source {name} missing canonical_artifact dict")
        sha = canonical.get("sha256")
        fn = canonical.get("filename")
    else:
        sha = src.get("sha256")
        fn = src.get("filename")

    if not sha or not isinstance(sha, str) or len(sha) != 64:
        raise ValueError(f"Source {name} missing valid 64-hex sha256: {sha}")
    if not fn or not isinstance(fn, str):
        raise ValueError(f"Source {name} missing valid filename: {fn}")

    # Ensure filename is safe (no slashes/directory separators or drive prefixes)
    if ":" in fn:
        raise ValueError(f"Source {name} filename contains drive prefix or colon: {fn}")
    PurePosixPath(fn)
    if "/" in fn or "\\" in fn:
        raise ValueError(f"Source {name} filename contains path separator: {fn}")


    return name, fn, sha


def generate_reproduction_readme(build_record: dict[str, Any], build_lock: dict[str, Any]) -> str:
    """Produce offline build reproduction instructions with exact reproduction commands."""
    host_inv = build_record.get("host_inventory", {})
    toolchain = host_inv.get("toolchain", {})
    env = toolchain.get("environment", build_lock.get("toolchain", {}).get("environment", "UCRT64"))
    target = toolchain.get("target", build_lock.get("toolchain", {}).get("target", "x86_64-w64-mingw32"))
    gcc_path = toolchain.get("gcc_path", "x86_64-w64-mingw32-gcc")
    tool_versions = host_inv.get("tool_versions", {})
    lock_sha = build_record.get("build_lock_sha256", "")
    recipe_sha = build_record.get("recipe_sha256", "")

    flags = build_record.get("configure", {}).get("flags", [])
    if not flags:
        flags = build_lock.get("configure", {}).get("flags", [])
    flags_formatted = " \\\n    ".join(flags)

    sources_list = []
    for s in build_lock.get("sources", []):
        s_name, s_fn, s_sha = extract_source_entry_info(s)
        sources_list.append(f"- **{s_name}**: `{s_fn}` (SHA-256: `{s_sha}`)")

    sources_formatted = "\n".join(sources_list)

    return f"""# FFmpeg 6.1.1 Offline Build Reproduction Guide

This archive contains the complete corresponding source code, build recipes,
patches, and reconstruction evidence required to reproduce the custom static
FFmpeg binaries under MSYS2 {env}.

## 1. Environment & Prerequisites

- **Environment**: MSYS2 {env}
- **Target Triple**: `{target}`
- **Compiler Executable**: `{gcc_path}`
- **Toolchain Versions**:
  - GCC: `{tool_versions.get("gcc", "unknown")}`
  - CMake: `{tool_versions.get("cmake", "unknown")}`
  - Meson: `{tool_versions.get("meson", "unknown")}`
  - Ninja: `{tool_versions.get("ninja", "unknown")}`
  - NASM: `{tool_versions.get("nasm", "unknown")}`
  - objdump: `{tool_versions.get("objdump", "unknown")}`

## 2. Integrity Verification

- **Build Lock SHA-256**: `{lock_sha}`
- **Recipe SHA-256**: `{recipe_sha}`

### Source Archives:
{sources_formatted}

## 3. Directory Layout

- `sources/`: All 9 pristine upstream source tarballs (indexed by canonical archive filename).
- `recipe/`: Declarative manifest, lock file, build script, patch updater, and acquisition report.
- `patches/`: Source patches applied during build (e.g. x265 CMake / Libs.private patches).
- `licenses/`: Applicable licenses and third-party notices.
- `reconstruction/`: Complete compilation logs, import audits, encoder listings, and build-record.

## 4. Offline Reproduction Steps

1. Launch MSYS2 UCRT64 terminal:
   ```bash
   # From MSYS2 UCRT64 shell
   cd /path/to/extracted/archive
   ```

2. Reconstruct build workspace and cache directory:
   Note that `build_ffmpeg.sh` resolves repository root from `../../` relative to its script directory,
   expects declarative patches in `packaging/ffmpeg-build/patches/`, expects required manifest validation
   modules in `build_workspace/src/video_converter/`, and accesses `--cache-dir` containing
   the source archives indexed by their SHA-256 hashes.
   ```bash
   mkdir -p build_workspace/packaging/ffmpeg-build/artifacts
   mkdir -p build_workspace/packaging/ffmpeg-build/patches
   mkdir -p /tmp/ffmpeg-source-cache

   cp recipe/acquisition-manifest.json build_workspace/packaging/ffmpeg-build/
   cp recipe/build.lock.json build_workspace/packaging/ffmpeg-build/
   cp recipe/build_ffmpeg.sh build_workspace/packaging/ffmpeg-build/
   cp recipe/update_report_patches.py build_workspace/packaging/ffmpeg-build/
   cp recipe/resolve_lock.py build_workspace/packaging/ffmpeg-build/
   cp recipe/acquisition-report.json build_workspace/packaging/ffmpeg-build/artifacts/
   cp patches/* build_workspace/packaging/ffmpeg-build/patches/

   # Index sources by sha256 into cache directory


   python -c "import json, shutil, pathlib; lock = json.loads(pathlib.Path('recipe/build.lock.json').read_text(encoding='utf-8')); [shutil.copyfile(pathlib.Path('sources') / (s.get('filename') if 'filename' in s else s['canonical_artifact']['filename']), pathlib.Path('/tmp/ffmpeg-source-cache') / (s.get('sha256') if 'sha256' in s else s['canonical_artifact']['sha256'])) for s in lock['sources']]"
   ```

3. Ensure host build tools match versions listed in `reconstruction/build-record.json`.

4. Execute the builder script from the workspace:
   ```bash
   bash build_workspace/packaging/ffmpeg-build/build_ffmpeg.sh \\
     --build-lock build_workspace/packaging/ffmpeg-build/build.lock.json \\
     --cache-dir /tmp/ffmpeg-source-cache \\
     --work-dir /tmp/ffmpeg-build-scratch \\
     --output-dir /tmp/ffmpeg-build-output
   ```

5. Compare generated binary digests with `reconstruction/build-record.json` (`outputs.binaries`).

## 5. Configure Flags

```bash
./configure \\
    {flags_formatted}
```
"""


# Internal test seam for hermetic testing without loosening production validation
_DEFAULT_LOCK_VALIDATOR = validate_build_lock


def create_corresponding_source_zip(
    source_cache_dir: Path,
    build_output_dir: Path,
    workspace_root: Path,
    output_zip_path: Path,
) -> dict[str, Any]:




    """Create deterministic corresponding-source ZIP archive and return summary."""
    # 3. Symlink safety: test supplied roots AND their ancestors BEFORE resolve
    _assert_no_symlinks_in_path_and_parents(source_cache_dir, "source_cache_dir")
    _assert_no_symlinks_in_path_and_parents(build_output_dir, "build_output_dir")
    _assert_no_symlinks_in_path_and_parents(workspace_root, "workspace_root")
    _assert_no_symlinks_in_path_and_parents(output_zip_path, "output_zip_path")

    resolved_source_cache_dir = source_cache_dir.resolve()
    resolved_build_output_dir = build_output_dir.resolve()
    resolved_workspace_root = workspace_root.resolve()
    resolved_output_zip_path = output_zip_path.resolve()

    _assert_not_symlink(resolved_source_cache_dir, "resolved source_cache_dir")
    _assert_not_symlink(resolved_build_output_dir, "resolved build_output_dir")
    _assert_not_symlink(resolved_workspace_root, "resolved workspace_root")
    _assert_not_symlink(resolved_output_zip_path, "resolved output_zip_path")


    # Use original roots for traversal checks so is_symlink() checks work beneath supplied roots



    manifest_path = workspace_root / "packaging" / "ffmpeg-build" / "acquisition-manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"Acquisition manifest file not found: {manifest_path}")
    _assert_path_under_root_and_no_symlinks(manifest_path, workspace_root, "acquisition manifest")

    manifest_raw_bytes = manifest_path.read_bytes()
    manifest_sha = _compute_sha256(manifest_raw_bytes)
    manifest = decode_json_without_duplicate_keys(manifest_raw_bytes.decode("utf-8"))

    lock_path = workspace_root / "packaging" / "ffmpeg-build" / "build.lock.json"
    if not lock_path.is_file():
        raise FileNotFoundError(f"Build lock file not found: {lock_path}")
    _assert_path_under_root_and_no_symlinks(lock_path, workspace_root, "build lock")

    lock_raw_bytes = lock_path.read_bytes()
    lock = decode_json_without_duplicate_keys(lock_raw_bytes.decode("utf-8"))

    # Verify lock acquisition_manifest_sha256
    lock_manifest_sha = lock.get("acquisition_manifest_sha256")
    if lock_manifest_sha != manifest_sha:
        raise ValueError(
            f"Build lock acquisition_manifest_sha256 mismatch: expected {manifest_sha}, got {lock_manifest_sha}"
        )

    # Validate lock against manifest
    _DEFAULT_LOCK_VALIDATOR(lock, manifest)





    # Validate build record against lock
    record_path = build_output_dir / "build-record.json"
    if not record_path.is_file():
        raise FileNotFoundError(f"Build record file not found: {record_path}")
    _assert_path_under_root_and_no_symlinks(record_path, build_output_dir, "build record")

    record_raw_bytes = record_path.read_bytes()
    record = decode_json_without_duplicate_keys(record_raw_bytes.decode("utf-8"))
    validate_build_record(lock, record, lock_raw_bytes=lock_raw_bytes)

    # Validate builder script sha256 against build record
    builder_script_path = workspace_root / "packaging" / "ffmpeg-build" / "build_ffmpeg.sh"
    if not builder_script_path.is_file():
        raise FileNotFoundError(f"Builder script file not found: {builder_script_path}")
    _assert_path_under_root_and_no_symlinks(builder_script_path, workspace_root, "builder script")
    actual_builder_sha = _compute_sha256(builder_script_path.read_bytes())
    if actual_builder_sha != record.get("builder_script_sha256"):
        raise ValueError(
            f"Builder script sha256 mismatch: expected {record.get('builder_script_sha256')}, got {actual_builder_sha}"
        )

    # Validate patches against lock
    lock_patches = {p.get("name"): p for p in lock.get("patches", [])}
    for rel_path, _ in STANDARD_PATCH_FILES:
        p_path = workspace_root / rel_path
        if not p_path.is_file():
            raise FileNotFoundError(f"Patch file not found: {p_path}")
        _assert_path_under_root_and_no_symlinks(p_path, workspace_root, f"patch file {rel_path}")
        patch_bytes = _canonicalize_locked_patch_bytes(p_path.read_bytes())
        actual_p_sha = _compute_sha256(patch_bytes)
        # Find matching patch in lock
        matching_locked_patch = next(
            (lp for lp in lock_patches.values() if lp.get("path") == rel_path), None
        )
        if not matching_locked_patch:
            raise ValueError(f"Patch {rel_path} not declared in build lock")
        if actual_p_sha != matching_locked_patch.get("sha256"):
            raise ValueError(
                f"Patch {rel_path} sha256 mismatch: expected {matching_locked_patch.get('sha256')}, got {actual_p_sha}"
            )


    # Validate cached inputs
    validate_cached_inputs(lock, source_cache_dir)

    # Map archive entries: arcname -> bytes or Path
    entries: dict[str, bytes | Path] = {}

    # 1. Sources (all 9 sources from lock)
    sources = lock.get("sources", [])
    seen_source_names = set()
    for src in sources:
        name, fn, sha = extract_source_entry_info(src)
        if name in seen_source_names:
            raise ValueError(f"Duplicate source name in lock: {name}")
        seen_source_names.add(name)

        cached_file = source_cache_dir / sha
        if not cached_file.is_file():
            raise FileNotFoundError(f"Cached source file not found for {name}: {cached_file}")
        _assert_path_under_root_and_no_symlinks(cached_file, source_cache_dir, f"cached source {name}")

        arcname = f"sources/{fn}"
        _validate_archive_rel_path(arcname)
        if arcname in entries:
            raise ValueError(f"Duplicate entry path planned in ZIP: {arcname}")
        entries[arcname] = cached_file

    if seen_source_names != REQUIRED_SOURCE_NAMES:
        raise ValueError(
            f"Sources closure must exactly match REQUIRED_SOURCE_NAMES. Missing: {REQUIRED_SOURCE_NAMES - seen_source_names}"
        )

    # 2. Recipe files
    for rel_path, arc_name in STANDARD_RECIPE_FILES:
        file_path = workspace_root / rel_path
        if not file_path.is_file():
            raise FileNotFoundError(f"Required recipe file not found: {file_path}")
        _assert_path_under_root_and_no_symlinks(file_path, workspace_root, f"recipe file {rel_path}")
        _validate_archive_rel_path(arc_name)
        if arc_name in entries:
            raise ValueError(f"Duplicate entry path planned in ZIP: {arc_name}")
        entries[arc_name] = file_path

    # 3. Patch files
    for rel_path, arc_name in STANDARD_PATCH_FILES:
        file_path = workspace_root / rel_path
        if not file_path.is_file():
            raise FileNotFoundError(f"Required patch file not found: {file_path}")
        _assert_path_under_root_and_no_symlinks(file_path, workspace_root, f"patch file {rel_path}")
        _validate_archive_rel_path(arc_name)
        if arc_name in entries:
            raise ValueError(f"Duplicate entry path planned in ZIP: {arc_name}")
        entries[arc_name] = _canonicalize_locked_patch_bytes(file_path.read_bytes())

    # 4. License files
    for rel_path, arc_name in STANDARD_LICENSE_FILES:
        file_path = workspace_root / rel_path
        if not file_path.is_file():
            raise FileNotFoundError(f"Required license file not found: {file_path}")
        _assert_path_under_root_and_no_symlinks(file_path, workspace_root, f"license file {rel_path}")
        _validate_archive_rel_path(arc_name)
        if arc_name in entries:
            raise ValueError(f"Duplicate entry path planned in ZIP: {arc_name}")
        entries[arc_name] = file_path

    # 4b. Archive-local reproduction python files
    for rel_path, arc_name in STANDARD_BUILD_WORKSPACE_PYTHON_FILES:
        file_path = workspace_root / rel_path
        if not file_path.is_file():
            raise FileNotFoundError(f"Required reproduction python file not found: {file_path}")
        _assert_path_under_root_and_no_symlinks(file_path, workspace_root, f"reproduction python file {rel_path}")
        _validate_archive_rel_path(arc_name)
        if arc_name in entries:
            raise ValueError(f"Duplicate entry path planned in ZIP: {arc_name}")
        entries[arc_name] = file_path

    # 5. Reconstruction files from build_output_dir
    # Bind reconstruction evidence during creation as well:
    cfg_log_path = build_output_dir / "config.log"
    if not cfg_log_path.is_file():
        raise FileNotFoundError(f"Required reconstruction file not found: {cfg_log_path}")
    _assert_path_under_root_and_no_symlinks(cfg_log_path, build_output_dir, "config.log")
    if _compute_sha256(cfg_log_path.read_bytes()) != record.get("config_log", {}).get("sha256"):
        raise ValueError("config.log sha256 mismatch with build record config_log.sha256")

    commands_log_path = build_output_dir / "commands.log"
    if not commands_log_path.is_file():
        raise FileNotFoundError(f"Required reconstruction file not found: {commands_log_path}")
    _assert_path_under_root_and_no_symlinks(commands_log_path, build_output_dir, "commands.log")
    if _compute_sha256(commands_log_path.read_bytes()) != record.get("command_log_sha256"):
        raise ValueError("commands.log sha256 mismatch with build record command_log_sha256")

    ffmpeg_bconf_path = build_output_dir / "ffmpeg-buildconf.txt"
    ffprobe_bconf_path = build_output_dir / "ffprobe-buildconf.txt"
    if not ffmpeg_bconf_path.is_file() or not ffprobe_bconf_path.is_file():
        raise FileNotFoundError("buildconf reconstruction files missing")
    _assert_path_under_root_and_no_symlinks(ffmpeg_bconf_path, build_output_dir, "ffmpeg-buildconf.txt")
    _assert_path_under_root_and_no_symlinks(ffprobe_bconf_path, build_output_dir, "ffprobe-buildconf.txt")
    rec_bconf = record.get("buildconf", {})
    if ffmpeg_bconf_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip() != rec_bconf.get("ffmpeg", "").replace("\r\n", "\n").strip():
        raise ValueError("ffmpeg-buildconf.txt content mismatch with build record buildconf.ffmpeg")
    if ffprobe_bconf_path.read_text(encoding="utf-8").replace("\r\n", "\n").strip() != rec_bconf.get("ffprobe", "").replace("\r\n", "\n").strip():
        raise ValueError("ffprobe-buildconf.txt content mismatch with build record buildconf.ffprobe")

    encoders_path = build_output_dir / "encoders.txt"
    if not encoders_path.is_file():
        raise FileNotFoundError(f"Required reconstruction file not found: {encoders_path}")
    _assert_path_under_root_and_no_symlinks(encoders_path, build_output_dir, "encoders.txt")
    validate_encoder_inventory(encoders_path.read_bytes(), record, "encoders.txt")

    # Parse and validate PE imports in creation
    ffmpeg_imports_path = build_output_dir / "ffmpeg-imports.txt"
    ffprobe_imports_path = build_output_dir / "ffprobe-imports.txt"
    if not ffmpeg_imports_path.is_file() or not ffprobe_imports_path.is_file():
        raise FileNotFoundError("imports reconstruction files missing")
    _assert_path_under_root_and_no_symlinks(ffmpeg_imports_path, build_output_dir, "ffmpeg-imports.txt")
    _assert_path_under_root_and_no_symlinks(ffprobe_imports_path, build_output_dir, "ffprobe-imports.txt")
    rec_pe_audit = record.get("pe_import_audit", {})
    expected_ffmpeg_dlls = {dll.lower() for dll in rec_pe_audit.get("ffmpeg.exe", {}).get("imported_dlls", [])}
    expected_ffprobe_dlls = {dll.lower() for dll in rec_pe_audit.get("ffprobe.exe", {}).get("imported_dlls", [])}
    if parse_pe_imports(ffmpeg_imports_path.read_text(encoding="utf-8")) != expected_ffmpeg_dlls:
        raise ValueError("ffmpeg-imports.txt parsed DLLs do not match build record pe_import_audit")
    if parse_pe_imports(ffprobe_imports_path.read_text(encoding="utf-8")) != expected_ffprobe_dlls:
        raise ValueError("ffprobe-imports.txt parsed DLLs do not match build record pe_import_audit")


    for fn in STANDARD_RECONSTRUCTION_FILES:
        file_path = build_output_dir / fn
        if not file_path.is_file():
            raise FileNotFoundError(f"Required reconstruction file not found: {file_path}")
        _assert_path_under_root_and_no_symlinks(file_path, build_output_dir, f"reconstruction file {fn}")
        arcname = f"reconstruction/{fn}"
        _validate_archive_rel_path(arcname)
        if arcname in entries:
            raise ValueError(f"Duplicate entry path planned in ZIP: {arcname}")
        entries[arcname] = file_path



    # Generated reconstruction README
    readme_content = generate_reproduction_readme(record, lock).encode("utf-8")
    readme_arcname = "reconstruction/README.md"
    _validate_archive_rel_path(readme_arcname)
    entries[readme_arcname] = readme_content

    # Create parent dir for output zip if needed
    output_zip_path.parent.mkdir(parents=True, exist_ok=True)

    # Write deterministic ZIP
    sorted_arcnames = sorted(entries.keys())
    with zipfile.ZipFile(output_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname in sorted_arcnames:
            val = entries[arcname]
            if isinstance(val, Path):
                data = val.read_bytes()
            else:
                data = val

            zinfo = zipfile.ZipInfo(filename=arcname, date_time=DETERMINISTIC_ZIP_TIMESTAMP)
            zinfo.create_system = ZIP_UNIX_SYSTEM
            # POSIX mode: regular file (0o100000) + permissions (0o644)
            zinfo.external_attr = ((0o100000 | DETERMINISTIC_FILE_MODE) & 0xFFFF) << 16
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zinfo, data)

    zip_bytes = output_zip_path.read_bytes()
    zip_sha = _compute_sha256(zip_bytes)

    return {
        "output_path": str(output_zip_path),
        "sha256": zip_sha,
        "entry_count": len(sorted_arcnames),
        "entries": sorted_arcnames,
    }


def validate_source_bundle_zip(zip_path: Path, expected_lock: dict[str, Any]) -> bool:
    """Validate source bundle ZIP structure, digests of all archived sources, and evidence."""


    _assert_no_symlinks_in_path_and_parents(zip_path, "source bundle ZIP")
    zip_path = zip_path.resolve()
    if not zip_path.is_file():
        raise FileNotFoundError(f"Source bundle ZIP not found: {zip_path}")
    _assert_not_symlink(zip_path, "resolved source bundle ZIP")



    seen_names: set[str] = set()
    with zipfile.ZipFile(zip_path, "r") as zf:
        infolist = zf.infolist()
        for info in infolist:
            # Check duplicate entry
            if info.filename in seen_names:
                raise ValueError(f"Duplicate entry found in ZIP: {info.filename}")
            seen_names.add(info.filename)

            # Check safe entry path first (rejects drives, colons, UNC, backslashes, traversals)
            # Use orig_filename if available on Python zipfile to catch raw backslashes/drives
            raw_entry_name = getattr(info, "orig_filename", info.filename)
            _validate_archive_rel_path(raw_entry_name)
            if raw_entry_name != info.filename:
                _validate_archive_rel_path(info.filename)

            # Check not directory or symlink
            if info.is_dir():
                raise ValueError(f"Directory entry forbidden in source bundle ZIP: {info.filename}")
            # Mode check
            mode = (info.external_attr >> 16) & 0o777
            file_type = (info.external_attr >> 16) & 0o170000
            if file_type != 0o100000:
                raise ValueError(
                    f"Non-regular file entry in ZIP: {info.filename} (type: {oct(file_type)})"
                )
            if mode != DETERMINISTIC_FILE_MODE:
                raise ValueError(
                    f"Invalid file mode for entry {info.filename}: expected {oct(DETERMINISTIC_FILE_MODE)}, got {oct(mode)}"
                )
            if info.create_system != ZIP_UNIX_SYSTEM:
                raise ValueError(
                    f"Invalid create_system for entry {info.filename}: expected {ZIP_UNIX_SYSTEM}, got {info.create_system}"
                )



        entries = seen_names

        # 1. Check required recipe files
        for _, arcname in STANDARD_RECIPE_FILES:
            if arcname not in entries:
                raise ValueError(f"Missing required recipe file in ZIP: {arcname}")

        # 2. Check required patch files
        for _, arcname in STANDARD_PATCH_FILES:
            if arcname not in entries:
                raise ValueError(f"Missing required patch file in ZIP: {arcname}")

        # 3. Check required license files
        for _, arcname in STANDARD_LICENSE_FILES:
            if arcname not in entries:
                raise ValueError(f"Missing required license file in ZIP: {arcname}")

        # 3b. Check required archive-local python files
        for _, arcname in STANDARD_BUILD_WORKSPACE_PYTHON_FILES:
            if arcname not in entries:
                raise ValueError(f"Missing required reproduction python file in ZIP: {arcname}")


        # 4. Check required reconstruction files
        for fn in STANDARD_RECONSTRUCTION_FILES:
            arcname = f"reconstruction/{fn}"
            if arcname not in entries:
                raise ValueError(f"Missing required reconstruction file in ZIP: {arcname}")
        if "reconstruction/README.md" not in entries:
            raise ValueError("Missing reconstruction/README.md in ZIP")

        # 5. Validate archived build lock against expected lock
        archived_lock_bytes = zf.read("recipe/build.lock.json")
        archived_lock = decode_json_without_duplicate_keys(archived_lock_bytes.decode("utf-8"))
        if archived_lock != expected_lock:
            raise ValueError("Archived build.lock.json does not match expected lock")

        # 6. Validate archived acquisition manifest
        archived_manifest_bytes = zf.read("recipe/acquisition-manifest.json")
        archived_manifest_sha = _compute_sha256(archived_manifest_bytes)
        if archived_manifest_sha != archived_lock.get("acquisition_manifest_sha256"):
            raise ValueError(
                f"Archived acquisition manifest sha256 mismatch: {archived_manifest_sha} != {archived_lock.get('acquisition_manifest_sha256')}"
            )
        archived_manifest = decode_json_without_duplicate_keys(archived_manifest_bytes.decode("utf-8"))
        _DEFAULT_LOCK_VALIDATOR(archived_lock, archived_manifest)





        # 7. Validate archived build record
        archived_record_bytes = zf.read("reconstruction/build-record.json")
        archived_record = decode_json_without_duplicate_keys(archived_record_bytes.decode("utf-8"))
        validate_build_record(archived_lock, archived_record, lock_raw_bytes=archived_lock_bytes)

        # 8. Validate builder script digest in archive
        archived_builder_bytes = zf.read("recipe/build_ffmpeg.sh")
        archived_builder_sha = _compute_sha256(archived_builder_bytes)
        if archived_builder_sha != archived_record.get("builder_script_sha256"):
            raise ValueError(
                f"Archived builder script digest mismatch: {archived_builder_sha} != {archived_record.get('builder_script_sha256')}"
            )

        # 9. Validate patch digests against locked patch hashes
        locked_patches = {p.get("name"): p for p in archived_lock.get("patches", [])}
        for rel_path, arc_name in STANDARD_PATCH_FILES:
            matching_patch = next(
                (lp for lp in locked_patches.values() if lp.get("path") == rel_path), None
            )
            if not matching_patch:
                raise ValueError(f"Patch {rel_path} not found in archived lock")
            patch_data = zf.read(arc_name)
            actual_patch_sha = _compute_sha256(patch_data)
            if actual_patch_sha != matching_patch.get("sha256"):
                raise ValueError(
                    f"Patch digest mismatch for {arc_name}: expected {matching_patch.get('sha256')}, got {actual_patch_sha}"
                )

        # 10. Validate README is deterministically derived
        expected_readme = generate_reproduction_readme(archived_record, archived_lock).encode("utf-8")
        actual_readme = zf.read("reconstruction/README.md")
        if actual_readme != expected_readme:
            raise ValueError("Archived reconstruction/README.md content mismatch with generated reproduction guide")

        # 10b. Bind reconstruction evidence files to archived build record
        # config.log sha must equal record config_log sha
        cfg_log_bytes = zf.read("reconstruction/config.log")
        cfg_log_sha = _compute_sha256(cfg_log_bytes)
        rec_cfg_log = archived_record.get("config_log", {})
        if cfg_log_sha != rec_cfg_log.get("sha256"):
            raise ValueError(
                f"reconstruction/config.log sha256 mismatch: {cfg_log_sha} != {rec_cfg_log.get('sha256')}"
            )

        # commands.log sha equals command_log_sha256
        commands_bytes = zf.read("reconstruction/commands.log")
        commands_sha = _compute_sha256(commands_bytes)
        if commands_sha != archived_record.get("command_log_sha256"):
            raise ValueError(
                f"reconstruction/commands.log sha256 mismatch: {commands_sha} != {archived_record.get('command_log_sha256')}"
            )

        # buildconf strings equal record buildconf values
        ffmpeg_bconf = zf.read("reconstruction/ffmpeg-buildconf.txt").decode("utf-8").replace("\r\n", "\n").strip()
        ffprobe_bconf = zf.read("reconstruction/ffprobe-buildconf.txt").decode("utf-8").replace("\r\n", "\n").strip()
        rec_bconf = archived_record.get("buildconf", {})
        if ffmpeg_bconf != rec_bconf.get("ffmpeg", "").replace("\r\n", "\n").strip():
            raise ValueError("reconstruction/ffmpeg-buildconf.txt content does not match build record buildconf.ffmpeg")
        if ffprobe_bconf != rec_bconf.get("ffprobe", "").replace("\r\n", "\n").strip():
            raise ValueError("reconstruction/ffprobe-buildconf.txt content does not match build record buildconf.ffprobe")

        # encoders listing corresponds to record encoders inventory
        validate_encoder_inventory(
            zf.read("reconstruction/encoders.txt"),
            archived_record,
            "reconstruction/encoders.txt",
        )

        # pe imports correspond exactly to record pe_import_audit
        ffmpeg_imports_text = zf.read("reconstruction/ffmpeg-imports.txt").decode("utf-8")
        ffprobe_imports_text = zf.read("reconstruction/ffprobe-imports.txt").decode("utf-8")
        rec_audit = archived_record.get("pe_import_audit", {})

        expected_ffmpeg_dlls = {dll.lower() for dll in rec_audit.get("ffmpeg.exe", {}).get("imported_dlls", [])}
        expected_ffprobe_dlls = {dll.lower() for dll in rec_audit.get("ffprobe.exe", {}).get("imported_dlls", [])}
        if parse_pe_imports(ffmpeg_imports_text) != expected_ffmpeg_dlls:
            raise ValueError("reconstruction/ffmpeg-imports.txt parsed DLLs do not match build record pe_import_audit")
        if parse_pe_imports(ffprobe_imports_text) != expected_ffprobe_dlls:
            raise ValueError("reconstruction/ffprobe-imports.txt parsed DLLs do not match build record pe_import_audit")


        # 11. Validate each locked source exists and hash matches

        sources = archived_lock.get("sources", [])
        seen_source_names = set()
        for src in sources:
            name, fn, expected_sha = extract_source_entry_info(src)
            if name in seen_source_names:
                raise ValueError(f"Duplicate source {name} in archived lock")
            seen_source_names.add(name)

            arcname = f"sources/{fn}"
            if arcname not in entries:
                raise ValueError(f"Missing source file in ZIP: {arcname} (source: {name})")

            data = zf.read(arcname)
            actual_sha = _compute_sha256(data)
            if actual_sha != expected_sha:
                raise ValueError(
                    f"Checksum mismatch for source '{name}' ({arcname}): "
                    f"expected {expected_sha}, got {actual_sha}"
                )

        if seen_source_names != REQUIRED_SOURCE_NAMES:
            raise ValueError(
                f"Archived sources closure must exactly match REQUIRED_SOURCE_NAMES. Missing: {REQUIRED_SOURCE_NAMES - seen_source_names}"
            )

    return True
