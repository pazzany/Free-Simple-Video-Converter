"""Linux release asset packager and verification orchestrator CLI.

Builds the v1.0.1 Linux release directory from an already qualified Linux
FFmpeg output directory, the pinned source cache, and a prebuilt application
tarball (see packaging/build_linux_app.py):

1. Cross-checks acquisition-manifest-linux.json against build-linux.lock.json.
2. Validates cached source inputs against the lock.
3. Validates build-record.json against the lock, builder script, and output files.
4. Verifies bin/ffmpeg and bin/ffprobe version prefixes by execution.
5. Creates and validates ffmpeg-6.1.1-custom-source-linux.zip (deterministic).
6. Copies the application tarball and writes SHA256SUMS.txt.

Never touches the Windows packaging path.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from video_converter.ffmpeg_build.source_bundle import (  # noqa: E402
    DETERMINISTIC_FILE_MODE,
    DETERMINISTIC_ZIP_TIMESTAMP,
    ZIP_UNIX_SYSTEM,
)

LINUX_REQUIRED_ENCODER_TOKENS = (
    "libx264",
    "libx265",
    "libvpx-vp9",
    "libsvtav1",
    "libopus",
    "_nvenc",
    "_qsv",
    "_vaapi",
)

SOURCE_ZIP_NAME = "ffmpeg-6.1.1-custom-source-linux.zip"

RECIPE_FILES = [
    ("packaging/ffmpeg-build/build-linux.lock.json", "recipe/build-linux.lock.json"),
    (
        "packaging/ffmpeg-build/acquisition-manifest-linux.json",
        "recipe/acquisition-manifest-linux.json",
    ),
    (
        "packaging/ffmpeg-build/build_ffmpeg_linux.sh",
        "recipe/build_ffmpeg_linux.sh",
    ),
    (
        "packaging/ffmpeg_artifact_manifest_linux.json",
        "recipe/ffmpeg_artifact_manifest_linux.json",
    ),
]

RECONSTRUCTION_FILES = [
    "build-record.json",
    "commands.log",
    "config.log",
    "encoders.txt",
    "ffmpeg-buildconf.txt",
    "ffprobe-buildconf.txt",
    "ffmpeg-deps.txt",
    "ffprobe-deps.txt",
    "hwaccels.txt",
]

LICENSE_FILES = [
    ("LICENSE", "licenses/LICENSE"),
    ("THIRD_PARTY_NOTICES.md", "licenses/THIRD_PARTY_NOTICES.md"),
]


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _source_cache_key(src: dict) -> tuple[str, str]:
    """Return (cache_sha, filename) for a lock source entry."""
    if "canonical_artifact" in src:
        return src["canonical_artifact"]["sha256"], src["canonical_artifact"]["filename"]
    return src["sha256"], src["filename"]


def check_manifest_against_lock(manifest: dict, lock: dict) -> None:
    """Verify the acquisition manifest intent matches the pinned lock."""
    lock_sources = {s["name"]: s for s in lock["sources"]}
    manifest_sources = {s["name"]: s for s in manifest["sources"]}
    if set(lock_sources) != set(manifest_sources):
        raise ValueError(
            f"Linux lock/manifest source mismatch: "
            f"lock={sorted(lock_sources)} manifest={sorted(manifest_sources)}"
        )
    for name, lsrc in lock_sources.items():
        msrc = manifest_sources[name]
        for key in ("acquisition_type", "commit", "version", "git_remote_url"):
            if key in msrc and key in lsrc and lsrc.get(key) != msrc[key]:
                raise ValueError(f"Source '{name}' field '{key}' differs between manifest and lock")
    if manifest["configure"]["flags"] != lock["configure"]["flags"]:
        raise ValueError("Linux manifest/lock configure flags differ")
    if manifest["outputs"] != lock["outputs"]:
        raise ValueError("Linux manifest/lock outputs differ")
    if manifest.get("patches", []) != lock.get("patches", []):
        raise ValueError("Linux manifest/lock patches differ")


def validate_cached_sources(lock: dict, source_cache_dir: Path) -> None:
    for src in lock["sources"]:
        sha, _ = _source_cache_key(src)
        cached = source_cache_dir / sha
        if not cached.is_file():
            raise FileNotFoundError(f"Cached Linux source missing for {src['name']}: {cached}")
        if _sha256_file(cached) != sha:
            raise ValueError(f"Cached Linux source hash mismatch for {src['name']}")


def validate_build_record(
    record: dict, lock: dict, repo_root: Path, output_dir: Path
) -> None:
    """Validate the Linux build record against lock, builder, and output files."""
    if record.get("configure_flags") != lock["configure"]["flags"]:
        raise ValueError("Linux build record configure flags do not match lock")
    builder_path = repo_root / "packaging" / "ffmpeg-build" / "build_ffmpeg_linux.sh"
    if _sha256_file(builder_path) != record.get("builder_script_sha256"):
        raise ValueError("Linux build record builder_script_sha256 mismatch")
    for name in ("config.log", "commands.log", "encoders.txt"):
        data = (output_dir / name).read_bytes()
        expected = (
            record["config_log"]["sha256"]
            if name == "config.log"
            else record["command_log_sha256"]
            if name == "commands.log"
            else record["encoders_sha256"]
        )
        if _sha256_bytes(data) != expected:
            raise ValueError(f"Linux output {name} sha256 mismatch")
    encoders_text = (output_dir / "encoders.txt").read_text(encoding="utf-8")
    for token in LINUX_REQUIRED_ENCODER_TOKENS:
        if token not in encoders_text:
            raise ValueError(f"Linux encoders.txt missing required token: {token}")
    for out in lock["outputs"]:
        name = Path(out["path"]).name
        info = record["outputs"]["binaries"][name]
        data = (output_dir / out["path"]).read_bytes()
        if _sha256_bytes(data) != info["sha256"] or len(data) != info["size_bytes"]:
            raise ValueError(f"Linux output binary mismatch: {name}")


def verify_binary_versions(bin_dir: Path, lock: dict) -> None:
    for out in lock["outputs"]:
        binary = bin_dir / Path(out["path"]).name
        result = subprocess.run(
            [str(binary), "-version"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=15,
        )
        first = result.stdout.strip().splitlines()[0] if result.stdout.strip() else ""
        if result.returncode != 0 or not first.startswith(out["version_prefix"]):
            raise ValueError(f"Linux binary version check failed for {binary}: {first!r}")


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=DETERMINISTIC_ZIP_TIMESTAMP)
    info.create_system = ZIP_UNIX_SYSTEM
    info.external_attr = (DETERMINISTIC_FILE_MODE & 0o777) << 16
    return info


def create_linux_source_zip(
    repo_root: Path,
    lock: dict,
    source_cache_dir: Path,
    output_dir: Path,
    zip_path: Path,
) -> dict:
    entries: dict[str, bytes] = {}

    for rel_path, arc_name in RECIPE_FILES:
        entries[arc_name] = (repo_root / rel_path).read_bytes()

    for src in lock["sources"]:
        sha, filename = _source_cache_key(src)
        entries[f"sources/{filename}"] = (source_cache_dir / sha).read_bytes()

    for name in RECONSTRUCTION_FILES:
        entries[f"reconstruction/{name}"] = (output_dir / name).read_bytes()

    readme = (
        "# Linux corresponding source reconstruction\n\n"
        "Built on Ubuntu 22.04 x86_64 with packaging/ffmpeg-build/build_ffmpeg_linux.sh\n"
        "using the pinned source archives in sources/ and the lock in\n"
        "recipe/build-linux.lock.json. See recipe/ files for the full contract.\n"
    )
    entries["reconstruction/README-linux.md"] = readme.encode("utf-8")

    for rel_path, arc_name in LICENSE_FILES:
        entries[arc_name] = (repo_root / rel_path).read_bytes()

    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(entries):
            zf.writestr(_zip_info(name), entries[name])

    return {
        "output_path": str(zip_path),
        "sha256": _sha256_file(zip_path),
        "size_bytes": zip_path.stat().st_size,
        "entry_count": len(entries),
    }


def validate_linux_source_zip(zip_path: Path, repo_root: Path, lock: dict) -> None:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        if len(set(names)) != len(names):
            raise ValueError("Duplicate entry in Linux source ZIP")
        for info in zf.infolist():
            if info.is_dir():
                raise ValueError(f"Directory entry forbidden: {info.filename}")
            if info.create_system != ZIP_UNIX_SYSTEM:
                raise ValueError(f"Non-unix entry: {info.filename}")
            if ((info.external_attr >> 16) & 0o777) != DETERMINISTIC_FILE_MODE:
                raise ValueError(f"Bad mode for entry: {info.filename}")
            if info.date_time != DETERMINISTIC_ZIP_TIMESTAMP:
                raise ValueError(f"Non-deterministic timestamp: {info.filename}")

        expected = (
            [arc for _, arc in RECIPE_FILES]
            + [f"sources/{_source_cache_key(s)[1]}" for s in lock["sources"]]
            + [f"reconstruction/{n}" for n in RECONSTRUCTION_FILES]
            + ["reconstruction/README-linux.md"]
            + [arc for _, arc in LICENSE_FILES]
        )
        if set(names) != set(expected):
            raise ValueError(
                f"Linux source ZIP entry mismatch. Missing: {set(expected) - set(names)}. "
                f"Extra: {set(names) - set(expected)}"
            )

        archived_lock = json.loads(zf.read("recipe/build-linux.lock.json").decode("utf-8"))
        if archived_lock != lock:
            raise ValueError("Archived Linux lock does not match expected lock")
        for src in lock["sources"]:
            sha, filename = _source_cache_key(src)
            if _sha256_bytes(zf.read(f"sources/{filename}")) != sha:
                raise ValueError(f"Archived Linux source digest mismatch: {filename}")
        for rel_path, arc_name in RECIPE_FILES:
            if zf.read(arc_name) != (repo_root / rel_path).read_bytes():
                raise ValueError(f"Archived Linux recipe file mismatch: {arc_name}")
        record = json.loads(zf.read("reconstruction/build-record.json").decode("utf-8"))
        if _sha256_bytes(zf.read("reconstruction/encoders.txt")) != record["encoders_sha256"]:
            raise ValueError("Archived Linux encoders.txt digest mismatch")


def package_linux_release(
    repo_root: Path,
    build_output_dir: Path,
    source_cache_dir: Path,
    app_tarball: Path,
    release_dir: Path,
) -> dict:
    lock = _load_json(repo_root / "packaging" / "ffmpeg-build" / "build-linux.lock.json")
    manifest = _load_json(
        repo_root / "packaging" / "ffmpeg-build" / "acquisition-manifest-linux.json"
    )
    check_manifest_against_lock(manifest, lock)
    validate_cached_sources(lock, source_cache_dir)
    record = _load_json(build_output_dir / "build-record.json")
    validate_build_record(record, lock, repo_root, build_output_dir)
    verify_binary_versions(build_output_dir / "bin", lock)

    release_dir.mkdir(parents=True, exist_ok=True)
    staged_tarball = release_dir / app_tarball.name
    shutil.copyfile(app_tarball, staged_tarball)
    source_zip = release_dir / SOURCE_ZIP_NAME
    summary = create_linux_source_zip(repo_root, lock, source_cache_dir, build_output_dir, source_zip)
    validate_linux_source_zip(source_zip, repo_root, lock)

    sums_path = release_dir / "SHA256SUMS.txt"
    lines = []
    checksums = {}
    for path in sorted([staged_tarball, source_zip], key=lambda p: p.name):
        digest = _sha256_file(path)
        checksums[path.name] = digest
        lines.append(f"{digest} *{path.name}\n")
    sums_path.write_text("".join(lines), encoding="utf-8")

    return {
        "status": "success",
        "release_dir": str(release_dir),
        "source_archive": summary,
        "checksums": checksums,
        "sums_file": str(sums_path),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Package Linux v1.0.1 release assets.")
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--build-output-dir", type=Path, required=True)
    parser.add_argument("--source-cache-dir", type=Path, required=True)
    parser.add_argument("--app-tarball", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = package_linux_release(
            args.repo_root,
            args.build_output_dir,
            args.source_cache_dir,
            args.app_tarball,
            args.release_dir,
        )
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
