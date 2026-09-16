"""Tests for packaging/ffmpeg-build/update_report_patches.py."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "packaging"
    / "ffmpeg-build"
    / "update_report_patches.py"
)


def _run_cli(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_cli_updates_report_patches_and_recipe_sha(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    patch_dir = repo_root / "packaging" / "ffmpeg-build" / "patches"
    patch_dir.mkdir(parents=True)
    patch_file = patch_dir / "test.patch"
    patch_content = b"diff --git a/foo b/foo\n+line\n"
    patch_file.write_bytes(patch_content)
    expected_patch_sha = hashlib.sha256(patch_content).hexdigest()

    patch_file2 = patch_dir / "test2.patch"
    patch_content2 = b"diff --git a/bar b/bar\n+line2\n"
    patch_file2.write_bytes(patch_content2)
    expected_patch_sha2 = hashlib.sha256(patch_content2).hexdigest()

    manifest_file = repo_root / "manifest.json"
    manifest_bytes = (
        b'{\n'
        b'  "patches": [\n'
        b'    {\n'
        b'      "name": "test-patch",\n'
        b'      "path": "packaging/ffmpeg-build/patches/test.patch"\n'
        b'    },\n'
        b'    {\n'
        b'      "name": "test-patch-2",\n'
        b'      "path": "packaging/ffmpeg-build/patches/test2.patch"\n'
        b'    }\n'
        b'  ]\n'
        b'}\n'
    )
    manifest_file.write_bytes(manifest_bytes)
    expected_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

    report_file = repo_root / "report.json"
    initial_report = {
        "recipe_sha256": "0" * 64,
        "source_evidence": {"key": "val"},
        "msys2": {"databases": []},
        "patches": [],
    }
    report_file.write_text(json.dumps(initial_report, indent=2) + "\n", encoding="utf-8")

    result = _run_cli(
        "--manifest",
        str(manifest_file),
        "--report",
        str(report_file),
        "--patch",
        "test-patch=packaging/ffmpeg-build/patches/test.patch",
        "--patch",
        "test-patch-2=packaging/ffmpeg-build/patches/test2.patch",
        cwd=repo_root,
    )

    assert result.returncode == 0, f"CLI failed: {result.stderr}"

    updated = json.loads(report_file.read_text(encoding="utf-8"))
    assert updated["recipe_sha256"] == expected_manifest_sha
    assert updated["patches"] == [
        {
            "name": "test-patch",
            "path": "packaging/ffmpeg-build/patches/test.patch",
            "sha256": expected_patch_sha,
        },
        {
            "name": "test-patch-2",
            "path": "packaging/ffmpeg-build/patches/test2.patch",
            "sha256": expected_patch_sha2,
        },
    ]
    assert updated["source_evidence"] == {"key": "val"}
    assert updated["msys2"] == {"databases": []}


def test_cli_rejects_missing_patch(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manifest_file = repo_root / "manifest.json"
    manifest_file.write_text(
        json.dumps(
            {
                "patches": [
                    {"name": "patch1", "path": "p1.patch"},
                    {"name": "patch2", "path": "p2.patch"},
                ]
            }
        ),
        encoding="utf-8",
    )
    report_file = repo_root / "report.json"
    report_file.write_text(json.dumps({"patches": []}), encoding="utf-8")
    (repo_root / "p1.patch").write_text("patch1", encoding="utf-8")

    result = _run_cli(
        "--manifest",
        str(manifest_file),
        "--report",
        str(report_file),
        "--patch",
        "patch1=p1.patch",
        cwd=repo_root,
    )
    assert result.returncode != 0
    assert "Missing patch definitions for: ['patch2']" in result.stderr


def test_cli_rejects_undeclared_patch(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manifest_file = repo_root / "manifest.json"
    manifest_file.write_text(json.dumps({"patches": []}), encoding="utf-8")
    report_file = repo_root / "report.json"
    report_file.write_text(json.dumps({"patches": []}), encoding="utf-8")
    (repo_root / "p1.patch").write_text("patch1", encoding="utf-8")

    result = _run_cli(
        "--manifest",
        str(manifest_file),
        "--report",
        str(report_file),
        "--patch",
        "patch1=p1.patch",
        cwd=repo_root,
    )
    assert result.returncode != 0
    assert "Patch 'patch1' not declared in manifest" in result.stderr


def test_cli_rejects_path_mismatch(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manifest_file = repo_root / "manifest.json"
    manifest_file.write_text(
        json.dumps({"patches": [{"name": "patch1", "path": "declared.patch"}]}),
        encoding="utf-8",
    )
    report_file = repo_root / "report.json"
    report_file.write_text(json.dumps({"patches": []}), encoding="utf-8")
    (repo_root / "other.patch").write_text("other", encoding="utf-8")

    result = _run_cli(
        "--manifest",
        str(manifest_file),
        "--report",
        str(report_file),
        "--patch",
        "patch1=other.patch",
        cwd=repo_root,
    )
    assert result.returncode != 0
    assert "Patch path mismatch for 'patch1'" in result.stderr


def test_cli_rejects_traversal_and_absolute_paths(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    outside_patch = tmp_path / "outside.patch"
    outside_patch.write_text("outside", encoding="utf-8")

    manifest_file = repo_root / "manifest.json"
    manifest_file.write_text(
        json.dumps({"patches": [{"name": "patch1", "path": "../outside.patch"}]}),
        encoding="utf-8",
    )
    report_file = repo_root / "report.json"
    report_file.write_text(json.dumps({"patches": []}), encoding="utf-8")

    result = _run_cli(
        "--manifest",
        str(manifest_file),
        "--report",
        str(report_file),
        "--patch",
        "patch1=../outside.patch",
        cwd=repo_root,
    )
    assert result.returncode != 0
    assert "Path traversal detected" in result.stderr

    # Test absolute path
    abs_path_str = str(outside_patch)
    manifest_file.write_text(
        json.dumps({"patches": [{"name": "patch1", "path": abs_path_str}]}),
        encoding="utf-8",
    )
    result_abs = _run_cli(
        "--manifest",
        str(manifest_file),
        "--report",
        str(report_file),
        "--patch",
        f"patch1={abs_path_str}",
        cwd=repo_root,
    )
    assert result_abs.returncode != 0
    assert "relative to repository root" in result_abs.stderr


def test_cli_rejects_non_regular_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    sub_dir = repo_root / "some_dir"
    sub_dir.mkdir()

    manifest_file = repo_root / "manifest.json"
    manifest_file.write_text(
        json.dumps({"patches": [{"name": "patch1", "path": "some_dir"}]}),
        encoding="utf-8",
    )
    report_file = repo_root / "report.json"
    report_file.write_text(json.dumps({"patches": []}), encoding="utf-8")

    result = _run_cli(
        "--manifest",
        str(manifest_file),
        "--report",
        str(report_file),
        "--patch",
        "patch1=some_dir",
        cwd=repo_root,
    )
    assert result.returncode != 0
    assert "does not exist or is not a regular file" in result.stderr


def test_cli_rejects_duplicate_cli_patches(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    manifest_file = repo_root / "manifest.json"
    manifest_file.write_text(
        json.dumps({"patches": [{"name": "patch1", "path": "p1.patch"}]}),
        encoding="utf-8",
    )
    report_file = repo_root / "report.json"
    report_file.write_text(json.dumps({"patches": []}), encoding="utf-8")
    (repo_root / "p1.patch").write_text("p1", encoding="utf-8")

    result = _run_cli(
        "--manifest",
        str(manifest_file),
        "--report",
        str(report_file),
        "--patch",
        "patch1=p1.patch",
        "--patch",
        "patch1=p1.patch",
        cwd=repo_root,
    )
    assert result.returncode != 0
    assert "Duplicate patch specified in arguments: patch1" in result.stderr


def test_cli_rejects_whitespace_normalized_patch_identity(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "p1.patch").write_text("patch1", encoding="utf-8")
    manifest_file = repo_root / "manifest.json"
    manifest_file.write_text(
        json.dumps({"patches": [{"name": "patch1", "path": "p1.patch"}]}),
        encoding="utf-8",
    )
    report_file = repo_root / "report.json"
    report_file.write_text(json.dumps({"patches": []}), encoding="utf-8")

    result = _run_cli(
        "--manifest", str(manifest_file), "--report", str(report_file),
        "--patch", " patch1=p1.patch ", cwd=repo_root,
    )

    assert result.returncode != 0
    assert "not declared" in result.stderr


def test_cli_rejects_symlink_patch_file(tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target = repo_root / "target.patch"
    target.write_text("patch", encoding="utf-8")
    link = repo_root / "linked.patch"
    try:
        link.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    manifest_file = repo_root / "manifest.json"
    manifest_file.write_text(
        json.dumps({"patches": [{"name": "patch1", "path": "linked.patch"}]}),
        encoding="utf-8",
    )
    report_file = repo_root / "report.json"
    report_file.write_text(json.dumps({"patches": []}), encoding="utf-8")

    result = _run_cli(
        "--manifest", str(manifest_file), "--report", str(report_file),
        "--patch", "patch1=linked.patch", cwd=repo_root,
    )

    assert result.returncode != 0
    assert "symbolic link" in result.stderr
