"""Tests for packaging binary artifact identity validation."""

import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

BUILD_EXE_PATH = Path(__file__).resolve().parents[2] / "packaging" / "build_exe.py"
spec = importlib.util.spec_from_file_location("packaging_build_exe", BUILD_EXE_PATH)
build_exe_module = importlib.util.module_from_spec(spec)
sys.modules["packaging_build_exe"] = build_exe_module
spec.loader.exec_module(build_exe_module)

load_artifact_manifest = build_exe_module.load_artifact_manifest
compute_sha256 = build_exe_module.compute_sha256
get_binary_version = build_exe_module.get_binary_version
validate_binary_artifacts = build_exe_module.validate_binary_artifacts
ArtifactValidationError = build_exe_module.ArtifactValidationError



@pytest.fixture
def manifest_data():
    return {
        "artifact_name": "Gyan FFmpeg 6.1.1 Full Windows x64",
        "archive_url": "https://github.com/GyanD/codexffmpeg/releases/download/6.1.1/ffmpeg-6.1.1-full_build.7z",
        "release_page": "https://github.com/GyanD/codexffmpeg/releases/tag/6.1.1",
        "expected_binaries": {
            "ffmpeg.exe": {
                "sha256": "aabbccdd11223344556677889900aabbccddeeff0011223344556677889900aa",
                "version_prefix": "ffmpeg version 6.1.1",
            },
            "ffprobe.exe": {
                "sha256": "eeff0011223344556677889900aabbccddeeff0011223344556677889900aabb",
                "version_prefix": "ffprobe version 6.1.1",
            },
        },
    }


def test_build_rejects_output_directory_without_deleting_it(tmp_path: Path):
    custom_dist = tmp_path / "custom_dist"
    custom_dist.mkdir(parents=True)
    custom_bin = tmp_path / "bin"
    custom_bin.mkdir(parents=True)
    f_bin = custom_bin / "ffmpeg.exe"
    p_bin = custom_bin / "ffprobe.exe"
    f_bin.write_bytes(b"ffmpeg")
    p_bin.write_bytes(b"ffprobe")

    exe_suffix = ".exe" if sys.platform == "win32" else ""
    out_dir = custom_dist / f"{build_exe_module.APP_NAME}{exe_suffix}"
    out_dir.mkdir(parents=True)
    sentinel = out_dir / "preserve.txt"
    sentinel.write_text("must not be deleted")

    with patch.object(build_exe_module, "validate_binary_artifacts"), \
         patch.object(build_exe_module, "BIN_DIR", custom_bin), \
         patch.object(build_exe_module, "FFMPEG_PATH", f_bin), \
         patch.object(build_exe_module, "FFPROBE_PATH", p_bin), \
         patch.object(build_exe_module.subprocess, "run") as mock_run:

        with pytest.raises(SystemExit) as exc_info:
            build_exe_module.build(dist_dir=custom_dist)
        assert exc_info.value.code != 0

        # Subprocess must not have been run
        mock_run.assert_not_called()
        # Directory must NOT be deleted
        assert out_dir.is_dir()
        assert sentinel.read_text() == "must not be deleted"


