"""Unit and integration tests for thin build lock resolution coordinator."""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
from pathlib import Path
import sys
from typing import Any
import urllib.request
import pytest

from video_converter.ffmpeg_build.acquisition_report import (
    AcquisitionReport,
    Msys2DatabaseEvidence,
    Msys2InstallerEvidence,
    Msys2PackageEvidence,
    Msys2ReportEvidence,
    PatchEvidence,
    SourceEvidence,
)
from video_converter.ffmpeg_build.msys2_closure import ResolvedMsys2Closure
from video_converter.ffmpeg_build.source_cache import ResolvedSource
from video_converter.ffmpeg_build_manifest import load_json


import json

RESOLVE_LOCK_PATH = Path("packaging/ffmpeg-build/resolve_lock.py").resolve()

# Import resolve_lock module dynamically from packaging/ffmpeg-build/resolve_lock.py
spec = importlib.util.spec_from_file_location("resolve_lock_module", RESOLVE_LOCK_PATH)
assert spec and spec.loader
resolve_lock_module = importlib.util.module_from_spec(spec)
sys.modules["resolve_lock_module"] = resolve_lock_module
spec.loader.exec_module(resolve_lock_module)

parse_args = resolve_lock_module.parse_args
main = resolve_lock_module.main
resolve_lock = resolve_lock_module.resolve_lock


def test_parse_args_requires_exact_four_options():
    with pytest.raises(SystemExit):
        parse_args([])

    with pytest.raises(SystemExit):
        parse_args(["--manifest", "m.json"])

    with pytest.raises(SystemExit):
        parse_args([
            "--manifest", "m.json",
            "--cache-dir", "cache",
            "--acquisition-report", "report.json",
        ])

    parsed = parse_args([
        "--manifest", "m.json",
        "--cache-dir", "cache",
        "--acquisition-report", "report.json",
        "--output", "lock.json",
    ])
    assert parsed.manifest == Path("m.json")
    assert parsed.cache_dir == Path("cache")
    assert parsed.acquisition_report == Path("report.json")
    assert parsed.output == Path("lock.json")


def test_parse_args_rejects_unknown_argument():
    with pytest.raises(SystemExit):
        parse_args([
            "--manifest", "m.json",
            "--cache-dir", "cache",
            "--acquisition-report", "report.json",
            "--output", "lock.json",
            "--extra-arg", "bad",
        ])


def _create_minimal_valid_manifest() -> dict[str, Any]:
    return load_json(Path("packaging/ffmpeg-build/acquisition-manifest.json"))


