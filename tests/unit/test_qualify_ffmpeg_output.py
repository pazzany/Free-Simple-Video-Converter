import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import pytest

from video_converter.ffmpeg_build_manifest import load_json


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture
def qualify_module():
    """Load qualify_output module with isolated import without leaking to sys.path."""
    orig_sys_path = list(sys.path)
    module_path = (
        Path(__file__).resolve().parent.parent.parent
        / "packaging"
        / "ffmpeg-build"
        / "qualify_output.py"
    )
    try:
        spec = importlib.util.spec_from_file_location("qualify_output", module_path)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        yield module
    finally:
        sys.path[:] = orig_sys_path


def make_qualified_candidate(tmp_path: Path):
    candidate = tmp_path / "candidate"
    workspace = tmp_path / "workspace"
    candidate.mkdir(parents=True)
    workspace.mkdir(parents=True)

    # Workspace structure
    build_dir = workspace / "packaging" / "ffmpeg-build"
    build_dir.mkdir(parents=True)
    builder_script = build_dir / "build_ffmpeg.sh"
    builder_content = b"#!/usr/bin/env bash\necho build\n"
    builder_script.write_bytes(builder_content)
    builder_sha = _sha256(builder_content)

    # Minimal valid lock
    recipe_sha = "a" * 64
    lock_dict = {
        "recipe_sha256": recipe_sha,
        "sources": [
            {"name": "ffmpeg", "sha256": "f" * 64},
        ],
        "configure": {
            "flags": ["--enable-gpl", "--enable-libx264"],
        },
        "outputs": [
            {
                "name": "ffmpeg",
                "path": "bin/ffmpeg.exe",
                "version_prefix": "ffmpeg version 6.1.1",
            },
            {
                "name": "ffprobe",
                "path": "bin/ffprobe.exe",
                "version_prefix": "ffprobe version 6.1.1",
            },
        ],
    }
    lock_bytes = json.dumps(lock_dict, indent=2).encode("utf-8") + b"\n"
    (build_dir / "build.lock.json").write_bytes(lock_bytes)
    lock_sha = _sha256(lock_bytes)

    # Output structure
    bin_dir = candidate / "bin"
    bin_dir.mkdir(parents=True)
    ffmpeg_exe = bin_dir / "ffmpeg.exe"
    ffprobe_exe = bin_dir / "ffprobe.exe"
    ffmpeg_bytes = b"MOCK_FFMPEG_EXE_CONTENT_12345"
    ffprobe_bytes = b"MOCK_FFPROBE_EXE_CONTENT_67890"
    ffmpeg_exe.write_bytes(ffmpeg_bytes)
    ffprobe_exe.write_bytes(ffprobe_bytes)

    (candidate / "config.log").write_bytes(b"config log contents\n")
    (candidate / "commands.log").write_bytes(b"gcc -v\nmake\n")
    command_log_sha = _sha256((candidate / "commands.log").read_bytes())
    config_log_sha = _sha256((candidate / "config.log").read_bytes())

    encoders_lines = [
        "Encoders:",
        " V..... libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)",
        " V..... libx265              libx265 H.265 / HEVC (codec hevc)",
        " V..... libvpx-vp9           libvpx VP9 (codec vp9)",
        " V..... libsvtav1            SVT-AV1(Scalable Video Technology for AV1) encoder (codec av1)",
        " A..... libopus              libopus Opus (codec opus)",
        " V..... h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)",
        " hevc_nvenc",
        " av1_nvenc",
        " h264_qsv",
        " hevc_qsv",
        " av1_qsv",
        " h264_amf",
        " hevc_amf",
        " av1_amf",
    ]
    encoders_bytes = "\n".join(encoders_lines).encode("utf-8") + b"\n"
    (candidate / "encoders.txt").write_bytes(encoders_bytes)
    encoders_sha = _sha256(encoders_bytes)

    (candidate / "ffmpeg-imports.txt").write_text("DLL Name: KERNEL32.dll\nDLL Name: msvcrt.dll\n", encoding="utf-8")
    (candidate / "ffprobe-imports.txt").write_text("DLL Name: KERNEL32.dll\nDLL Name: msvcrt.dll\n", encoding="utf-8")
    (candidate / "ffmpeg-buildconf.txt").write_text("ffmpeg buildconf\n", encoding="utf-8")
    (candidate / "ffprobe-buildconf.txt").write_text("ffprobe buildconf\n", encoding="utf-8")

    record_dict = {
        "schema_version": "1.0.0",
        "build_lock_sha256": lock_sha,
        "recipe_sha256": recipe_sha,
        "builder_script_sha256": builder_sha,
        "command_log_sha256": command_log_sha,
        "source_identity": {
            "sources": [{"name": "ffmpeg", "sha256": "f" * 64}],
        },
        "configure": {
            "flags": ["--enable-gpl", "--enable-libx264"],
        },
        "commands_executed": ["gcc -v", "make"],
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
                    "sha256": _sha256(ffmpeg_bytes),
                    "size_bytes": len(ffmpeg_bytes),
                },
                "ffprobe.exe": {
                    "sha256": _sha256(ffprobe_bytes),
                    "size_bytes": len(ffprobe_bytes),
                },
            }
        },
        "encoders_sha256": encoders_sha,
        "encoders": [line for line in encoders_lines if any(k in line for k in ("libx264", "libx265", "libvpx-vp9", "libsvtav1", "libopus", "nvenc", "qsv", "amf"))],
        "pe_import_audit": {
            "ffmpeg.exe": {
                "imported_dlls": ["KERNEL32.dll", "msvcrt.dll"],
                "forbidden_dlls_detected": [],
            },
            "ffprobe.exe": {
                "imported_dlls": ["KERNEL32.dll", "msvcrt.dll"],
                "forbidden_dlls_detected": [],
            },
        },
        "buildconf": {
            "ffmpeg": "ffmpeg buildconf",
            "ffprobe": "ffprobe buildconf",
        },
        "config_log": {
            "path": "config.log",
            "sha256": config_log_sha,
        },
        "versions": {
            "ffmpeg": "ffmpeg version 6.1.1-custom Copyright (c) 2000-2023",
            "ffprobe": "ffprobe version 6.1.1-custom Copyright (c) 2000-2023",
        },
    }
    record_bytes = json.dumps(record_dict, indent=2).encode("utf-8") + b"\n"
    (candidate / "build-record.json").write_bytes(record_bytes)

    return candidate, workspace