def test_build_rejects_stale_or_corrupt_output(tmp_path: Path):
    custom_dist = tmp_path / "custom_dist"
    custom_bin = tmp_path / "bin"
    custom_bin.mkdir(parents=True)
    f_bin = custom_bin / "ffmpeg.exe"
    p_bin = custom_bin / "ffprobe.exe"
    f_bin.write_bytes(b"ffmpeg")
    p_bin.write_bytes(b"ffprobe")

    exe_suffix = ".exe" if sys.platform == "win32" else ""
    out_exe = custom_dist / f"{build_exe_module.APP_NAME}{exe_suffix}"

    # Case 1: PyInstaller succeeds but leaves out_exe empty (0 bytes)
    with patch.object(build_exe_module, "validate_binary_artifacts"), \
         patch.object(build_exe_module, "BIN_DIR", custom_bin), \
         patch.object(build_exe_module, "FFMPEG_PATH", f_bin), \
         patch.object(build_exe_module, "FFPROBE_PATH", p_bin), \
         patch.object(build_exe_module.subprocess, "run") as mock_run:

        def empty_effect(args, **kwargs):
            custom_dist.mkdir(parents=True, exist_ok=True)
            out_exe.write_bytes(b"")
            res = MagicMock()
            res.returncode = 0
            return res

        mock_run.side_effect = empty_effect
        with pytest.raises(SystemExit) as exc_info:
            build_exe_module.build(dist_dir=custom_dist)
        assert exc_info.value.code != 0

    # Case 2: Output file is a directory
    with patch.object(build_exe_module, "validate_binary_artifacts"), \
         patch.object(build_exe_module, "BIN_DIR", custom_bin), \
         patch.object(build_exe_module, "FFMPEG_PATH", f_bin), \
         patch.object(build_exe_module, "FFPROBE_PATH", p_bin), \
         patch.object(build_exe_module.subprocess, "run") as mock_run:

        def dir_effect(args, **kwargs):
            if out_exe.exists():
                out_exe.unlink()
            out_exe.mkdir(parents=True, exist_ok=True)
            res = MagicMock()
            res.returncode = 0
            return res

        mock_run.side_effect = dir_effect
        with pytest.raises(SystemExit) as exc_info:
            build_exe_module.build(dist_dir=custom_dist)
        assert exc_info.value.code != 0


def test_build_removes_stale_preexisting_output(tmp_path: Path):
    custom_dist = tmp_path / "custom_dist"
    custom_dist.mkdir(parents=True)
    custom_bin = tmp_path / "bin"
    custom_bin.mkdir(parents=True)
    f_bin = custom_bin / "ffmpeg.exe"
    p_bin = custom_bin / "ffprobe.exe"
    f_bin.write_bytes(b"ffmpeg")
    p_bin.write_bytes(b"ffprobe")

    exe_suffix = ".exe" if sys.platform == "win32" else ""
    out_exe = custom_dist / f"{build_exe_module.APP_NAME}{exe_suffix}"
    out_exe.write_bytes(b"stale binary from previous run")

    with patch.object(build_exe_module, "validate_binary_artifacts"), \
         patch.object(build_exe_module, "BIN_DIR", custom_bin), \
         patch.object(build_exe_module, "FFMPEG_PATH", f_bin), \
         patch.object(build_exe_module, "FFPROBE_PATH", p_bin), \
         patch.object(build_exe_module.subprocess, "run") as mock_run:

        def clean_effect(args, **kwargs):
            # Assert that before PyInstaller runs, stale binary was removed
            assert not out_exe.exists()
            assert kwargs.get("check") is False
            out_exe.write_bytes(b"fresh binary")
            res = MagicMock()
            res.returncode = 0
            return res

        mock_run.side_effect = clean_effect
        build_exe_module.build(dist_dir=custom_dist)
        assert out_exe.read_bytes() == b"fresh binary"


def test_build_with_custom_dist_dir(tmp_path: Path):

    custom_dist = tmp_path / "custom_dist"
    custom_bin = tmp_path / "bin"
    custom_bin.mkdir(parents=True)
    f_bin = custom_bin / "ffmpeg.exe"
    p_bin = custom_bin / "ffprobe.exe"
    f_bin.write_bytes(b"ffmpeg")
    p_bin.write_bytes(b"ffprobe")

    # Mock validate_binary_artifacts and subprocess.run
    with patch.object(build_exe_module, "validate_binary_artifacts"), \
         patch.object(build_exe_module, "BIN_DIR", custom_bin), \
         patch.object(build_exe_module, "FFMPEG_PATH", f_bin), \
         patch.object(build_exe_module, "FFPROBE_PATH", p_bin), \
         patch.object(build_exe_module.subprocess, "run") as mock_run:
        # Create output file to satisfy post-build existence check
        exe_suffix = ".exe" if sys.platform == "win32" else ""
        out_exe = custom_dist / f"{build_exe_module.APP_NAME}{exe_suffix}"

        def side_effect(args, **kwargs):
            assert kwargs.get("check") is False
            custom_dist.mkdir(parents=True, exist_ok=True)
            out_exe.write_bytes(b"dummy")
            res = MagicMock()
            res.returncode = 0
            return res

        mock_run.side_effect = side_effect

        build_exe_module.build(dist_dir=custom_dist)
        assert out_exe.is_file()
        # Verify --distpath was passed
        passed_args = mock_run.call_args[0][0]
        distpath_idx = passed_args.index("--distpath")
        assert passed_args[distpath_idx + 1] == str(custom_dist.resolve())



