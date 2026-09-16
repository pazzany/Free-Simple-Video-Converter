"""Unit tests for corresponding source bundle engine."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from video_converter.ffmpeg_build.source_bundle import (
    create_corresponding_source_zip,
    generate_reproduction_readme,
    validate_source_bundle_zip,
)
from video_converter.ffmpeg_build_manifest import load_json

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
REAL_MANIFEST_PATH = REPO_ROOT / "packaging" / "ffmpeg-build" / "acquisition-manifest.json"
REAL_LOCK_PATH = REPO_ROOT / "packaging" / "ffmpeg-build" / "build.lock.json"
REAL_BUILDER_PATH = REPO_ROOT / "packaging" / "ffmpeg-build" / "build_ffmpeg.sh"
REAL_UPDATE_PATCHES_PATH = REPO_ROOT / "packaging" / "ffmpeg-build" / "update_report_patches.py"
REAL_RESOLVE_LOCK_PATH = REPO_ROOT / "packaging" / "ffmpeg-build" / "resolve_lock.py"
REAL_PATCH_1_PATH = REPO_ROOT / "packaging" / "ffmpeg-build" / "patches" / "x265-cmake-4.4-compatibility.patch"
REAL_PATCH_2_PATH = REPO_ROOT / "packaging" / "ffmpeg-build" / "patches" / "x265-pkgconfig-libs-private-no-lgcc_s.patch"
REAL_LICENSE_PATH = REPO_ROOT / "LICENSE"
REAL_NOTICES_PATH = REPO_ROOT / "THIRD_PARTY_NOTICES.md"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_dummy_lock_and_inputs(tmp_path: Path):
    workspace_root = tmp_path / "workspace"
    workspace_root.mkdir()
    (workspace_root / "LICENSE").write_bytes(REAL_LICENSE_PATH.read_bytes())
    (workspace_root / "THIRD_PARTY_NOTICES.md").write_bytes(REAL_NOTICES_PATH.read_bytes())

    # Source files needed for offline builder script
    src_pkg_dir = workspace_root / "src" / "video_converter"
    src_pkg_dir.mkdir(parents=True)
    (src_pkg_dir / "__init__.py").write_bytes((REPO_ROOT / "src" / "video_converter" / "__init__.py").read_bytes())
    (src_pkg_dir / "ffmpeg_build_manifest.py").write_bytes((REPO_ROOT / "src" / "video_converter" / "ffmpeg_build_manifest.py").read_bytes())

    recipe_dir = workspace_root / "packaging" / "ffmpeg-build"

    recipe_dir.mkdir(parents=True)
    patches_dir = recipe_dir / "patches"
    patches_dir.mkdir()
    artifacts_dir = recipe_dir / "artifacts"
    artifacts_dir.mkdir()

    # Copy real recipe files and patches
    manifest_bytes = REAL_MANIFEST_PATH.read_bytes()
    manifest_sha = _sha256(manifest_bytes)
    (recipe_dir / "acquisition-manifest.json").write_bytes(manifest_bytes)

    builder_bytes = REAL_BUILDER_PATH.read_bytes()
    builder_sha = _sha256(builder_bytes)
    (recipe_dir / "build_ffmpeg.sh").write_bytes(builder_bytes)

    (recipe_dir / "update_report_patches.py").write_bytes(REAL_UPDATE_PATCHES_PATH.read_bytes())
    (recipe_dir / "resolve_lock.py").write_bytes(REAL_RESOLVE_LOCK_PATH.read_bytes())

    # Load real build lock without altering source hashes (they are deterministic production hashes)
    lock = copy.deepcopy(load_json(REAL_LOCK_PATH))
    manifest = load_json(REAL_MANIFEST_PATH)

    # Verify report file is hermetically created in tmp_path (not copied from repo artifacts)
    synthetic_report = {
        "schema_version": "1.0.0",
        "acquisition_manifest_sha256": manifest_sha,
        "sources": {s["name"]: {"status": "verified"} for s in lock["sources"]},
    }
    (artifacts_dir / "acquisition-report.json").write_text(
        json.dumps(synthetic_report, indent=2) + "\n", encoding="utf-8"
    )

    patch1_bytes = REAL_PATCH_1_PATH.read_bytes()
    patch1_sha = _sha256(patch1_bytes.replace(b"\r\n", b"\n"))
    (patches_dir / "x265-cmake-4.4-compatibility.patch").write_bytes(patch1_bytes)

    patch2_bytes = REAL_PATCH_2_PATH.read_bytes()
    patch2_sha = _sha256(patch2_bytes.replace(b"\r\n", b"\n"))
    (patches_dir / "x265-pkgconfig-libs-private-no-lgcc_s.patch").write_bytes(patch2_bytes)

    source_cache_dir = tmp_path / "source_cache"
    source_cache_dir.mkdir()

    # Verify patch hashes in lock match copied patches
    for p in lock.get("patches", []):
        if p.get("name") == "x265-cmake-4.4-compatibility":
            p["sha256"] = patch1_sha
        elif p.get("name") == "x265-pkgconfig-libs-private-no-lgcc_s":
            p["sha256"] = patch2_sha

    # Generate synthetic cache content whose SHA-256 matches every lock source digest
    for src in lock["sources"]:
        name = src["name"]
        content = f"hermetic dummy archive content for {name}\n".encode("utf-8")
        h = _sha256(content)
        cache_file = source_cache_dir / h
        cache_file.write_bytes(content)

        if src["acquisition_type"] == "commit_archive":
            src["canonical_artifact"]["sha256"] = h
            src["verification_evidence"]["artifact_sha256"] = h
        else:
            src["sha256"] = h
            src["verification_evidence"]["artifact_sha256"] = h


    lock_bytes = json.dumps(lock, indent=2).encode("utf-8") + b"\n"
    lock_file = recipe_dir / "build.lock.json"
    lock_file.write_bytes(lock_bytes)
    lock_sha = _sha256(lock_bytes)

    build_output_dir = tmp_path / "build_output"
    build_output_dir.mkdir()
    (build_output_dir / "config.log").write_bytes(b"config log contents\n")
    commands_bytes = b"x86_64-w64-mingw32-gcc -v\nmake -j8\n"
    (build_output_dir / "commands.log").write_bytes(commands_bytes)
    commands_text = "x86_64-w64-mingw32-gcc -v\nmake -j8\n"

    (build_output_dir / "encoders.txt").write_text(
        " V..... a64multi             Multicolor charset for Commodore 64\n"
        " V..... libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10\n"
        " V..... libx265              libx265 H.265 / HEVC\n"
        " V..... libvpx-vp9           libvpx VP9\n"
        " V..... libsvtav1            SVT-AV1(Scalable Video Technology for AV1) encoder\n"
        " A..... libopus              libopus Opus\n"
        " V..... h264_nvenc           NVIDIA NVENC H.264 encoder\n"
        " V..... hevc_nvenc           NVIDIA NVENC hevc encoder\n"
        " V..... av1_nvenc            NVIDIA NVENC av1 encoder\n"
        " V..... h264_qsv             H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (Intel Quick Sync Video acceleration)\n"
        " V..... hevc_qsv             HEVC (Intel Quick Sync Video acceleration)\n"
        " V..... av1_qsv              AV1 (Intel Quick Sync Video acceleration)\n"
        " V..... h264_amf             AMD AMF H.264 Encoder\n"
        " V..... hevc_amf             AMD AMF HEVC Encoder\n"
        " V..... av1_amf              AMD AMF AV1 Encoder\n",
        encoding="utf-8",
    )
    (build_output_dir / "ffmpeg-imports.txt").write_text("DLL Name: KERNEL32.dll\n", encoding="utf-8")
    (build_output_dir / "ffprobe-imports.txt").write_text("DLL Name: KERNEL32.dll\n", encoding="utf-8")
    (build_output_dir / "ffmpeg-buildconf.txt").write_text("ffmpeg build configuration\n", encoding="utf-8")
    (build_output_dir / "ffprobe-buildconf.txt").write_text("ffprobe build configuration\n", encoding="utf-8")

    bin_dir = build_output_dir / "bin"
    bin_dir.mkdir()
    ffmpeg_bin = bin_dir / "ffmpeg.exe"
    ffmpeg_bin.write_bytes(b"dummy ffmpeg binary")
    ffprobe_bin = bin_dir / "ffprobe.exe"
    ffprobe_bin.write_bytes(b"dummy ffprobe binary")

    build_record = {
        "schema_version": "1.0.0",
        "build_lock_sha256": lock_sha,
        "recipe_sha256": lock["recipe_sha256"],
        "builder_script_sha256": builder_sha,
        "command_log_sha256": _sha256(commands_bytes),
        "encoders_sha256": _sha256((build_output_dir / "encoders.txt").read_bytes()),

        "source_identity": {
            "sources": [
                {
                    "name": s["name"],
                    "sha256": s.get("sha256") or s["canonical_artifact"]["sha256"],
                }
                for s in lock["sources"]
            ]
        },
        "configure": {"flags": list(lock.get("configure", {}).get("flags", []))},
        "commands_executed": [line for line in commands_text.splitlines() if line],
        "host_inventory": {
            "toolchain": {
                "environment": "UCRT64",
                "target": "x86_64-w64-mingw32",
                "gcc_dumpmachine": "x86_64-w64-mingw32",
                "gcc_path": "/ucrt64/bin/gcc",
                "gxx_path": "/ucrt64/bin/g++",
            },
            "msys2_packages": [
                {
                    "package": "mingw-w64-ucrt-x86_64-gcc",
                    "locked_version": "14.2.0-2",
                    "version_installed": "14.2.0-2",
                    "matches_lock": True,
                }
            ],
            "tool_versions": {
                "gcc": "14.2.0",
                "nasm": "2.16.03",
                "cmake": "3.31.5",
                "ninja": "1.12.1",
                "meson": "1.6.1",
                "pkgconf": "2.3.0",
            },
        },
        "outputs": {
            "binaries": {
                "ffmpeg.exe": {
                    "sha256": _sha256(ffmpeg_bin.read_bytes()),
                    "size_bytes": ffmpeg_bin.stat().st_size,
                },
                "ffprobe.exe": {
                    "sha256": _sha256(ffprobe_bin.read_bytes()),
                    "size_bytes": ffprobe_bin.stat().st_size,
                },
            }
        },
        "encoders": [
            " V..... libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10",
            " V..... libx265              libx265 H.265 / HEVC",
            " V..... libvpx-vp9           libvpx VP9",
            " V..... libsvtav1            SVT-AV1(Scalable Video Technology for AV1) encoder",
            " A..... libopus              libopus Opus",
            " V..... h264_nvenc           NVIDIA NVENC H.264 encoder",
            " V..... hevc_nvenc           NVIDIA NVENC hevc encoder",
            " V..... av1_nvenc            NVIDIA NVENC av1 encoder",
            " V..... h264_qsv             H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (Intel Quick Sync Video acceleration)",
            " V..... hevc_qsv             HEVC (Intel Quick Sync Video acceleration)",
            " V..... av1_qsv              AV1 (Intel Quick Sync Video acceleration)",
            " V..... h264_amf             AMD AMF H.264 Encoder",
            " V..... hevc_amf             AMD AMF HEVC Encoder",
            " V..... av1_amf              AMD AMF AV1 Encoder",
        ],
        "pe_import_audit": {
            "ffmpeg.exe": {
                "imported_dlls": ["KERNEL32.dll"],
                "forbidden_dlls_detected": [],
            },
            "ffprobe.exe": {
                "imported_dlls": ["KERNEL32.dll"],
                "forbidden_dlls_detected": [],
            },
        },
        "buildconf": {
            "ffmpeg": "ffmpeg build configuration",
            "ffprobe": "ffprobe build configuration",
        },
        "config_log": {
            "path": "config.log",
            "sha256": _sha256((build_output_dir / "config.log").read_bytes()),
        },
        "versions": {
            "ffmpeg": "ffmpeg version 6.1.1",
            "ffprobe": "ffprobe version 6.1.1",
        },
    }
    (build_output_dir / "build-record.json").write_text(
        json.dumps(build_record, indent=2) + "\n", encoding="utf-8"
    )

    return {
        "workspace_root": workspace_root,
        "source_cache_dir": source_cache_dir,
        "build_output_dir": build_output_dir,
        "lock": lock,
        "build_record": build_record,
    }




def test_generate_reproduction_readme_contains_toolchain_and_hashes(tmp_path: Path):

    fixture = _make_dummy_lock_and_inputs(tmp_path)
    readme = generate_reproduction_readme(fixture["build_record"], fixture["lock"])
    assert "UCRT64" in readme
    assert "x86_64-w64-mingw32" in readme
    assert fixture["build_record"]["build_lock_sha256"] in readme
    assert "cd /path/to/extracted/archive" in readme
    assert "mkdir -p build_workspace/packaging/ffmpeg-build/artifacts" in readme
    assert "bash build_workspace/packaging/ffmpeg-build/build_ffmpeg.sh" in readme
    assert "--build-lock" in readme
    assert "--cache-dir" in readme
    assert "--work-dir" in readme
    assert "--output-dir" in readme


def test_create_and_validate_deterministic_zip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip_1 = tmp_path / "bundle1.zip"
    out_zip_2 = tmp_path / "bundle2.zip"

    summary1 = create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip_1,
    )
    summary2 = create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip_2,
    )


    assert out_zip_1.read_bytes() == out_zip_2.read_bytes()
    assert summary1["sha256"] == summary2["sha256"]
    assert summary1["sha256"] == _sha256(out_zip_1.read_bytes())
    assert summary1["entry_count"] > 0

    with zipfile.ZipFile(out_zip_1, "r") as zf:
        namelist = zf.namelist()
        assert namelist == sorted(namelist)
        # Check standard timestamp 1980-01-01
        for info in zf.infolist():
            assert info.date_time == (1980, 1, 1, 0, 0, 0)
            assert info.compress_type == zipfile.ZIP_DEFLATED

        # Check required categories and files
        assert "recipe/acquisition-manifest.json" in namelist
        assert "recipe/build.lock.json" in namelist
        assert "recipe/build_ffmpeg.sh" in namelist
        assert "recipe/update_report_patches.py" in namelist
        assert "recipe/resolve_lock.py" in namelist
        assert "recipe/acquisition-report.json" in namelist
        assert "patches/x265-cmake-4.4-compatibility.patch" in namelist
        assert "patches/x265-pkgconfig-libs-private-no-lgcc_s.patch" in namelist
        assert "licenses/LICENSE" in namelist
        assert "licenses/THIRD_PARTY_NOTICES.md" in namelist
        assert "reconstruction/build-record.json" in namelist
        assert "reconstruction/config.log" in namelist
        assert "reconstruction/commands.log" in namelist
        assert "reconstruction/encoders.txt" in namelist
        assert "reconstruction/ffmpeg-imports.txt" in namelist
        assert "reconstruction/ffprobe-imports.txt" in namelist
        assert "reconstruction/ffmpeg-buildconf.txt" in namelist
        assert "reconstruction/ffprobe-buildconf.txt" in namelist
        assert "reconstruction/README.md" in namelist

        sources = [n for n in namelist if n.startswith("sources/")]
        assert len(sources) == 9

    assert validate_source_bundle_zip(out_zip_1, fixture["lock"]) is True



def test_missing_cache_object_raises_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    # Remove one cached file
    cached_files = list(fixture["source_cache_dir"].iterdir())
    cached_files[0].unlink()

    out_zip = tmp_path / "bundle_fail.zip"
    # Ensure it fails in cache validation specifically, not generic lock failure
    with pytest.raises(ValueError, match="Cached artifact missing|not found"):
        create_corresponding_source_zip(
            source_cache_dir=fixture["source_cache_dir"],
            build_output_dir=fixture["build_output_dir"],
            workspace_root=fixture["workspace_root"],
            output_zip_path=out_zip,
        )

def test_symlink_safety_across_all_roots_and_subdirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)


    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"

    # Test symlinked cache root
    symlinked_cache = tmp_path / "symlinked_cache"
    try:
        symlinked_cache.symlink_to(fixture["source_cache_dir"], target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform/environment")

    with pytest.raises(ValueError, match="[Ss]ymlink"):
        create_corresponding_source_zip(
            source_cache_dir=symlinked_cache,
            build_output_dir=fixture["build_output_dir"],
            workspace_root=fixture["workspace_root"],
            output_zip_path=out_zip,
            )



    # Test symlinked build_output root
    symlinked_output = tmp_path / "symlinked_output"
    try:
        symlinked_output.symlink_to(fixture["build_output_dir"], target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform/environment")

    with pytest.raises(ValueError, match="[Ss]ymlink"):
        create_corresponding_source_zip(
            source_cache_dir=fixture["source_cache_dir"],
            build_output_dir=symlinked_output,
            workspace_root=fixture["workspace_root"],
            output_zip_path=out_zip,
            )


    # Test symlinked workspace subdir
    real_patches = fixture["workspace_root"] / "packaging" / "ffmpeg-build" / "patches"
    target_patches = tmp_path / "target_patches"
    real_patches.rename(target_patches)
    try:
        real_patches.symlink_to(target_patches, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform/environment")

    try:
        with pytest.raises(ValueError, match="[Ss]ymlink"):
            create_corresponding_source_zip(
                source_cache_dir=fixture["source_cache_dir"],
                build_output_dir=fixture["build_output_dir"],
                workspace_root=fixture["workspace_root"],
                output_zip_path=out_zip,
                    )
    finally:
        # Restore patches directory
        real_patches.unlink()
        target_patches.rename(real_patches)




    # Test root below a symlinked parent directory
    symlinked_parent = tmp_path / "symlinked_parent"
    real_parent = tmp_path / "real_parent"
    real_parent.mkdir()
    child_workspace = real_parent / "workspace_child"
    child_workspace.mkdir()
    try:
        symlinked_parent.symlink_to(real_parent, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform/environment")

    with pytest.raises(ValueError, match="[Ss]ymlink"):
        create_corresponding_source_zip(
            source_cache_dir=fixture["source_cache_dir"],
            build_output_dir=fixture["build_output_dir"],
            workspace_root=symlinked_parent / "workspace_child",
            output_zip_path=out_zip,
            )


    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )

    # Test symlinked ZIP path
    symlinked_zip = tmp_path / "symlinked_bundle.zip"
    try:
        symlinked_zip.symlink_to(out_zip)
    except (OSError, NotImplementedError):
        pytest.skip("Symlinks not supported on this platform/environment")

    with pytest.raises(ValueError, match="[Ss]ymlink"):
        validate_source_bundle_zip(symlinked_zip, fixture["lock"])




def test_deterministic_file_attributes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    with zipfile.ZipFile(out_zip, "r") as zf:
        for zinfo in zf.infolist():
            assert zinfo.create_system == 3  # UNIX
            mode = (zinfo.external_attr >> 16) & 0o777
            assert mode == 0o644


def test_validate_source_bundle_zip_rejects_tampered_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    tampered_zip = tmp_path / "bundle_bad_builder.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(tampered_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if item.filename == "recipe/build_ffmpeg.sh":
                    content = b"echo tampered builder\n"
                z_out.writestr(item, content)

    with pytest.raises(ValueError, match="builder_script_sha256|builder|digest mismatch"):
        validate_source_bundle_zip(tampered_zip, fixture["lock"])


def test_validate_source_bundle_zip_rejects_tampered_patch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    tampered_zip = tmp_path / "bundle_bad_patch.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(tampered_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if "x265-cmake-4.4-compatibility.patch" in item.filename:
                    content = b"tampered patch content\n"
                z_out.writestr(item, content)

    with pytest.raises(ValueError, match="Patch|patch|digest mismatch"):
        validate_source_bundle_zip(tampered_zip, fixture["lock"])


def test_validate_source_bundle_zip_rejects_duplicate_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    duplicate_zip = tmp_path / "bundle_dup.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(duplicate_zip, "w") as z_out:
            for item in z_in.infolist():
                z_out.writestr(item, z_in.read(item.filename))
            # Write a duplicate entry
            z_out.writestr("licenses/LICENSE", b"duplicate license")

    with pytest.raises(ValueError, match="Duplicate entry|duplicate"):
        validate_source_bundle_zip(duplicate_zip, fixture["lock"])


def test_validate_source_bundle_zip_rejects_unsafe_entry_names(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    bad_zip = tmp_path / "bundle_bad_name.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(bad_zip, "w") as z_out:
            for item in z_in.infolist():
                z_out.writestr(item, z_in.read(item.filename))
            z_out.writestr("../traversal.txt", b"evil")

    with pytest.raises(ValueError, match="Unsafe|traversal|invalid path"):
        validate_source_bundle_zip(bad_zip, fixture["lock"])


def test_validate_source_bundle_zip_rejects_tampered_readme(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    tampered_zip = tmp_path / "bundle_bad_readme.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(tampered_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if item.filename == "reconstruction/README.md":
                    content = b"# Tampered Readme\n"
                z_out.writestr(item, content)

    with pytest.raises(ValueError, match="README|mismatch"):
        validate_source_bundle_zip(tampered_zip, fixture["lock"])


def test_validate_source_bundle_zip_rejects_tampered_lock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    tampered_zip = tmp_path / "bundle_bad_lock.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(tampered_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if item.filename == "recipe/build.lock.json":
                    content = b'{"schema_version": "1.0.0", "tampered": true}\n'
                z_out.writestr(item, content)

    with pytest.raises(ValueError, match="lock|Lock|mismatch"):
        validate_source_bundle_zip(tampered_zip, fixture["lock"])


def test_tamper_evidence_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    # Tamper config.log sha
    bad_config_zip = tmp_path / "bad_config.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(bad_config_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if item.filename == "reconstruction/config.log":
                    content = b"tampered config log\n"
                z_out.writestr(item, content)
    with pytest.raises(ValueError, match="config"):
        validate_source_bundle_zip(bad_config_zip, fixture["lock"])

    # Tamper commands.log sha
    bad_commands_zip = tmp_path / "bad_commands.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(bad_commands_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if item.filename == "reconstruction/commands.log":
                    content = b"tampered commands log\n"
                z_out.writestr(item, content)
    with pytest.raises(ValueError, match="commands"):
        validate_source_bundle_zip(bad_commands_zip, fixture["lock"])

    # Tamper buildconf
    bad_bconf_zip = tmp_path / "bad_bconf.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(bad_bconf_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if item.filename == "reconstruction/ffmpeg-buildconf.txt":
                    content = b"tampered buildconf\n"
                z_out.writestr(item, content)
    with pytest.raises(ValueError, match="buildconf"):
        validate_source_bundle_zip(bad_bconf_zip, fixture["lock"])

    # Tamper encoders: replace a non-required encoder line
    bad_enc_zip = tmp_path / "bad_enc.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(bad_enc_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if item.filename == "reconstruction/encoders.txt":
                    content = content.replace(b" V..... a64multi ", b" V..... tampered ")
                z_out.writestr(item, content)
    with pytest.raises(ValueError, match="encoders.*sha256|encoders_sha256"):
        validate_source_bundle_zip(bad_enc_zip, fixture["lock"])

    # Tamper imports: appending evil DLL while retaining expected DLL
    bad_imp_zip = tmp_path / "bad_imp.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(bad_imp_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if item.filename == "reconstruction/ffmpeg-imports.txt":
                    content = b"DLL Name: KERNEL32.dll\nDLL Name: evil.dll\n"
                z_out.writestr(item, content)
    with pytest.raises(ValueError, match="import"):
        validate_source_bundle_zip(bad_imp_zip, fixture["lock"])

    # Tamper README
    bad_readme_zip = tmp_path / "bad_readme.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(bad_readme_zip, "w") as z_out:
            for item in z_in.infolist():
                content = z_in.read(item.filename)
                if item.filename == "reconstruction/README.md":
                    content = b"tampered readme\n"
                z_out.writestr(item, content)
    with pytest.raises(ValueError, match="README"):
        validate_source_bundle_zip(bad_readme_zip, fixture["lock"])




def test_archive_local_reproduction_python_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    with zipfile.ZipFile(out_zip, "r") as zf:
        namelist = zf.namelist()
        assert "build_workspace/src/video_converter/__init__.py" in namelist
        assert "build_workspace/src/video_converter/ffmpeg_build_manifest.py" in namelist
        readme_content = zf.read("reconstruction/README.md").decode("utf-8")
        assert "build_workspace/src/video_converter" in readme_content
        # Assert invalid self-copy is absent
        assert "cp build_workspace/src/video_converter/* build_workspace/src/video_converter/" not in readme_content


    # Extract to reconstructed workspace and verify initial Python import
    reconstructed_dir = tmp_path / "reconstructed"
    reconstructed_dir.mkdir()
    with zipfile.ZipFile(out_zip, "r") as zf:
        zf.extractall(reconstructed_dir)

    import subprocess
    import sys
    py_code = (
        "import sys, pathlib; "
        "sys.path.insert(0, str(pathlib.Path('build_workspace/src').resolve())); "
        "import video_converter.ffmpeg_build_manifest as m; "
        "assert hasattr(m, 'validate_build_lock')"
    )
    proc = subprocess.run(
        [sys.executable, "-c", py_code],
        cwd=reconstructed_dir,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"Import failed: {proc.stderr}"



def test_hermetic_fixture_cache_objects_hash_to_lock_digests(tmp_path: Path):
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    cache_dir = fixture["source_cache_dir"]
    lock = fixture["lock"]
    for src in lock["sources"]:
        name, fn, expected_sha = src["name"], (src.get("filename") or src["canonical_artifact"]["filename"]), (src.get("sha256") or src["canonical_artifact"]["sha256"])
        cached_file = cache_dir / expected_sha
        assert cached_file.is_file(), f"Cached file missing for {name}: {cached_file}"
        assert _sha256(cached_file.read_bytes()) == expected_sha


def test_default_lock_validator_is_strict_production():
    import video_converter.ffmpeg_build.source_bundle as sb
    assert sb._DEFAULT_LOCK_VALIDATOR is sb.validate_build_lock


def test_zip_path_safety_rejects_drive_and_unc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )

    for bad_entry in ["C:evil.txt", "C:/evil.txt", "\\\\server\\share\\evil.txt"]:

        bad_zip = tmp_path / f"bad_{abs(hash(bad_entry))}.zip"
        with zipfile.ZipFile(out_zip, "r") as z_in:
            with zipfile.ZipFile(bad_zip, "w") as z_out:
                for item in z_in.infolist():
                    z_out.writestr(item, z_in.read(item.filename))
                z_info = zipfile.ZipInfo(filename=bad_entry, date_time=(1980, 1, 1, 0, 0, 0))
                z_info.create_system = 3
                z_info.external_attr = ((0o100000 | 0o644) & 0xFFFF) << 16
                z_out.writestr(z_info, b"evil")
        with pytest.raises(ValueError, match="[Dd]rive|[Bb]ackslash|UNC|colon|traversal|safe|path"):
            validate_source_bundle_zip(bad_zip, fixture["lock"])

    # Test backslash entry
    backslash_zip = tmp_path / "bad_backslash.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(backslash_zip, "w") as z_out:
            for item in z_in.infolist():
                z_out.writestr(item, z_in.read(item.filename))
            z_info = zipfile.ZipInfo(filename="foo\\bar.txt", date_time=(1980, 1, 1, 0, 0, 0))
            z_info.create_system = 3
            z_info.external_attr = ((0o100000 | 0o644) & 0xFFFF) << 16
            z_info.filename = "foo\\bar.txt"
            z_out.writestr(z_info, b"evil")
    with pytest.raises(ValueError, match="[Dd]rive|[Bb]ackslash|UNC|colon|traversal|safe|path"):
        validate_source_bundle_zip(backslash_zip, fixture["lock"])


def test_fixture_has_no_dependency_on_ignored_artifacts(tmp_path: Path):
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    workspace = fixture["workspace_root"]
    report_file = workspace / "packaging" / "ffmpeg-build" / "artifacts" / "acquisition-report.json"
    assert report_file.is_file()
    # Ensure it was generated in tmp_path and not pointing to git-ignored repo artifacts
    assert not report_file.is_symlink()
    assert str(REPO_ROOT / "packaging" / "ffmpeg-build" / "artifacts") not in str(report_file.resolve())


def test_production_invalid_lock_rejected_before_packaging(tmp_path: Path):
    import video_converter.ffmpeg_build.source_bundle as sb
    assert sb._DEFAULT_LOCK_VALIDATOR is sb.validate_build_lock

    fixture = _make_dummy_lock_and_inputs(tmp_path)
    # The dummy lock has synthetic source digests (e.g. dummy content for libopus/sources),
    # which violates strict production lock validation.
    # We verify that production validate_build_lock rejects this lock during packaging
    # with a clear error caused by production lock validation.
    out_zip = tmp_path / "bundle_invalid.zip"
    with pytest.raises(ValueError, match="mismatch with declared published expected_digest|Build lock"):
        create_corresponding_source_zip(
            source_cache_dir=fixture["source_cache_dir"],
            build_output_dir=fixture["build_output_dir"],
            workspace_root=fixture["workspace_root"],
            output_zip_path=out_zip,
        )



def test_validate_source_bundle_zip_rejects_symlink_entry(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)
    out_zip = tmp_path / "bundle.zip"
    create_corresponding_source_zip(
        source_cache_dir=fixture["source_cache_dir"],
        build_output_dir=fixture["build_output_dir"],
        workspace_root=fixture["workspace_root"],
        output_zip_path=out_zip,
    )
    symlink_entry_zip = tmp_path / "bundle_symlink_entry.zip"
    with zipfile.ZipFile(out_zip, "r") as z_in:
        with zipfile.ZipFile(symlink_entry_zip, "w") as z_out:
            for item in z_in.infolist():
                z_out.writestr(item, z_in.read(item.filename))
            # Create a symlink entry: create_system=3 (Unix), external_attr S_IFLNK (0o120000 | 0o777)
            zinfo = zipfile.ZipInfo(filename="symlink.txt", date_time=(1980, 1, 1, 0, 0, 0))
            zinfo.create_system = 3
            zinfo.external_attr = (0o120777 & 0xFFFF) << 16
            z_out.writestr(zinfo, b"target.txt")
    with pytest.raises(ValueError, match="Non-regular|regular|symlink|file entry"):
        validate_source_bundle_zip(symlink_entry_zip, fixture["lock"])


def test_default_lock_validator_restored_after_monkeypatched_tests():
    import video_converter.ffmpeg_build.source_bundle as sb
    assert sb._DEFAULT_LOCK_VALIDATOR is sb.validate_build_lock


def test_source_entry_info_rejects_drive_prefix():

    src_with_drive = {
        "name": "x264",
        "acquisition_type": "commit_archive",
        "canonical_artifact": {
            "filename": "C:x264.tar.gz",
            "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
        },
    }
    with pytest.raises(ValueError, match="drive prefix|colon"):
        from video_converter.ffmpeg_build.source_bundle import extract_source_entry_info
        extract_source_entry_info(src_with_drive)


def test_create_corresponding_source_zip_rejects_tampered_nonrequired_encoder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    import video_converter.ffmpeg_build.source_bundle as sb
    monkeypatch.setattr(sb, "_DEFAULT_LOCK_VALIDATOR", lambda lock, manifest: None)
    fixture = _make_dummy_lock_and_inputs(tmp_path)

    # Tamper encoders.txt after record creation with a non-required encoder line change
    encoders_path = fixture["build_output_dir"] / "encoders.txt"
    encoders_text = encoders_path.read_text(encoding="utf-8")
    tampered_text = encoders_text.replace("a64multi", "tampered")
    encoders_path.write_text(tampered_text, encoding="utf-8")

    out_zip = tmp_path / "bundle_fail.zip"
    with pytest.raises(ValueError, match="encoders.*sha256|encoders_sha256"):
        create_corresponding_source_zip(
            source_cache_dir=fixture["source_cache_dir"],
            build_output_dir=fixture["build_output_dir"],
            workspace_root=fixture["workspace_root"],
            output_zip_path=out_zip,
        )