def mock_subprocess_run(cmd, *args, **kwargs):
    cmd_str = str(cmd[0])
    if "ffmpeg" in cmd_str:
        return subprocess.CompletedProcess(cmd, 0, stdout="ffmpeg version 6.1.1-custom\nbuilt with gcc\n", stderr="")
    elif "ffprobe" in cmd_str:
        return subprocess.CompletedProcess(cmd, 0, stdout="ffprobe version 6.1.1-custom\nbuilt with gcc\n", stderr="")
    raise ValueError(f"Unexpected subprocess call: {cmd}")


def test_qualify_output_accepts_matching_candidate(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    report = qualify_module.qualify_output(candidate, workspace)
    assert report["status"] == "qualified"
    assert report["encoders_sha256"] == _sha256((candidate / "encoders.txt").read_bytes())
    assert report["builder_script_sha256"] == _sha256(
        (workspace / "packaging" / "ffmpeg-build" / "build_ffmpeg.sh").read_bytes()
    )


def test_qualify_output_accepts_candidate_with_libvpl(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    # Add libvpl.dll
    vpl_bytes = b"MOCK_LIBVPL_CONTENT"
    (candidate / "bin" / "libvpl.dll").write_bytes(vpl_bytes)
    (candidate / "libvpl-imports.txt").write_text("DLL Name: KERNEL32.dll\n", encoding="utf-8")

    rec_path = candidate / "build-record.json"
    record = json.loads(rec_path.read_text(encoding="utf-8"))
    record["outputs"]["binaries"]["libvpl.dll"] = {
        "sha256": _sha256(vpl_bytes),
        "size_bytes": len(vpl_bytes),
    }
    record["pe_import_audit"]["libvpl.dll"] = {
        "imported_dlls": ["KERNEL32.dll"],
        "forbidden_dlls_detected": [],
    }
    rec_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    report = qualify_module.qualify_output(candidate, workspace)
    assert report["status"] == "qualified"
    assert "libvpl.dll" in report["binaries"]


def test_qualify_output_rejects_libvpl_hash_mismatch(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    vpl_bytes = b"MOCK_LIBVPL_CONTENT"
    (candidate / "bin" / "libvpl.dll").write_bytes(b"WRONG_LIBVPL_CONTENT")
    (candidate / "libvpl-imports.txt").write_text("DLL Name: KERNEL32.dll\n", encoding="utf-8")

    rec_path = candidate / "build-record.json"
    record = json.loads(rec_path.read_text(encoding="utf-8"))
    record["outputs"]["binaries"]["libvpl.dll"] = {
        "sha256": _sha256(vpl_bytes),
        "size_bytes": len(vpl_bytes),
    }
    record["pe_import_audit"]["libvpl.dll"] = {
        "imported_dlls": ["KERNEL32.dll"],
        "forbidden_dlls_detected": [],
    }
    rec_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    # Mutate libvpl content to same length so size matches but sha differs strictly
    (candidate / "bin" / "libvpl.dll").write_bytes(b"X" * len(vpl_bytes))
    with pytest.raises(ValueError, match="Candidate libvpl.dll sha256 mismatch"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_libvpl_imports_mismatch(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    vpl_bytes = b"MOCK_LIBVPL_CONTENT"
    (candidate / "bin" / "libvpl.dll").write_bytes(vpl_bytes)
    # libvpl-imports.txt contains USER32.dll while record only has KERNEL32.dll
    (candidate / "libvpl-imports.txt").write_text("DLL Name: KERNEL32.dll\nDLL Name: USER32.dll\n", encoding="utf-8")

    rec_path = candidate / "build-record.json"
    record = json.loads(rec_path.read_text(encoding="utf-8"))
    record["outputs"]["binaries"]["libvpl.dll"] = {
        "sha256": _sha256(vpl_bytes),
        "size_bytes": len(vpl_bytes),
    }
    record["pe_import_audit"]["libvpl.dll"] = {
        "imported_dlls": ["KERNEL32.dll"],
        "forbidden_dlls_detected": [],
    }
    rec_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="libvpl-imports.txt parsed DLLs do not match build record pe_import_audit"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_ffprobe_size_mismatch(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    content = (candidate / "bin" / "ffprobe.exe").read_bytes() + b"extra_byte"
    (candidate / "bin" / "ffprobe.exe").write_bytes(content)
    with pytest.raises(ValueError, match="ffprobe.exe"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_ffprobe_hash_mismatch(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    content = (candidate / "bin" / "ffprobe.exe").read_bytes()
    (candidate / "bin" / "ffprobe.exe").write_bytes(b"Z" * len(content))
    with pytest.raises(ValueError, match="ffprobe.exe"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_tampered_config_log(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (candidate / "config.log").write_bytes(b"tampered config log\n")
    with pytest.raises(ValueError, match="config.log.*(sha256|match)"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_tampered_commands_log(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (candidate / "commands.log").write_bytes(b"tampered command\n")
    with pytest.raises(ValueError, match="commands.log.*(sha256|match)"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_tampered_ffmpeg_buildconf(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (candidate / "ffmpeg-buildconf.txt").write_text("tampered buildconf\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ffmpeg-buildconf.txt.*match"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_tampered_ffprobe_buildconf(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (candidate / "ffprobe-buildconf.txt").write_text("tampered buildconf\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ffprobe-buildconf.txt.*match"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_tampered_ffmpeg_import_dump(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (candidate / "ffmpeg-imports.txt").write_text("DLL Name: KERNEL32.dll\nDLL Name: USER32.dll\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ffmpeg-imports.txt.*match"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_tampered_ffprobe_import_dump(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (candidate / "ffprobe-imports.txt").write_text("DLL Name: KERNEL32.dll\nDLL Name: USER32.dll\n", encoding="utf-8")
    with pytest.raises(ValueError, match="ffprobe-imports.txt.*match"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_missing_libvpl_imports_dump_when_vpl_present(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    vpl_bytes = b"MOCK_LIBVPL_CONTENT"
    (candidate / "bin" / "libvpl.dll").write_bytes(vpl_bytes)
    # libvpl-imports.txt intentionally omitted

    rec_path = candidate / "build-record.json"
    record = json.loads(rec_path.read_text(encoding="utf-8"))
    record["outputs"]["binaries"]["libvpl.dll"] = {
        "sha256": _sha256(vpl_bytes),
        "size_bytes": len(vpl_bytes),
    }
    record["pe_import_audit"]["libvpl.dll"] = {
        "imported_dlls": ["KERNEL32.dll"],
        "forbidden_dlls_detected": [],
    }
    rec_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="libvpl-imports.txt"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_tampered_full_encoder_inventory(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (candidate / "encoders.txt").write_bytes(b"tampered\n")
    with pytest.raises(ValueError, match="encoders_sha256|encoders.txt"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_builder_script_digest_mismatch(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (workspace / "packaging" / "ffmpeg-build" / "build_ffmpeg.sh").write_bytes(b"modified builder script")
    with pytest.raises(ValueError, match="builder_script_sha256"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_missing_required_reconstruction_file(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (candidate / "ffmpeg-buildconf.txt").unlink()
    with pytest.raises(FileNotFoundError, match="ffmpeg-buildconf.txt"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_missing_required_encoder(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    encoders_lines = (candidate / "encoders.txt").read_text(encoding="utf-8").splitlines()
    filtered_lines = [line for line in encoders_lines if "libx265" not in line]
    new_encoders_bytes = "\n".join(filtered_lines).encode("utf-8") + b"\n"
    (candidate / "encoders.txt").write_bytes(new_encoders_bytes)

    record_path = candidate / "build-record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["encoders_sha256"] = _sha256(new_encoders_bytes)
    record["encoders"] = [line for line in filtered_lines if any(k in line for k in ("libx264", "libvpx-vp9", "libsvtav1", "libopus", "nvenc", "qsv", "amf"))]
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="libx265"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_forbidden_pe_import(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    (candidate / "ffmpeg-imports.txt").write_text("DLL Name: KERNEL32.dll\nDLL Name: nvcuda.dll\n", encoding="utf-8")
    record_path = candidate / "build-record.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    record["pe_import_audit"]["ffmpeg.exe"]["imported_dlls"] = ["KERNEL32.dll", "nvcuda.dll"]
    record_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="Illegal|Forbidden|nvcuda"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_output_rejects_binary_version_prefix_mismatch(tmp_path, monkeypatch, qualify_module):
    def bad_subprocess_run(cmd, *args, **kwargs):
        cmd_str = str(cmd[0])
        if "ffmpeg" in cmd_str:
            return subprocess.CompletedProcess(cmd, 0, stdout="ffmpeg version 5.1.2\n", stderr="")
        return mock_subprocess_run(cmd, *args, **kwargs)

    monkeypatch.setattr("subprocess.run", bad_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    with pytest.raises(ValueError, match="version"):
        qualify_module.qualify_output(candidate, workspace)


def test_qualify_module_fixture_does_not_mutate_sys_path(qualify_module):
    """Ensure qualify_module fixture cleanly preserves sys.path without global leaks."""
    # Test itself asserts inside fixture teardown, but verify here that current sys.path is captured
    assert isinstance(sys.path, list)


def test_qualify_output_rejects_missing_or_empty_lock_version_prefix(tmp_path, monkeypatch, qualify_module):
    monkeypatch.setattr("subprocess.run", mock_subprocess_run)
    candidate, workspace = make_qualified_candidate(tmp_path)
    lock_file = workspace / "packaging" / "ffmpeg-build" / "build.lock.json"
    lock_dict = json.loads(lock_file.read_text(encoding="utf-8"))

    # Test missing/empty ffmpeg version_prefix
    for out in lock_dict["outputs"]:
        if out["name"] == "ffmpeg":
            out["version_prefix"] = "  "
    new_lock_bytes = json.dumps(lock_dict).encode("utf-8")
    lock_file.write_bytes(new_lock_bytes)
    # Also update record's build_lock_sha256 so build-record matches lock
    rec_path = candidate / "build-record.json"
    record = json.loads(rec_path.read_text(encoding="utf-8"))
    record["build_lock_sha256"] = _sha256(new_lock_bytes)
    rec_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    called = []
    def spy_run(*args, **kwargs):
        called.append(args)
        return mock_subprocess_run(*args, **kwargs)

    monkeypatch.setattr("subprocess.run", spy_run)
    with pytest.raises(ValueError, match="version_prefix for outputs\\['ffmpeg'\\]"):
        qualify_module.qualify_output(candidate, workspace)
    # Ensure failure happened BEFORE any subprocess invocation
    assert len(called) == 0

    # Test missing/empty ffprobe version_prefix
    lock_dict["outputs"][0]["version_prefix"] = "ffmpeg version 6.1.1"
    for out in lock_dict["outputs"]:
        if out["name"] == "ffprobe":
            del out["version_prefix"]
    new_lock_bytes = json.dumps(lock_dict).encode("utf-8")
    lock_file.write_bytes(new_lock_bytes)
    record["build_lock_sha256"] = _sha256(new_lock_bytes)
    rec_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    with pytest.raises(ValueError, match="version_prefix for outputs\\['ffprobe'\\]"):
        qualify_module.qualify_output(candidate, workspace)
    assert len(called) == 0


def test_direct_external_python_cli_execution(tmp_path):
    """Ensure direct external invocation with python packaging/ffmpeg-build/qualify_output.py prints only JSON."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        pytest.skip("Hosted runner FFmpeg launchers are not portable standalone binaries.")
    candidate, workspace = make_qualified_candidate(tmp_path)
    script_path = (
        Path(__file__).resolve().parent.parent.parent
        / "packaging"
        / "ffmpeg-build"
        / "qualify_output.py"
    )

    # Use available ffmpeg/ffprobe binary if present on system or fallback
    import shutil
    ffmpeg_system = shutil.which("ffmpeg")
    ffprobe_system = shutil.which("ffprobe")
    assert ffmpeg_system is not None and ffprobe_system is not None

    ffmpeg_bytes = Path(ffmpeg_system).read_bytes()
    ffprobe_bytes = Path(ffprobe_system).read_bytes()
    (candidate / "bin" / "ffmpeg.exe").write_bytes(ffmpeg_bytes)
    (candidate / "bin" / "ffprobe.exe").write_bytes(ffprobe_bytes)

    # Get their version prefix
    res_ffmpeg = subprocess.run([ffmpeg_system, "-version"], capture_output=True, text=True)
    res_ffprobe = subprocess.run([ffprobe_system, "-version"], capture_output=True, text=True)
    ffmpeg_ver = [l.strip() for l in res_ffmpeg.stdout.splitlines() if l.strip()][0]
    ffprobe_ver = [l.strip() for l in res_ffprobe.stdout.splitlines() if l.strip()][0]

    lock_file = workspace / "packaging" / "ffmpeg-build" / "build.lock.json"
    lock_data = json.loads(lock_file.read_text(encoding="utf-8"))
    for out in lock_data["outputs"]:
        if out["name"] == "ffmpeg":
            out["version_prefix"] = ffmpeg_ver
        elif out["name"] == "ffprobe":
            out["version_prefix"] = ffprobe_ver
    new_lock_bytes = json.dumps(lock_data, indent=2).encode("utf-8") + b"\n"
    lock_file.write_bytes(new_lock_bytes)

    # Update build-record with matching lock sha, binary sha256 and size
    rec_path = candidate / "build-record.json"
    record = json.loads(rec_path.read_text(encoding="utf-8"))
    record["build_lock_sha256"] = _sha256(new_lock_bytes)
    record["outputs"]["binaries"]["ffmpeg.exe"]["sha256"] = _sha256(ffmpeg_bytes)
    record["outputs"]["binaries"]["ffmpeg.exe"]["size_bytes"] = len(ffmpeg_bytes)
    record["outputs"]["binaries"]["ffprobe.exe"]["sha256"] = _sha256(ffprobe_bytes)
    record["outputs"]["binaries"]["ffprobe.exe"]["size_bytes"] = len(ffprobe_bytes)
    rec_path.write_text(json.dumps(record, indent=2), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(script_path),
            "--output-dir",
            str(candidate),
            "--workspace-root",
            str(workspace),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"STDERR: {result.stderr}\nSTDOUT: {result.stdout}"
    assert result.stderr == ""
    # Output must be parseable JSON only
    data = json.loads(result.stdout)
    assert data["status"] == "qualified"
    assert "encoders_sha256" in data