def test_compute_sha256(tmp_path: Path):
    test_file = tmp_path / "sample.bin"
    content = b"sample binary content"
    test_file.write_bytes(content)
    expected_hash = hashlib.sha256(content).hexdigest().lower()

    assert compute_sha256(test_file) == expected_hash


def test_get_binary_version_success():
    with patch.object(build_exe_module.subprocess, "run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="ffmpeg version 6.1.1-full_build-www.gyan.dev Copyright (c) 2000-2023\nconfiguration: ...",
            stderr="",
        )
        version = get_binary_version(Path("dummy_ffmpeg.exe"))
        assert version == "ffmpeg version 6.1.1-full_build-www.gyan.dev Copyright (c) 2000-2023"


def test_get_binary_version_failure():
    with patch.object(build_exe_module.subprocess, "run", side_effect=subprocess.SubprocessError("Failed")):
        version = get_binary_version(Path("dummy_ffmpeg.exe"))
        assert version == ""


def test_validate_binary_artifacts_success(tmp_path: Path, manifest_data):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    ffmpeg_file = bin_dir / "ffmpeg.exe"
    ffprobe_file = bin_dir / "ffprobe.exe"
    ffmpeg_file.write_bytes(b"ffmpeg binary")
    ffprobe_file.write_bytes(b"ffprobe binary")

    manifest_data["expected_binaries"]["ffmpeg.exe"]["sha256"] = compute_sha256(ffmpeg_file)
    manifest_data["expected_binaries"]["ffprobe.exe"]["sha256"] = compute_sha256(ffprobe_file)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    def mock_version(path: Path) -> str:
        if path.name == "ffmpeg.exe":
            return "ffmpeg version 6.1.1-full_build"
        return "ffprobe version 6.1.1-full_build"

    with patch.object(build_exe_module, "get_binary_version", side_effect=mock_version):
        # Should not raise
        validate_binary_artifacts(bin_dir, manifest_path)


def test_validate_binary_artifacts_missing_file(tmp_path: Path, manifest_data):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ArtifactValidationError) as exc_info:
        validate_binary_artifacts(bin_dir, manifest_path)

    assert "ffmpeg.exe" in str(exc_info.value)
    assert "not found" in str(exc_info.value).lower()


def test_validate_binary_artifacts_hash_mismatch(tmp_path: Path, manifest_data):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    ffmpeg_file = bin_dir / "ffmpeg.exe"
    ffprobe_file = bin_dir / "ffprobe.exe"
    ffmpeg_file.write_bytes(b"wrong ffmpeg")
    ffprobe_file.write_bytes(b"ffprobe binary")

    manifest_data["expected_binaries"]["ffmpeg.exe"]["sha256"] = "0000000000000000000000000000000000000000000000000000000000000000"
    manifest_data["expected_binaries"]["ffprobe.exe"]["sha256"] = compute_sha256(ffprobe_file)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    def mock_version(path: Path) -> str:
        return "ffmpeg version 6.1.1-full_build" if path.name == "ffmpeg.exe" else "ffprobe version 6.1.1-full_build"

    with patch.object(build_exe_module, "get_binary_version", side_effect=mock_version):
        with pytest.raises(ArtifactValidationError) as exc_info:
            validate_binary_artifacts(bin_dir, manifest_path)

    assert "SHA-256 mismatch for ffmpeg.exe" in str(exc_info.value)


def test_validate_binary_artifacts_version_mismatch(tmp_path: Path, manifest_data):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    ffmpeg_file = bin_dir / "ffmpeg.exe"
    ffprobe_file = bin_dir / "ffprobe.exe"
    ffmpeg_file.write_bytes(b"ffmpeg binary")
    ffprobe_file.write_bytes(b"ffprobe binary")

    manifest_data["expected_binaries"]["ffmpeg.exe"]["sha256"] = compute_sha256(ffmpeg_file)
    manifest_data["expected_binaries"]["ffprobe.exe"]["sha256"] = compute_sha256(ffprobe_file)

    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    def mock_version(path: Path) -> str:
        if path.name == "ffmpeg.exe":
            return "ffmpeg version 7.0"
        return "ffprobe version 6.1.1"

    with patch.object(build_exe_module, "get_binary_version", side_effect=mock_version):
        with pytest.raises(ArtifactValidationError) as exc_info:
            validate_binary_artifacts(bin_dir, manifest_path)

    assert "Version prefix mismatch for ffmpeg.exe" in str(exc_info.value)