def test_coordinator_lifecycle_order(tmp_path, monkeypatch):
    manifest_data = _create_minimal_valid_manifest()
    manifest_path = tmp_path / "manifest.json"
    import json
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")
    report_path = tmp_path / "report.json"
    report_path.write_text("{}", encoding="utf-8")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    output_path = tmp_path / "build.lock.json"

    calls: list[str] = []

    # Build a mock AcquisitionReport that has report.source_evidence
    class MockReport:
        source_evidence = {src["name"]: f"ev_{src['name']}" for src in manifest_data["sources"]}

    mock_report_instance = MockReport()

    def fake_load_manifest_and_sha(path: Path):
        calls.append("acquire_and_validate_manifest")
        assert path == manifest_path
        return manifest_data, "mock_sha"

    monkeypatch.setattr(resolve_lock_module, "load_and_validate_manifest", fake_load_manifest_and_sha)

    def fake_parse_report(path: Path):
        calls.append("parse_report")
        assert path == report_path
        return mock_report_instance

    def fake_resolve_msys2(policy: dict, report: Any):
        calls.append("resolve_msys2")
        assert policy == manifest_data["msys2"]
        assert report is mock_report_instance
        return "mock_msys2"

    def fake_resolve_source(source: dict, evidence: Any, cache_dir: Path, download: Any):
        calls.append(f"resolve_source:{source['name']}")
        return ResolvedSource(
            name=source["name"],
            artifact_url=source.get("artifact_url"),
            filename="file.tar",
            sha256="1" * 64,
            verification_evidence={"verified": True, "type": "commit_archive", "artifact_sha256": "1" * 64},
        )

    def fake_assemble_lock(manifest: dict, manifest_sha256: str, sources: Any, msys2: Any, report: Any):
        calls.append("assemble_lock")
        return {"assembled": True}

    def fake_validate_build_lock(lock: dict, manifest: dict):
        calls.append("validate_build_lock")
        assert lock == {"assembled": True}

    def fake_validate_cached_inputs(lock: dict, c_dir: Path):
        calls.append("validate_cached_inputs")
        assert lock == {"assembled": True}
        assert c_dir == cache_dir

    def fake_publish_build_lock(lock: dict, out_path: Path):
        calls.append("publish_build_lock")
        assert lock == {"assembled": True}
        assert out_path == output_path
        return out_path

    monkeypatch.setattr(resolve_lock_module, "parse_acquisition_report", fake_parse_report)
    monkeypatch.setattr(resolve_lock_module, "resolve_msys2_closure", fake_resolve_msys2)
    monkeypatch.setattr(resolve_lock_module, "resolve_source", fake_resolve_source)
    monkeypatch.setattr(resolve_lock_module, "assemble_build_lock", fake_assemble_lock)
    monkeypatch.setattr(resolve_lock_module, "validate_build_lock", fake_validate_build_lock)
    monkeypatch.setattr(resolve_lock_module, "validate_cached_inputs", fake_validate_cached_inputs)
    monkeypatch.setattr(resolve_lock_module, "publish_build_lock", fake_publish_build_lock)

    res = resolve_lock(
        manifest_path=manifest_path,
        cache_dir=cache_dir,
        acquisition_report_path=report_path,
        output_path=output_path,
    )
    assert res == output_path

    # Verify lifecycle ordering:
    # 1. read_bytes & sha256 & json.loads & validate_acquisition_manifest
    # 2. parse_report
    # 3. resolve_msys2
    # 4. resolve_source for each source (9 sources)
    # 5. assemble_lock
    # 6. validate_build_lock
    # 7. validate_cached_inputs
    # 8. publish_build_lock
    expected_order = [
        "acquire_and_validate_manifest",
        "parse_report",
        "resolve_msys2",
        *[f"resolve_source:{s['name']}" for s in manifest_data["sources"]],
        "assemble_lock",
        "validate_build_lock",
        "validate_cached_inputs",
        "publish_build_lock",
    ]
    assert calls == expected_order


def test_main_cli_exit_codes(tmp_path, monkeypatch):
    def fake_resolve_lock(**kwargs):
        return kwargs["output_path"]

    monkeypatch.setattr(resolve_lock_module, "resolve_lock", fake_resolve_lock)
    ret = main([
        "--manifest", "m.json",
        "--cache-dir", "cache",
        "--acquisition-report", "report.json",
        "--output", "lock.json",
    ])
    assert ret == 0

    def failing_resolve_lock(**kwargs):
        raise ValueError("Invalid source evidence")

    monkeypatch.setattr(resolve_lock_module, "resolve_lock", failing_resolve_lock)
    ret_fail = main([
        "--manifest", "m.json",
        "--cache-dir", "cache",
        "--acquisition-report", "report.json",
        "--output", "lock.json",
    ])
    assert ret_fail == 1


