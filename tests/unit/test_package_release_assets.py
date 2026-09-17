"""Unit tests for local release assets orchestrator CLI (packaging/package_release_assets.py)."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock
import zipfile

import pytest

CLI_PATH = Path(__file__).resolve().parents[2] / "packaging" / "package_release_assets.py"
spec = importlib.util.spec_from_file_location("package_release_assets", CLI_PATH)
if spec is None or spec.loader is None:
    raise ImportError(f"Could not load {CLI_PATH}")
pra = importlib.util.module_from_spec(spec)
sys.modules["package_release_assets"] = pra
spec.loader.exec_module(pra)

# Load test_source_bundle module
TEST_SB_PATH = Path(__file__).resolve().parent / "test_source_bundle.py"
spec_sb = importlib.util.spec_from_file_location("test_source_bundle", TEST_SB_PATH)
if spec_sb is None or spec_sb.loader is None:
    raise ImportError(f"Could not load {TEST_SB_PATH}")
test_sb = importlib.util.module_from_spec(spec_sb)
sys.modules["test_source_bundle"] = test_sb
spec_sb.loader.exec_module(test_sb)

import video_converter.ffmpeg_build.source_bundle as sb


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_lf_text(p: Path, text: str) -> None:
    with p.open("w", encoding="utf-8", newline="") as f:
        f.write(text)


_orig_make_dummy = test_sb._make_dummy_lock_and_inputs


def _make_dummy_with_manifest(tmp_path: Path):
    fixture = _orig_make_dummy(tmp_path)
    ws = fixture["workspace_root"]
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    manifest_data = {
        "artifact_name": "Local Custom UCRT64 FFmpeg 6.1.1 Static",
        "archive_url": "local://ffmpeg-v1-output",
        "release_page": None,
        "expected_binaries": {
            "ffmpeg.exe": {
                "sha256": fixture["build_record"]["outputs"]["binaries"]["ffmpeg.exe"]["sha256"],
                "version_prefix": "ffmpeg version 6.1.1",
            },
            "ffprobe.exe": {
                "sha256": fixture["build_record"]["outputs"]["binaries"]["ffprobe.exe"]["sha256"],
                "version_prefix": "ffprobe version 6.1.1",
            },
        },
    }
    (packaging_dir / "ffmpeg_artifact_manifest.json").write_text(
        json.dumps(manifest_data, indent=2), encoding="utf-8"
    )
    return fixture


test_sb._make_dummy_lock_and_inputs = _make_dummy_with_manifest


def test_cli_parser_defaults():
    parser = pra.build_arg_parser()
    args = parser.parse_args([])
    assert args.build_output_dir == Path(r"D:\ffmpeg-v1-output")
    assert args.source_cache_dir == Path(r"D:\ffmpeg-release-source-cache")
    assert args.workspace_root is None
    assert args.dist_dir is None
    assert args.skip_pyinstaller is False
    assert args.dry_run is False


def test_cli_parser_custom_overrides(tmp_path: Path):
    out_dir = tmp_path / "out"
    cache_dir = tmp_path / "cache"
    ws = tmp_path / "ws"
    dist = tmp_path / "dist"

    parser = pra.build_arg_parser()
    args = parser.parse_args([
        "--build-output-dir", str(out_dir),
        "--source-cache-dir", str(cache_dir),
        "--workspace-root", str(ws),
        "--dist-dir", str(dist),
        "--skip-pyinstaller",
        "--dry-run",
    ])
    assert args.build_output_dir == out_dir
    assert args.source_cache_dir == cache_dir
    assert args.workspace_root == ws
    assert args.dist_dir == dist
    assert args.skip_pyinstaller is True
    assert args.dry_run is True


def test_format_sha256sums_and_verify(tmp_path: Path):
    file1 = tmp_path / "test1.zip"
    file2 = tmp_path / "test2.zip"
    content1 = b"archive 1 payload"
    content2 = b"archive 2 payload"
    file1.write_bytes(content1)
    file2.write_bytes(content2)

    sums_file = tmp_path / "SHA256SUMS.txt"
    entries = pra.write_sha256sums(sums_file, [file1, file2])

    expected_text = f"{_sha256(content1)} *{file1.name}\n{_sha256(content2)} *{file2.name}\n"
    assert sums_file.read_text(encoding="utf-8") == expected_text
    assert entries == {
        file1.name: _sha256(content1),
        file2.name: _sha256(content2),
    }

    # Verify checksums roundtrip
    verified = pra.verify_sha256sums(sums_file)
    assert verified == entries


def test_verify_sha256sums_rejects_corrupted_file(tmp_path: Path):
    file1 = tmp_path / "test1.zip"
    file1.write_bytes(b"original content")
    sums_file = tmp_path / "SHA256SUMS.txt"
    pra.write_sha256sums(sums_file, [file1])

    # Corrupt content
    file1.write_bytes(b"tampered content")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        pra.verify_sha256sums(sums_file)


def test_verify_sha256sums_rejects_missing_file(tmp_path: Path):
    file1 = tmp_path / "test1.zip"
    file1.write_bytes(b"original content")
    sums_file = tmp_path / "SHA256SUMS.txt"
    pra.write_sha256sums(sums_file, [file1])

    file1.unlink()
    with pytest.raises(FileNotFoundError, match="File declared in SHA256SUMS.txt not found"):
        pra.verify_sha256sums(sums_file)


def test_verify_sha256sums_strict_rejections(tmp_path: Path):
    sums_file = tmp_path / "SHA256SUMS.txt"
    f1 = tmp_path / "test.zip"
    f1.write_bytes(b"data")
    digest = hashlib.sha256(b"data").hexdigest().lower()

    # CRLF rejection
    sums_file.write_bytes(f"{digest} *{f1.name}\r\n".encode("utf-8"))
    with pytest.raises(ValueError, match="CRLF line endings detected"):
        pra.verify_sha256sums(sums_file)

    # Missing trailing newline
    sums_file.write_bytes(f"{digest} *{f1.name}".encode("utf-8"))
    with pytest.raises(ValueError, match="Line in SHA256SUMS.txt does not end with newline"):
        pra.verify_sha256sums(sums_file)

    # Blank line
    sums_file.write_bytes(f"{digest} *{f1.name}\n\n".encode("utf-8"))
    with pytest.raises(ValueError, match="Blank line detected in SHA256SUMS.txt"):
        pra.verify_sha256sums(sums_file)

    # Filename with space (rejected by strict grammar ^[0-9a-f]{64} \*[^/\\\s]+\.zip\n$)
    bad_f = tmp_path / "bad space.zip"
    bad_f.write_bytes(b"data")
    sums_file.write_bytes(f"{digest} *bad space.zip\n".encode("utf-8"))
    with pytest.raises(ValueError, match="Invalid checksum line format"):
        pra.verify_sha256sums(sums_file)


def test_dry_run_requires_manifest_when_not_skip_pyinstaller(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"

    manifest = packaging_dir / "ffmpeg_artifact_manifest.json"
    if manifest.exists():
        manifest.unlink()

    with pytest.raises(FileNotFoundError, match="Artifact manifest not found"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )


def test_dry_run_manifest_validates_both_binaries(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"

    # Read record from build_output_dir / "build-record.json"
    record = json.loads((fixture["build_output_dir"] / "build-record.json").read_text(encoding="utf-8"))
    record_binaries = record["outputs"]["binaries"]
    manifest_data = {
        "expected_binaries": {
            "ffmpeg.exe": {
                "sha256": record_binaries["ffmpeg.exe"]["sha256"],
                "version_prefix": "ffmpeg version 6.1.1",
            }
        }
    }
    manifest = packaging_dir / "ffmpeg_artifact_manifest.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="ffprobe.exe"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )


def test_dry_run_manifest_validates_version_prefix_compatibility(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"

    record = json.loads((fixture["build_output_dir"] / "build-record.json").read_text(encoding="utf-8"))
    record_binaries = record["outputs"]["binaries"]
    manifest_data = {
        "expected_binaries": {
            "ffmpeg.exe": {
                "sha256": record_binaries["ffmpeg.exe"]["sha256"],
                "version_prefix": "ffmpeg version 7.999",
            },
            "ffprobe.exe": {
                "sha256": record_binaries["ffprobe.exe"]["sha256"],
                "version_prefix": "ffprobe version 6.1.1",
            },
        }
    }
    manifest = packaging_dir / "ffmpeg_artifact_manifest.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="Binary manifest version_prefix mismatch"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )


def test_dry_run_rejects_file_where_dist_or_release_assets_expected_dir(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    dist = ws / "dist"
    dist.mkdir(parents=True)
    # File where dist/release-assets is expected dir
    bad_assets = dist / "release-assets"
    bad_assets.write_text("not a directory")

    with pytest.raises(ValueError, match="Destination release-assets path is a file, not a directory"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=True,
        )


def test_dry_run_skip_mode_rejects_missing_empty_or_dir_workspace_executable(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    dist = ws / "dist"
    dist.mkdir(parents=True)
    app_exe = dist / "FreeSimpleVideoConverter.exe"

    # 1. Missing
    with pytest.raises(FileNotFoundError, match="Expected pre-existing application executable not found"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=True,
        )

    # 2. Directory
    app_exe.mkdir()
    with pytest.raises(ValueError, match="Application executable is a directory, not a regular file"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=True,
        )
    app_exe.rmdir()

    # 3. Empty (0 bytes)
    app_exe.write_bytes(b"")
    with pytest.raises(ValueError, match="Application executable is empty"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=True,
        )


def test_cleanup_failure_after_publication_surfaces_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ synthetic executable")

    existing_assets = dist / "release-assets"
    existing_assets.mkdir()
    (existing_assets / "old.txt").write_text("old version")

    def mock_run(cmd, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "ffprobe" in str(cmd[0]):
            res.stdout = "ffprobe version 6.1.1\n"
        else:
            res.stdout = "ffmpeg version 6.1.1\n"
        return res

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    # Mock shutil.rmtree during backup cleanup to fail
    orig_rmtree = pra.shutil.rmtree
    def failing_rmtree(path, *args, **kwargs):
        if "release-assets-backup-" in str(path):
            raise OSError("Permission denied deleting backup")
        return orig_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(pra.shutil, "rmtree", failing_rmtree)

    with pytest.raises(OSError, match="Permission denied deleting backup"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=False,
        )

    # Published final remains despite cleanup failure
    assert existing_assets.is_dir()
    assert (existing_assets / "SHA256SUMS.txt").is_file()


def test_rollback_restores_old_final_on_promotion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ synthetic executable")

    existing_assets = dist / "release-assets"
    existing_assets.mkdir()
    (existing_assets / "sentinel.txt").write_text("must be restored on promotion failure")

    def mock_run(cmd, **kwargs):
        res = MagicMock()
        res.returncode = 0
        if "ffprobe" in str(cmd[0]):
            res.stdout = "ffprobe version 6.1.1\n"
        else:
            res.stdout = "ffmpeg version 6.1.1\n"
        return res

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    # Mock Path.rename so that promoting temp_assets_dir to release_assets_dir fails
    orig_rename = Path.rename
    def failing_rename(self, target, *args, **kwargs):
        if "release-assets-tmp-" in str(self) and str(target).endswith("release-assets"):
            raise OSError("Simulated promotion disk failure")
        return orig_rename(self, target, *args, **kwargs)

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises(OSError, match="Simulated promotion disk failure"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=False,
        )

    # Old directory restored
    assert existing_assets.is_dir()
    assert (existing_assets / "sentinel.txt").read_text() == "must be restored on promotion failure"


def test_cli_help_subprocess():
    res = subprocess.run(
        [sys.executable, str(CLI_PATH), "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0
    assert "--build-output-dir" in res.stdout
    assert "--source-cache-dir" in res.stdout
    assert "--workspace-root" in res.stdout
    assert "--dist-dir" in res.stdout
    assert "--skip-pyinstaller" in res.stdout
    assert "--dry-run" in res.stdout


def test_verify_binary_versions_fails_on_empty_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ffmpeg_exe = tmp_path / "ffmpeg.exe"
    ffprobe_exe = tmp_path / "ffprobe.exe"
    ffmpeg_exe.write_bytes(b"binary1")
    ffprobe_exe.write_bytes(b"binary2")

    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            stdout = ""
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)
    with pytest.raises(RuntimeError, match="empty version output"):
        pra.verify_binary_versions(ffmpeg_exe, ffprobe_exe)


def test_verify_sha256sums_strict_canonical_rules(tmp_path: Path):
    z1 = tmp_path / "a.zip"
    z2 = tmp_path / "b.zip"
    z1.write_bytes(b"content1")
    z2.write_bytes(b"content2")
    h1 = _sha256(b"content1")
    h2 = _sha256(b"content2")

    sums_file = tmp_path / "SHA256SUMS.txt"

    # Rule: reject non-.zip entry
    txt_file = tmp_path / "other.txt"
    txt_file.write_bytes(b"text")
    htxt = _sha256(b"text")
    _write_lf_text(sums_file, f"{h1} *a.zip\n{htxt} *other.txt\n")
    with pytest.raises(ValueError, match="(Non-ZIP entry declared in SHA256SUMS.txt|Invalid checksum line format)"):
        pra.verify_sha256sums(sums_file)

    # Rule: reject blank lines or trailing blank lines
    _write_lf_text(sums_file, f"{h1} *a.zip\n\n{h2} *b.zip\n")
    with pytest.raises(ValueError, match="Blank line detected"):
        pra.verify_sha256sums(sums_file)

    # Rule: reject leading or multiple whitespace
    _write_lf_text(sums_file, f" {h1} *a.zip\n{h2} *b.zip\n")
    with pytest.raises(ValueError, match="Invalid checksum line format"):
        pra.verify_sha256sums(sums_file)

    _write_lf_text(sums_file, f"{h1}  *{z1.name}\n{h2} *{z2.name}\n")
    with pytest.raises(ValueError, match="Invalid checksum line format"):
        pra.verify_sha256sums(sums_file)

    # Rule: reject omitted zip (zip exists on disk but not in SHA256SUMS)
    _write_lf_text(sums_file, f"{h1} *a.zip\n")
    with pytest.raises(ValueError, match="Mismatch between declared checksums and directory zip files"):
        pra.verify_sha256sums(sums_file)

    # Rule: uppercase hex rejected
    _write_lf_text(sums_file, f"{h1.upper()} *a.zip\n{h2} *b.zip\n")
    with pytest.raises(ValueError, match="Invalid checksum line format"):
        pra.verify_sha256sums(sums_file)


def test_dry_run_zero_subprocesses_and_fails_on_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")

    # Guard against ANY subprocess call under dry-run
    def forbidden_subprocess(*args, **kwargs):
        raise AssertionError("No subprocess may be invoked during --dry-run!")

    monkeypatch.setattr(pra.subprocess, "run", forbidden_subprocess)

    dist = ws / "dist"

    report = pra.package_release_assets(
        build_output_dir=fixture["build_output_dir"],
        source_cache_dir=fixture["source_cache_dir"],
        workspace_root=ws,
        dist_dir=dist,
        skip_pyinstaller=False,
        dry_run=True,
    )
    assert report["status"] == "dry_run_success"

    # Test conflicting layout: workspace/bin is an existing file instead of directory
    conflict_bin = ws / "bin"
    conflict_bin.write_text("conflict file")
    with pytest.raises(ValueError, match="Destination bin path is a file, not a directory"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )
    conflict_bin.unlink()

    # Test conflicting layout: dist_dir is an existing file instead of directory
    conflict_dist = ws / "dist_file"
    conflict_dist.write_text("conflict dist")
    with pytest.raises(ValueError, match="Destination dist path is a file, not a directory"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=conflict_dist,
            skip_pyinstaller=False,
            dry_run=True,
        )


def test_transactional_publication_rollback_on_promotion_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ synthetic executable")

    # Pre-populate release-assets with an existing file
    existing_assets = dist / "release-assets"
    existing_assets.mkdir()
    sentinel_file = existing_assets / "sentinel.txt"
    sentinel_file.write_text("initial state")

    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            if "ffmpeg" in str(cmd[0]):
                stdout = "ffmpeg version 6.1.1\n"
            else:
                stdout = "ffprobe version 6.1.1\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    # Injected failure: rename of temp to release_assets_dir fails
    orig_rename = Path.rename

    def failing_rename(self, target):
        if "release-assets-tmp-" in str(self) and "release-assets" == Path(target).name:
            raise OSError("Injected failure during temp promotion rename")
        return orig_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises(OSError, match="Injected failure during temp promotion rename"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=False,
        )

    # Old directory restored exactly
    assert existing_assets.is_dir()
    assert sentinel_file.read_text() == "initial state"
    assert len(list(dist.glob("release-assets-tmp-*"))) == 0
    assert len(list(dist.glob("release-assets-backup-*"))) == 0


def test_transactional_publication_rollback_on_backup_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ synthetic executable")

    existing_assets = dist / "release-assets"
    existing_assets.mkdir()
    sentinel_file = existing_assets / "sentinel.txt"
    sentinel_file.write_text("initial state")

    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            if "ffmpeg" in str(cmd[0]):
                stdout = "ffmpeg version 6.1.1\n"
            else:
                stdout = "ffprobe version 6.1.1\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    # Injected failure: initial backup rename of release_assets_dir fails
    orig_rename = Path.rename

    def failing_rename(self, target):
        if Path(self).name == "release-assets" and "release-assets-backup-" in str(target):
            raise OSError("Injected failure during backup rename")
        return orig_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises(OSError, match="Injected failure during backup rename"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=False,
        )

    # Old directory untouched
    assert existing_assets.is_dir()
    assert sentinel_file.read_text() == "initial state"
    assert len(list(dist.glob("release-assets-tmp-*"))) == 0
    assert len(list(dist.glob("release-assets-backup-*"))) == 0


def test_successful_reports_contain_promoted_paths_and_sizes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ synthetic executable")

    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            if "ffmpeg" in str(cmd[0]):
                stdout = "ffmpeg version 6.1.1\n"
            else:
                stdout = "ffprobe version 6.1.1\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    report = pra.package_release_assets(
        build_output_dir=fixture["build_output_dir"],
        source_cache_dir=fixture["source_cache_dir"],
        workspace_root=ws,
        dist_dir=dist,
        skip_pyinstaller=True,
        dry_run=False,
    )

    source_path = Path(report["source_archive"]["output_path"])
    app_path = Path(report["app_archive"]["output_path"])
    sums_path = Path(report["sums_file"])

    # Must point to final promoted release-assets dir, NOT temp dir
    assert "release-assets-tmp-" not in str(source_path)
    assert "release-assets-tmp-" not in str(app_path)
    assert "release-assets-tmp-" not in str(sums_path)

    assert source_path.is_file()
    assert app_path.is_file()
    assert sums_path.is_file()

    # Verify app archive byte size reported and accurate
    assert "size_bytes" in report["app_archive"]
    assert report["app_archive"]["size_bytes"] == app_path.stat().st_size
    assert "size_bytes" in report["source_archive"]
    assert report["source_archive"]["size_bytes"] == source_path.stat().st_size

    assert report["source_archive"]["sha256"] == _sha256(source_path.read_bytes())
    assert report["app_archive"]["sha256"] == _sha256(app_path.read_bytes())


def test_verify_sha256sums_rejects_unsafe_names(tmp_path: Path):
    sums_file = tmp_path / "SHA256SUMS.txt"
    _write_lf_text(sums_file, "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855 *../traversal.zip\n")
    with pytest.raises(ValueError, match="(Unsafe filename in checksum line|Invalid checksum line format)"):
        pra.verify_sha256sums(sums_file)


def test_verify_sha256sums_rejects_duplicate_filenames(tmp_path: Path):
    f1 = tmp_path / "test.zip"
    f1.write_bytes(b"data")
    h = _sha256(b"data")
    sums_file = tmp_path / "SHA256SUMS.txt"
    _write_lf_text(sums_file, f"{h} *test.zip\n{h} *test.zip\n")
    with pytest.raises(ValueError, match="Duplicate filename in SHA256SUMS.txt"):
        pra.verify_sha256sums(sums_file)


def test_strict_module_local_subprocess_mocking_and_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    build_exe_script = packaging_dir / "build_exe.py"
    build_exe_script.write_text("# dummy build_exe\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ executable")

    calls = []

    def strict_subprocess_run(cmd, **kwargs):
        calls.append({"cmd": list(cmd), "kwargs": kwargs})
        str_cmd = [str(c) for c in cmd]
        if str_cmd[1:] == ["-version"] and "ffmpeg.exe" in str_cmd[0]:
            assert kwargs.get("timeout") == 15
            assert kwargs.get("text") is True
            assert kwargs.get("check") is False
            class Res:
                returncode = 0
                stdout = "ffmpeg version 6.1.1\n"
            return Res()
        elif str_cmd[1:] == ["-version"] and "ffprobe.exe" in str_cmd[0]:
            assert kwargs.get("timeout") == 15
            assert kwargs.get("text") is True
            assert kwargs.get("check") is False
            class Res:
                returncode = 0
                stdout = "ffprobe version 6.1.1\n"
            return Res()
        elif str_cmd[0] == sys.executable and str_cmd[1] == str(build_exe_script) and str_cmd[2:4] == ["--dist-dir", str(dist)]:
            assert kwargs.get("cwd") == str(ws)
            assert kwargs.get("check") is False
            dummy_exe.write_bytes(b"rebuilt binary")
            class Res:
                returncode = 0
                stdout = "Success\n"
            return Res()
        else:
            raise AssertionError(f"Unexpected subprocess invocation: {cmd} with kwargs {kwargs}")

    # Patch module-local subprocess specifically
    monkeypatch.setattr(pra.subprocess, "run", strict_subprocess_run)

    report = pra.package_release_assets(
        build_output_dir=fixture["build_output_dir"],
        source_cache_dir=fixture["source_cache_dir"],
        workspace_root=ws,
        dist_dir=dist,
        skip_pyinstaller=False,
        dry_run=False,
    )
    assert report["status"] == "success"
    assert len(calls) == 3




def test_stage_binaries_copies_executables(tmp_path: Path):
    build_output_dir = tmp_path / "build_output"
    src_bin = build_output_dir / "bin"
    src_bin.mkdir(parents=True)
    f_content = b"dummy ffmpeg"
    p_content = b"dummy ffprobe"
    (src_bin / "ffmpeg.exe").write_bytes(f_content)
    (src_bin / "ffprobe.exe").write_bytes(p_content)

    record = {
        "outputs": {
            "binaries": {
                "ffmpeg.exe": {"sha256": _sha256(f_content), "size_bytes": len(f_content)},
                "ffprobe.exe": {"sha256": _sha256(p_content), "size_bytes": len(p_content)},
            }
        }
    }

    target_bin = tmp_path / "workspace" / "bin"
    pra.stage_binaries(build_output_dir, target_bin, record=record, dry_run=False)

    assert (target_bin / "ffmpeg.exe").read_bytes() == f_content
    assert (target_bin / "ffprobe.exe").read_bytes() == p_content


def test_stage_binaries_dry_run_no_writes(tmp_path: Path):
    build_output_dir = tmp_path / "build_output"
    src_bin = build_output_dir / "bin"
    src_bin.mkdir(parents=True)
    f_content = b"dummy ffmpeg"
    p_content = b"dummy ffprobe"
    (src_bin / "ffmpeg.exe").write_bytes(f_content)
    (src_bin / "ffprobe.exe").write_bytes(p_content)

    record = {
        "outputs": {
            "binaries": {
                "ffmpeg.exe": {"sha256": _sha256(f_content), "size_bytes": len(f_content)},
                "ffprobe.exe": {"sha256": _sha256(p_content), "size_bytes": len(p_content)},
            }
        }
    }

    target_bin = tmp_path / "workspace" / "bin"
    dest_ffmpeg, dest_ffprobe = pra.stage_binaries(build_output_dir, target_bin, record=record, dry_run=True)

    assert not target_bin.exists()
    assert dest_ffmpeg == target_bin / "ffmpeg.exe"
    assert dest_ffprobe == target_bin / "ffprobe.exe"



def test_verify_binary_versions_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ffmpeg_exe = tmp_path / "ffmpeg.exe"
    ffprobe_exe = tmp_path / "ffprobe.exe"
    ffmpeg_exe.write_bytes(b"binary1")
    ffprobe_exe.write_bytes(b"binary2")

    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            if "ffmpeg" in str(cmd[0]):
                stdout = "ffmpeg version 6.1.1-custom Copyright (c) 2000-2023\nother line\n"
            else:
                stdout = "ffprobe version 6.1.1-custom Copyright (c) 2000-2023\nother line\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)
    ff_ver, fp_ver = pra.verify_binary_versions(
        ffmpeg_exe,
        ffprobe_exe,
        expected_ffmpeg_version="ffmpeg version 6.1.1",
        expected_ffprobe_version="ffprobe version 6.1.1",
    )
    assert ff_ver.startswith("ffmpeg version 6.1.1")
    assert fp_ver.startswith("ffprobe version 6.1.1")


def test_verify_binary_versions_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    ffmpeg_exe = tmp_path / "ffmpeg.exe"
    ffprobe_exe = tmp_path / "ffprobe.exe"
    ffmpeg_exe.write_bytes(b"binary1")
    ffprobe_exe.write_bytes(b"binary2")

    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            stdout = "ffmpeg version 5.0 Copyright (c) 2000-2022\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)
    with pytest.raises(ValueError, match="ffmpeg version mismatch"):
        pra.verify_binary_versions(
            ffmpeg_exe,
            ffprobe_exe,
            expected_ffmpeg_version="ffmpeg version 6.1.1",
            expected_ffprobe_version="ffprobe version 6.1.1",
        )


def test_create_app_distribution_zip_contents(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    (ws / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (ws / "THIRD_PARTY_NOTICES.md").write_text("Notices\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir()
    app_exe = dist / "FreeSimpleVideoConverter.exe"
    app_exe.write_bytes(b"MZ synthetic executable")

    out_zip = dist / "app.zip"
    summary = pra.create_app_distribution_zip(app_exe, ws, out_zip)

    assert out_zip.is_file()
    assert summary["entry_count"] == 4
    with zipfile.ZipFile(out_zip, "r") as zf:
        namelist = zf.namelist()
        assert namelist == [
            "FreeSimpleVideoConverter.exe",
            "LICENSE",
            "README.md",
            "THIRD_PARTY_NOTICES.md",
        ]
        info = zf.getinfo("FreeSimpleVideoConverter.exe")
        assert info.date_time == pra.DETERMINISTIC_ZIP_TIMESTAMP
        assert (info.external_attr >> 16) == (0o100000 | pra.DETERMINISTIC_FILE_MODE)


def test_package_release_assets_pipeline_dry_run_no_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")

    dist = ws / "dist"
    # Ensure dist does not exist initially
    assert not dist.exists()

    report = pra.package_release_assets(
        build_output_dir=fixture["build_output_dir"],
        source_cache_dir=fixture["source_cache_dir"],
        workspace_root=ws,
        dist_dir=dist,
        skip_pyinstaller=False,
        dry_run=True,
    )
    assert report["status"] == "dry_run_success"
    assert not dist.exists()
    assert not (ws / "bin").exists()


def test_package_release_assets_pipeline_skip_pyinstaller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ synthetic executable")

    # Mock subprocess.run for binary version checks
    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            if "ffmpeg" in str(cmd[0]):
                stdout = "ffmpeg version 6.1.1\n"
            else:
                stdout = "ffprobe version 6.1.1\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    report = pra.package_release_assets(
        build_output_dir=fixture["build_output_dir"],
        source_cache_dir=fixture["source_cache_dir"],
        workspace_root=ws,
        dist_dir=dist,
        skip_pyinstaller=True,
        dry_run=False,
    )
    assert report["status"] == "success"

    release_assets = dist / "release-assets"
    source_zip = release_assets / "ffmpeg-6.1.1-custom-source.zip"
    app_zip = release_assets / pra.APP_DIST_ZIP_NAME
    sums_file = release_assets / "SHA256SUMS.txt"

    assert source_zip.is_file()
    assert app_zip.is_file()
    assert sums_file.is_file()

    # Validate source ZIP via source_bundle engine
    assert sb.validate_source_bundle_zip(source_zip, fixture["lock"]) is True

    # Validate checksums roundtrip
    verified = pra.verify_sha256sums(sums_file)
    assert set(verified.keys()) == {
        "ffmpeg-6.1.1-custom-source.zip",
        pra.APP_DIST_ZIP_NAME,
    }
    assert verified["ffmpeg-6.1.1-custom-source.zip"] == _sha256(source_zip.read_bytes())
    assert verified[pra.APP_DIST_ZIP_NAME] == _sha256(app_zip.read_bytes())


def test_main_cli_entrypoint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")

    dist = ws / "dist"
    argv = [
        "--build-output-dir", str(fixture["build_output_dir"]),
        "--source-cache-dir", str(fixture["source_cache_dir"]),
        "--workspace-root", str(ws),
        "--dist-dir", str(dist),
        "--dry-run",
    ]
    exit_code = pra.main(argv)
    assert exit_code == 0


def test_package_release_assets_fails_on_missing_executable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")

    dist = ws / "dist"

    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            if "ffmpeg" in str(cmd[0]):
                stdout = "ffmpeg version 6.1.1\n"
            else:
                stdout = "ffprobe version 6.1.1\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    with pytest.raises(FileNotFoundError, match="Expected pre-existing application executable not found"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=False,
        )



def test_package_release_assets_fails_on_pyinstaller_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")

    dist = ws / "dist"

    def mock_run(cmd, **kwargs):
        class MockResult:
            if any("build_exe.py" in str(arg) for arg in cmd):
                returncode = 1
                stdout = "PyInstaller error"
            elif "ffmpeg" in str(cmd[0]):
                returncode = 0
                stdout = "ffmpeg version 6.1.1\n"
            else:
                returncode = 0
                stdout = "ffprobe version 6.1.1\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    with pytest.raises(RuntimeError, match="PyInstaller build failed with exit code 1"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=False,
        )


def test_package_release_assets_pipeline_dry_run_fails_on_tampered_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")

    # Tamper one cached source
    src0 = fixture["lock"]["sources"][0]
    sha0 = src0.get("sha256") or src0["canonical_artifact"]["sha256"]
    cached_file = fixture["source_cache_dir"] / sha0
    cached_file.write_bytes(b"corrupted cache content")

    dist = ws / "dist"

    with pytest.raises(ValueError, match="Cached artifact digest mismatch"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )


def test_package_release_assets_pipeline_dry_run_fails_on_tampered_binary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")

    # Corrupt source ffmpeg.exe
    src_ffmpeg = fixture["build_output_dir"] / "bin" / "ffmpeg.exe"
    src_ffmpeg.write_bytes(b"tampered ffmpeg binary")

    dist = ws / "dist"

    with pytest.raises(ValueError, match="Source ffmpeg.exe (size|sha256) mismatch"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )


def test_atomic_replacement_cleans_temp_on_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ synthetic executable")

    # Pre-populate release-assets with an existing file
    existing_assets = dist / "release-assets"
    existing_assets.mkdir()
    sentinel_file = existing_assets / "sentinel.txt"
    sentinel_file.write_text("should remain unchanged on error")

    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            if "ffmpeg" in str(cmd[0]):
                stdout = "ffmpeg version 6.1.1\n"
            else:
                stdout = "ffprobe version 6.1.1\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    # Force error during app distribution zip creation
    def bad_create_app_zip(*args, **kwargs):
        raise RuntimeError("Simulated failure in ZIP creation")

    monkeypatch.setattr(pra, "create_app_distribution_zip", bad_create_app_zip)

    with pytest.raises(RuntimeError, match="Simulated failure in ZIP creation"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=False,
        )

    # Old directory untouched
    assert existing_assets.is_dir()
    assert sentinel_file.read_text() == "should remain unchanged on error"
    # No temp directories left behind
    temp_dirs = list(dist.glob("release-assets-tmp-*"))
    assert len(temp_dirs) == 0


def test_deterministic_app_zip_byte_identical(tmp_path: Path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    (ws / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (ws / "THIRD_PARTY_NOTICES.md").write_text("Notices\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir()
    app_exe = dist / "FreeSimpleVideoConverter.exe"
    app_exe.write_bytes(b"MZ synthetic executable")

    out_zip1 = dist / "app1.zip"
    out_zip2 = dist / "app2.zip"

    res1 = pra.create_app_distribution_zip(app_exe, ws, out_zip1)
    res2 = pra.create_app_distribution_zip(app_exe, ws, out_zip2)

    assert res1["sha256"] == res2["sha256"]
    assert out_zip1.read_bytes() == out_zip2.read_bytes()


def test_dry_run_manifest_rejects_missing_or_empty_version_prefix(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"

    record = json.loads((fixture["build_output_dir"] / "build-record.json").read_text(encoding="utf-8"))
    record_binaries = record["outputs"]["binaries"]
    manifest_data = {
        "expected_binaries": {
            "ffmpeg.exe": {
                "sha256": record_binaries["ffmpeg.exe"]["sha256"],
                "version_prefix": "   ",
            },
            "ffprobe.exe": {
                "sha256": record_binaries["ffprobe.exe"]["sha256"],
                "version_prefix": "ffprobe version 6.1.1",
            },
        }
    }
    manifest = packaging_dir / "ffmpeg_artifact_manifest.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="version_prefix"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )


def test_dry_run_skip_pyinstaller_missing_manifest_rejected(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    manifest = packaging_dir / "ffmpeg_artifact_manifest.json"
    if manifest.exists():
        manifest.unlink()
    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"dummy exe")

    # Missing manifest must fail even when skip_pyinstaller=True and dry_run=True
    with pytest.raises(FileNotFoundError, match="Artifact manifest not found"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=True,
        )


def test_manifest_rejects_uppercase_sha_without_case_folding(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"dummy exe")

    record = json.loads((fixture["build_output_dir"] / "build-record.json").read_text(encoding="utf-8"))
    record_binaries = record["outputs"]["binaries"]
    manifest_data = {
        "expected_binaries": {
            "ffmpeg.exe": {
                "sha256": record_binaries["ffmpeg.exe"]["sha256"].upper(),
                "version_prefix": "ffmpeg version 6.1.1",
            },
            "ffprobe.exe": {
                "sha256": record_binaries["ffprobe.exe"]["sha256"],
                "version_prefix": "ffprobe version 6.1.1",
            },
        }
    }
    manifest = packaging_dir / "ffmpeg_artifact_manifest.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="sha256"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=True,
        )


def test_manifest_rejects_extra_binary_key(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"dummy exe")

    record = json.loads((fixture["build_output_dir"] / "build-record.json").read_text(encoding="utf-8"))
    record_binaries = record["outputs"]["binaries"]
    manifest_data = {
        "expected_binaries": {
            "ffmpeg.exe": {
                "sha256": record_binaries["ffmpeg.exe"]["sha256"],
                "version_prefix": "ffmpeg version 6.1.1",
            },
            "ffprobe.exe": {
                "sha256": record_binaries["ffprobe.exe"]["sha256"],
                "version_prefix": "ffprobe version 6.1.1",
            },
            "unexpected.exe": {
                "sha256": "aabbccdd11223344556677889900aabbccddeeff0011223344556677889900aa",
                "version_prefix": "unexpected 1.0",
            },
        }
    }
    manifest = packaging_dir / "ffmpeg_artifact_manifest.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="expected_binaries"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=True,
        )


def test_conflict_all_three_release_assets_destination_directories_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"
    dist.mkdir(parents=True)
    release_assets_dir = dist / "release-assets"
    release_assets_dir.mkdir(parents=True)

    conflict_targets = [
        "ffmpeg-6.1.1-custom-source.zip",
        pra.APP_DIST_ZIP_NAME,
        "SHA256SUMS.txt",
    ]

    calls = []
    def mock_run(*args, **kwargs):
        calls.append(args)
        return MagicMock(returncode=0)
    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    for conflict_name in conflict_targets:
        conflict_path = release_assets_dir / conflict_name
        conflict_path.mkdir()

        try:
            # Dry run must reject with zero subprocess calls
            with pytest.raises(ValueError, match=conflict_name):
                pra.package_release_assets(
                    build_output_dir=fixture["build_output_dir"],
                    source_cache_dir=fixture["source_cache_dir"],
                    workspace_root=ws,
                    dist_dir=dist,
                    skip_pyinstaller=False,
                    dry_run=True,
                )
            assert len(calls) == 0

            # Non dry run must reject with zero subprocess calls and zero writes
            with pytest.raises(ValueError, match=conflict_name):
                pra.package_release_assets(
                    build_output_dir=fixture["build_output_dir"],
                    source_cache_dir=fixture["source_cache_dir"],
                    workspace_root=ws,
                    dist_dir=dist,
                    skip_pyinstaller=False,
                    dry_run=False,
                )
            assert len(calls) == 0
        finally:
            conflict_path.rmdir()


def test_dry_run_manifest_rejects_invalid_sha256(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"

    manifest_data = {
        "expected_binaries": {
            "ffmpeg.exe": {
                "sha256": "not-a-valid-sha",
                "version_prefix": "ffmpeg version 6.1.1",
            },
            "ffprobe.exe": {
                "sha256": "aabbccddeeff",
                "version_prefix": "ffprobe version 6.1.1",
            },
        }
    }
    manifest = packaging_dir / "ffmpeg_artifact_manifest.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="sha256"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )


def test_dry_run_manifest_rejects_omitted_binary(tmp_path: Path):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"

    record = json.loads((fixture["build_output_dir"] / "build-record.json").read_text(encoding="utf-8"))
    record_binaries = record["outputs"]["binaries"]
    manifest_data = {
        "expected_binaries": {
            "ffprobe.exe": {
                "sha256": record_binaries["ffprobe.exe"]["sha256"],
                "version_prefix": "ffprobe version 6.1.1",
            }
        }
    }
    manifest = packaging_dir / "ffmpeg_artifact_manifest.json"
    manifest.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ValueError, match="ffmpeg.exe"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )


def test_conflict_destination_directory_rejected_before_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    (packaging_dir / "build_exe.py").write_text("# dummy\n", encoding="utf-8")
    dist = ws / "dist"
    dist.mkdir(parents=True)

    # Make workspace/bin/ffmpeg.exe a directory!
    target_bin = ws / "bin"
    target_bin.mkdir(parents=True)
    conflict_ffmpeg = target_bin / "ffmpeg.exe"
    conflict_ffmpeg.mkdir()

    calls = []
    def mock_run(*args, **kwargs):
        calls.append(args)
        return MagicMock(returncode=0)
    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    # Dry-run must reject
    with pytest.raises(ValueError, match="ffmpeg.exe"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )
    assert len(calls) == 0

    # Non-dry-run must reject before any subprocess or writes
    with pytest.raises(ValueError, match="ffmpeg.exe"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=False,
        )
    assert len(calls) == 0

    # Clean up conflict_ffmpeg and make dist/FreeSimpleVideoConverter.exe a directory when skip_pyinstaller=False
    conflict_ffmpeg.rmdir()
    conflict_dist_exe = dist / "FreeSimpleVideoConverter.exe"
    conflict_dist_exe.mkdir()

    with pytest.raises(ValueError, match="FreeSimpleVideoConverter.exe"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=True,
        )
    assert len(calls) == 0

    with pytest.raises(ValueError, match="FreeSimpleVideoConverter.exe"):
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=False,
            dry_run=False,
        )
    assert len(calls) == 0


def test_promotion_double_failure_retains_backup_and_raises(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ synthetic executable")

    existing_assets = dist / "release-assets"
    existing_assets.mkdir()
    sentinel_file = existing_assets / "sentinel.txt"
    sentinel_file.write_text("critical prior release asset")

    def mock_run(cmd, **kwargs):
        class MockResult:
            returncode = 0
            if "ffmpeg" in str(cmd[0]):
                stdout = "ffmpeg version 6.1.1\n"
            else:
                stdout = "ffprobe version 6.1.1\n"
        return MockResult()
    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    # Monkeypatch rename:
    # When renaming temp_assets_dir to release_assets_dir, fail with PromotionError!
    # And then when restoring backup_dir to release_assets_dir, fail with RestoreError!
    orig_rename = Path.rename
    backup_path_holder = []

    def failing_rename(self, target):
        target_p = Path(target)
        if "release-assets-backup-" in str(target_p):
            # Backing up release_assets_dir
            backup_path_holder.append(target_p)
            return orig_rename(self, target)
        if target_p.name == "release-assets":
            if "release-assets-tmp-" in str(self):
                raise OSError("Disk failure during promotion rename")
            if "release-assets-backup-" in str(self):
                raise OSError("Permissions error during backup restoration")
        return orig_rename(self, target)

    monkeypatch.setattr(Path, "rename", failing_rename)

    with pytest.raises(RuntimeError) as exc_info:
        pra.package_release_assets(
            build_output_dir=fixture["build_output_dir"],
            source_cache_dir=fixture["source_cache_dir"],
            workspace_root=ws,
            dist_dir=dist,
            skip_pyinstaller=True,
            dry_run=False,
        )

    err_msg = str(exc_info.value)
    assert "Disk failure during promotion rename" in err_msg
    assert "Permissions error during backup restoration" in err_msg
    assert str(backup_path_holder[0]) in err_msg
    # Ensure backup directory was NOT deleted!
    assert backup_path_holder[0].exists()
    assert (backup_path_holder[0] / "sentinel.txt").read_text() == "critical prior release asset"


def test_subprocess_calls_and_pyinstaller_args(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = test_sb._make_dummy_lock_and_inputs(tmp_path)
    ws = fixture["workspace_root"]
    (ws / "README.md").write_text("# Readme\n", encoding="utf-8")
    packaging_dir = ws / "packaging"
    packaging_dir.mkdir(parents=True, exist_ok=True)
    build_exe_script = packaging_dir / "build_exe.py"
    build_exe_script.write_text("# dummy build_exe\n", encoding="utf-8")

    dist = ws / "dist"
    dist.mkdir(parents=True)
    dummy_exe = dist / "FreeSimpleVideoConverter.exe"
    dummy_exe.write_bytes(b"MZ executable")

    invocations = []

    def mock_run(cmd, **kwargs):
        invocations.append({
            "cmd": [str(c) for c in cmd],
            "cwd": kwargs.get("cwd"),
            "check": kwargs.get("check"),
        })
        # If running build_exe, write executable to dist
        if any("build_exe.py" in str(arg) for arg in cmd):
            assert kwargs.get("check") is False
            assert kwargs.get("cwd") == str(ws)
            dummy_exe.write_bytes(b"newly built executable")
            class MockResult:
                returncode = 0
                stdout = "PyInstaller success\n"
            return MockResult()

        assert kwargs.get("check") is False
        assert kwargs.get("timeout") == 15
        assert kwargs.get("text") is True
        assert kwargs.get("stdout") == subprocess.PIPE
        assert kwargs.get("stderr") == subprocess.STDOUT
        assert "creationflags" in kwargs
        class MockResult:
            returncode = 0
            if "ffmpeg" in str(cmd[0]):
                stdout = "ffmpeg version 6.1.1\n"
            else:
                stdout = "ffprobe version 6.1.1\n"
        return MockResult()

    monkeypatch.setattr(pra.subprocess, "run", mock_run)

    report = pra.package_release_assets(
        build_output_dir=fixture["build_output_dir"],
        source_cache_dir=fixture["source_cache_dir"],
        workspace_root=ws,
        dist_dir=dist,
        skip_pyinstaller=False,
        dry_run=False,
    )
    assert report["status"] == "success"

    # Exactly 3 subprocess invocations: ffmpeg -version, ffprobe -version, and python build_exe.py --dist-dir ...
    assert len(invocations) == 3
    assert invocations[0]["cmd"][1] == "-version"
    assert "ffmpeg.exe" in invocations[0]["cmd"][0]
    assert invocations[1]["cmd"][1] == "-version"
    assert "ffprobe.exe" in invocations[1]["cmd"][0]

    pyinstaller_inv = invocations[2]
    assert "build_exe.py" in pyinstaller_inv["cmd"][1]
    assert pyinstaller_inv["cmd"][2] == "--dist-dir"
    assert pyinstaller_inv["cmd"][3] == str(dist)
    assert pyinstaller_inv["cwd"] == str(ws)


def test_app_dist_zip_name_matches_released_version():
    import tomllib

    repo_root = Path(__file__).resolve().parents[2]
    with open(repo_root / "pyproject.toml", "rb") as f:
        project_version = tomllib.load(f)["project"]["version"]
    assert pra.APP_VERSION == project_version
    assert pra.APP_DIST_ZIP_NAME == f"FreeSimpleVideoConverter-v{project_version}-windows-x64.zip"
