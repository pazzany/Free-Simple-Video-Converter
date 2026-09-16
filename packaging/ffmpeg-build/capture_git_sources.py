"""CLI tool to capture verified Git sources into cache and emit provenance evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Sequence

from video_converter.ffmpeg_build.git_capture import (
    CommandRunner,
    capture_git_sources,
    default_runner,
)
from video_converter.ffmpeg_build_manifest import (
    decode_json_without_duplicate_keys,
    validate_acquisition_manifest,
)


def main(argv: Sequence[str] | None = None, runner: CommandRunner = default_runner) -> None:
    parser = argparse.ArgumentParser(
        description="Capture verified Git sources, generate canonical archives, and emit provenance evidence."
    )
    parser.add_argument("--manifest", required=True, type=Path, help="Path to acquisition manifest JSON")
    parser.add_argument("--cache-dir", required=True, type=Path, help="Path to source cache directory")
    parser.add_argument("--retention-dir", required=True, type=Path, help="Path to retention directory")
    parser.add_argument("--output", required=True, type=Path, help="Path to write output evidence JSON")

    args = parser.parse_args(argv)

    raw_manifest = args.manifest.read_bytes()
    manifest = decode_json_without_duplicate_keys(raw_manifest.decode("utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(f"Root JSON element in {args.manifest} must be an object/dict")
    validate_acquisition_manifest(manifest)

    evidence = capture_git_sources(manifest, args.cache_dir, args.retention_dir, runner=runner)

    # Atomically write sorted JSON evidence only
    json_bytes = (json.dumps(evidence, indent=2, sort_keys=True) + "\n").encode("utf-8")
    output_path = args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    import tempfile
    fd, tmp_path_str = tempfile.mkstemp(
        prefix=f".tmp.{output_path.name}.",
        dir=str(output_path.parent),
    )
    os.close(fd)
    tmp_output = Path(tmp_path_str)

    try:
        tmp_output.write_bytes(json_bytes)
        tmp_output.replace(output_path)
    except BaseException:
        try:
            if tmp_output.exists():
                tmp_output.unlink()
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
