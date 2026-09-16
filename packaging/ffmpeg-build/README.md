# FFmpeg Reproducible Build

This directory contains configuration, manifests, and tooling for building reproducible, standalone FFmpeg and ffprobe binaries on Windows (UCRT64).

## Overview & Architecture

The build lock resolver is structured into independent, focused components in `src/video_converter/ffmpeg_build/`:

1. **`acquisition_report.py`**: Parses and validates the strict schema of UCRT64 capture reports into immutable dataclasses.
2. **`source_cache.py`**: Manages source downloading, content-addressed caching (`<cache>/<sha256>`), SHA-256 computation, and cryptographic/commit evidence verification.
3. **`msys2_closure.py`**: Validates the MSYS2 environment closure (installer, databases, packages, signatures, dependency graph reachability, and project-controlled retention URIs).
4. **`lock_assembler.py`**: Assembles canonical, deterministic build locks bound to the raw manifest SHA-256 digest and performs atomic lock publication.
5. **`resolve_lock.py`**: Thin CLI coordinator connecting the above modular components.

## CLI Usage

### 1. Capture Git Sources

Before resolving the build lock, canonical Git source archives and git bundles must be captured and populated into the content-addressed source cache using `capture_git_sources.py`:

```bash
python packaging/ffmpeg-build/capture_git_sources.py \
  --manifest packaging/ffmpeg-build/acquisition-manifest.json \
  --cache-dir packaging/ffmpeg-build/artifacts/sources \
  --retention-dir C:/ffmpeg-build-retention \
  --output packaging/ffmpeg-build/artifacts/git-source-evidence.json
```

Then merge the generated seven evidence entries into the real acquisition report before running `resolve_lock.py`.

### 2. Resolve Build Lock

The public CLI contract remains unchanged:

```bash
python packaging/ffmpeg-build/resolve_lock.py \
  --manifest packaging/ffmpeg-build/acquisition-manifest.json \
  --cache-dir packaging/ffmpeg-build/artifacts/sources \
  --acquisition-report <ucrt64-capture-report.json> \
  --output packaging/ffmpeg-build/build.lock.json
```

All four CLI options are required:
- `--manifest`: Path to the human-reviewed `acquisition-manifest.json`.
- `--cache-dir`: Directory for caching content-addressed verified source artifacts.
- `--acquisition-report`: Path to the UCRT64 capture report JSON.
- `--output`: Path where the verified `build.lock.json` will be published atomically.

`resolve_lock.py` never fetches Git dependencies over the network or executes Git operations. It strictly requires pre-populated canonical Git source archives in `--cache-dir` matching the evidence in `--acquisition-report`. No lock is published when any canonical Git cache object is absent.

## UCRT64 Capture Requirement

Actual `build.lock.json` files are never generated or committed without a complete, verified UCRT64 capture report produced by a real UCRT64 environment. The lock resolver strictly refuses missing, incomplete, or unverified capture data.
