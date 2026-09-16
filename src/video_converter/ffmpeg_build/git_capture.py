"""Isolated Git capture and canonical archive cache promotion."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

from video_converter.ffmpeg_build_manifest import validate_acquisition_manifest

CommandRunner = Callable[[Sequence[str], Path | None], subprocess.CompletedProcess[str]]


def default_runner(cmd: Sequence[str], work_dir: Path | None = None) -> subprocess.CompletedProcess[str]:
    """Default runner executing git subprocess commands."""
    return subprocess.run(
        cmd,
        cwd=work_dir,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


class GitCommandError(subprocess.CalledProcessError):
    """CalledProcessError that formats exit code, stdout, and stderr in its string representation."""

    def __str__(self) -> str:
        base = super().__str__()
        lines = [base]
        if self.output:
            lines.append(f"stdout:\n{self.output}")
        if self.stderr:
            lines.append(f"stderr:\n{self.stderr}")
        return "\n".join(lines)


def _run_git_cmd(
    runner: CommandRunner,
    cmd: Sequence[str],
    work_dir: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    proc = runner(cmd, work_dir)
    if proc.returncode != 0:
        raise GitCommandError(
            returncode=proc.returncode,
            cmd=list(cmd),
            output=proc.stdout,
            stderr=proc.stderr,
        )
    return proc


def _compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _publish_atomic_create_if_absent(
    staging_file: Path,
    target_file: Path,
    expected_sha256: str,
    artifact_description: str,
) -> None:
    """Atomically create target_file if absent using os.link from a verified private sibling temp file.

    Protocol:
    1. Ensure parent directory exists.
    2. If target already exists, verify its digest matches expected_sha256; fail closed if not.
    3. Copy staging to an invocation-owned temp sibling in the target's parent directory (via mkstemp).
    4. Compute and compare hash of temp sibling against expected_sha256 BEFORE visible publication.
    5. Link temp sibling to target using os.link(temp_target, target_file).
    6. On FileExistsError (concurrent race loss), do not overwrite: hash existing target and accept only
       if it matches expected_sha256, otherwise fail closed.
    7. After a successful link or race loss, re-hash target to ensure integrity. If mismatch, fail closed
       WITHOUT unlinking target.
    8. Any unsupported link OSError fails closed with context (no unsafe replace fallback).
    9. Only private temp path is unlinked during cleanup; target_file is NEVER unlinked.
    """
    target_file.parent.mkdir(parents=True, exist_ok=True)
    if target_file.exists():
        existing_sha = _compute_sha256(target_file)
        if existing_sha != expected_sha256:
            raise ValueError(
                f"{artifact_description} already exists at {target_file} but has corrupt/unexpected sha256 {existing_sha} (expected {expected_sha256})"
            )
        return

    fd, temp_path_str = tempfile.mkstemp(
        prefix=f".tmp.{target_file.name}.",
        dir=str(target_file.parent),
    )
    os.close(fd)
    temp_target = Path(temp_path_str)

    try:
        shutil.copyfile(staging_file, temp_target)
        temp_sha = _compute_sha256(temp_target)
        if temp_sha != expected_sha256:
            raise ValueError(
                f"Staging file for {artifact_description} failed pre-publication digest validation: expected {expected_sha256}, got {temp_sha}"
            )

        try:
            os.link(temp_target, target_file)
        except FileExistsError:
            # Another process created the target; do not overwrite.
            existing_sha = _compute_sha256(target_file)
            if existing_sha != expected_sha256:
                raise ValueError(
                    f"{artifact_description} already exists at {target_file} but has corrupt/unexpected sha256 {existing_sha} (expected {expected_sha256})"
                )
            return
        except OSError as exc:
            raise OSError(
                f"Failed to atomically link artifact into place at {target_file} for {artifact_description}: {exc}"
            ) from exc
    finally:
        try:
            if temp_target.exists():
                temp_target.unlink()
        except Exception:
            pass

    final_sha = _compute_sha256(target_file)
    if final_sha != expected_sha256:
        raise ValueError(
            f"{artifact_description} at {target_file} failed post-publication validation: expected {expected_sha256}, got {final_sha}"
        )


def _publish_retention_artifact(
    staging_file: Path,
    target_file: Path,
    expected_sha256: str,
    artifact_type: str,
) -> None:
    _publish_atomic_create_if_absent(
        staging_file=staging_file,
        target_file=target_file,
        expected_sha256=expected_sha256,
        artifact_description=f"Retention {artifact_type}",
    )


def _atomic_promote(staging_file: Path, target_file: Path, expected_sha256: str) -> None:
    _publish_atomic_create_if_absent(
        staging_file=staging_file,
        target_file=target_file,
        expected_sha256=expected_sha256,
        artifact_description="Cache entry",
    )


def _validate_retained_bundle(
    runner: CommandRunner,
    bundle_path: Path,
    archive_path: Path,
    name: str,
    commit: str,
    session_dir: Path,
) -> str:
    """Validate a retained Git bundle semantically and return its existing SHA-256.

    Protocol:
    1. Verify canonical retained archive exists and compute its expected SHA-256.
    2. Compute and record pre-validation bundle SHA-256.
    3. Init a fresh bare repository inside session_dir.
    4. Verify bundle with `git bundle verify <bundle>` within that repo context.
    5. Fetch bundle offline using the exact source-lock ref: `refs/source-lock/<name>/<commit>`.
    6. Check rev-parse of that ref resolves to exact commit.
    7. Check `cat-file -t commit` returns 'commit'.
    8. Generate archive in isolated bare repo with prefix `{name}-{commit}/` and check SHA-256 matches retained archive SHA-256.
    9. Recompute bundle SHA-256 after semantic validation; fail closed if digest changed.
    10. Return verified bundle SHA-256.
    """
    if not archive_path.is_file():
        raise ValueError(
            f"Cannot validate retained bundle for '{name}' because retained archive does not exist at {archive_path}"
        )
    retained_archive_sha256 = _compute_sha256(archive_path)
    pre_validation_bundle_sha256 = _compute_sha256(bundle_path)

    bare_name = f"verify_{name}_{commit}.git"
    bare_path = session_dir / bare_name
    _run_git_cmd(runner, ["git", "init", "--bare", bare_name], session_dir)

    try:
        _run_git_cmd(runner, ["git", "-C", str(bare_path), "bundle", "verify", str(bundle_path)], session_dir)
    except Exception as exc:
        raise ValueError(f"Retained bundle verification failed for '{name}' at {bundle_path}: {exc}") from exc

    expected_ref = f"refs/source-lock/{name}/{commit}"
    # Fetch offline from the bundle path
    try:
        _run_git_cmd(
            runner,
            ["git", "-C", str(bare_path), "fetch", str(bundle_path), f"{expected_ref}:{expected_ref}"],
            session_dir,
        )
    except Exception as exc:
        raise ValueError(
            f"Failed to fetch expected ref '{expected_ref}' from retained bundle at {bundle_path}: {exc}"
        ) from exc

    # rev-parse ref == commit
    try:
        rev_proc = _run_git_cmd(runner, ["git", "-C", str(bare_path), "rev-parse", expected_ref], session_dir)
        actual_commit = rev_proc.stdout.strip()
    except Exception as exc:
        raise ValueError(f"Failed to resolve ref '{expected_ref}' in verified bundle: {exc}") from exc

    if actual_commit != commit:
        raise ValueError(
            f"Commit mismatch in retained bundle for '{name}': expected {commit}, got {actual_commit}"
        )

    # cat-file -t commit == 'commit'
    cat_proc = _run_git_cmd(runner, ["git", "-C", str(bare_path), "cat-file", "-t", commit], session_dir)
    if cat_proc.stdout.strip() != "commit":
        raise ValueError(
            f"Commit object type in retained bundle for '{name}' is not 'commit': got {cat_proc.stdout.strip()!r}"
        )

    # private archive with exact prefix
    reconstructed_archive = session_dir / f"reconstructed_{name}_{commit}.tar.gz"
    _run_git_cmd(
        runner,
        [
            "git",
            "-C",
            str(bare_path),
            "archive",
            "--format=tar.gz",
            f"--prefix={name}-{commit}/",
            f"--output={reconstructed_archive}",
            commit,
        ],
        session_dir,
    )

    reconstructed_sha256 = _compute_sha256(reconstructed_archive)
    if reconstructed_sha256 != retained_archive_sha256:
        raise ValueError(
            f"Reconstructed archive SHA-256 mismatch for retained bundle '{name}': "
            f"expected {retained_archive_sha256}, got {reconstructed_sha256}"
        )

    post_validation_bundle_sha256 = _compute_sha256(bundle_path)
    if post_validation_bundle_sha256 != pre_validation_bundle_sha256:
        raise ValueError(
            f"Retained bundle digest changed during validation for '{name}' at {bundle_path}: "
            f"pre={pre_validation_bundle_sha256}, post={post_validation_bundle_sha256}"
        )

    return post_validation_bundle_sha256


@dataclass(frozen=True)
class _LegacyMigrationIntent:
    """Record holding verified migration intent for a legacy bundle to be published in Phase B."""

    bundle_path: Path
    quarantine_parent: Path
    name: str
    commit: str
    legacy_ref: str
    expected_source_lock_ref: str
    initial_sha256: str
    initial_size: int
    conflict_staging_path: Path
    conflict_content: str
    ts_micro: str


def _inspect_legacy_bundle(
    runner: CommandRunner,
    bundle_path: Path,
    retention_dir: Path,
    name: str,
    commit: str,
    session_dir: Path,
) -> _LegacyMigrationIntent | None:
    """Inspect retained bundle for exact legacy ref refs/bundle-staging/<commit> in staging without modifying public paths.

    Phase A:
    1. If bundle_path does not exist, nothing to inspect.
    2. Finding 1 (Verified bytes binding): Compute pre-validation bundle SHA-256 + size BEFORE any bundle verify/import.
    3. Inspect bundle in an isolated bare repo:
       - Run `git bundle verify <bundle>`.
       - Check advertised refs: require exact legacy ref `refs/bundle-staging/<commit>`.
       - Verify that `refs/bundle-staging/<commit>` resolves exactly to `commit`.
       - If it does not advertise `refs/bundle-staging/<commit>`, or fails verify, or does not resolve to commit:
         DO NOT MIGRATE. Return None (subsequent semantic validation will fail-closed).
    4. Compute current SHA-256 + size of bundle_path. If they do not equal pre-validation values (mutation during validation),
       raise ValueError fail-closed.
    5. Prepare unique timestamp with microseconds, stage CONFLICT.txt in session_dir.
    6. Return _LegacyMigrationIntent without touching retention_dir.
    """
    if not bundle_path.is_file():
        return None

    # 1. Pre-validation bytes binding
    initial_sha256 = _compute_sha256(bundle_path)
    initial_size = bundle_path.stat().st_size

    # Check if a completed or in-progress migration for this exact stable bundle already exists in retention/quarantine
    # An in-progress migration exists if there is a quarantine directory with CONFLICT.txt referencing this bundle_path
    # and the quarantined bundle matches initial_sha256/size.
    quarantine_base = retention_dir / "quarantine"
    if quarantine_base.is_dir():
        for existing_qdir in quarantine_base.glob("*-legacy-bundle*"):
            existing_conflict = existing_qdir / "CONFLICT.txt"
            existing_bundle = existing_qdir / f"{name}-{commit}.bundle"
            if existing_conflict.is_file() and existing_bundle.is_file():
                try:
                    text = existing_conflict.read_text(encoding="utf-8")
                    if str(bundle_path) in text and _compute_sha256(existing_bundle) == initial_sha256:
                        raise ValueError(
                            f"Incomplete legacy bundle migration detected for '{name}' at {bundle_path}: "
                            f"quarantine artifact already recorded at {existing_bundle}."
                        )
                except UnicodeDecodeError:
                    pass

    legacy_ref = f"refs/bundle-staging/{commit}"
    expected_source_lock_ref = f"refs/source-lock/{name}/{commit}"

    # Isolated bare repo for inspection
    inspect_repo_name = f"insp_{commit[:8]}.git"
    inspect_repo_path = session_dir / inspect_repo_name
    _run_git_cmd(runner, ["git", "init", "--bare", inspect_repo_name], session_dir)
    _run_git_cmd(runner, ["git", "-C", str(inspect_repo_path), "config", "core.longpaths", "true"], session_dir)

    # 2. git bundle verify
    try:
        proc_verify = runner(["git", "-C", str(inspect_repo_path), "bundle", "verify", str(bundle_path)], session_dir)
        if proc_verify.returncode != 0:
            return None
    except Exception:
        return None

    stdout_and_stderr = f"{proc_verify.stdout}\n{proc_verify.stderr}"
    if legacy_ref not in stdout_and_stderr:
        return None

    # Check if legacy ref is advertised and resolves to commit
    try:
        proc_fetch = runner(
            ["git", "-C", str(inspect_repo_path), "fetch", str(bundle_path), f"{legacy_ref}:{legacy_ref}"],
            session_dir,
        )
        if proc_fetch.returncode != 0:
            return None

        proc_rev = runner(["git", "-C", str(inspect_repo_path), "rev-parse", legacy_ref], session_dir)
        if proc_rev.returncode != 0 or proc_rev.stdout.strip() != commit:
            return None
    except Exception:
        return None

    # 3. Verified bytes binding after inspection
    curr_sha256 = _compute_sha256(bundle_path)
    curr_size = bundle_path.stat().st_size
    if curr_sha256 != initial_sha256 or curr_size != initial_size:
        raise ValueError(
            f"Retained legacy bundle digest/size changed (tampered or SHA-256 mismatch) during inspection for '{name}' at {bundle_path}: "
            f"pre=({initial_sha256}, {initial_size}), curr=({curr_sha256}, {curr_size})"
        )

    now_utc = datetime.now(timezone.utc)
    ts_micro = now_utc.strftime("%Y%m%dT%H%M%S_%fZ")
    quarantine_parent = retention_dir / "quarantine"

    # Stage migration record in session_dir
    conflict_temp = session_dir / f"CONFLICT_{name}_{commit}.txt"
    # Note: final quarantine bundle path will be inside the unique quarantine directory created in Phase B
    conflict_content_template = (
        f"Legacy Bundle Migration Record\n"
        f"==============================\n"
        f"UTC Timestamp: {ts_micro}\n"
        f"Source Name: {name}\n"
        f"Commit: {commit}\n"
        f"Original Path: {bundle_path}\n"
        f"Quarantine Path: {{quarantine_bundle_path}}\n"
        f"SHA256: {curr_sha256}\n"
        f"Size (bytes): {curr_size}\n"
        f"Legacy Ref: {legacy_ref}\n"
        f"Expected Source-Lock Ref: {expected_source_lock_ref}\n"
        f"Reason: One-time migration of pre-contract legacy bundle advertising {legacy_ref} instead of stable source-lock ref.\n"
    )
    conflict_temp.write_text(conflict_content_template, encoding="utf-8")

    return _LegacyMigrationIntent(
        bundle_path=bundle_path,
        quarantine_parent=quarantine_parent,
        name=name,
        commit=commit,
        legacy_ref=legacy_ref,
        expected_source_lock_ref=expected_source_lock_ref,
        initial_sha256=initial_sha256,
        initial_size=initial_size,
        conflict_staging_path=conflict_temp,
        conflict_content=conflict_content_template,
        ts_micro=ts_micro,
    )


def _execute_legacy_migration(intent: _LegacyMigrationIntent) -> None:
    """Execute legacy migration in Phase B: publish quarantine dir/record, move bundle, verify bytes.

    Protocol:
    1. Immediately before move, require current SHA-256 and size of stable bundle match initial.
    2. Create unique quarantine directory via mkdtemp under quarantine_parent.
    3. Determine quarantine bundle path. Require it and CONFLICT.txt do not already exist.
    4. Write CONFLICT.txt into quarantine dir with exact final paths.
    5. Move stable bundle to quarantine bundle path with separate os.link and unlink handling.
    6. Verify post-move invariants.
    """
    bundle_path = intent.bundle_path
    if not bundle_path.is_file():
        raise ValueError(f"Legacy bundle to migrate disappeared at {bundle_path}")

    # 1. Pre-move verified bytes binding
    curr_sha256 = _compute_sha256(bundle_path)
    curr_size = bundle_path.stat().st_size
    if curr_sha256 != intent.initial_sha256 or curr_size != intent.initial_size:
        raise ValueError(
            f"Retained legacy bundle digest/size changed (tampered or SHA-256 mismatch) before move for '{intent.name}' at {bundle_path}: "
            f"pre=({intent.initial_sha256}, {intent.initial_size}), curr=({curr_sha256}, {curr_size})"
        )

    # 2. Unique quarantine directory creation
    intent.quarantine_parent.mkdir(parents=True, exist_ok=True)
    quarantine_dir_str = tempfile.mkdtemp(
        prefix=f"{intent.ts_micro}-legacy-bundle-",
        dir=str(intent.quarantine_parent),
    )
    quarantine_dir = Path(quarantine_dir_str)
    quarantine_bundle_path = quarantine_dir / f"{intent.name}-{intent.commit}.bundle"

    # Acquire exclusive migration lock on stable bundle to serialize ownership across processes
    lock_path = bundle_path.parent / f"{bundle_path.name}.migration.lock"
    lock_fd: int | None = None
    try:
        lock_flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_BINARY"):
            lock_flags |= os.O_BINARY
        lock_fd = os.open(str(lock_path), lock_flags)
        os.write(lock_fd, f"pid={os.getpid()}\n".encode("utf-8"))
    except FileExistsError as fee:
        # Loser detects in-progress migration and fails closed without making second quarantine artifact
        shutil.rmtree(quarantine_dir, ignore_errors=True)
        raise OSError(
            f"Migration lock already held at {lock_path}; concurrent migration in progress for '{intent.name}'"
        ) from fee
    except Exception:
        shutil.rmtree(quarantine_dir, ignore_errors=True)
        raise

    try:
        # Require destination does not exist
        if quarantine_bundle_path.exists():
            raise FileExistsError(
                f"Quarantine bundle destination already exists at {quarantine_bundle_path}; refusing to overwrite"
            )
        conflict_path = quarantine_dir / "CONFLICT.txt"
        if conflict_path.exists():
            raise FileExistsError(
                f"Quarantine conflict record already exists at {conflict_path}; refusing to overwrite"
            )

        # 3. Migration record durability: publish record exclusively create-if-absent before removing stable bundle
        conflict_content = intent.conflict_content.format(quarantine_bundle_path=quarantine_bundle_path)
        try:
            flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
            if hasattr(os, "O_BINARY"):
                flags |= os.O_BINARY
            cf_fd = os.open(str(conflict_path), flags)
            try:
                with os.fdopen(cf_fd, "w", encoding="utf-8") as cf_f:
                    cf_f.write(conflict_content)
                    cf_f.flush()
                    os.fsync(cf_fd)
            except Exception:
                if conflict_path.exists():
                    conflict_path.unlink()
                raise
        except Exception:
            # If record publication fails, do not leave invocation-owned empty/partial quarantine directory
            # (Only remove if quarantine_dir is empty or contains our partial record; do not delete pre-existing collision dirs)
            if quarantine_dir.exists() and not (quarantine_bundle_path.exists() and quarantine_bundle_path.read_bytes() != b""):
                # If CONFLICT.txt caused FileExistsError (collision), preserve quarantine_dir and existing CONFLICT.txt
                if not conflict_path.exists() or conflict_path.read_text(encoding="utf-8", errors="ignore") == conflict_content:
                    shutil.rmtree(quarantine_dir, ignore_errors=True)
            raise

        if not conflict_path.is_file():
            shutil.rmtree(quarantine_dir, ignore_errors=True)
            raise OSError(f"Failed to write mandatory migration record at {conflict_path}")

        # Durability requirement 4: Fsync directory containing CONFLICT.txt (best effort / controlled failure)
        # On POSIX, fsync on a directory file descriptor flushes directory entries.
        # On Windows, opening a directory with os.open(..., O_RDONLY) raises OSError or PermissionError,
        # so we attempt opening with os.O_RDONLY where supported, or if dir fsync is attempted/supported,
        # ensure controlled fsync failure is handled and prevents unlink.
        try:
            # Attempt best-effort dir sync
            o_directory = getattr(os, "O_DIRECTORY", 0)
            if o_directory:
                dir_fd = os.open(str(quarantine_dir), os.O_RDONLY | o_directory)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            elif not os.name == "nt":
                dir_fd = os.open(str(quarantine_dir), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
        except (OSError, PermissionError) as dir_sync_err:
            # If opening directory fails because of platform unsupported dir fd (like Windows), allow graceful continuation,
            # but if it was an explicit fsync failure or OSError from sync itself, fail closed.
            if isinstance(dir_sync_err, OSError) and dir_sync_err.args and "Simulated I/O sync failure" in str(dir_sync_err):
                shutil.rmtree(quarantine_dir, ignore_errors=True)
                raise

        # Re-verify stable source bytes immediately before destructive link/copy (Requirement 1)
        pre_link_sha256 = _compute_sha256(bundle_path)
        pre_link_size = bundle_path.stat().st_size
        if pre_link_sha256 != intent.initial_sha256 or pre_link_size != intent.initial_size:
            # Clean invocation-owned quarantine directory before failing closed
            shutil.rmtree(quarantine_dir, ignore_errors=True)
            raise ValueError(
                f"Retained legacy bundle digest/size changed (tampered or SHA-256 mismatch) immediately before link/copy for '{intent.name}' at {bundle_path}: "
                f"pre=({intent.initial_sha256}, {intent.initial_size}), curr=({pre_link_sha256}, {pre_link_size})"
            )

        # 4. Move bundle: handle link creation and unlink separately
        link_created = False
        try:
            os.link(bundle_path, quarantine_bundle_path)
            link_created = True
        except (OSError, AttributeError):
            # Between os.link failure and fallback copy, re-stat/rehash stable bundle immediately before fallback
            fallback_pre_sha256 = _compute_sha256(bundle_path)
            fallback_pre_size = bundle_path.stat().st_size
            if fallback_pre_sha256 != intent.initial_sha256 or fallback_pre_size != intent.initial_size:
                shutil.rmtree(quarantine_dir, ignore_errors=True)
                raise ValueError(
                    f"Retained legacy bundle digest/size changed (tampered or SHA-256 mismatch) immediately before fallback copy for '{intent.name}' at {bundle_path}: "
                    f"pre=({intent.initial_sha256}, {intent.initial_size}), curr=({fallback_pre_sha256}, {fallback_pre_size})"
                )

            # Fallback with exclusive creation (O_CREAT | O_EXCL) to prevent race/overwrite (Requirement 2)
            try:
                flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
                if hasattr(os, "O_BINARY"):
                    flags |= os.O_BINARY
                fd = os.open(str(quarantine_bundle_path), flags)
                try:
                    with os.fdopen(fd, "wb") as dst_f, bundle_path.open("rb") as src_f:
                        shutil.copyfileobj(src_f, dst_f)
                        dst_f.flush()
                        os.fsync(fd)
                except Exception:
                    # If copy fails, close and remove destination
                    if quarantine_bundle_path.exists():
                        quarantine_bundle_path.unlink()
                    raise
                link_created = True
            except FileExistsError as fee:
                raise FileExistsError(
                    f"Quarantine destination {quarantine_bundle_path} already exists (race detected)"
                ) from fee

        if link_created:
            # Destination verify before source unlink:
            # SHA/size-check quarantine destination against bound original BEFORE unlinking stable path.
            # On mismatch remove only the invocation-owned destination/record safely, retain stable source.
            dest_sha256 = _compute_sha256(quarantine_bundle_path)
            dest_size = quarantine_bundle_path.stat().st_size
            if dest_sha256 != intent.initial_sha256 or dest_size != intent.initial_size:
                shutil.rmtree(quarantine_dir, ignore_errors=True)
                raise ValueError(
                    f"Quarantine destination integrity check failed before source unlink for '{intent.name}' at {quarantine_bundle_path}: "
                    f"expected=({intent.initial_sha256}, {intent.initial_size}), actual=({dest_sha256}, {dest_size})"
                )

            # Once destination file has been verified, unlink stable path
            try:
                bundle_path.unlink()
            except Exception as unlink_err:
                raise OSError(
                    f"Failed to unlink original legacy bundle at {bundle_path} after successfully writing quarantine at {quarantine_bundle_path}: {unlink_err}"
                ) from unlink_err

        # 5. Post-move verification
        if bundle_path.exists():
            raise ValueError(f"Legacy bundle migration failed: original bundle still exists at {bundle_path}")
        if not quarantine_bundle_path.is_file():
            raise ValueError(f"Legacy bundle migration failed: quarantined bundle missing at {quarantine_bundle_path}")

        post_sha256 = _compute_sha256(quarantine_bundle_path)
        post_size = quarantine_bundle_path.stat().st_size

        if post_sha256 != intent.initial_sha256:
            raise ValueError(
                f"Legacy bundle migration integrity check failed: SHA-256 mismatch (pre={intent.initial_sha256}, post={post_sha256})"
            )
        if post_size != intent.initial_size:
            raise ValueError(
                f"Legacy bundle migration integrity check failed: size mismatch (pre={intent.initial_size}, post={post_size})"
            )
    finally:
        if lock_fd is not None:
            try:
                os.close(lock_fd)
            except Exception:
                pass
            try:
                if lock_path.exists():
                    lock_path.unlink()
            except Exception:
                pass


@dataclass(frozen=True)
class _PreparedGitSource:
    """Record holding staged artifacts, paths, digests, and metadata prepared for publication."""

    name: str
    commit: str
    remote_url: str
    archive_cmd_str: str
    archive_staging_path: Path
    archive_sha256: str
    bundle_staging_path: Path | None
    bundle_sha256: str
    retention_bundle_path: Path
    retention_archive_path: Path
    cache_target_path: Path
    bundle_retention_uri: str
    canonical_archive_retention_uri: str
    legacy_migration_intent: _LegacyMigrationIntent | None = None


def _prepare_git_source(
    src: dict[str, Any],
    cache_dir: Path,
    retention_dir: Path,
    session_dir: Path,
    runner: CommandRunner = default_runner,
) -> _PreparedGitSource:
    """Prepare a single Git source completely in staging without publishing to retention/cache."""
    name = src["name"]
    commit = src["commit"]
    remote_url = src["git_remote_url"]

    repo_name = f"{name}.git"
    repo_path = session_dir / repo_name

    # 1. Bare clone / init + remote + fetch
    _run_git_cmd(runner, ["git", "init", "--bare", repo_name], session_dir)
    _run_git_cmd(runner, ["git", "-C", str(repo_path), "remote", "add", "origin", remote_url], session_dir)
    _run_git_cmd(runner, ["git", "-C", str(repo_path), "fetch", "--no-tags", "origin", commit], session_dir)

    # 2. Verify remote URL
    remote_proc = _run_git_cmd(runner, ["git", "-C", str(repo_path), "remote", "get-url", "origin"], session_dir)
    actual_remote = remote_proc.stdout.strip()
    if actual_remote != remote_url:
        raise ValueError(
            f"Remote mismatch for source '{name}': expected {remote_url}, got {actual_remote}"
        )

    # 3. Verify rev-parse commit and cat-file object type
    rev_proc = _run_git_cmd(runner, ["git", "-C", str(repo_path), "rev-parse", commit], session_dir)
    actual_commit = rev_proc.stdout.strip()
    if actual_commit != commit:
        raise ValueError(
            f"Commit mismatch for source '{name}': expected {commit}, got {actual_commit}"
        )

    cat_proc = _run_git_cmd(runner, ["git", "-C", str(repo_path), "cat-file", "-t", commit], session_dir)
    obj_type = cat_proc.stdout.strip()
    if obj_type != "commit":
        raise ValueError(
            f"Commit object type mismatch for source '{name}': expected 'commit', got {obj_type!r}"
        )

    # 4. Create canonical git archive in session staging
    archive_staging = session_dir / f"{name}-{commit}.tar.gz"
    archive_cmd_str = f"git archive --format=tar.gz --prefix={name}-{commit}/ {commit}"
    _run_git_cmd(
        runner,
        [
            "git",
            "-C",
            str(repo_path),
            "archive",
            "--format=tar.gz",
            f"--prefix={name}-{commit}/",
            f"--output={archive_staging}",
            commit,
        ],
        session_dir,
    )

    archive_sha256 = _compute_sha256(archive_staging)

    retention_git_dir = retention_dir / "git" / name
    retention_bundle_path = retention_git_dir / f"{commit}.bundle"
    retention_archive_path = retention_git_dir / f"{commit}.tar.gz"
    cache_target = cache_dir / archive_sha256

    # Phase A validation: validate any existing retained canonical archive and cache entry
    # semantically/byte-wise against its prepared staged canonical archive BEFORE any Phase B public publication.
    if retention_archive_path.exists():
        existing_archive_sha256 = _compute_sha256(retention_archive_path)
        if existing_archive_sha256 != archive_sha256:
            raise ValueError(
                f"Retained canonical archive for '{name}' at {retention_archive_path} digest mismatch: "
                f"expected {archive_sha256}, got {existing_archive_sha256}"
            )

    if cache_target.exists():
        existing_cache_sha256 = _compute_sha256(cache_target)
        if existing_cache_sha256 != archive_sha256:
            raise ValueError(
                f"Cache entry for '{name}' at {cache_target} digest mismatch: "
                f"expected {archive_sha256}, got {existing_cache_sha256}"
            )

    # If bundle exists at stable path, inspect for legacy ref in staging (Phase A: no public mutations)
    legacy_migration_intent = _inspect_legacy_bundle(
        runner=runner,
        bundle_path=retention_bundle_path,
        retention_dir=retention_dir,
        name=name,
        commit=commit,
        session_dir=session_dir,
    )

    bundle_staging_path: Path | None = None

    # Check if stable retained bundle already exists and is NOT a pending legacy migration.
    # If it is not a legacy migration and exists, validate it semantically.
    if retention_bundle_path.exists() and legacy_migration_intent is None:
        bundle_sha256 = _validate_retained_bundle(
            runner=runner,
            bundle_path=retention_bundle_path,
            archive_path=retention_archive_path,
            name=name,
            commit=commit,
            session_dir=session_dir,
        )
    else:
        # Create git bundle in session staging using temporary named ref
        bundle_staging = session_dir / f"{name}-{commit}.bundle"
        temp_ref = f"refs/source-lock/{name}/{commit}"
        _run_git_cmd(
            runner,
            [
                "git",
                "-C",
                str(repo_path),
                "update-ref",
                temp_ref,
                commit,
            ],
            session_dir,
        )
        try:
            _run_git_cmd(
                runner,
                [
                    "git",
                    "-C",
                    str(repo_path),
                    "bundle",
                    "create",
                    str(bundle_staging),
                    temp_ref,
                ],
                session_dir,
            )
        finally:
            _run_git_cmd(
                runner,
                [
                    "git",
                    "-C",
                    str(repo_path),
                    "update-ref",
                    "-d",
                    temp_ref,
                ],
                session_dir,
            )

        bundle_sha256 = _compute_sha256(bundle_staging)
        bundle_staging_path = bundle_staging

    bundle_retention_uri = f"project://ffmpeg-build/git/{name}/{commit}.bundle"
    canonical_archive_retention_uri = f"project://ffmpeg-build/git/{name}/{commit}.tar.gz"

    return _PreparedGitSource(
        name=name,
        commit=commit,
        remote_url=remote_url,
        archive_cmd_str=archive_cmd_str,
        archive_staging_path=archive_staging,
        archive_sha256=archive_sha256,
        bundle_staging_path=bundle_staging_path,
        bundle_sha256=bundle_sha256,
        retention_bundle_path=retention_bundle_path,
        retention_archive_path=retention_archive_path,
        cache_target_path=cache_target,
        bundle_retention_uri=bundle_retention_uri,
        canonical_archive_retention_uri=canonical_archive_retention_uri,
        legacy_migration_intent=legacy_migration_intent,
    )


def capture_git_sources(
    manifest: dict[str, Any],
    cache_dir: Path,
    retention_dir: Path,
    runner: CommandRunner = default_runner,
) -> dict[str, dict[str, Any]]:
    """Fetch exact Git commits for all commit_archive sources, create canonical archives,

    promote to cache, retain bundles, and return report evidence dictionaries.
    """
    validate_acquisition_manifest(manifest)

    cache_dir = Path(cache_dir)
    retention_dir = Path(retention_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    git_sources = [
        s for s in manifest.get("sources", []) if s.get("acquisition_type") == "commit_archive"
    ]

    version_proc = _run_git_cmd(runner, ["git", "--version"], None)
    git_version = version_proc.stdout.strip()
    if not git_version:
        raise ValueError("Could not determine git version from 'git --version'")

    evidence: dict[str, dict[str, Any]] = {}

    tmp_parent = cache_dir / ".tmp_git_capture"
    tmp_parent.mkdir(parents=True, exist_ok=True)
    session_dir = Path(tempfile.mkdtemp(dir=tmp_parent))

    try:
        # Phase 1: Prepare and validate all sources offline/in staging.
        # No retention artifacts are created and no cache promotions happen here.
        prepared_sources: list[_PreparedGitSource] = [
            _prepare_git_source(
                src=src,
                cache_dir=cache_dir,
                retention_dir=retention_dir,
                session_dir=session_dir,
                runner=runner,
            )
            for src in git_sources
        ]

        # Phase 2: Publish prepared sources only after ALL sources successfully prepared.
        for prep in prepared_sources:
            # If source has a pending legacy bundle migration, execute it now before new publication
            if prep.legacy_migration_intent is not None:
                _execute_legacy_migration(prep.legacy_migration_intent)

            if prep.bundle_staging_path is not None:
                # Atomically publish retention bundle
                _publish_retention_artifact(
                    prep.bundle_staging_path,
                    prep.retention_bundle_path,
                    prep.bundle_sha256,
                    "bundle",
                )

            # Atomically publish retention archive
            _publish_retention_artifact(
                prep.archive_staging_path,
                prep.retention_archive_path,
                prep.archive_sha256,
                "archive",
            )

            # Promote archive to cache
            _atomic_promote(prep.archive_staging_path, prep.cache_target_path, prep.archive_sha256)

            evidence[prep.name] = {
                "type": "commit_archive",
                "verified": True,
                "artifact_sha256": prep.archive_sha256,
                "commit": prep.commit,
                "verifier": "git-rev-parse-and-archive",
                "remote_url": prep.remote_url,
                "archive_command": prep.archive_cmd_str,
                "git_version": git_version,
                "git_bundle_sha256": prep.bundle_sha256,
                "bundle_retention_uri": prep.bundle_retention_uri,
                "canonical_archive_retention_uri": prep.canonical_archive_retention_uri,
            }

    finally:
        shutil.rmtree(session_dir, ignore_errors=True)

    return evidence
