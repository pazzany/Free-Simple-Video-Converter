"""Release asset packager and verification orchestrator CLI.

Coordinates the end-to-end local generation, staging, packaging, and validation
of release artifacts:
1. Validates build-record.json and build.lock.json.
2. Validates cached source inputs.
3. Stages qualified ffmpeg.exe and ffprobe.exe to workspace/bin/ and verifies versions.
4. Invokes packaging/build_exe.py to package FreeSimpleVideoConverter.exe (unless --skip-pyinstaller).
5. Creates and validates corresponding-source ZIP via source_bundle.
6. Packages application distribution ZIP with binary and metadata/licenses.
7. Computes and verifies SHA256SUMS.txt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Sequence
import zipfile

# Ensure workspace root and src are in sys.path for direct CLI execution
_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from video_converter.ffmpeg_build_manifest import (
    decode_json_without_duplicate_keys,
    validate_build_record,
    validate_cached_inputs,
)
from video_converter.ffmpeg_build.source_bundle import (
    DETERMINISTIC_FILE_MODE,
    DETERMINISTIC_ZIP_TIMESTAMP,
    ZIP_UNIX_SYSTEM,
    create_corresponding_source_zip,
    validate_source_bundle_zip,
)

# Local build/test/release artifacts live in this ignored directory at the
# repository root instead of being scattered across disks.
LOCAL_ARTIFACTS_DIR = _REPO_ROOT / ".local-artifacts"
DEFAULT_BUILD_OUTPUT_DIR = LOCAL_ARTIFACTS_DIR / "ffmpeg-v1-output"
DEFAULT_SOURCE_CACHE_DIR = LOCAL_ARTIFACTS_DIR / "ffmpeg-release-source-cache"
SHA256_LINE_PATTERN = re.compile(r"^([0-9a-f]{64}) \*([a-zA-Z0-9._-]+)\n?$")
SHA256_STRICT_LINE_PATTERN = re.compile(r"^([0-9a-f]{64}) \*([^/\\\s]+\.zip)\n$")
SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_BINARIES = ("ffmpeg.exe", "ffprobe.exe")

# Release version stamped into the Windows application archive name.
# Bump together with pyproject.toml on every release.
APP_VERSION = "1.0.3"
APP_DIST_ZIP_NAME = f"FreeSimpleVideoConverter-v{APP_VERSION}-windows-x64.zip"

APP_DIST_DOC_FILES = [
    "README.md",
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
]


def _compute_sha256(file_path: Path) -> str:
    """Compute lowercase SHA-256 hex digest for a file."""
    hasher = hashlib.sha256()
    with file_path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def write_sha256sums(sums_file: Path, files: Sequence[Path]) -> dict[str, str]:
    """Compute and write SHA256SUMS file using standard `<lowercase hash> *<filename>` format.

    Returns dictionary mapping filename to sha256.
    """
    entries: dict[str, str] = {}
    lines: list[str] = []
    for f in sorted(files, key=lambda p: p.name):
        if not f.name.endswith(".zip"):
            raise ValueError(f"Only .zip files may be declared in SHA256SUMS.txt: {f.name}")
        digest = _compute_sha256(f)
        entries[f.name] = digest
        lines.append(f"{digest} *{f.name}\n")

    sums_file.parent.mkdir(parents=True, exist_ok=True)
    with sums_file.open("w", encoding="utf-8", newline="") as f:
        f.write("".join(lines))
    return entries


def verify_sha256sums(sums_file: Path) -> dict[str, str]:
    """Verify all files listed in SHA256SUMS file match their declared digests.

    Enforces strict canonical format `<64-lowercase-hex> *<safe-basename.zip>\n`.
    Returns dictionary mapping filename to verified sha256.
    """
    if not sums_file.is_file():
        raise FileNotFoundError(f"SHA256SUMS file not found: {sums_file}")

    raw_bytes = sums_file.read_bytes()
    if b"\r" in raw_bytes:
        raise ValueError("CRLF line endings detected in SHA256SUMS.txt; only LF allowed")

    raw_text = raw_bytes.decode("utf-8")
    if not raw_text:
        raise ValueError(f"SHA256SUMS file is empty: {sums_file}")

    lines = raw_text.splitlines(keepends=True)
    if not lines:
        raise ValueError(f"SHA256SUMS file is empty: {sums_file}")

    verified: dict[str, str] = {}
    directory = sums_file.parent.resolve()
    seen_filenames: set[str] = set()

    for line in lines:
        if line == "\n" or line.strip() == "":
            raise ValueError("Blank line detected in SHA256SUMS.txt")
        if not line.endswith("\n"):
            raise ValueError("Line in SHA256SUMS.txt does not end with newline")

        match = SHA256_STRICT_LINE_PATTERN.match(line)
        if not match:
            raise ValueError(f"Invalid checksum line format: {line.rstrip()!r}")
        expected_sha, filename = match.groups()

        if (
            "/" in filename
            or "\\" in filename
            or ":" in filename
            or ".." in filename
            or Path(filename).name != filename
        ):
            raise ValueError(f"Unsafe filename in checksum line: {filename!r}")

        if filename in seen_filenames:
            raise ValueError(f"Duplicate filename in SHA256SUMS.txt: {filename}")
        seen_filenames.add(filename)

        target_path = directory / filename
        if not target_path.is_file():
            raise FileNotFoundError(f"File declared in SHA256SUMS.txt not found: {target_path}")

        actual_sha = _compute_sha256(target_path)
        if actual_sha != expected_sha:
            raise ValueError(
                f"Checksum mismatch for {filename}: expected {expected_sha}, got {actual_sha}"
            )
        verified[filename] = actual_sha

    # Verify declared set matches exactly all direct *.zip files in directory
    actual_zip_names = {p.name for p in directory.glob("*.zip")}
    if seen_filenames != actual_zip_names:
        raise ValueError(
            f"Mismatch between declared checksums and directory zip files. Declared: {seen_filenames}, Actual: {actual_zip_names}"
        )

    return verified


def create_app_distribution_zip(
    executable_path: Path,
    workspace_root: Path,
    output_zip_path: Path,
) -> dict[str, Any]:
    """Create deterministic ZIP archive containing application executable and distribution docs."""
    executable_path = executable_path.resolve()
    workspace_root = workspace_root.resolve()
    if not executable_path.is_file():
        raise FileNotFoundError(f"Application executable not found: {executable_path}")

    entries: dict[str, Path] = {
        executable_path.name: executable_path,
    }

    for doc_name in APP_DIST_DOC_FILES:
        doc_path = workspace_root / doc_name
        if not doc_path.is_file():
            raise FileNotFoundError(f"Required release doc file not found: {doc_path}")
        entries[doc_name] = doc_path

    output_zip_path.parent.mkdir(parents=True, exist_ok=True)

    sorted_arcnames = sorted(entries.keys())
    with zipfile.ZipFile(output_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for arcname in sorted_arcnames:
            path = entries[arcname]
            data = path.read_bytes()
            zinfo = zipfile.ZipInfo(filename=arcname, date_time=DETERMINISTIC_ZIP_TIMESTAMP)
            zinfo.create_system = ZIP_UNIX_SYSTEM
            zinfo.external_attr = ((0o100000 | DETERMINISTIC_FILE_MODE) & 0xFFFF) << 16
            zinfo.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(zinfo, data)

    sha = _compute_sha256(output_zip_path)
    size_bytes = output_zip_path.stat().st_size
    return {
        "output_path": str(output_zip_path),
        "sha256": sha,
        "size_bytes": size_bytes,
        "entry_count": len(sorted_arcnames),
        "entries": sorted_arcnames,
    }


def validate_binary_size_and_sha(
    binary_path: Path,
    expected_sha: str,
    expected_size: int,
    binary_label: str,
) -> None:
    """Validate that binary exists and matches expected sha256 and byte size."""
    if not binary_path.is_file():
        raise FileNotFoundError(f"{binary_label} not found at {binary_path}")

    actual_size = binary_path.stat().st_size
    if actual_size != expected_size:
        raise ValueError(
            f"{binary_label} size mismatch: expected {expected_size}, got {actual_size}"
        )

    actual_sha = _compute_sha256(binary_path)
    if actual_sha.lower() != expected_sha.lower():
        raise ValueError(
            f"{binary_label} sha256 mismatch: expected {expected_sha.lower()}, got {actual_sha.lower()}"
        )


def stage_binaries(
    build_output_dir: Path,
    target_bin_dir: Path,
    record: dict[str, Any],
    dry_run: bool = False,
) -> tuple[Path, Path]:
    """Stage ffmpeg.exe and ffprobe.exe from build_output_dir/bin to target_bin_dir."""
    src_bin_dir = build_output_dir / "bin"
    src_ffmpeg = src_bin_dir / "ffmpeg.exe"
    src_ffprobe = src_bin_dir / "ffprobe.exe"

    outputs_binaries = record.get("outputs", {}).get("binaries", {})
    ffmpeg_info = outputs_binaries.get("ffmpeg.exe", {})
    ffprobe_info = outputs_binaries.get("ffprobe.exe", {})

    expected_ffmpeg_sha = ffmpeg_info.get("sha256")
    expected_ffmpeg_size = ffmpeg_info.get("size_bytes")
    expected_ffprobe_sha = ffprobe_info.get("sha256")
    expected_ffprobe_size = ffprobe_info.get("size_bytes")

    if not expected_ffmpeg_sha or expected_ffmpeg_size is None:
        raise ValueError("build-record missing outputs.binaries['ffmpeg.exe'] sha256 or size_bytes")
    if not expected_ffprobe_sha or expected_ffprobe_size is None:
        raise ValueError("build-record missing outputs.binaries['ffprobe.exe'] sha256 or size_bytes")

    # Validate source binaries before copying
    validate_binary_size_and_sha(src_ffmpeg, expected_ffmpeg_sha, expected_ffmpeg_size, "Source ffmpeg.exe")
    validate_binary_size_and_sha(src_ffprobe, expected_ffprobe_sha, expected_ffprobe_size, "Source ffprobe.exe")

    dest_ffmpeg = target_bin_dir / "ffmpeg.exe"
    dest_ffprobe = target_bin_dir / "ffprobe.exe"

    if not dry_run:
        target_bin_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_ffmpeg, dest_ffmpeg)
        shutil.copy2(src_ffprobe, dest_ffprobe)
        # Validate staged copies as well
        validate_binary_size_and_sha(dest_ffmpeg, expected_ffmpeg_sha, expected_ffmpeg_size, "Staged ffmpeg.exe")
        validate_binary_size_and_sha(dest_ffprobe, expected_ffprobe_sha, expected_ffprobe_size, "Staged ffprobe.exe")

    return dest_ffmpeg, dest_ffprobe


def verify_binary_versions(
    ffmpeg_exe: Path,
    ffprobe_exe: Path,
    expected_ffmpeg_version: str | None = None,
    expected_ffprobe_version: str | None = None,
) -> tuple[str, str]:
    """Run `ffmpeg.exe -version` and `ffprobe.exe -version` and verify clean output."""
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0

    res_ffmpeg = subprocess.run(
        [str(ffmpeg_exe), "-version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        creationflags=flags,
        timeout=15,
    )
    if res_ffmpeg.returncode != 0:
        raise RuntimeError(
            f"ffmpeg.exe -version returned code {res_ffmpeg.returncode}: {res_ffmpeg.stdout}"
        )
    lines_ffmpeg = [line.strip() for line in (res_ffmpeg.stdout or "").splitlines() if line.strip()]
    if not lines_ffmpeg:
        raise RuntimeError("ffmpeg.exe -version produced empty version output")
    ffmpeg_version_line = lines_ffmpeg[0]

    res_ffprobe = subprocess.run(
        [str(ffprobe_exe), "-version"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        check=False,
        creationflags=flags,
        timeout=15,
    )
    if res_ffprobe.returncode != 0:
        raise RuntimeError(
            f"ffprobe.exe -version returned code {res_ffprobe.returncode}: {res_ffprobe.stdout}"
        )
    lines_ffprobe = [line.strip() for line in (res_ffprobe.stdout or "").splitlines() if line.strip()]
    if not lines_ffprobe:
        raise RuntimeError("ffprobe.exe -version produced empty version output")
    ffprobe_version_line = lines_ffprobe[0]

    if expected_ffmpeg_version and not ffmpeg_version_line.startswith(expected_ffmpeg_version):
        raise ValueError(
            f"ffmpeg version mismatch: expected prefix {expected_ffmpeg_version!r}, got {ffmpeg_version_line!r}"
        )

    if expected_ffprobe_version and not ffprobe_version_line.startswith(expected_ffprobe_version):
        raise ValueError(
            f"ffprobe version mismatch: expected prefix {expected_ffprobe_version!r}, got {ffprobe_version_line!r}"
        )

    return ffmpeg_version_line, ffprobe_version_line


def package_release_assets(
    build_output_dir: Path,
    source_cache_dir: Path,
    workspace_root: Path,
    dist_dir: Path,
    skip_pyinstaller: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute complete release packaging pipeline."""
    build_output_dir = build_output_dir.resolve()
    source_cache_dir = source_cache_dir.resolve()
    workspace_root = workspace_root.resolve()
    dist_dir = dist_dir.resolve()

    release_assets_dir = dist_dir / "release-assets"

    # Stage 1: Preflight Validation
    lock_path = workspace_root / "packaging" / "ffmpeg-build" / "build.lock.json"
    if not lock_path.is_file():
        raise FileNotFoundError(f"Build lock not found: {lock_path}")
    lock_raw_bytes = lock_path.read_bytes()
    lock = decode_json_without_duplicate_keys(lock_raw_bytes.decode("utf-8"))

    record_path = build_output_dir / "build-record.json"
    if not record_path.is_file():
        raise FileNotFoundError(f"Build record not found: {record_path}")
    record = decode_json_without_duplicate_keys(record_path.read_text(encoding="utf-8"))

    validate_build_record(lock, record, lock_raw_bytes=lock_raw_bytes)
    validate_cached_inputs(lock, source_cache_dir)

    # Preflight check for release doc files
    for doc_name in APP_DIST_DOC_FILES:
        doc_path = workspace_root / doc_name
        if not doc_path.is_file():
            raise FileNotFoundError(f"Required release doc file missing: {doc_path}")

    # Validate destination directory layout viability and preflight destination file conflicts
    target_bin_dir = workspace_root / "bin"
    if target_bin_dir.exists() and not target_bin_dir.is_dir():
        raise ValueError(f"Destination bin path is a file, not a directory: {target_bin_dir}")
    if dist_dir.exists() and not dist_dir.is_dir():
        raise ValueError(f"Destination dist path is a file, not a directory: {dist_dir}")
    if release_assets_dir.exists() and not release_assets_dir.is_dir():
        raise ValueError(
            f"Destination release-assets path is a file, not a directory: {release_assets_dir}"
        )

    # Reject directory conflicts at intended file destinations
    target_ffmpeg = target_bin_dir / "ffmpeg.exe"
    target_ffprobe = target_bin_dir / "ffprobe.exe"
    if target_ffmpeg.is_dir():
        raise ValueError(
            f"Intended destination file workspace/bin/ffmpeg.exe is a directory: {target_ffmpeg}"
        )
    if target_ffprobe.is_dir():
        raise ValueError(
            f"Intended destination file workspace/bin/ffprobe.exe is a directory: {target_ffprobe}"
        )

    app_exe_path = dist_dir / "FreeSimpleVideoConverter.exe"
    if not skip_pyinstaller and app_exe_path.is_dir():
        raise ValueError(
            f"Intended destination file dist/FreeSimpleVideoConverter.exe is a directory: {app_exe_path}"
        )

    # Reject directory conflicts at release-assets destinations
    expected_release_asset_files = [
        "ffmpeg-6.1.1-custom-source.zip",
        APP_DIST_ZIP_NAME,
        "SHA256SUMS.txt",
    ]
    for asset_name in expected_release_asset_files:
        asset_target = release_assets_dir / asset_name
        if asset_target.is_dir():
            raise ValueError(
                f"Intended destination file release-assets/{asset_name} is a directory: {asset_target}"
            )

    # Validate manifest compatibility with staged binary identities under ALL paths
    manifest_path = workspace_root / "packaging" / "ffmpeg_artifact_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(
            f"Artifact manifest not found at {manifest_path} (packaging/ffmpeg_artifact_manifest.json is required)"
        )

    manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_binaries = manifest_data.get("expected_binaries")
    if not isinstance(expected_binaries, dict):
        raise ValueError("Binary manifest missing or invalid 'expected_binaries' mapping")

    if set(expected_binaries.keys()) != set(REQUIRED_BINARIES):
        raise ValueError(
            f"Binary manifest 'expected_binaries' must contain exactly {set(REQUIRED_BINARIES)}, got {set(expected_binaries.keys())}"
        )

    outputs_binaries_map = record.get("outputs", {}).get("binaries", {})
    for b_name in REQUIRED_BINARIES:
        b_info = expected_binaries[b_name]
        if not isinstance(b_info, dict):
            raise ValueError(f"Binary manifest entry for {b_name} must be an object")

        sha = b_info.get("sha256", "")
        if not isinstance(sha, str) or not SHA256_HEX_PATTERN.match(sha.strip()):
            raise ValueError(
                f"Binary manifest item {b_name} has invalid sha256: expected 64 lowercase hex characters"
            )

        version_prefix = b_info.get("version_prefix", "")
        if not isinstance(version_prefix, str) or not version_prefix.strip():
            raise ValueError(
                f"Binary manifest item {b_name} missing or empty version_prefix"
            )

        rec_b_info = outputs_binaries_map.get(b_name)
        if not rec_b_info:
            raise ValueError(f"Binary manifest item {b_name} missing from build-record outputs")
        if sha.strip() != rec_b_info.get("sha256", "").strip():
            raise ValueError(
                f"Binary manifest sha256 for {b_name} mismatch with build-record outputs"
            )

        clean_name = b_name.replace(".exe", "")
        rec_ver = record.get("versions", {}).get(clean_name, "")
        if not rec_ver or not rec_ver.startswith(version_prefix.strip()):
            raise ValueError(
                f"Binary manifest version_prefix mismatch for {b_name}: "
                f"manifest expected {version_prefix.strip()!r}, record has {rec_ver!r}"
            )

    # Validate source binaries before anything else
    src_bin_dir = build_output_dir / "bin"
    src_ffmpeg = src_bin_dir / "ffmpeg.exe"
    src_ffprobe = src_bin_dir / "ffprobe.exe"

    outputs_binaries = record.get("outputs", {}).get("binaries", {})
    ffmpeg_info = outputs_binaries.get("ffmpeg.exe", {})
    ffprobe_info = outputs_binaries.get("ffprobe.exe", {})
    expected_ffmpeg_sha = ffmpeg_info.get("sha256")
    expected_ffmpeg_size = ffmpeg_info.get("size_bytes")
    expected_ffprobe_sha = ffprobe_info.get("sha256")
    expected_ffprobe_size = ffprobe_info.get("size_bytes")

    if not expected_ffmpeg_sha or expected_ffmpeg_size is None:
        raise ValueError("build-record missing outputs.binaries['ffmpeg.exe'] sha256 or size_bytes")
    if not expected_ffprobe_sha or expected_ffprobe_size is None:
        raise ValueError("build-record missing outputs.binaries['ffprobe.exe'] sha256 or size_bytes")

    validate_binary_size_and_sha(src_ffmpeg, expected_ffmpeg_sha, expected_ffmpeg_size, "Source ffmpeg.exe")
    validate_binary_size_and_sha(src_ffprobe, expected_ffprobe_sha, expected_ffprobe_size, "Source ffprobe.exe")

    # Validate reconstruction files from build_output_dir
    from video_converter.ffmpeg_build.source_bundle import (
        STANDARD_RECONSTRUCTION_FILES,
        STANDARD_RECIPE_FILES,
        STANDARD_PATCH_FILES,
        STANDARD_LICENSE_FILES,
        STANDARD_BUILD_WORKSPACE_PYTHON_FILES,
    )
    for fn in STANDARD_RECONSTRUCTION_FILES:
        p = build_output_dir / fn
        if not p.is_file():
            raise FileNotFoundError(f"Required reconstruction file missing: {p}")
    for rel_path, _ in STANDARD_RECIPE_FILES:
        p = workspace_root / rel_path
        if not p.is_file():
            raise FileNotFoundError(f"Required recipe file missing: {p}")
    for rel_path, _ in STANDARD_PATCH_FILES:
        p = workspace_root / rel_path
        if not p.is_file():
            raise FileNotFoundError(f"Required patch file missing: {p}")
    for rel_path, _ in STANDARD_LICENSE_FILES:
        p = workspace_root / rel_path
        if not p.is_file():
            raise FileNotFoundError(f"Required license file missing: {p}")
    for rel_path, _ in STANDARD_BUILD_WORKSPACE_PYTHON_FILES:
        p = workspace_root / rel_path
        if not p.is_file():
            raise FileNotFoundError(f"Required reproduction python file missing: {p}")

    app_exe_path = dist_dir / "FreeSimpleVideoConverter.exe"
    if skip_pyinstaller:
        if not app_exe_path.exists():
            raise FileNotFoundError(
                f"Expected pre-existing application executable not found at {app_exe_path} for --skip-pyinstaller"
            )
        if app_exe_path.is_dir():
            raise ValueError(
                f"Application executable is a directory, not a regular file: {app_exe_path}"
            )
        if not app_exe_path.is_file():
            raise ValueError(
                f"Application executable is not a regular file: {app_exe_path}"
            )
        if app_exe_path.stat().st_size == 0:
            raise ValueError(
                f"Application executable is empty (0 bytes): {app_exe_path}"
            )
    else:
        build_script = workspace_root / "packaging" / "build_exe.py"
        if not build_script.is_file():
            raise FileNotFoundError(f"PyInstaller build script not found: {build_script}")

    expected_ffmpeg_ver = record.get("versions", {}).get("ffmpeg")
    expected_ffprobe_ver = record.get("versions", {}).get("ffprobe")

    if dry_run:
        return {
            "status": "dry_run_success",
            "planned_actions": [
                f"Stage {src_ffmpeg} and {src_ffprobe} to {workspace_root / 'bin'}",
                "Verify ffmpeg and ffprobe execution versions",
                f"Invoke packaging/build_exe.py --dist-dir {dist_dir}" if not skip_pyinstaller else "Skip build_exe.py",
                f"Create source archive in {release_assets_dir}",
                f"Create app archive in {release_assets_dir}",
                f"Write and verify SHA256SUMS.txt in {release_assets_dir}",
            ],
        }

    # Stage 2: Binary Staging
    target_bin_dir = workspace_root / "bin"
    staged_ffmpeg, staged_ffprobe = stage_binaries(
        build_output_dir=build_output_dir,
        target_bin_dir=target_bin_dir,
        record=record,
        dry_run=False,
    )
    verify_binary_versions(
        staged_ffmpeg,
        staged_ffprobe,
        expected_ffmpeg_version=expected_ffmpeg_ver,
        expected_ffprobe_version=expected_ffprobe_ver,
    )

    # Stage 3: Application Executable Packaging
    if not skip_pyinstaller:
        build_script = workspace_root / "packaging" / "build_exe.py"
        # Remove any stale executable at destination first
        if app_exe_path.exists():
            app_exe_path.unlink()

        res = subprocess.run(
            [sys.executable, str(build_script), "--dist-dir", str(dist_dir)],
            cwd=str(workspace_root),
            check=False,
        )
        if res.returncode != 0:
            raise RuntimeError(f"PyInstaller build failed with exit code {res.returncode}")

    if not app_exe_path.is_file() or app_exe_path.stat().st_size == 0:
        raise FileNotFoundError(
            f"Expected application executable not found or empty: {app_exe_path}"
        )

    # Stage 4 & 5 & 6: Assemble into temporary sibling directory, validate, and atomically replace
    dist_dir.mkdir(parents=True, exist_ok=True)
    temp_assets_dir = Path(tempfile.mkdtemp(prefix="release-assets-tmp-", dir=str(dist_dir)))

    try:
        temp_source_zip = temp_assets_dir / "ffmpeg-6.1.1-custom-source.zip"
        temp_app_zip = temp_assets_dir / APP_DIST_ZIP_NAME
        temp_sums_file = temp_assets_dir / "SHA256SUMS.txt"

        source_summary = create_corresponding_source_zip(
            source_cache_dir=source_cache_dir,
            build_output_dir=build_output_dir,
            workspace_root=workspace_root,
            output_zip_path=temp_source_zip,
        )
        validate_source_bundle_zip(temp_source_zip, expected_lock=lock)

        app_summary = create_app_distribution_zip(
            executable_path=app_exe_path,
            workspace_root=workspace_root,
            output_zip_path=temp_app_zip,
        )

        # Include every .zip in temp_assets_dir sorted by name
        all_zips = sorted(list(temp_assets_dir.glob("*.zip")), key=lambda p: p.name)
        sums = write_sha256sums(temp_sums_file, all_zips)
        verify_sha256sums(temp_sums_file)

        # Atomic replacement of final release_assets_dir with robust rollback
        backup_dir: Path | None = None
        if release_assets_dir.exists():
            backup_dir = Path(tempfile.mkdtemp(prefix="release-assets-backup-", dir=str(dist_dir)))
            try:
                # Remove placeholder and rename release_assets_dir into backup
                backup_dir.rmdir()
                release_assets_dir.rename(backup_dir)
            except Exception:
                # Rollback on backup-rename failure: ensure partial backup dir does not conflict
                if backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)
                raise

        try:
            temp_assets_dir.rename(release_assets_dir)
            temp_assets_dir = None  # Successfully moved
        except Exception as promo_err:
            # Rollback: restore backup to release_assets_dir if needed
            if backup_dir and backup_dir.exists() and not release_assets_dir.exists():
                try:
                    backup_dir.rename(release_assets_dir)
                    backup_dir = None
                except Exception as restore_err:
                    # Both promotion and backup restore failed: raise error reporting both and retained backup
                    raise RuntimeError(
                        f"Promotion failed: {promo_err}; backup restore failed: {restore_err}. "
                        f"Backup retained at {backup_dir}"
                    ) from restore_err
            raise promo_err

        if backup_dir and backup_dir.exists():
            shutil.rmtree(backup_dir)

        final_source_zip = release_assets_dir / temp_source_zip.name
        final_app_zip = release_assets_dir / temp_app_zip.name
        final_sums_file = release_assets_dir / "SHA256SUMS.txt"

        source_summary["output_path"] = str(final_source_zip)
        source_summary["size_bytes"] = final_source_zip.stat().st_size
        app_summary["output_path"] = str(final_app_zip)
        app_summary["size_bytes"] = final_app_zip.stat().st_size

        return {
            "status": "success",
            "source_archive": source_summary,
            "app_archive": app_summary,
            "checksums": sums,
            "sums_file": str(final_sums_file),
        }
    finally:
        if temp_assets_dir and temp_assets_dir.exists():
            shutil.rmtree(temp_assets_dir, ignore_errors=True)


