"""Tests for isolated Git capture and canonical archive cache promotion."""
from __future__ import annotations
from collections.abc import Callable
import concurrent.futures
import hashlib
import json
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
from typing import Any, Sequence
import pytest
from video_converter.ffmpeg_build.git_capture import capture_git_sources
def _load_cli_main():
    cli_path = Path(__file__).resolve().parent.parent.parent / "packaging" / "ffmpeg-build" / "capture_git_sources.py"
    spec = importlib.util.spec_from_file_location("capture_git_sources_cli", cli_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main



MANIFEST_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "packaging"
    / "ffmpeg-build"
    / "acquisition-manifest.json"
)


def _make_manifest() -> dict[str, Any]:
    with MANIFEST_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)
    # Set all git remotes to https://example.invalid/<name>.git
    for s in data["sources"]:
        if s.get("acquisition_type") == "commit_archive":
            s["git_remote_url"] = f"https://example.invalid/{s['name']}.git"
    return data


class FakeGitRunner:
    """Offline fake command runner that simulates Git commands and creates expected files."""

    def __init__(
        self,
        *,
        git_version: str = "git version 2.45.0",
        remote_url: str | None = None,
        rev_parse_commit: str | None = None,
        cat_file_type: str = "commit",
        archive_bytes: bytes = b"fake-tar-gz-archive-bytes-x264",
        bundle_bytes: bytes = b"fake-git-bundle-bytes-x264",
        fail_command: str | None = None,
    ) -> None:
        self.git_version = git_version
        self.remote_url = remote_url
        self.rev_parse_commit = rev_parse_commit
        self.cat_file_type = cat_file_type
        self.archive_bytes = archive_bytes
        self.bundle_bytes = bundle_bytes
        self.fail_command = fail_command
        self.recorded_commands: list[Sequence[str]] = []

    def __call__(
        self, cmd: Sequence[str], work_dir: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        self.recorded_commands.append(list(cmd))

        if self.fail_command and any(self.fail_command in arg for arg in cmd):
            raise subprocess.CalledProcessError(1, list(cmd), output="", stderr=f"Simulated failure for {self.fail_command}")

        cmd_list = list(cmd)
        if cmd_list == ["git", "--version"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=self.git_version, stderr="")

        if len(cmd_list) >= 3 and cmd_list[0] == "git" and cmd_list[1] == "init" and cmd_list[2] == "--bare":
            # repo created
            if work_dir:
                repo_dir = work_dir / cmd_list[3]
                repo_dir.mkdir(parents=True, exist_ok=True)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if "remote" in cmd_list and "get-url" in cmd_list:
            if self.remote_url is not None:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{self.remote_url}\n", stderr="")
            # infer from repo or return match
            repo_arg = cmd_list[2]
            name = Path(repo_arg).name.removesuffix(".git")
            return subprocess.CompletedProcess(cmd, 0, stdout=f"https://example.invalid/{name}.git\n", stderr="")

        if "rev-parse" in cmd_list:
            if self.rev_parse_commit is not None:
                return subprocess.CompletedProcess(cmd, 0, stdout=f"{self.rev_parse_commit}\n", stderr="")
            # echo back commit
            target = cmd_list[-1].split("^")[0]
            if target.startswith("refs/"):
                commit = target.rsplit("/", 1)[-1]
            else:
                commit = target
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{commit}\n", stderr="")

        if "cat-file" in cmd_list and "-t" in cmd_list:
            return subprocess.CompletedProcess(cmd, 0, stdout=f"{self.cat_file_type}\n", stderr="")

        if "archive" in cmd_list:
            # Handle stdout or output file if provided
            for idx, arg in enumerate(cmd_list):
                if arg.startswith("--output="):
                    out_path = Path(arg.split("=", 1)[1])
                    out_path.write_bytes(self.archive_bytes)
                elif arg == "-o" and idx + 1 < len(cmd_list):
                    out_path = Path(cmd_list[idx + 1])
                    out_path.write_bytes(self.archive_bytes)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if "bundle" in cmd_list and "verify" in cmd_list:
            bundle_idx = cmd_list.index("verify") + 1
            bundle_path = Path(cmd_list[bundle_idx])
            content = bundle_path.read_bytes()
            if b"corrupt" in content or b"bad" in content:
                raise subprocess.CalledProcessError(1, list(cmd), output="", stderr="fatal: bundle verify failed")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        if "bundle" in cmd_list and "create" in cmd_list:
            bundle_idx = cmd_list.index("create") + 1
            bundle_path = Path(cmd_list[bundle_idx])
            bundle_path.parent.mkdir(parents=True, exist_ok=True)
            bundle_path.write_bytes(self.bundle_bytes)
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")


def test_git_capture_success_contract(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner()

    evidence = capture_git_sources(manifest, cache_dir, retention_dir, runner)

    git_src = next(s for s in manifest["sources"] if s.get("acquisition_type") == "commit_archive" and s["name"] == "x264")
    commit = git_src["commit"]
    expected_archive_sha = hashlib.sha256(runner.archive_bytes).hexdigest()
    expected_bundle_sha = hashlib.sha256(runner.bundle_bytes).hexdigest()

    assert "x264" in evidence
    rec = evidence["x264"]
    assert rec["type"] == "commit_archive"
    assert rec["verified"] is True
    assert rec["artifact_sha256"] == expected_archive_sha
    assert rec["commit"] == commit
    assert rec["verifier"] == "git-rev-parse-and-archive"
    assert rec["remote_url"] == "https://example.invalid/x264.git"
    assert rec["archive_command"].endswith(commit)
    assert rec["archive_command"].startswith("git ")
    assert rec["git_version"] == "git version 2.45.0"
    assert rec["git_bundle_sha256"] == expected_bundle_sha
    assert rec["bundle_retention_uri"] == f"project://ffmpeg-build/git/x264/{commit}.bundle"
    assert rec["canonical_archive_retention_uri"] == f"project://ffmpeg-build/git/x264/{commit}.tar.gz"

    # Verify cached artifact promoted
    cached_artifact = cache_dir / expected_archive_sha
    assert cached_artifact.is_file()
    assert cached_artifact.read_bytes() == runner.archive_bytes

    # Verify no command contains ^{commit}
    for recorded in runner.recorded_commands:
        for arg in recorded:
            assert "^{commit}" not in arg, f"Command contains ^{{commit}}: {recorded}"

    # Verify rev-parse and cat-file commands recorded brace-free
    expected_commits = {
        s["commit"]
        for s in manifest["sources"]
        if s.get("acquisition_type") == "commit_archive"
    }
    rev_parse_cmds = [cmd for cmd in runner.recorded_commands if "rev-parse" in cmd]
    assert rev_parse_cmds, "Expected rev-parse command to be run"
    for rcmd in rev_parse_cmds:
        assert rcmd[-1] in expected_commits, f"rev-parse should take exact manifest commit ID without braces: {rcmd}"

    cat_file_cmds = [cmd for cmd in runner.recorded_commands if "cat-file" in cmd and "-t" in cmd]
    assert cat_file_cmds, "Expected cat-file -t command to be run"
    for ccmd in cat_file_cmds:
        assert ccmd[-1] in expected_commits, f"cat-file -t should take exact manifest commit ID without braces: {ccmd}"

    source_lock_ref = f"refs/source-lock/x264/{commit}"
    assert any(
        "update-ref" in command and source_lock_ref in command
        for command in runner.recorded_commands
    )
    assert any(
        "bundle" in command and "create" in command and command[-1] == source_lock_ref
        for command in runner.recorded_commands
    )
    assert not any(
        "refs/bundle-staging/" in argument
        for command in runner.recorded_commands
        for argument in command
    )

    # Verify retention files created
    bundle_file = retention_dir / "git" / "x264" / f"{commit}.bundle"
    assert bundle_file.is_file()
    assert bundle_file.read_bytes() == runner.bundle_bytes

    retention_archive = retention_dir / "git" / "x264" / f"{commit}.tar.gz"
    assert retention_archive.is_file()
    assert retention_archive.read_bytes() == runner.archive_bytes


def test_git_capture_nonzero_fetch_fails(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner(fail_command="fetch")

    with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)


def test_git_capture_rev_parse_commit_mismatch_fails(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner(rev_parse_commit="e" * 40)

    with pytest.raises(ValueError, match="Commit mismatch"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)


def test_git_capture_cat_file_blob_type_fails(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner(cat_file_type="blob")

    with pytest.raises(ValueError, match="Commit object type mismatch|Expected 'commit'"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)


def test_git_capture_cat_file_nonzero_fails(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner(fail_command="cat-file")

    with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)


def test_git_capture_remote_mismatch_fails(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner(remote_url="https://example.invalid/other.git")

    with pytest.raises(ValueError, match="Remote mismatch"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)


def test_git_capture_archive_failure_fails(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner(fail_command="archive")

    with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)


def test_git_capture_corrupt_existing_cache_object_rejected(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner()

    archive_sha = hashlib.sha256(runner.archive_bytes).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    # Put corrupt content at destination sha
    (cache_dir / archive_sha).write_bytes(b"corrupt-data-differing-hash")

    with pytest.raises(ValueError, match="Cache entry.*corrupt|hash mismatch"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)


def test_git_capture_existing_identical_cache_object_accepted(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner()

    archive_sha = hashlib.sha256(runner.archive_bytes).hexdigest()
    cache_dir.mkdir(parents=True, exist_ok=True)
    (cache_dir / archive_sha).write_bytes(runner.archive_bytes)

    evidence = capture_git_sources(manifest, cache_dir, retention_dir, runner)
    assert evidence["x264"]["artifact_sha256"] == archive_sha
    assert (cache_dir / archive_sha).read_bytes() == runner.archive_bytes


def test_capture_git_sources_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = _make_manifest()
    manifest_path = tmp_path / "acquisition-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    output_path = tmp_path / "git-evidence.json"

    runner = FakeGitRunner()
    monkeypatch.setattr("video_converter.ffmpeg_build.git_capture.default_runner", runner)

    # CLI args: --manifest --cache-dir --retention-dir --output
    cli_main = _load_cli_main()
    cli_main(
        [
            "--manifest", str(manifest_path),
            "--cache-dir", str(cache_dir),
            "--retention-dir", str(retention_dir),
            "--output", str(output_path),
        ],
        runner=runner,
    )

    assert output_path.is_file()
    data = json.loads(output_path.read_text(encoding="utf-8"))
    assert "x264" in data
    assert data["x264"]["verified"] is True
    assert (cache_dir / data["x264"]["artifact_sha256"]).is_file()


def test_git_capture_nonzero_fetch_returns_process_fails_closed(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    # Runner returns returncode 1 for fetch without raising CalledProcessError
    class ReturnNonzeroRunner(FakeGitRunner):
        def __call__(self, cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
            self.recorded_commands.append(list(cmd))
            if "fetch" in cmd:
                return subprocess.CompletedProcess(list(cmd), 1, stdout="", stderr="fatal: remote error")
            return super().__call__(cmd, work_dir)

    runner = ReturnNonzeroRunner()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        capture_git_sources(manifest, cache_dir, retention_dir, runner)
    assert exc_info.value.returncode == 1
    assert "fatal: remote error" in (exc_info.value.stderr or "")


def test_git_capture_nonzero_archive_returns_process_fails_closed(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    class ReturnNonzeroArchiveRunner(FakeGitRunner):
        def __call__(self, cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
            self.recorded_commands.append(list(cmd))
            if "archive" in cmd:
                return subprocess.CompletedProcess(list(cmd), 2, stdout="", stderr="fatal: archive creation failed")
            return super().__call__(cmd, work_dir)

    runner = ReturnNonzeroArchiveRunner()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        capture_git_sources(manifest, cache_dir, retention_dir, runner)
    assert exc_info.value.returncode == 2
    assert "fatal: archive creation failed" in (exc_info.value.stderr or "")


def test_git_capture_nonzero_bundle_returns_process_fails_closed(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    class ReturnNonzeroBundleRunner(FakeGitRunner):
        def __call__(self, cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
            self.recorded_commands.append(list(cmd))
            if "bundle" in cmd:
                return subprocess.CompletedProcess(list(cmd), 128, stdout="", stderr="fatal: bundle failed")
            return super().__call__(cmd, work_dir)

    runner = ReturnNonzeroBundleRunner()
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        capture_git_sources(manifest, cache_dir, retention_dir, runner)
    assert exc_info.value.returncode == 128
    assert "fatal: bundle failed" in (exc_info.value.stderr or "")


def test_atomic_temp_cleanup_preserves_unrelated_temp_files(tmp_path: Path) -> None:
    manifest = _make_manifest()
    manifest_path = tmp_path / "acquisition-manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    output_path = tmp_path / "git-evidence.json"

    # Pre-create unrelated temp files in cache_dir and output_path.parent
    cache_dir.mkdir(parents=True, exist_ok=True)
    unrelated_cache_tmp = cache_dir / ".tmp.unrelated_cache_temp"
    unrelated_cache_tmp.write_text("unrelated-cache-data", encoding="utf-8")

    unrelated_output_tmp = output_path.parent / ".tmp.unrelated_output_temp"
    unrelated_output_tmp.write_text("unrelated-output-data", encoding="utf-8")

    runner = FakeGitRunner()
    cli_main = _load_cli_main()
    cli_main(
        [
            "--manifest", str(manifest_path),
            "--cache-dir", str(cache_dir),
            "--retention-dir", str(retention_dir),
            "--output", str(output_path),
        ],
        runner=runner,
    )

    assert unrelated_cache_tmp.is_file()
    assert unrelated_cache_tmp.read_text(encoding="utf-8") == "unrelated-cache-data"
    assert unrelated_output_tmp.is_file()
    assert unrelated_output_tmp.read_text(encoding="utf-8") == "unrelated-output-data"


def test_git_capture_corrupt_existing_retention_bundle_fails_closed(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner()

    git_src = next(s for s in manifest["sources"] if s.get("acquisition_type") == "commit_archive" and s["name"] == "x264")
    commit = git_src["commit"]
    archive_sha = hashlib.sha256(runner.archive_bytes).hexdigest()

    # Pre-populate corrupt retention bundle
    retention_bundle_path = retention_dir / "git" / "x264" / f"{commit}.bundle"
    retention_bundle_path.parent.mkdir(parents=True, exist_ok=True)
    retention_bundle_path.write_bytes(b"corrupted-bundle-bytes")

    with pytest.raises(ValueError, match="Retention.*corrupt|hash mismatch|bundle"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)

    # Cache entry must NOT be promoted when retention publication fails
    assert not (cache_dir / archive_sha).exists()


def test_git_capture_corrupt_existing_retention_archive_fails_closed(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner()

    git_src = next(s for s in manifest["sources"] if s.get("acquisition_type") == "commit_archive" and s["name"] == "x264")
    commit = git_src["commit"]
    archive_sha = hashlib.sha256(runner.archive_bytes).hexdigest()

    # Pre-populate corrupt retention archive
    retention_archive_path = retention_dir / "git" / "x264" / f"{commit}.tar.gz"
    retention_archive_path.parent.mkdir(parents=True, exist_ok=True)
    retention_archive_path.write_bytes(b"corrupted-archive-bytes")

    with pytest.raises(ValueError, match="Retention.*corrupt|hash mismatch|archive"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)

    # Cache entry must NOT be promoted when retention publication fails
    assert not (cache_dir / archive_sha).exists()


def test_git_capture_bundle_creation_failure_leaves_cache_untouched(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner(fail_command="bundle")

    archive_sha = hashlib.sha256(runner.archive_bytes).hexdigest()

    with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)

    # Cache entry must NOT be promoted if bundle creation fails
    assert not (cache_dir / archive_sha).exists()


def test_git_capture_existing_identical_retention_artifacts_accepted(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    runner = FakeGitRunner()

    git_src = next(s for s in manifest["sources"] if s.get("acquisition_type") == "commit_archive" and s["name"] == "x264")
    commit = git_src["commit"]

    # Pre-populate identical retention artifacts
    retention_git_dir = retention_dir / "git" / "x264"
    retention_git_dir.mkdir(parents=True, exist_ok=True)
    (retention_git_dir / f"{commit}.bundle").write_bytes(runner.bundle_bytes)
    (retention_git_dir / f"{commit}.tar.gz").write_bytes(runner.archive_bytes)

    evidence = capture_git_sources(manifest, cache_dir, retention_dir, runner)
    assert "x264" in evidence
    assert (retention_git_dir / f"{commit}.bundle").read_bytes() == runner.bundle_bytes
    assert (retention_git_dir / f"{commit}.tar.gz").read_bytes() == runner.archive_bytes


def test_capture_git_sources_cli_rejects_duplicate_manifest_keys(tmp_path: Path):
    main_func = _load_cli_main()
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text(
        '{"schema_version": "1.0.0", "schema_version": "1.0.0"}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON object member: schema_version"):
        main_func([
            "--manifest", str(bad_manifest),
            "--cache-dir", str(tmp_path / "cache"),
            "--retention-dir", str(tmp_path / "retention"),
            "--output", str(tmp_path / "out.json"),
        ])


def test_capture_git_sources_cli_rejects_nested_duplicate_manifest_keys(tmp_path: Path):
    main_func = _load_cli_main()
    bad_manifest = tmp_path / "bad_manifest.json"
    bad_manifest.write_text(
        '{"schema_version": "1.0.0", "sources": [{"name": "x264", "name": "x264"}]}',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="duplicate JSON object member: name"):
        main_func([
            "--manifest", str(bad_manifest),
            "--cache-dir", str(tmp_path / "cache"),
            "--retention-dir", str(tmp_path / "retention"),
            "--output", str(tmp_path / "out.json"),
        ])



def test_publish_atomic_create_if_absent_concurrent_conflicting_winner_fails(tmp_path: Path) -> None:
    from video_converter.ffmpeg_build.git_capture import _publish_atomic_create_if_absent

    staging = tmp_path / "staging"
    staging.write_bytes(b"our-content")
    target = tmp_path / "target"
    expected_sha = hashlib.sha256(b"our-content").hexdigest()

    # Pre-existing conflicting target (winner of race with different content)
    target.write_bytes(b"conflicting-content")
    with pytest.raises(ValueError, match="already exists.*corrupt|unexpected|mismatch"):
        _publish_atomic_create_if_absent(staging, target, expected_sha, "test-artifact")

    # Target must NOT be overwritten or unlinked
    assert target.read_bytes() == b"conflicting-content"


def test_publish_atomic_create_if_absent_concurrent_identical_winner_accepted(tmp_path: Path) -> None:
    from video_converter.ffmpeg_build.git_capture import _publish_atomic_create_if_absent

    staging = tmp_path / "staging"
    staging.write_bytes(b"our-content")
    target = tmp_path / "target"
    expected_sha = hashlib.sha256(b"our-content").hexdigest()

    # Pre-existing identical target
    target.write_bytes(b"our-content")
    _publish_atomic_create_if_absent(staging, target, expected_sha, "test-artifact")
    assert target.read_bytes() == b"our-content"


def test_publish_atomic_create_if_absent_race_loss_conflicting_winner_leaves_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from video_converter.ffmpeg_build.git_capture import _publish_atomic_create_if_absent

    staging = tmp_path / "staging"
    staging.write_bytes(b"our-content")
    target = tmp_path / "target"
    expected_sha = hashlib.sha256(b"our-content").hexdigest()

    # Simulate race: target doesn't exist at first, but os.link fails because competitor created it right before link
    orig_link = os.link

    def race_link(src: Any, dst: Any) -> None:
        target.write_bytes(b"competitor-conflicting-content")
        raise FileExistsError("File already exists")

    monkeypatch.setattr(os, "link", race_link)

    with pytest.raises(ValueError, match="corrupt|unexpected|mismatch"):
        _publish_atomic_create_if_absent(staging, target, expected_sha, "test-artifact")

    # Conflicting winner target must NOT be deleted or overwritten
    assert target.is_file()
    assert target.read_bytes() == b"competitor-conflicting-content"


def test_publish_atomic_create_if_absent_race_loss_identical_winner_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from video_converter.ffmpeg_build.git_capture import _publish_atomic_create_if_absent

    staging = tmp_path / "staging"
    staging.write_bytes(b"our-content")
    target = tmp_path / "target"
    expected_sha = hashlib.sha256(b"our-content").hexdigest()

    def race_link(src: Any, dst: Any) -> None:
        target.write_bytes(b"our-content")
        raise FileExistsError("File already exists")

    monkeypatch.setattr(os, "link", race_link)

    _publish_atomic_create_if_absent(staging, target, expected_sha, "test-artifact")
    assert target.is_file()
    assert target.read_bytes() == b"our-content"


def test_publish_atomic_create_if_absent_unsupported_link_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from video_converter.ffmpeg_build.git_capture import _publish_atomic_create_if_absent

    staging = tmp_path / "staging"
    staging.write_bytes(b"our-content")
    target = tmp_path / "target"
    expected_sha = hashlib.sha256(b"our-content").hexdigest()

    def failing_link(src: Any, dst: Any) -> None:
        raise OSError(1, "Operation not permitted")

    monkeypatch.setattr(os, "link", failing_link)

    with pytest.raises(OSError, match="Operation not permitted"):
        _publish_atomic_create_if_absent(staging, target, expected_sha, "test-artifact")

    assert not target.exists()


def test_publish_atomic_create_if_absent_staging_digest_mismatch_before_link(tmp_path: Path) -> None:
    from video_converter.ffmpeg_build.git_capture import _publish_atomic_create_if_absent

    staging = tmp_path / "staging"
    staging.write_bytes(b"corrupt-staging-content")
    target = tmp_path / "target"
    expected_sha = hashlib.sha256(b"expected-content").hexdigest()

    with pytest.raises(ValueError, match="corrupt|staging|digest|validation"):
        _publish_atomic_create_if_absent(staging, target, expected_sha, "test-artifact")

    assert not target.exists()


def test_publish_atomic_create_if_absent_post_link_rehash_mismatch_leaves_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from video_converter.ffmpeg_build.git_capture import _publish_atomic_create_if_absent

    staging = tmp_path / "staging"
    staging.write_bytes(b"our-content")
    target = tmp_path / "target"
    expected_sha = hashlib.sha256(b"our-content").hexdigest()

    orig_compute = hashlib.sha256

    # When computing sha after link, pretend target is corrupted or post-publication validation fails
    call_count = 0
    from video_converter.ffmpeg_build import git_capture

    orig_compute_sha = git_capture._compute_sha256

    def mocked_compute_sha(path: Path) -> str:
        nonlocal call_count
        call_count += 1
        if call_count > 1 and path == target:
            return "tampered_sha"
        return orig_compute_sha(path)

    monkeypatch.setattr(git_capture, "_compute_sha256", mocked_compute_sha)

    with pytest.raises(ValueError, match="tampered_sha|failed post"):
        _publish_atomic_create_if_absent(staging, target, expected_sha, "test-artifact")

    # Target must NOT be unlinked! Never unlink target
    assert target.is_file()
    assert target.read_bytes() == b"our-content"


def test_publish_atomic_create_if_absent_threads_barrier_race(tmp_path: Path) -> None:
    from video_converter.ffmpeg_build.git_capture import _publish_atomic_create_if_absent

    target = tmp_path / "shared_target"
    content = b"identical-multithread-content"
    expected_sha = hashlib.sha256(content).hexdigest()

    num_threads = 8
    barrier = threading.Barrier(num_threads)
    stagings = [tmp_path / f"staging_{i}" for i in range(num_threads)]
    for s in stagings:
        s.write_bytes(content)

    errors: list[Exception] = []

    def worker(idx: int) -> None:
        try:
            barrier.wait(timeout=5)
            _publish_atomic_create_if_absent(stagings[idx], target, expected_sha, "test-concurrent")
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert target.is_file()
    assert target.read_bytes() == content


def test_retention_and_atomic_promote_wrappers_delegate_to_helper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from video_converter.ffmpeg_build import git_capture

    calls: list[dict[str, Any]] = []

    def mock_helper(staging_file: Path, target_file: Path, expected_sha256: str, artifact_description: str) -> None:
        calls.append({
            "staging_file": staging_file,
            "target_file": target_file,
            "expected_sha256": expected_sha256,
            "artifact_description": artifact_description,
        })

    monkeypatch.setattr(git_capture, "_publish_atomic_create_if_absent", mock_helper)

    staging = tmp_path / "src"
    target = tmp_path / "dst"

    git_capture._publish_retention_artifact(staging, target, "dummy_hash", "bundle")
    assert len(calls) == 1
    assert calls[0]["artifact_description"] == "Retention bundle"
    assert calls[0]["staging_file"] == staging
    assert calls[0]["target_file"] == target
    assert calls[0]["expected_sha256"] == "dummy_hash"

    git_capture._atomic_promote(staging, target, "dummy_hash")
    assert len(calls) == 2
    assert calls[1]["artifact_description"] == "Cache entry"
    assert calls[1]["staging_file"] == staging
    assert calls[1]["target_file"] == target
    assert calls[1]["expected_sha256"] == "dummy_hash"


def test_detached_commit_git_bundle_real_bare_repo(tmp_path: Path) -> None:
    """Proves raw SHA git bundle create fails on detached commit, but capture_git_sources succeeds

    by creating a temporary ref, producing a verifiable bundle, and removing the temporary ref.
    """
    upstream_dir = tmp_path / "upstream"
    upstream_dir.mkdir(parents=True, exist_ok=True)

    # Initialize upstream git repo and commit a file
    subprocess.run(["git", "init"], cwd=upstream_dir, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.name", "Test Runner"], cwd=upstream_dir, check=True)
    subprocess.run(["git", "config", "user.email", "runner@example.com"], cwd=upstream_dir, check=True)
    (upstream_dir / "sample.txt").write_text("hello detached commit", encoding="utf-8")
    subprocess.run(["git", "add", "sample.txt"], cwd=upstream_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=upstream_dir, check=True, capture_output=True)

    rev_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=upstream_dir, check=True, capture_output=True, text=True)
    commit_sha = rev_proc.stdout.strip()

    # Create another local bare clone representing the fetched state in a capture runner
    test_bare = tmp_path / "test_bare.git"
    subprocess.run(["git", "init", "--bare", str(test_bare)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(test_bare), "fetch", "--no-tags", str(upstream_dir), commit_sha], check=True, capture_output=True)

    # 1. Proves raw SHA git bundle create fails
    raw_bundle_path = tmp_path / "raw_fail.bundle"
    raw_proc = subprocess.run(
        ["git", "-C", str(test_bare), "bundle", "create", str(raw_bundle_path), commit_sha],
        capture_output=True,
        text=True,
    )
    assert raw_proc.returncode != 0
    assert not raw_bundle_path.exists()

    # 2. Build manifest targeting this commit from upstream_dir using _make_manifest helper
    # Build manifest with only x264 as commit_archive
    manifest = _make_manifest()
    fake_https_x264 = "https://example.invalid/x264.git"
    git_src = next(s for s in manifest["sources"] if s.get("acquisition_type") == "commit_archive" and s["name"] == "x264")
    git_src["commit"] = commit_sha
    git_src["git_remote_url"] = fake_https_x264
    # Filter manifest["sources"] to only include x264
    manifest["sources"] = [git_src]

    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    def real_git_runner(cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
        cmd_list = list(cmd)
        # Only inject insteadOf for fetch command to avoid affecting get-url
        if cmd_list and cmd_list[0] == "git":
            if "fetch" in cmd_list:
                cmd_list = [
                    "git",
                    "-c", f"url.{upstream_dir.as_uri()}.insteadOf={fake_https_x264}",
                ] + cmd_list[1:]
        return subprocess.run(
            cmd_list,
            cwd=work_dir,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    # Monkeypatch validate_acquisition_manifest to allow our single-source manifest
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    try:
        evidence = capture_git_sources(manifest, cache_dir, retention_dir, runner=real_git_runner)
    finally:
        monkeypatch.undo()
    assert "x264" in evidence
    rec = evidence["x264"]
    assert rec["commit"] == commit_sha

    # Verify bundle was created and is verifiable
    bundle_file = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    assert bundle_file.is_file()

    verify_proc = subprocess.run(
        ["git", "bundle", "verify", str(bundle_file)],
        capture_output=True,
        text=True,
    )
    assert verify_proc.returncode == 0


def test_temporary_ref_deleted_even_on_bundle_failure(tmp_path: Path) -> None:
    manifest = _make_manifest()
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    # When fail_command is "bundle create", it fails on bundle create. But if update-ref -d doesn't match fail_command, it runs.
    runner = FakeGitRunner(fail_command="create")

    with pytest.raises((subprocess.CalledProcessError, RuntimeError)):
        capture_git_sources(manifest, cache_dir, retention_dir, runner)

    # Check that update-ref with -d was invoked for the temporary ref
    ref_created = any("update-ref" in cmd and "refs/source-lock/" in " ".join(cmd) and "-d" not in cmd for cmd in runner.recorded_commands)
    ref_deleted = any("update-ref" in cmd and "-d" in cmd and "refs/source-lock/" in " ".join(cmd) for cmd in runner.recorded_commands)
    assert ref_created is True
    assert ref_deleted is True


def test_real_bare_repo_proves_raw_sha_fails_and_temp_ref_removed(tmp_path: Path) -> None:
    """Explicitly verify on a real bare Git repo that raw SHA bundle create fails,

    and that after creating a temporary ref and bundling, deleting the ref leaves no temporary ref behind.
    """
    repo_bare = tmp_path / "bare.git"
    subprocess.run(["git", "init", "--bare", str(repo_bare)], check=True, capture_output=True)

    work_dir = tmp_path / "work"
    subprocess.run(["git", "init", str(work_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=work_dir, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=work_dir, check=True)
    (work_dir / "f.txt").write_text("content", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=work_dir, check=True)
    subprocess.run(["git", "commit", "-m", "detached test commit"], cwd=work_dir, check=True, capture_output=True)
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work_dir, check=True, capture_output=True, text=True).stdout.strip()

    # Fetch into repo_bare
    subprocess.run(["git", "-C", str(repo_bare), "fetch", str(work_dir), sha], check=True, capture_output=True)

    # Raw bundle fails
    raw_bundle = tmp_path / "test.bundle"
    raw_res = subprocess.run(["git", "-C", str(repo_bare), "bundle", "create", str(raw_bundle), sha], capture_output=True, text=True)
    assert raw_res.returncode != 0
    assert not raw_bundle.exists()

    # Create temporary named ref
    temp_ref = f"refs/bundle-staging/{sha}"
    subprocess.run(["git", "-C", str(repo_bare), "update-ref", temp_ref, sha], check=True, capture_output=True)

    # Ref exists in repo_bare
    show_ref_res = subprocess.run(["git", "-C", str(repo_bare), "show-ref", temp_ref], capture_output=True, text=True)
    assert show_ref_res.returncode == 0

    # Bundle succeeds on named ref
    try:
        subprocess.run(["git", "-C", str(repo_bare), "bundle", "create", str(raw_bundle), temp_ref], check=True, capture_output=True)
    finally:
        subprocess.run(["git", "-C", str(repo_bare), "update-ref", "-d", temp_ref], check=True, capture_output=True)

    # Bundle is verifiable
    verify_res = subprocess.run(["git", "bundle", "verify", str(raw_bundle)], capture_output=True, text=True)
    assert verify_res.returncode == 0

    # Temporary ref is deleted
    del_check = subprocess.run(["git", "-C", str(repo_bare), "show-ref", temp_ref], capture_output=True, text=True)
    assert del_check.returncode != 0


def test_real_git_rev_parse_and_cat_file_commit_verification(tmp_path: Path) -> None:
    """Local real-Git test proving fetched commit gives rev-parse exact ID + cat-file type commit

    and absent 40-hex object fails cat-file.
    """
    repo = tmp_path / "repo.git"
    subprocess.run(["git", "init", "--bare", str(repo)], check=True, capture_output=True)

    work = tmp_path / "work"
    subprocess.run(["git", "init", str(work)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=work, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=work, check=True)
    (work / "file.txt").write_text("commit content", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=work, check=True)
    subprocess.run(["git", "commit", "-m", "sample commit"], cwd=work, check=True, capture_output=True)

    commit_sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=work, check=True, capture_output=True, text=True
    ).stdout.strip()

    # Fetch into repo
    subprocess.run(["git", "-C", str(repo), "fetch", str(work), commit_sha], check=True, capture_output=True)

    # rev-parse brace-free matches exact ID
    rev_res = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", commit_sha], check=True, capture_output=True, text=True
    )
    assert rev_res.stdout.strip() == commit_sha

    # cat-file -t gives 'commit'
    cat_res = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", commit_sha], check=True, capture_output=True, text=True
    )
    assert cat_res.stdout.strip() == "commit"

    # absent 40-hex object fails cat-file
    absent_sha = "f" * 40
    absent_cat = subprocess.run(
        ["git", "-C", str(repo), "cat-file", "-t", absent_sha], capture_output=True, text=True
    )
    assert absent_cat.returncode != 0


def test_default_runner_specifies_utf8_and_replace_decoding(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure default_runner passes encoding='utf-8' and errors='replace' to avoid UnicodeDecodeError under UCRT/cp1251."""
    from video_converter.ffmpeg_build.git_capture import default_runner

    captured_kwargs: dict[str, Any] = {}

    def mock_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured_kwargs.update(kwargs)
        return subprocess.CompletedProcess(args[0] if args else kwargs.get("args"), 0, stdout="test-out", stderr="")

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    res = default_runner(["git", "--version"], work_dir=Path("/dummy"))
    assert res.stdout == "test-out"
    assert captured_kwargs.get("check") is False
    assert captured_kwargs.get("stdout") == subprocess.PIPE
    assert captured_kwargs.get("stderr") == subprocess.PIPE
    assert captured_kwargs.get("text") is True
    assert captured_kwargs.get("encoding") == "utf-8"
    assert captured_kwargs.get("errors") == "replace"
    assert captured_kwargs.get("cwd") == Path("/dummy")
    assert "env" not in captured_kwargs or captured_kwargs["env"] is None



def test_default_runner_nonzero_returns_completed_process_and_run_git_cmd_raises_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify default_runner returns CompletedProcess on nonzero exit (check=False),

    and _run_git_cmd raises CalledProcessError preserving command, returncode, stdout, and stderr.
    """
    from video_converter.ffmpeg_build.git_capture import _run_git_cmd, default_runner

    fake_proc = subprocess.CompletedProcess(
        args=["git", "fetch", "--no-tags", "origin", "deadbeef"],
        returncode=128,
        stdout="remote stdout diagnostic info",
        stderr="fatal: remote error diagnostic info",
    )

    def mock_subprocess_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs.get("check") is False
        return fake_proc

    monkeypatch.setattr(subprocess, "run", mock_subprocess_run)

    # default_runner should return the CompletedProcess without raising
    res = default_runner(["git", "fetch", "--no-tags", "origin", "deadbeef"])
    assert res is fake_proc
    assert res.returncode == 128
    assert res.stdout == "remote stdout diagnostic info"
    assert res.stderr == "fatal: remote error diagnostic info"

    # _run_git_cmd should act as the single fail-closed gate and raise CalledProcessError with diagnostics
    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_git_cmd(default_runner, ["git", "fetch", "--no-tags", "origin", "deadbeef"])

    err = exc_info.value
    assert err.returncode == 128
    assert err.cmd == ["git", "fetch", "--no-tags", "origin", "deadbeef"]
    assert err.output == "remote stdout diagnostic info"
    assert err.stderr == "fatal: remote error diagnostic info"


def test_run_git_cmd_called_process_error_str_contains_diagnostics() -> None:
    from video_converter.ffmpeg_build.git_capture import _run_git_cmd

    fake_proc = subprocess.CompletedProcess(
        args=["git", "fetch", "--no-tags", "origin", "deadbeef"],
        returncode=128,
        stdout="remote stdout output line",
        stderr="fatal: remote error detail",
    )

    def failing_runner(cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
        return fake_proc

    with pytest.raises(subprocess.CalledProcessError) as exc_info:
        _run_git_cmd(failing_runner, ["git", "fetch", "--no-tags", "origin", "deadbeef"])

    err_str = str(exc_info.value)
    assert "git fetch --no-tags origin deadbeef" in err_str or "['git', 'fetch', '--no-tags', 'origin', 'deadbeef']" in err_str
    assert "exit status 128" in err_str
    assert "stdout:" in err_str
    assert "remote stdout output line" in err_str
    assert "stderr:" in err_str
    assert "fatal: remote error detail" in err_str


def _snapshot_tree(root: Path) -> dict[str, bytes]:
    """Capture relative path -> content mapping for all non-temporary files under root."""
    snapshot: dict[str, bytes] = {}
    if not root.exists():
        return snapshot
    for p in root.rglob("*"):
        if p.is_file():
            rel = p.relative_to(root).as_posix()
            # Ignore transient session temporary folders
            if rel.startswith(".tmp") or "/.tmp" in rel:
                continue
            snapshot[rel] = p.read_bytes()
    return snapshot


def _setup_real_git_source(tmp_path: Path) -> tuple[Path, str, dict[str, Any], Callable[..., subprocess.CompletedProcess[str]]]:
    upstream_dir = tmp_path / "upstream_x264"
    upstream_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(upstream_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=upstream_dir, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=upstream_dir, check=True)
    (upstream_dir / "file.txt").write_text("retained bundle test content", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=upstream_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=upstream_dir, check=True, capture_output=True)

    rev_proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=upstream_dir, check=True, capture_output=True, text=True)
    commit_sha = rev_proc.stdout.strip()

    fake_https_x264 = "https://example.invalid/x264.git"
    manifest = _make_manifest()
    git_src = next(s for s in manifest["sources"] if s.get("acquisition_type") == "commit_archive" and s["name"] == "x264")
    git_src["commit"] = commit_sha
    git_src["git_remote_url"] = fake_https_x264
    manifest["sources"] = [git_src]

    def real_git_runner(cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
        cmd_list = list(cmd)
        if cmd_list and cmd_list[0] == "git":
            if "fetch" in cmd_list:
                cmd_list = [
                    "git",
                    "-c", f"url.{upstream_dir.as_uri()}.insteadOf={fake_https_x264}",
                ] + cmd_list[1:]
        return subprocess.run(
            cmd_list,
            cwd=work_dir,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

    return upstream_dir, commit_sha, manifest, real_git_runner


def test_retained_bundle_semantic_reuse_accepts_valid_bundle_with_different_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    # Step 1: Initial capture creates standard bundle and canonical archive
    ev1 = capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)
    first_bundle_sha = ev1["x264"]["git_bundle_sha256"]
    bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    first_bundle_bytes = bundle_path.read_bytes()

    # Step 2: Create an alternative semantically valid bundle that encodes the EXACT ref & commit,
    # but with different bytes (e.g. by using bundle version 3).
    alt_bare = tmp_path / "alt_bare.git"
    subprocess.run(["git", "init", "--bare", str(alt_bare)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(alt_bare), "fetch", str(upstream_dir), f"{commit_sha}:refs/source-lock/x264/{commit_sha}"], check=True, capture_output=True)
    alt_bundle = tmp_path / "alt.bundle"
    # Create with --version=3 (or different compression) to ensure distinct bundle encoding
    subprocess.run(["git", "-C", str(alt_bare), "bundle", "create", "--version=3", str(alt_bundle), f"refs/source-lock/x264/{commit_sha}"], check=True, capture_output=True)
    alt_bytes = alt_bundle.read_bytes()
    alt_sha = hashlib.sha256(alt_bytes).hexdigest()

    # Verify that the two valid bundle representations actually have different bytes and SHAs
    assert alt_bytes != first_bundle_bytes
    assert alt_sha != first_bundle_sha

    # Put the alternative valid bundle into the retained stable path
    bundle_path.write_bytes(alt_bytes)

    # Clean cache_dir so we verify promotion
    shutil.rmtree(cache_dir, ignore_errors=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Capture again: it must accept and reuse the retained bundle's actual SHA and bytes,
    # and NOT regenerate or overwrite it with first_bundle_sha/first_bundle_bytes.
    ev2 = capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)
    assert ev2["x264"]["git_bundle_sha256"] == alt_sha
    assert bundle_path.read_bytes() == alt_bytes


def test_retained_bundle_semantic_reuse_rejects_missing_retained_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    # Initial capture
    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)
    archive_path = retention_dir / "git" / "x264" / f"{commit_sha}.tar.gz"
    bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"

    # Remove retained archive
    archive_path.unlink()

    # Snapshot public trees before failing capture
    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    # Next capture must fail closed with ValueError
    with pytest.raises(ValueError, match="archive"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    assert _snapshot_tree(retention_dir) == retention_snapshot_before
    assert _snapshot_tree(cache_dir) == cache_snapshot_before


def test_retained_bundle_semantic_reuse_rejects_corrupted_bundle_and_leaves_bytes_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)
    bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    corrupt_bytes = b"garbage-corrupt-bundle-data"
    bundle_path.write_bytes(corrupt_bytes)

    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    with pytest.raises(ValueError, match="bundle"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    assert _snapshot_tree(retention_dir) == retention_snapshot_before
    assert _snapshot_tree(cache_dir) == cache_snapshot_before


def test_retained_bundle_semantic_reuse_rejects_wrong_ref_and_leaves_bytes_unchanged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)
    bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"

    # Create bundle with wrong ref name (e.g. refs/heads/wrong_ref)
    wrong_bare = tmp_path / "wrong_bare.git"
    subprocess.run(["git", "init", "--bare", str(wrong_bare)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(wrong_bare), "fetch", str(upstream_dir), f"{commit_sha}:refs/heads/wrong_ref"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(wrong_bare), "bundle", "create", str(bundle_path), "refs/heads/wrong_ref"], check=True, capture_output=True)

    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    with pytest.raises(ValueError, match="ref|bundle"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    assert _snapshot_tree(retention_dir) == retention_snapshot_before
    assert _snapshot_tree(cache_dir) == cache_snapshot_before


def test_retained_bundle_semantic_reuse_rejects_archive_sha_mismatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)
    archive_path = retention_dir / "git" / "x264" / f"{commit_sha}.tar.gz"
    bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"

    # Tamper with archive content (still a valid archive file, but different SHA)
    archive_path.write_bytes(b"tampered-archive-content-differing-sha")

    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    with pytest.raises(ValueError, match="archive|sha256"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    assert _snapshot_tree(retention_dir) == retention_snapshot_before
    assert _snapshot_tree(cache_dir) == cache_snapshot_before


def test_retained_bundle_semantic_reuse_rejects_bundle_with_prerequisites(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real-Git negative test: bundle created with prerequisites (not self-contained)

    must fail semantic validation and leave public retention/cache trees untouched.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha_1, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    # Add a second commit in upstream
    (upstream_dir / "second.txt").write_text("second commit content", encoding="utf-8")
    subprocess.run(["git", "add", "second.txt"], cwd=upstream_dir, check=True)
    subprocess.run(["git", "commit", "-m", "second commit"], cwd=upstream_dir, check=True, capture_output=True)
    commit_sha_2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=upstream_dir, check=True, capture_output=True, text=True).stdout.strip()

    # Update manifest to target commit_sha_2
    manifest["sources"][0]["commit"] = commit_sha_2

    # Perform initial capture to establish retention & cache for commit_sha_2
    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Now replace the bundle with a thin bundle having commit_sha_1 as prerequisite:
    # `git bundle create <path> refs/source-lock/x264/<commit_sha_2> ^<commit_sha_1>`
    bundle_path = retention_dir / "git" / "x264" / f"{commit_sha_2}.bundle"
    ref_name = f"refs/source-lock/x264/{commit_sha_2}"
    subprocess.run(["git", "update-ref", ref_name, commit_sha_2], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(
        ["git", "bundle", "create", str(bundle_path), ref_name, f"^{commit_sha_1}"],
        cwd=upstream_dir,
        check=True,
        capture_output=True,
    )

    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    with pytest.raises(ValueError, match="bundle"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    assert _snapshot_tree(retention_dir) == retention_snapshot_before
    assert _snapshot_tree(cache_dir) == cache_snapshot_before


def test_retained_bundle_mutation_during_validation_fails_and_never_returns_changed_bytes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If bundle file changes during semantic validation, _validate_retained_bundle must raise ValueError

    and not return the altered digest or accept altered state.
    """
    from video_converter.ffmpeg_build.git_capture import _validate_retained_bundle, default_runner

    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo_dir, check=True)
    (repo_dir / "f.txt").write_text("content", encoding="utf-8")
    subprocess.run(["git", "add", "f.txt"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "commit 1"], cwd=repo_dir, check=True, capture_output=True)
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True).stdout.strip()

    bundle_path = tmp_path / f"{commit}.bundle"
    ref = f"refs/source-lock/x264/{commit}"
    subprocess.run(["git", "update-ref", ref, commit], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(bundle_path), ref], cwd=repo_dir, check=True, capture_output=True)

    archive_path = tmp_path / f"{commit}.tar.gz"
    subprocess.run(
        ["git", "archive", "--format=tar.gz", f"--prefix=x264-{commit}/", f"--output={archive_path}", commit],
        cwd=repo_dir,
        check=True,
    )

    session_dir = tmp_path / "session"
    session_dir.mkdir()

    # Wrap runner to mutate bundle_path during git archive command inside validation
    real_runner = default_runner

    def mutating_runner(cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
        res = real_runner(cmd, work_dir)
        if "archive" in cmd:
            # Mutate bundle file after fetch / verify but before hash check
            bundle_path.write_bytes(b"tampered-bundle-bytes-after-archive-step")
        return res

    with pytest.raises(ValueError, match="digest changed|sha256 changed|tampered|hash"):
        _validate_retained_bundle(
            runner=mutating_runner,
            bundle_path=bundle_path,
            archive_path=archive_path,
            name="x264",
            commit=commit,
            session_dir=session_dir,
        )


def test_retained_bundle_semantic_reuse_rejects_non_commit_object_type(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from video_converter.ffmpeg_build.git_capture import _validate_retained_bundle, default_runner

    # Create a real Git repo with a tag object having name == commit_sha
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init", str(repo_dir)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo_dir, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=repo_dir, check=True)
    (repo_dir / "file.txt").write_text("hello", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "msg"], cwd=repo_dir, check=True, capture_output=True)
    head_commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_dir, check=True, capture_output=True, text=True).stdout.strip()

    # Create an annotated tag object whose target is head_commit, and get tag SHA
    subprocess.run(["git", "tag", "-a", "my_tag", "-m", "tag message"], cwd=repo_dir, check=True, capture_output=True)
    tag_sha = subprocess.run(["git", "rev-parse", "my_tag"], cwd=repo_dir, check=True, capture_output=True, text=True).stdout.strip()
    assert tag_sha != head_commit

    # Now create a bundle advertising refs/source-lock/x264/{tag_sha} pointing to tag_sha (which is a tag object, not a commit object)
    bundle_path = tmp_path / f"{tag_sha}.bundle"
    ref_name = f"refs/source-lock/x264/{tag_sha}"
    subprocess.run(["git", "update-ref", ref_name, tag_sha], cwd=repo_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(bundle_path), ref_name], cwd=repo_dir, check=True, capture_output=True)

    archive_path = tmp_path / f"{tag_sha}.tar.gz"
    archive_path.write_bytes(b"dummy")

    session_dir = tmp_path / "session"
    session_dir.mkdir()

    with pytest.raises(ValueError, match="Commit object type.*not 'commit'"):
        _validate_retained_bundle(
            runner=default_runner,
            bundle_path=bundle_path,
            archive_path=archive_path,
            name="x264",
            commit=tag_sha,
            session_dir=session_dir,
        )


def test_two_source_second_fails_validation_prevents_all_publications(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import video_converter.ffmpeg_build.git_capture as gc_mod

    manifest = _make_manifest()
    git_sources = [s for s in manifest["sources"] if s.get("acquisition_type") == "commit_archive"]
    assert len(git_sources) >= 2, "Expected at least 2 commit_archive sources in manifest"
    src1, src2 = git_sources[0], git_sources[1]
    bad_commit = src2["commit"]

    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    cache_dir.mkdir(parents=True, exist_ok=True)
    retention_dir.mkdir(parents=True, exist_ok=True)

    # Monitor publication helpers so we assert they are NEVER called if preparation fails
    publish_calls: list[str] = []
    original_publish_retention = gc_mod._publish_retention_artifact
    original_atomic_promote = gc_mod._atomic_promote

    def tracked_publish_retention(*args: Any, **kwargs: Any) -> None:
        publish_calls.append("publish_retention")
        return original_publish_retention(*args, **kwargs)

    def tracked_atomic_promote(*args: Any, **kwargs: Any) -> None:
        publish_calls.append("atomic_promote")
        return original_atomic_promote(*args, **kwargs)

    monkeypatch.setattr(gc_mod, "_publish_retention_artifact", tracked_publish_retention)
    monkeypatch.setattr(gc_mod, "_atomic_promote", tracked_atomic_promote)

    class TwoSourceRunner(FakeGitRunner):
        def __call__(self, cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
            cmd_list = list(cmd)
            # Fail cat-file -t check for src2
            if "cat-file" in cmd_list and "-t" in cmd_list:
                if bad_commit in cmd_list:
                    return subprocess.CompletedProcess(cmd, 0, stdout="tree\n", stderr="")
            return super().__call__(cmd, work_dir)

    runner = TwoSourceRunner()

    with pytest.raises(ValueError, match=f"Commit object type mismatch for source '{src2['name']}'"):
        gc_mod.capture_git_sources(manifest, cache_dir, retention_dir, runner)

    # Publication helpers must never be invoked
    assert publish_calls == []

    # Retention tree and cache tree must be completely empty / untouched
    assert list(retention_dir.rglob("*")) == []
    assert [p for p in cache_dir.rglob("*") if p.name != ".tmp_git_capture"] == []


def test_legacy_bundle_migration_success_and_record(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real-Git test: legacy bundle advertising refs/bundle-staging/<commit> resolving expected commit

    must be moved to retention/quarantine/<timestamp>-legacy-bundle/<name>-<commit>.bundle,
    record CONFLICT.txt with full metadata, and then a new source-lock bundle published at stable path.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    # First perform normal capture to create canonical archive & cache
    evidence_initial = capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)
    archive_sha = evidence_initial["x264"]["artifact_sha256"]

    # Now replace the bundle at stable path with a legacy bundle advertising refs/bundle-staging/<commit_sha>
    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)

    legacy_bundle_bytes = stable_bundle_path.read_bytes()
    legacy_bundle_sha = hashlib.sha256(legacy_bundle_bytes).hexdigest()
    legacy_bundle_size = len(legacy_bundle_bytes)

    # Re-run capture
    evidence_migrated = capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # 1. Stable bundle exists and is newly published (advertising refs/source-lock/x264/<commit_sha>)
    assert stable_bundle_path.is_file()
    # It should have the new source-lock ref
    verify_repo = tmp_path / "verify_migrated.git"
    subprocess.run(["git", "init", "--bare", str(verify_repo)], check=True, capture_output=True)
    fetch_res = subprocess.run(
        ["git", "-C", str(verify_repo), "fetch", str(stable_bundle_path), f"refs/source-lock/x264/{commit_sha}:refs/source-lock/x264/{commit_sha}"],
        capture_output=True,
        text=True,
    )
    assert fetch_res.returncode == 0

    # 2. Quarantine directory exists under retention_dir / "quarantine"
    quarantine_base = retention_dir / "quarantine"
    assert quarantine_base.is_dir()
    quarantine_dirs = list(quarantine_base.glob("*-legacy-bundle*"))
    assert len(quarantine_dirs) == 1
    qdir = quarantine_dirs[0]

    quarantined_bundle = qdir / f"x264-{commit_sha}.bundle"
    assert quarantined_bundle.is_file()
    assert quarantined_bundle.read_bytes() == legacy_bundle_bytes
    assert hashlib.sha256(quarantined_bundle.read_bytes()).hexdigest() == legacy_bundle_sha
    assert quarantined_bundle.stat().st_size == legacy_bundle_size

    conflict_file = qdir / "CONFLICT.txt"
    assert conflict_file.is_file()
    conflict_text = conflict_file.read_text(encoding="utf-8")

    assert str(stable_bundle_path) in conflict_text
    assert str(quarantined_bundle) in conflict_text
    assert "x264" in conflict_text
    assert commit_sha in conflict_text
    assert legacy_bundle_sha in conflict_text
    assert str(legacy_bundle_size) in conflict_text
    assert legacy_ref in conflict_text
    assert f"refs/source-lock/x264/{commit_sha}" in conflict_text
    assert "reason" in conflict_text.lower() or "legacy" in conflict_text.lower()


def test_invalid_legacy_bundle_remains_stable_and_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real-Git test: corrupt or invalid legacy bundle at stable path must NOT be moved to quarantine

    and capture must fail closed without modifying retention/cache.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    stable_bundle_path.write_bytes(b"corrupt-non-bundle-data")

    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    with pytest.raises(ValueError):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    assert _snapshot_tree(retention_dir) == retention_snapshot_before
    assert _snapshot_tree(cache_dir) == cache_snapshot_before
    assert not (retention_dir / "quarantine").exists()


def test_nonlegacy_wrong_ref_bundle_remains_stable_and_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Real-Git test: valid bundle that advertises an unexpected/non-legacy ref (e.g. refs/heads/main)

    must NOT be moved to quarantine, and capture must fail closed.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    wrong_ref = "refs/heads/custom-feature"
    subprocess.run(["git", "update-ref", wrong_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), wrong_ref], cwd=upstream_dir, check=True, capture_output=True)

    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    with pytest.raises(ValueError, match="ref"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    assert _snapshot_tree(retention_dir) == retention_snapshot_before
    assert _snapshot_tree(cache_dir) == cache_snapshot_before
    assert not (retention_dir / "quarantine").exists()


def test_failed_post_migration_publication_preserves_quarantine_bytes_and_no_other_public_changes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If publication fails after a legacy bundle has been quarantined, quarantine bytes are preserved,

    no further public changes occur, and capture stops.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    # Simulate failure during publication phase for bundle
    def failing_publish(*args: Any, **kwargs: Any) -> None:
        if kwargs.get("artifact_type") == "bundle" or (len(args) >= 4 and args[3] == "bundle"):
            raise OSError("Disk failure during bundle publication")
        return gc._publish_atomic_create_if_absent(*args, **kwargs)

    monkeypatch.setattr(gc, "_publish_retention_artifact", failing_publish)

    with pytest.raises(OSError, match="Disk failure during bundle publication"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Quarantine must exist and contain the uncorrupted legacy bundle
    quarantine_base = retention_dir / "quarantine"
    assert quarantine_base.is_dir()
    qdirs = list(quarantine_base.glob("*-legacy-bundle*"))
    assert len(qdirs) == 1
    qbundle = qdirs[0] / f"x264-{commit_sha}.bundle"
    assert qbundle.is_file()
    assert qbundle.read_bytes() == legacy_bytes

    # Stable bundle path was removed during migration and could not be published, so it should be absent
    assert not stable_bundle_path.exists()


def test_legacy_bundle_mutation_during_validation_fails_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finding 1: If bundle is mutated during legacy inspection, migration must fail closed (ValueError),

    and neither stable path nor quarantine must be modified/created with bad data.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)

    # Wrap runner so that during inspection (e.g. rev-parse), stable_bundle_path is tampered
    def mutating_runner(cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
        res = runner(cmd, work_dir)
        if "rev-parse" in cmd and any("bundle-staging" in a for a in cmd):
            stable_bundle_path.write_bytes(b"tampered-legacy-bundle-bytes-after-rev-parse")
        return res

    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    with pytest.raises(ValueError, match="tampered|digest changed|SHA-256 mismatch|mismatch"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=mutating_runner)

    # No quarantine should exist
    assert not (retention_dir / "quarantine").exists()


def test_quarantine_destination_collision_fails_closed_and_preserves_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 2: Quarantine destination must be unique and never overwrite existing files.

    If collision occurs, existing quarantine artifact must remain untouched and migration fail closed.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    # First perform capture to establish initial state
    evidence = capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)
    actual_commit = manifest["sources"][0]["commit"]

    stable_bundle_path = retention_dir / "git" / "x264" / f"{actual_commit}.bundle"
    legacy_ref = f"refs/bundle-staging/{actual_commit}"
    subprocess.run(["git", "update-ref", legacy_ref, actual_commit], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    # Pre-populate a colliding quarantine directory with existing bundle and conflict record
    quarantine_base = retention_dir / "quarantine"
    quarantine_base.mkdir(parents=True, exist_ok=True)
    fixed_qdir = quarantine_base / "fixed-collision-legacy-bundle"
    fixed_qdir.mkdir(parents=True, exist_ok=True)
    colliding_bundle = fixed_qdir / f"x264-{actual_commit}.bundle"
    colliding_bundle.write_bytes(b"pre-existing-quarantine-artifact")

    # Force the quarantine dir to be fixed_qdir
    original_mkdtemp = gc.tempfile.mkdtemp

    def colliding_mkdtemp(suffix: str | None = None, prefix: str | None = None, dir: str | None = None) -> str:
        if prefix and "legacy-bundle" in prefix:
            return str(fixed_qdir)
        return original_mkdtemp(suffix=suffix, prefix=prefix, dir=dir)

    monkeypatch.setattr(gc.tempfile, "mkdtemp", colliding_mkdtemp)

    # In collision case, quarantine_bundle_path already exists inside fixed_qdir
    # Migration must fail closed without modifying colliding_bundle or stable_bundle_path
    with pytest.raises((FileExistsError, ValueError, OSError)):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Colliding bundle must remain in place and untouched!
    assert colliding_bundle.is_file()
    assert colliding_bundle.read_bytes() == b"pre-existing-quarantine-artifact"
    # Stable bundle must remain in place!
    assert stable_bundle_path.is_file()
    assert stable_bundle_path.read_bytes() == legacy_bytes


def test_migration_record_failure_prevents_unrecorded_quarantine(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 3: If migration record writing/publication fails, stable bundle must not disappear

    without a valid recorded quarantine bundle.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    # Simulate failure when writing CONFLICT.txt
    real_open = os.open

    def failing_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if "CONFLICT.txt" in str(path):
            raise OSError("Disk failure writing CONFLICT.txt")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", failing_open)

    with pytest.raises(OSError, match="Disk failure writing CONFLICT.txt"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Stable bundle must still be present and unmodified, OR if quarantined, must have CONFLICT.txt
    assert stable_bundle_path.is_file()
    assert stable_bundle_path.read_bytes() == legacy_bytes


def test_two_source_second_fails_validation_leaves_first_legacy_bundle_untouched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 1 (Two-phase boundary regression):

    Source 1 has an eligible legacy bundle.
    Source 2 fails preparation/validation in Phase A.
    Result: Source 1 legacy stable bundle must remain untouched at stable path.
    NO quarantine directory, NO CONFLICT.txt, NO new source-lock bundle, NO cache,
    and NO retention archive must be published for Source 1. Entire trees remain clean.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    # Setup real git for source 1 (x264)
    upstream_x264, commit_x264, manifest_base, runner_x264 = _setup_real_git_source(tmp_path)

    # Setup real git for source 2 (dav1d)
    upstream_dav1d = tmp_path / "upstream_dav1d"
    upstream_dav1d.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(upstream_dav1d)], check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "Tester"], cwd=upstream_dav1d, check=True)
    subprocess.run(["git", "config", "user.email", "tester@example.com"], cwd=upstream_dav1d, check=True)
    (upstream_dav1d / "dav1d.txt").write_text("dav1d content", encoding="utf-8")
    subprocess.run(["git", "add", "dav1d.txt"], cwd=upstream_dav1d, check=True)
    subprocess.run(["git", "commit", "-m", "dav1d initial"], cwd=upstream_dav1d, check=True, capture_output=True)
    commit_dav1d = subprocess.run(["git", "rev-parse", "HEAD"], cwd=upstream_dav1d, check=True, capture_output=True, text=True).stdout.strip()

    fake_https_dav1d = "https://example.invalid/dav1d.git"
    src_dav1d = {
        "name": "dav1d",
        "license": "BSD-2-Clause",
        "acquisition_type": "commit_archive",
        "commit": commit_dav1d,
        "git_remote_url": fake_https_dav1d,
    }
    manifest = {
        "schema_version": "1.0.0",
        "sources": [manifest_base["sources"][0], src_dav1d],
    }

    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    fake_https_x264 = manifest["sources"][0]["git_remote_url"]

    # Initial capture to establish retention archive and cache for x264 and dav1d
    def composite_runner(cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
        cmd_list = list(cmd)
        if cmd_list and cmd_list[0] == "git" and "fetch" in cmd_list:
            cmd_list = [
                "git",
                "-c", f"url.{upstream_x264.as_uri()}.insteadOf={fake_https_x264}",
                "-c", f"url.{upstream_dav1d.as_uri()}.insteadOf={fake_https_dav1d}",
            ] + cmd_list[1:]
        return subprocess.run(cmd_list, cwd=work_dir, capture_output=True, text=True, check=False)

    capture_git_sources(manifest, cache_dir, retention_dir, runner=composite_runner)

    # Now convert x264 bundle to legacy bundle advertising refs/bundle-staging/<commit_x264>
    stable_x264_bundle = retention_dir / "git" / "x264" / f"{commit_x264}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_x264}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_x264], cwd=upstream_x264, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_x264_bundle), legacy_ref], cwd=upstream_x264, check=True, capture_output=True)
    legacy_x264_bytes = stable_x264_bundle.read_bytes()

    # Clear cache to detect any premature promotion
    shutil.rmtree(cache_dir, ignore_errors=True)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Snapshot before second capture run
    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    # Wrap runner to simulate failure on source 2 (dav1d) during prepare phase (e.g. cat-file -t)
    def failing_runner(cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
        cmd_list = list(cmd)
        if "cat-file" in cmd_list and "-t" in cmd_list and commit_dav1d in cmd_list:
            return subprocess.CompletedProcess(cmd, 0, stdout="tag\n", stderr="")
        return composite_runner(cmd, work_dir)

    with pytest.raises(ValueError, match="Commit object type mismatch for source 'dav1d'"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=failing_runner)

    # Entire retention and cache trees must be completely unchanged!
    assert _snapshot_tree(retention_dir) == retention_snapshot_before
    assert _snapshot_tree(cache_dir) == cache_snapshot_before
    # Specifically, x264 legacy bundle is STILL at stable path and unmodified
    assert stable_x264_bundle.is_file()
    assert stable_x264_bundle.read_bytes() == legacy_x264_bytes
    # No quarantine directory exists
    assert not (retention_dir / "quarantine").exists()


def test_migration_unlink_failure_fails_closed_without_fallback_or_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Finding 2 (Link/unlink correctness):

    If os.link succeeds in creating the quarantine artifact but bundle_path.unlink() fails,
    system must NOT attempt fallback copy/move (which would fail or duplicate),
    and must fail closed with explicit diagnostic.
    A subsequent run must recognize incomplete migration or fail closed without creating duplicate destinations.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    # Track copy calls (shutil.copyfileobj) to ensure fallback is NEVER invoked once link succeeds
    copy_called = []
    orig_copyfileobj = shutil.copyfileobj

    def monitored_copyfileobj(*args: Any, **kwargs: Any) -> Any:
        copy_called.append(args)
        return orig_copyfileobj(*args, **kwargs)

    monkeypatch.setattr(shutil, "copyfileobj", monitored_copyfileobj)

    # Monkeypatch Path.unlink so that unlinking stable_bundle_path fails
    orig_unlink = Path.unlink

    def failing_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == stable_bundle_path:
            raise PermissionError("Simulated locked file: cannot unlink original bundle")
        return orig_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises((PermissionError, OSError, ValueError), match="cannot unlink|unlink"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Fallback copyfileobj must NOT have been called!
    assert copy_called == []
    # Both stable and quarantine exist (due to incomplete move), but stable was not deleted
    assert stable_bundle_path.is_file()


def test_migration_mutation_immediately_before_link_fails_and_cleans_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 1: Rehash/restat stable source immediately before destructive link/copy.

    If file changes after quarantine dir/record creation but before link/copy:
    Must raise ValueError fail-closed, stable bundle must remain in place and not removed,
    and no valid quarantine bundle artifact must be created/left published.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)

    # Monkeypatch conflict record writing to mutate stable bundle right before link/copy
    orig_open = os.open

    def mutating_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        fd = orig_open(path, flags, *args, **kwargs)
        if "CONFLICT.txt" in str(path):
            # Mutate stable bundle right after CONFLICT.txt is created/written but before bundle move!
            stable_bundle_path.write_bytes(b"tampered-just-before-link-copy")
        return fd

    monkeypatch.setattr(os, "open", mutating_open)

    with pytest.raises(ValueError, match="tampered|digest/size changed|mismatch"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Stable bundle must still be present and not removed!
    assert stable_bundle_path.is_file()
    assert stable_bundle_path.read_bytes() == b"tampered-just-before-link-copy"
    # No quarantine bundle artifact should be left published
    quarantine_base = retention_dir / "quarantine"
    if quarantine_base.exists():
        quarantine_bundles = list(quarantine_base.glob("**/*.bundle"))
        assert quarantine_bundles == []


def test_migration_mutation_between_link_failure_and_fallback_copy_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 1: Between os.link failure and fallback copy, re-stat/rehash stable bundle.

    Any mutation must fail closed before fallback copy/unlink and not publish a valid quarantine artifact.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)

    # Mutate source triggered by first os.link failure
    def failing_and_mutating_link(src: Any, dst: Any) -> None:
        stable_bundle_path.write_bytes(b"tampered-between-link-and-fallback")
        raise OSError("Simulated cross-device link failure")

    monkeypatch.setattr(os, "link", failing_and_mutating_link)

    with pytest.raises(ValueError, match="tampered|digest/size changed|mismatch"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Stable bundle must remain in place (with the mutated bytes) and not unlinked
    assert stable_bundle_path.is_file()
    assert stable_bundle_path.read_bytes() == b"tampered-between-link-and-fallback"

    # No valid quarantine bundle artifact must be left published
    quarantine_base = retention_dir / "quarantine"
    if quarantine_base.exists():
        quarantine_bundles = list(quarantine_base.glob("**/*.bundle"))
        assert quarantine_bundles == []


def test_migration_fallback_exclusive_creation_race_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 2: Fallback copy must open with O_CREAT | O_EXCL.

    If target exists or race condition occurs, must fail closed and never overwrite target.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    # Force os.link to fail with OSError to trigger fallback
    def failing_link(src: Any, dst: Any) -> None:
        raise OSError("Simulated cross-device link failure")

    monkeypatch.setattr(os, "link", failing_link)

    # In fallback path, simulate that right after directory/record creation, an existing file was placed at destination
    orig_open = os.open

    def racing_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        fd = orig_open(path, flags, *args, **kwargs)
        if "CONFLICT.txt" in str(path):
            # Simulate a racing process creating the bundle destination before copy
            racing_dst = Path(str(path)).parent / f"x264-{commit_sha}.bundle"
            racing_dst.write_bytes(b"existing-racing-bundle-bytes")
        return fd

    monkeypatch.setattr(os, "open", racing_open)

    with pytest.raises((FileExistsError, OSError)):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Check that the racing destination was NOT overwritten
    quarantine_base = retention_dir / "quarantine"
    racing_files = list(quarantine_base.glob(f"**/*-{commit_sha}.bundle"))
    assert len(racing_files) == 1
    assert racing_files[0].read_bytes() == b"existing-racing-bundle-bytes"
    # Stable bundle must still exist
    assert stable_bundle_path.is_file()
    assert stable_bundle_path.read_bytes() == legacy_bytes


def test_migration_conflict_record_collision_fails_and_preserves_existing_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 2: CONFLICT.txt must be published exclusively create-if-absent.

    Collision must preserve existing record bytes and fail closed without leaving partial artifacts.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    # Pre-create CONFLICT.txt inside any mkdtemp-created quarantine directory right before writing
    orig_mkdtemp = tempfile.mkdtemp

    def colliding_mkdtemp(*args: Any, **kwargs: Any) -> str:
        d = orig_mkdtemp(*args, **kwargs)
        if "legacy-bundle" in str(d):
            # Pre-seed existing CONFLICT.txt with sensitive/original content
            cpath = Path(d) / "CONFLICT.txt"
            cpath.write_bytes(b"existing-unrelated-conflict-record-bytes")
        return d

    monkeypatch.setattr(tempfile, "mkdtemp", colliding_mkdtemp)

    with pytest.raises((FileExistsError, OSError)):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Stable bundle must be untouched
    assert stable_bundle_path.is_file()
    assert stable_bundle_path.read_bytes() == legacy_bytes

    # Existing CONFLICT.txt bytes must be preserved!
    quarantine_base = retention_dir / "quarantine"
    assert quarantine_base.exists()
    conflict_files = list(quarantine_base.glob("**/CONFLICT.txt"))
    assert len(conflict_files) == 1
    assert conflict_files[0].read_bytes() == b"existing-unrelated-conflict-record-bytes"

    # No quarantine bundle artifact should have been created
    assert list(quarantine_base.glob("**/*.bundle")) == []


def test_migration_conflict_record_write_failure_cleans_partial_dir_safely(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 2: If record publication fails, do not leave a public quarantine dir/partial record.

    Only invocation-owned empty/partial dir is safely removed; stable bundle remains untouched.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    created_qdirs = []
    orig_mkdtemp = tempfile.mkdtemp

    def tracking_mkdtemp(*args: Any, **kwargs: Any) -> str:
        d = orig_mkdtemp(*args, **kwargs)
        if "legacy-bundle" in str(d):
            created_qdirs.append(Path(d))
        return d

    monkeypatch.setattr(tempfile, "mkdtemp", tracking_mkdtemp)

    # Injected failure on CONFLICT.txt creation
    orig_open = os.open

    def failing_conflict_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        if "CONFLICT.txt" in str(path):
            raise OSError("Injected disk full error on CONFLICT.txt write")
        return orig_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", failing_conflict_open)

    # Also monkeypatch write_text just in case old implementation uses it
    orig_write_text = Path.write_text

    def failing_write_text(self: Path, *args: Any, **kwargs: Any) -> int:
        if self.name == "CONFLICT.txt":
            raise OSError("Injected disk full error on CONFLICT.txt write")
        return orig_write_text(self, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", failing_write_text)

    with pytest.raises(OSError, match="Injected disk full error"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Stable bundle must be untouched
    assert stable_bundle_path.is_file()
    assert stable_bundle_path.read_bytes() == legacy_bytes

    # The created quarantine dir must have been cleaned up and not left as a public empty/partial dir
    assert len(created_qdirs) == 1
    assert not created_qdirs[0].exists()


def test_migration_retry_recognizes_incomplete_migration_and_fails_without_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Requirement 3: When unlink fails after link, a subsequent run (retry)

    must recognize the exact recorded in-progress migration rather than create a new destination,
    and fail closed deterministically without duplicate quarantine.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)

    # 1. Run with unlink failure to simulate partial migration
    orig_unlink = Path.unlink

    def failing_unlink(self: Path, *args: Any, **kwargs: Any) -> None:
        if self == stable_bundle_path:
            raise PermissionError("Simulated locked file: cannot unlink original bundle")
        return orig_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", failing_unlink)

    with pytest.raises((PermissionError, OSError, ValueError)):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    quarantine_base = retention_dir / "quarantine"
    q_dirs_first_run = list(quarantine_base.glob("*-legacy-bundle*"))
    assert len(q_dirs_first_run) == 1
    first_qdir = q_dirs_first_run[0]
    quarantine_snapshot_before_retry = _snapshot_tree(first_qdir)

    # 2. Reset unlink monkeypatch to standard behavior
    monkeypatch.undo()
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    # Now run capture again (retry).
    # Since stable_bundle_path is still present but already quarantined with identical CONFLICT.txt & SHA,
    # the retry must detect incomplete migration, fail closed, and NOT create a second quarantine dir/bundle!
    with pytest.raises(ValueError, match="[Ii]ncomplete.*migration|already migrated|in-progress"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    q_dirs_second_run = list(quarantine_base.glob("*-legacy-bundle*"))
    # MUST NOT have created a second quarantine directory!
    assert len(q_dirs_second_run) == 1
    assert _snapshot_tree(first_qdir) == quarantine_snapshot_before_retry


def test_prepare_git_source_phase_a_semantic_and_bytewise_validation_mismatch_prevents_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect 1: _prepare_git_source must validate any existing retained canonical archive and cache entry

    semantically/byte-wise against its prepared staged canonical archive BEFORE any Phase B public publication.
    Add a two-source test where first source new but second existing archive/cache mismatch; assert full retention/cache
    snapshot unchanged and no publication call.
    """
    import video_converter.ffmpeg_build.git_capture as gc_mod

    manifest = _make_manifest()
    git_sources = [s for s in manifest["sources"] if s.get("acquisition_type") == "commit_archive"]
    assert len(git_sources) >= 2, "Expected at least 2 commit_archive sources in manifest"
    src1, src2 = git_sources[0], git_sources[1]

    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"
    cache_dir.mkdir(parents=True, exist_ok=True)
    retention_dir.mkdir(parents=True, exist_ok=True)

    # Pre-populate src2 in retention with a corrupt/mismatched archive and/or cache entry
    src2_retention_git = retention_dir / "git" / src2["name"]
    src2_retention_git.mkdir(parents=True, exist_ok=True)
    src2_retention_archive = src2_retention_git / f"{src2['commit']}.tar.gz"
    src2_retention_archive.write_bytes(b"corrupted_or_mismatched_archive_bytes")

    retention_snapshot_before = _snapshot_tree(retention_dir)
    cache_snapshot_before = _snapshot_tree(cache_dir)

    publish_calls: list[str] = []
    original_publish_retention = gc_mod._publish_retention_artifact
    original_atomic_promote = gc_mod._atomic_promote

    def tracked_publish_retention(*args: Any, **kwargs: Any) -> None:
        publish_calls.append("publish_retention")
        return original_publish_retention(*args, **kwargs)

    def tracked_atomic_promote(*args: Any, **kwargs: Any) -> None:
        publish_calls.append("atomic_promote")
        return original_atomic_promote(*args, **kwargs)

    monkeypatch.setattr(gc_mod, "_publish_retention_artifact", tracked_publish_retention)
    monkeypatch.setattr(gc_mod, "_atomic_promote", tracked_atomic_promote)

    runner = FakeGitRunner()

    with pytest.raises(ValueError, match="[Aa]rchive|[Cc]ache|[Mm]ismatch|[Cc]orrupt"):
        gc_mod.capture_git_sources(manifest, cache_dir, retention_dir, runner)

    # Assert no publication call was ever made (Phase B did not run)
    assert publish_calls == []

    # Retention snapshot and cache snapshot must remain completely unchanged!
    assert _snapshot_tree(retention_dir) == retention_snapshot_before
    # Note: tmp dir inside cache_dir may be created and removed, but no other cache entries
    cache_entries_after = {k: v for k, v in _snapshot_tree(cache_dir).items() if not k.startswith(".tmp_git_capture")}
    assert cache_entries_after == cache_snapshot_before


def test_cross_process_migration_ownership_lock_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect 2: serialize ownership of a stable legacy bundle before any quarantine record/target creation.

    Use an exclusive stable-path-adjacent/invocation lock with O_EXCL or equivalent that is safely released;
    a loser detects in-progress migration and fails closed without making second quarantine artifact.
    Test simulate lock owner/second executor: no new quarantine/record and stable untouched (or deterministic existing partial state untouched).
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    # Capture first so archive and bundle exist
    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    quarantine_base = retention_dir / "quarantine"
    assert not quarantine_base.exists() or list(quarantine_base.iterdir()) == []

    # Simulate process 1 having acquired the migration lock on stable_bundle_path
    # Lock file is adjacent to stable bundle path (e.g., .lock or similar lock protocol)
    # When process 2 runs _execute_legacy_migration or capture_git_sources, it sees the lock,
    # fails closed, and creates NO quarantine directories, NO CONFLICT.txt, and leaves stable bundle untouched.
    lock_file = stable_bundle_path.parent / f"{stable_bundle_path.name}.migration.lock"
    lock_file.write_text("simulated_holder_pid_1234\n", encoding="utf-8")

    with pytest.raises((OSError, ValueError), match="[Ll]ock|[Mm]igration in progress|[Cc]oncurrent"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Stable bundle must be untouched
    assert stable_bundle_path.exists()
    assert stable_bundle_path.read_bytes() == legacy_bytes

    # Quarantine dir must not have any migration folders created
    if quarantine_base.exists():
        assert list(quarantine_base.glob("*-legacy-bundle*")) == []


def test_destination_verify_before_source_unlink_mismatch_retains_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect 3: after hard-link OR exclusive fallback copy, SHA/size-check quarantine destination

    against bound original BEFORE unlinking stable path. On mismatch remove only the invocation-owned
    destination/record safely, retain stable source. Test force destination byte mismatch and assert original
    survives/no accepted migration.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    # Intercept copy or link creation to corrupt destination before verification
    # When os.link or fallback copy creates the quarantine bundle, force destination bytes to mismatch
    orig_open = os.open

    # Simulate copy path (e.g. by making os.link fail) and corrupting the destination file immediately after creation
    def failing_link(src: Any, dst: Any) -> None:
        raise OSError("EXDEV cross-device link not permitted")

    monkeypatch.setattr(os, "link", failing_link)

    # Monkeypatch copyfileobj to write corrupt content to destination
    orig_copyfileobj = shutil.copyfileobj

    def corrupting_copyfileobj(fsrc: Any, fdst: Any, *args: Any, **kwargs: Any) -> None:
        orig_copyfileobj(fsrc, fdst, *args, **kwargs)
        # Overwrite with corrupted bytes
        fdst.seek(0)
        fdst.write(b"corrupt_destination_bytes_mismatch")
        fdst.truncate()

    monkeypatch.setattr(shutil, "copyfileobj", corrupting_copyfileobj)

    with pytest.raises(ValueError, match="[Mm]ismatch|[Ii]ntegrity"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    # Original stable bundle must survive!
    assert stable_bundle_path.exists()
    assert stable_bundle_path.read_bytes() == legacy_bytes

    # Invocation-owned destination and partial quarantine dir must be cleaned up safely
    quarantine_base = retention_dir / "quarantine"
    if quarantine_base.exists():
        assert list(quarantine_base.glob("*-legacy-bundle*")) == []


def test_durable_record_fsync_failure_prevents_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Defect 4: before destructive stable unlink, fsync CONFLICT fd and fsync the quarantine directory.

    If portability makes dir fsync unsupported (Windows), use platform-appropriate best effort but do not
    falsely claim durability; implement/test a controlled fsync failure that prevents unlink.
    """
    import video_converter.ffmpeg_build.git_capture as gc
    monkeypatch.setattr(gc, "validate_acquisition_manifest", lambda m: None)

    upstream_dir, commit_sha, manifest, runner = _setup_real_git_source(tmp_path)
    cache_dir = tmp_path / "cache"
    retention_dir = tmp_path / "retention"

    capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    stable_bundle_path = retention_dir / "git" / "x264" / f"{commit_sha}.bundle"
    legacy_ref = f"refs/bundle-staging/{commit_sha}"
    subprocess.run(["git", "update-ref", legacy_ref, commit_sha], cwd=upstream_dir, check=True, capture_output=True)
    subprocess.run(["git", "bundle", "create", str(stable_bundle_path), legacy_ref], cwd=upstream_dir, check=True, capture_output=True)
    legacy_bytes = stable_bundle_path.read_bytes()

    # Intercept os.fsync to raise an OSError when syncing conflict record fd or dir
    orig_fsync = os.fsync
    fsync_called = []

    def failing_fsync(fd: int) -> None:
        fsync_called.append(fd)
        raise OSError("Simulated I/O sync failure during durability commit")

    monkeypatch.setattr(os, "fsync", failing_fsync)

    with pytest.raises(OSError, match="Simulated I/O sync failure"):
        capture_git_sources(manifest, cache_dir, retention_dir, runner=runner)

    assert len(fsync_called) > 0
    # Original stable bundle MUST NOT be unlinked
    assert stable_bundle_path.exists()
    assert stable_bundle_path.read_bytes() == legacy_bytes

    # Invocation-owned partial quarantine dir must be cleaned safely
    quarantine_base = retention_dir / "quarantine"
    if quarantine_base.exists():
        assert list(quarantine_base.glob("*-legacy-bundle*")) == []