def test_coordinator_git_sources_prepopulated_only_ffmpeg_and_opus_downloaded(tmp_path, monkeypatch):
    """Test coordinator integration with seven canonical Git cache entries pre-populated.

    Injected recording downloader asserts only FFmpeg and libopus URLs are downloaded,
    resolver CLI never fetches Git dependencies, and missing any Git cache entry fails
    before output lock publication.
    """
    # Block any real network requests via urllib.request.urlopen
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("Unexpected real network request via urllib.request.urlopen")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    # Deterministic local fixture payloads
    ffmpeg_content = b"fake-ffmpeg-tar-xz-content-deterministic"
    ffmpeg_sha = hashlib.sha256(ffmpeg_content).hexdigest()

    opus_content = b"fake-deterministic-libopus-tar-gz-content"
    opus_digest = hashlib.sha256(opus_content).hexdigest()

    manifest_data = copy.deepcopy(_create_minimal_valid_manifest())
    libopus_manifest_entry = next(s for s in manifest_data["sources"] if s["name"] == "libopus")
    libopus_manifest_entry["verification"]["expected_digest"] = opus_digest

    # Monkeypatch validate_acquisition_manifest and validate_build_lock in resolve_lock module
    # so test manifest and lock pass with the test's expected_digest
    import video_converter.ffmpeg_build_manifest as manifest_mod
    orig_validate_acq = manifest_mod.validate_acquisition_manifest
    orig_validate_lock = manifest_mod.validate_build_lock

    def test_validate_acquisition_manifest(manifest: dict) -> None:
        m_copy = copy.deepcopy(manifest)
        entry = next(s for s in m_copy["sources"] if s["name"] == "libopus")
        entry["verification"]["expected_digest"] = "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f"
        orig_validate_acq(m_copy)

    def test_validate_build_lock(lock: dict, acquisition_manifest: dict) -> None:
        l_copy = copy.deepcopy(lock)
        entry = next(s for s in l_copy["sources"] if s["name"] == "libopus")
        if entry.get("sha256") == opus_digest:
            entry["sha256"] = "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f"
            entry["verification_evidence"]["expected_digest"] = "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f"
            entry["verification_evidence"]["artifact_sha256"] = "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f"
        m_copy = copy.deepcopy(acquisition_manifest)
        m_entry = next(s for s in m_copy["sources"] if s["name"] == "libopus")
        m_entry["verification"]["expected_digest"] = "c9b32b4253be5ae63d1ff16eea06b94b5f0f2951b7a02aceef58e3a3ce49c51f"
        orig_validate_lock(l_copy, m_copy)

    monkeypatch.setattr(resolve_lock_module, "validate_acquisition_manifest", test_validate_acquisition_manifest)
    monkeypatch.setattr(resolve_lock_module, "validate_build_lock", test_validate_build_lock)
    monkeypatch.setattr(manifest_mod, "validate_build_lock", test_validate_build_lock)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    output_path = tmp_path / "build.lock.json"

    # Pre-populate cache for the 7 git sources
    git_sources = [s for s in manifest_data["sources"] if s.get("acquisition_type") == "commit_archive"]
    assert len(git_sources) == 7

    source_evidence_map: dict[str, Any] = {}
    git_cache_files: dict[str, Path] = {}

    for s in git_sources:
        name = s["name"]
        commit = s["commit"]
        content = f"canonical-git-archive-content-for-{name}-{commit}".encode("utf-8")
        sha = hashlib.sha256(content).hexdigest()
        cache_file = cache_dir / sha
        cache_file.write_bytes(content)
        git_cache_files[name] = cache_file

        bundle_sha = hashlib.sha256(f"bundle-{name}".encode("utf-8")).hexdigest()
        source_evidence_map[name] = {
            "type": "commit_archive",
            "verified": True,
            "artifact_sha256": sha,
            "commit": commit,
            "verifier": "git-rev-parse-and-archive",
            "remote_url": s["git_remote_url"],
            "archive_command": f"git archive --format=tar.gz --prefix={name}-{commit}/ {commit}",
            "git_version": "git version 2.45.0",
            "git_bundle_sha256": bundle_sha,
            "bundle_retention_uri": f"project://ffmpeg-build/git/{name}/{commit}.bundle",
            "canonical_archive_retention_uri": f"project://ffmpeg-build/git/{name}/{commit}.tar.gz",
        }

    # Prepare evidence for official release sources (ffmpeg and libopus)
    source_evidence_map["ffmpeg"] = {
        "type": "pgp_signature",
        "verified": True,
        "artifact_sha256": ffmpeg_sha,
        "signature_url": "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz.asc",
        "signer": "FCF986EA15E6E293A5644F10B4322F04D67658D8",
    }

    source_evidence_map["libopus"] = {
        "type": "published_checksum",
        "algorithm": "sha256",
        "expected_digest": opus_digest,
        "verified": True,
        "artifact_sha256": opus_digest,
        "verifier": "sha256sum-test",
    }


    # Minimal MSYS2 closure report
    report_data = {
        "source_evidence": source_evidence_map,
        "recipe_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
        "patches": [
            {
                "name": patch["name"],
                "path": patch["path"],
                "sha256": "0" * 64,
            }
            for patch in manifest_data.get("patches", [])
        ],
        "msys2": {
            "installer": {
                "url": "https://repo.msys2.org/distrib/msys2-x86_64-latest.tar.xz",
                "sha256": "b" * 64,
                "signature_filename": "msys2-x86_64-latest.tar.xz.sig",
                "signature_sha256": "f" * 64,
                "signature_retention_uri": "project://ffmpeg-build/installer.tar.xz.sig",
                "retention_uri": "project://ffmpeg-build/installer.tar.xz",
                "signature_verification": {
                    "verified": True,
                    "verifier": "gpgv",
                    "signer": "msys2-keyring",
                },
            },
            "databases": [
                {
                    "name": "ucrt64.db",
                    "sha256": "c" * 64,
                    "signature_filename": "ucrt64.db.sig",
                    "signature_sha256": "8" * 64,
                    "signature_retention_uri": "project://ffmpeg-build/ucrt64.db.sig",
                    "retention_uri": "project://ffmpeg-build/ucrt64.db",
                    "signature_verification": {
                        "verified": True,
                        "verifier": "gpgv",
                        "signer": "msys2-keyring",
                    },
                }
            ],
            "packages": [
                {
                    "name": pkg_name,
                    "version": "1.0",
                    "filename": f"{pkg_name}-1.0-any.pkg.tar.zst",
                    "sha256": hashlib.sha256(pkg_name.encode("utf-8")).hexdigest(),
                    "signature_filename": f"{pkg_name}-1.0-any.pkg.tar.zst.sig",
                    "signature_sha256": hashlib.sha256((pkg_name + ".sig").encode("utf-8")).hexdigest(),
                    "signature_retention_uri": f"project://ffmpeg-build/{pkg_name}.sig",
                    "retention_uri": f"project://ffmpeg-build/{pkg_name}",
                    "dependencies": [],
                    "signature_verification": {
                        "verified": True,
                        "verifier": "gpgv",
                        "signer": "msys2-keyring",
                    },
                }
                for pkg_name in manifest_data["msys2"]["requested_packages"]
            ],
        },
    }

    report_path = tmp_path / "acquisition-report.json"
    report_path.write_text(json.dumps(report_data, indent=2), encoding="utf-8")

    # Injected downloader that records downloaded URLs and writes the matching bytes
    downloader_urls: list[str] = []

    def recording_download(url: str, dest: Path):
        downloader_urls.append(url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if url == "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz":
            dest.write_bytes(ffmpeg_content)
        elif url == "https://github.com/xiph/opus/releases/download/v1.4/opus-1.4.tar.gz":
            dest.write_bytes(opus_content)
        else:
            raise AssertionError(f"Unexpected download URL requested: {url}")

    # First test missing any Git cache entry fails before output lock publication
    missing_git_file = git_cache_files["x264"]
    missing_git_file.unlink()

    with pytest.raises(Exception):
        resolve_lock(
            manifest_path=manifest_path,
            cache_dir=cache_dir,
            acquisition_report_path=report_path,
            output_path=output_path,
            download=recording_download,
        )

    assert not output_path.exists()

    # Note that during the failed run, ffmpeg was downloaded before x264 failed.
    # We remove the cached ffmpeg file so it gets downloaded fresh in the next run:
    (cache_dir / ffmpeg_sha).unlink(missing_ok=True)

    # Restore missing git cache file
    x264_content = f"canonical-git-archive-content-for-x264-{git_sources[0]['commit']}".encode("utf-8")
    missing_git_file.write_bytes(x264_content)
    downloader_urls.clear()

    # Expect real cache validation to pass without monkeypatching!
    # Under old bypass setup, if we require real cache validation, it would fail because opus_content was b"fake-opus-bytes".
    resolved_out = resolve_lock(
        manifest_path=manifest_path,
        cache_dir=cache_dir,
        acquisition_report_path=report_path,
        output_path=output_path,
        download=recording_download,
    )

    assert downloader_urls == [
        "https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz",
        "https://github.com/xiph/opus/releases/download/v1.4/opus-1.4.tar.gz",
    ]
    assert resolved_out == output_path
    assert output_path.is_file()

    published_lock = json.loads(output_path.read_text(encoding="utf-8"))
    assert len(published_lock["sources"]) == 9
    for s in published_lock["sources"]:
        if s["acquisition_type"] == "commit_archive":
            assert "artifact_url" not in s
            assert "canonical_artifact" in s
            assert (cache_dir / s["canonical_artifact"]["sha256"]).is_file()
        else:
            assert "artifact_url" in s
            assert (cache_dir / s["sha256"]).is_file()

    # Finally, corrupt a Git cache object and verify no output lock publishes
    corrupted_lock_output = tmp_path / "corrupted_build.lock.json"
    corrupted_git_file = git_cache_files["libvpx"]
    corrupted_git_file.write_bytes(b"corrupted-cache-content-does-not-match-sha")

    with pytest.raises(Exception):
        resolve_lock(
            manifest_path=manifest_path,
            cache_dir=cache_dir,
            acquisition_report_path=report_path,
            output_path=corrupted_lock_output,
            download=recording_download,
        )

    assert not corrupted_lock_output.exists()


def test_coordinator_integration_real_cache_validation_and_publish(tmp_path, monkeypatch):
    """Exercise real cache validation and successful publish with local fixture cache without mocking validate_cached_inputs or publish_build_lock."""
    from video_converter.ffmpeg_build_manifest import validate_cached_inputs

    manifest_data = _create_minimal_valid_manifest()
    manifest_path = tmp_path / "acquisition-manifest.json"
    manifest_path.write_text(json.dumps(manifest_data, indent=2), encoding="utf-8")

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    output_path = tmp_path / "build.lock.json"
    report_path = tmp_path / "acquisition-report.json"
    report_path.write_text("{}", encoding="utf-8")

    # Generate real payloads for each source in manifest
    # Create real files in cache_dir with exact sha256
    source_resolved_list: list[ResolvedSource] = []
    fake_lock_sources: list[dict[str, Any]] = []

    for idx, src in enumerate(manifest_data["sources"]):
        name = src["name"]
        data = f"real-fixture-content-for-source-{name}-{idx}".encode("utf-8")
        real_sha = hashlib.sha256(data).hexdigest()

        # Write real file to cache_dir / real_sha
        (cache_dir / real_sha).write_bytes(data)

        if src["acquisition_type"] == "commit_archive":
            resolved_src = ResolvedSource(
                name=name,
                artifact_url=None,
                filename=f"{name}.tar.gz",
                sha256=real_sha,
                verification_evidence={
                    "type": "commit_archive",
                    "verified": True,
                    "artifact_sha256": real_sha,
                    "commit": src.get("commit", "0" * 40),
                    "verifier": "test-verifier",
                },
                upstream_remote_url=src.get("git_remote_url"),
                canonical_filename=f"{name}.tar.gz",
                canonical_retention_uri=f"project://ffmpeg-build/{real_sha}",
            )
            fake_lock_sources.append({
                "name": name,
                "acquisition_type": "commit_archive",
                "canonical_artifact": {
                    "origin": "git_archive",
                    "filename": f"{name}.tar.gz",
                    "sha256": real_sha,
                    "retention_uri": f"project://ffmpeg-build/{real_sha}",
                },
                "upstream_remote_url": src.get("git_remote_url"),
                "commit": src.get("commit", "0" * 40),
                "verification_evidence": {
                    "type": "commit_archive",
                    "verified": True,
                    "artifact_sha256": real_sha,
                    "commit": src.get("commit", "0" * 40),
                    "verifier": "test-verifier",
                },
            })
        else:
            resolved_src = ResolvedSource(
                name=name,
                artifact_url=src.get("artifact_url"),
                filename=f"{name}.tar.gz",
                sha256=real_sha,
                verification_evidence={
                    "type": "commit_archive",
                    "verified": True,
                    "artifact_sha256": real_sha,
                    "commit": src.get("commit", "0" * 40),
                    "verifier": "test-verifier",
                },
            )
            fake_lock_sources.append({
                "name": name,
                "acquisition_type": src["acquisition_type"],
                "artifact_url": src.get("artifact_url"),
                "filename": f"{name}.tar.gz",
                "sha256": real_sha,
                "verification_evidence": {
                    "type": "commit_archive",
                    "verified": True,
                    "artifact_sha256": real_sha,
                    "commit": src.get("commit", "0" * 40),
                    "verifier": "test-verifier",
                },
            })
        source_resolved_list.append(resolved_src)

    # To isolate and preserve lower module boundaries (MSYS2 closure, report parser, lock assembler, etc.),
    # we mock the upstream steps (report parse, msys2, resolve_source, assemble_lock, validate_build_lock),
    # but DO NOT mock validate_cached_inputs or publish_build_lock!
    class MockReport:
        source_evidence = {src["name"]: None for src in manifest_data["sources"]}

    fake_lock = {
        "sources": fake_lock_sources,
        "assembled": True,
    }

    monkeypatch.setattr(resolve_lock_module, "parse_acquisition_report", lambda p: MockReport())
    monkeypatch.setattr(resolve_lock_module, "resolve_msys2_closure", lambda m, r: "dummy_msys2")
    src_iter = iter(source_resolved_list)
    monkeypatch.setattr(resolve_lock_module, "resolve_source", lambda source, evidence, cache_dir, download: next(src_iter))
    monkeypatch.setattr(resolve_lock_module, "assemble_build_lock", lambda **kwargs: fake_lock)
    monkeypatch.setattr(resolve_lock_module, "validate_build_lock", lambda lock, manifest: None)

    # Note: validate_cached_inputs and publish_build_lock are the REAL production implementations!
    res = resolve_lock(
        manifest_path=manifest_path,
        cache_dir=cache_dir,
        acquisition_report_path=report_path,
        output_path=output_path,
    )
    assert res == output_path
    assert output_path.is_file()
    published_lock = json.loads(output_path.read_text(encoding="utf-8"))
    assert published_lock["assembled"] is True
    assert len(published_lock["sources"]) == len(manifest_data["sources"])

    # Now verify that real validate_cached_inputs actually executed by corrupting a cache file:
    # If one cached file is removed, resolve_lock should fail in validate_cached_inputs!
    (cache_dir / source_resolved_list[0].sha256).unlink()
    src_iter2 = iter(source_resolved_list)
    monkeypatch.setattr(resolve_lock_module, "resolve_source", lambda source, evidence, cache_dir, download: next(src_iter2))
    with pytest.raises(ValueError, match="Cached artifact missing"):
        resolve_lock(
            manifest_path=manifest_path,
            cache_dir=cache_dir,
            acquisition_report_path=report_path,
            output_path=output_path,
        )


def test_load_and_validate_manifest_rejects_duplicate_keys(tmp_path: Path):
    load_func = resolve_lock_module.load_and_validate_manifest
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text('{"schema_version": "1.0.0", "schema_version": "1.0.0"}', encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate JSON object member: schema_version"):
        load_func(bad_manifest)


def test_load_and_validate_manifest_rejects_nested_duplicate_keys(tmp_path: Path):
    load_func = resolve_lock_module.load_and_validate_manifest
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text(
        '{"schema_version": "1.0.0", "toolchain": {"environment": "UCRT64", "environment": "UCRT64"}}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON object member: environment"):
        load_func(bad_manifest)


def test_load_and_validate_manifest_preserves_digest_over_raw_bytes(tmp_path: Path):
    load_func = resolve_lock_module.load_and_validate_manifest
    manifest_file = tmp_path / "manifest.json"
    raw_content = b'{\n  "schema_version": "1.0.0"\n}\n'
    manifest_file.write_bytes(raw_content)
    expected_sha = hashlib.sha256(raw_content).hexdigest()
    # It will fail at validate_acquisition_manifest because keys are missing,
    # but before validation it calculates hash. Let's test with valid minimal structure or catch error.
    # To verify sha256 is exactly over raw bytes:
    try:
        parsed, sha = load_func(manifest_file)
        assert sha == expected_sha
    except ValueError as err:
        # If validate_acquisition_manifest raises, load_and_validate_manifest raises.
        # But let's verify load_and_validate_manifest computes sha over raw bytes with a real manifest:
        pass

    import shutil
    real_manifest = Path("packaging/ffmpeg-build/acquisition-manifest.json")
    if real_manifest.exists():
        raw = real_manifest.read_bytes()
        parsed, sha = load_func(real_manifest)
        assert sha == hashlib.sha256(raw).hexdigest()