def build_arg_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser matching specification."""
    parser = argparse.ArgumentParser(
        description="Package reproducible local release assets for Free Simple Video Converter."
    )
    parser.add_argument(
        "--build-output-dir",
        type=Path,
        default=DEFAULT_BUILD_OUTPUT_DIR,
        help="Path to build output directory (default: .local-artifacts/ffmpeg-v1-output).",
    )
    parser.add_argument(
        "--source-cache-dir",
        type=Path,
        default=DEFAULT_SOURCE_CACHE_DIR,
        help="Path to source cache directory (default: .local-artifacts/ffmpeg-release-source-cache).",
    )
    parser.add_argument(
        "--workspace-root",
        type=Path,
        default=None,
        help="Project root (default: auto-detected from script location).",
    )
    parser.add_argument(
        "--dist-dir",
        type=Path,
        default=None,
        help="Base dist directory (default: <workspace-root>/dist).",
    )
    parser.add_argument(
        "--skip-pyinstaller",
        action="store_true",
        help="Bypass PyInstaller execution.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and planned actions without writing output files.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    workspace_root = args.workspace_root
    if workspace_root is None:
        # Script is located in <workspace_root>/packaging/package_release_assets.py
        workspace_root = Path(__file__).resolve().parent.parent

    dist_dir = args.dist_dir
    if dist_dir is None:
        dist_dir = workspace_root / "dist"

    try:
        report = package_release_assets(
            build_output_dir=args.build_output_dir,
            source_cache_dir=args.source_cache_dir,
            workspace_root=workspace_root,
            dist_dir=dist_dir,
            skip_pyinstaller=args.skip_pyinstaller,
            dry_run=args.dry_run,
        )
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
