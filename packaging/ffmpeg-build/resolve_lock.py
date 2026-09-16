"""Thin CLI coordinator for FFmpeg build lock resolution."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Sequence
import urllib.request

from video_converter.ffmpeg_build.acquisition_report import parse_acquisition_report
from video_converter.ffmpeg_build.lock_assembler import (
    assemble_build_lock,
    publish_build_lock,
)
from video_converter.ffmpeg_build.msys2_closure import resolve_msys2_closure
from video_converter.ffmpeg_build.source_cache import resolve_source
from video_converter.ffmpeg_build_manifest import (
    decode_json_without_duplicate_keys,
    validate_acquisition_manifest,
    validate_build_lock,
    validate_cached_inputs,
)


def load_and_validate_manifest(manifest_path: Path) -> tuple[dict, str]:
    """Acquire raw manifest bytes once, compute sha256, parse JSON, and validate manifest."""
    raw_bytes = manifest_path.read_bytes()
    manifest_sha256 = hashlib.sha256(raw_bytes).hexdigest()
    parsed = decode_json_without_duplicate_keys(raw_bytes.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError(f"Root JSON element in {manifest_path} must be an object/dict")
    validate_acquisition_manifest(parsed)
    return parsed, manifest_sha256


def default_download(url: str, destination: Path) -> None:
    """Default HTTP downloader using urllib."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response, destination.open("wb") as out_file:
        while chunk := response.read(65536):
            out_file.write(chunk)


def resolve_lock(
    manifest_path: Path,
    cache_dir: Path,
    acquisition_report_path: Path,
    output_path: Path,
    download=default_download,
) -> Path:
    """Coordinate build lock resolution across modular components."""
    # 1. Acquire raw manifest bytes once, compute sha256, parse and validate manifest (no TOCTOU)
    manifest, manifest_sha256 = load_and_validate_manifest(manifest_path)

    # 2. Parse and schema-validate acquisition report
    report = parse_acquisition_report(acquisition_report_path)

    # 3. Resolve MSYS2 closure
    msys2_closure = resolve_msys2_closure(manifest["msys2"], report)

    # 4. Resolve verified sources with download injection
    resolved_sources = []
    for source_entry in manifest.get("sources", []):
        name = source_entry["name"]
        evidence = report.source_evidence[name]
        resolved = resolve_source(
            source=source_entry,
            evidence=evidence,
            cache_dir=cache_dir,
            download=download,
        )
        resolved_sources.append(resolved)

    # 5. Assemble build lock
    lock = assemble_build_lock(
        manifest=manifest,
        manifest_sha256=manifest_sha256,
        sources=resolved_sources,
        msys2=msys2_closure,
        report=report,
    )

    # 6. Validate build lock against manifest
    validate_build_lock(lock, manifest)

    # 7. Revalidate cached inputs against lock
    validate_cached_inputs(lock, cache_dir)

    # 8. Publish build lock atomically
    return publish_build_lock(lock, output_path)


def parse_args(args: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments for FFmpeg build lock resolution."""
    parser = argparse.ArgumentParser(
        description="Resolve verified FFmpeg build lock from acquisition manifest and capture report."
    )
    parser.add_argument(
        "--manifest",
        required=True,
        type=Path,
        help="Path to human-reviewed acquisition-manifest.json",
    )
    parser.add_argument(
        "--cache-dir",
        required=True,
        type=Path,
        help="Path to source artifacts cache directory",
    )
    parser.add_argument(
        "--acquisition-report",
        required=True,
        type=Path,
        help="Path to UCRT64 capture acquisition report",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination path for resolved build.lock.json",
    )
    return parser.parse_args(args)


def main(args: Sequence[str] | None = None) -> int:
    """Entry point for CLI resolution."""
    parsed = parse_args(args)
    try:
        resolve_lock(
            manifest_path=parsed.manifest,
            cache_dir=parsed.cache_dir,
            acquisition_report_path=parsed.acquisition_report,
            output_path=parsed.output,
        )
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