def test_build_aborts_without_invoking_pyinstaller_on_validation_failure(tmp_path: Path):
    with patch.object(build_exe_module, "validate_binary_artifacts", side_effect=ArtifactValidationError("Validation failed")), \
         patch.object(build_exe_module.subprocess, "run") as mock_run:
        with pytest.raises(SystemExit) as exc_info:
            build_exe_module.build()
        assert exc_info.value.code == 1
        mock_run.assert_not_called()


def test_validate_binary_artifacts_manifest_missing_required_entry(tmp_path: Path, manifest_data):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg.exe").write_bytes(b"ffmpeg")
    (bin_dir / "ffprobe.exe").write_bytes(b"ffprobe")

    # Omit ffprobe.exe
    del manifest_data["expected_binaries"]["ffprobe.exe"]
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="ffprobe.exe"):
        validate_binary_artifacts(bin_dir, manifest_path)


def test_validate_binary_artifacts_manifest_invalid_sha256(tmp_path: Path, manifest_data):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg.exe").write_bytes(b"ffmpeg")
    (bin_dir / "ffprobe.exe").write_bytes(b"ffprobe")

    # Invalid sha256 (not 64 lowercase hex)
    manifest_data["expected_binaries"]["ffmpeg.exe"]["sha256"] = "invalid-sha"
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="sha256"):
        validate_binary_artifacts(bin_dir, manifest_path)


def test_validate_binary_artifacts_manifest_rejects_uppercase_sha(tmp_path: Path, manifest_data):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ffmpeg_file = bin_dir / "ffmpeg.exe"
    ffprobe_file = bin_dir / "ffprobe.exe"
    ffmpeg_file.write_bytes(b"ffmpeg")
    ffprobe_file.write_bytes(b"ffprobe")

    # Uppercase sha256 must be rejected based on original string without case folding
    manifest_data["expected_binaries"]["ffmpeg.exe"]["sha256"] = compute_sha256(ffmpeg_file).upper()
    manifest_data["expected_binaries"]["ffprobe.exe"]["sha256"] = compute_sha256(ffprobe_file)
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="sha256"):
        validate_binary_artifacts(bin_dir, manifest_path)


def test_validate_binary_artifacts_manifest_rejects_extra_binary_key(tmp_path: Path, manifest_data):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    ffmpeg_file = bin_dir / "ffmpeg.exe"
    ffprobe_file = bin_dir / "ffprobe.exe"
    ffmpeg_file.write_bytes(b"ffmpeg")
    ffprobe_file.write_bytes(b"ffprobe")

    manifest_data["expected_binaries"]["ffmpeg.exe"]["sha256"] = compute_sha256(ffmpeg_file)
    manifest_data["expected_binaries"]["ffprobe.exe"]["sha256"] = compute_sha256(ffprobe_file)
    manifest_data["expected_binaries"]["extra.exe"] = {
        "sha256": "aabbccdd11223344556677889900aabbccddeeff0011223344556677889900aa",
        "version_prefix": "extra version 1.0",
    }
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="expected_binaries"):
        validate_binary_artifacts(bin_dir, manifest_path)


def test_validate_binary_artifacts_manifest_missing_or_empty_version_prefix(tmp_path: Path, manifest_data):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "ffmpeg.exe").write_bytes(b"ffmpeg")
    (bin_dir / "ffprobe.exe").write_bytes(b"ffprobe")

    manifest_data["expected_binaries"]["ffmpeg.exe"]["version_prefix"] = "   "
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest_data), encoding="utf-8")

    with pytest.raises(ArtifactValidationError, match="version_prefix"):
        validate_binary_artifacts(bin_dir, manifest_path)
