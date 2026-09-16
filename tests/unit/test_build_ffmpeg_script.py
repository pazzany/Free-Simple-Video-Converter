from __future__ import annotations

import copy
import hashlib
from pathlib import Path
import pytest

from video_converter.ffmpeg_build_manifest import (
    load_json,
    validate_build_record,
)


BUILD_SCRIPT = (
    Path(__file__).resolve().parents[2] / "packaging" / "ffmpeg-build" / "build_ffmpeg.sh"
)
LOCK_PATH = (
    Path(__file__).resolve().parents[2] / "packaging" / "ffmpeg-build" / "build.lock.json"
)


def sample_valid_build_record(lock: dict) -> dict:
    source_identities = []
    for s in lock.get("sources", []):
        s_name = s.get("name")
        if s.get("acquisition_type") == "commit_archive":
            s_sha = s.get("canonical_artifact", {}).get("sha256")
        else:
            s_sha = s.get("sha256")
        source_identities.append({"name": s_name, "sha256": s_sha})

    import hashlib
    import json
    lock_sha = hashlib.sha256(
        json.dumps(lock, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    ).hexdigest()

    return {
        "schema_version": "1.0.0",
        "build_lock_sha256": lock_sha,
        "recipe_sha256": lock["recipe_sha256"],
        "builder_script_sha256": "5" * 64,
        "source_identity": {"sources": source_identities},
        "configure": {"flags": list(lock["configure"]["flags"])},
        "commands_executed": [
            "./configure --host=x86_64-w64-mingw32 --prefix=/prefix --enable-static --disable-shared --disable-cli --enable-pic",
            "make -j4 && make install",
            "cmake -S /sources/x265/source -B /work/x265-build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/prefix -DENABLE_SHARED=OFF -DENABLE_CLI=OFF -DHIGH_BIT_DEPTH=OFF -DMAIN12=OFF",
            "cmake --build /work/x265-build && cmake --install /work/x265-build",
        ],
        "host_inventory": {
            "toolchain": {
                "environment": "UCRT64",
                "target": "x86_64-w64-mingw32",
                "gcc_dumpmachine": "x86_64-w64-mingw32",
                "gcc_path": "/ucrt64/bin/gcc.exe",
                "gxx_path": "/ucrt64/bin/g++.exe",
            },
            "msys2_packages": [
                {
                    "package": "mingw-w64-ucrt-x86_64-gcc",
                    "locked_version": "14.2.0-2",
                    "version_installed": "14.2.0-3",
                    "matches_lock": False,
                }
            ],
            "tool_versions": {
                "gcc": "gcc 14.2.0",
                "g++": "g++ 14.2.0",
                "make": "GNU Make 4.4.1",
                "nasm": "NASM version 2.16.03",
                "cmake": "cmake version 3.31.5",
                "ninja": "1.12.1",
                "meson": "1.6.1",
                "pkgconf": "2.3.0",
                "python": "Python 3.11.11",
                "sha256sum": "sha256sum (GNU coreutils) 9.5",
                "objdump": "GNU objdump (GNU Binutils) 2.43.1",
                "tar": "tar (GNU tar) 1.35",
            },
        },
        "outputs": {
            "binaries": {
                "ffmpeg.exe": {
                    "sha256": "2" * 64,
                    "size_bytes": 12345678,
                },
                "ffprobe.exe": {
                    "sha256": "3" * 64,
                    "size_bytes": 9876543,
                },
            }
        },
        "encoders_sha256": "e" * 64,
        "encoders": [
            " V..... libx264              libx264 H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (codec h264)",
            " V..... libx265              libx265 H.265 / HEVC (codec hevc)",
            " V..... libvpx-vp9           libvpx VP9 (codec vp9)",
            " V..... libsvtav1            SVT-AV1(Scalable Video Technology for AV1) encoder (codec av1)",
            " A..... libopus              libopus Opus (codec opus)",
            " V..... h264_nvenc           NVIDIA NVENC H.264 encoder (codec h264)",
            " V..... hevc_nvenc           NVIDIA NVENC hevc encoder (codec hevc)",
            " V..... av1_nvenc            NVIDIA NVENC av1 encoder (codec av1)",
            " V..... h264_qsv             H.264 / AVC / MPEG-4 AVC / MPEG-4 part 10 (Intel Quick Sync Video acceleration) (codec h264)",
            " V..... hevc_qsv             HEVC (Intel Quick Sync Video acceleration) (codec hevc)",
            " V..... av1_qsv              AV1 (Intel Quick Sync Video acceleration) (codec av1)",
            " V..... h264_amf             AMD AMF H.264 Encoder (codec h264)",
            " V..... hevc_amf             AMD AMF HEVC Encoder (codec hevc)",
            " V..... av1_amf              AMD AMF AV1 Encoder (codec av1)",
        ],
        "pe_import_audit": {
            "ffmpeg.exe": {
                "imported_dlls": ["KERNEL32.dll", "msvcrt.dll", "USER32.dll", "WS2_32.dll"],
                "forbidden_dlls_detected": [],
            },
            "ffprobe.exe": {
                "imported_dlls": ["KERNEL32.dll", "msvcrt.dll"],
                "forbidden_dlls_detected": [],
            },
        },
        "buildconf": {
            "ffmpeg": "  --enable-gpl --enable-libx264",
            "ffprobe": "  --enable-gpl --enable-libx264",
        },
        "config_log": {
            "path": "config.log",
            "sha256": "4" * 64,
        },
        "versions": {
            "ffmpeg": "ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers",
            "ffprobe": "ffprobe version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers",
        },
    }


def test_builder_declares_hermetic_ucrt64_contract() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert '"${MSYSTEM:-}" != "UCRT64"' in script
    for argument in ("--build-lock", "--cache-dir", "--work-dir", "--output-dir"):
        assert argument in script
    for tool in ("gcc", "nasm", "cmake", "ninja", "meson", "pkgconf", "python"):
        assert tool in script
    assert "patch;" not in script
    assert " tar;" in script or "tar python" in script or "tar" in script
    for flag in (
        "--enable-static",
        "--disable-shared",
    ):
        assert flag in script
    # Dynamic lock flags extraction
    assert 'lock_flags' in script
    assert 'load_json(Path(sys.argv[1]))["configure"]["flags"]' in script
    assert "--enable-nonfree" not in script
    for forbidden_network_command in ("curl ", "wget ", "git clone", "pacman -S"):
        assert forbidden_network_command not in script


def test_builder_uses_lock_content_addressed_source_cache() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    assert "canonical_artifact" in script
    assert "validate_build_lock(lock, manifest)" in script
    assert "validate_cached_inputs(lock, cache_path)" in script
    assert "sha256" in script


def test_builder_script_implements_review_requirements() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")

    # 1. Lock validation with acquisition manifest sha256 check
    assert "acquisition-manifest.json" in script
    assert "computed_manifest_sha" in script
    assert "lock_manifest_sha" in script
    assert "validate_build_lock(lock, manifest)" in script

    # 2. AMF public/include safe discovery
    assert "amf_include_dir=$(find" in script
    assert "*/public/include" in script
    assert "$PREFIX/include/AMF/" in script

    # 3. FFmpeg config.log copy from ffbuild/config.log
    assert "ffbuild/config.log" in script

    # 4. Toolchain UCRT verification and gcc -dumpmachine
    assert "gcc -dumpmachine" in script
    assert "x86_64-w64-mingw32" in script
    assert "/ucrt64/bin/gcc" in script
    assert "pacman" in script

    # 5. PE audit and builder script sha
    assert "builder_script_sha256" in script
    assert "recipe_sha256" in script
    assert "BUILDER_SCRIPT_SHA" in script
    assert "FORBIDDEN_DLL_PATTERN" in script
    assert "nvencodeapi" in script
    assert "libgcc_s" in script
    assert "libstdc++" in script
    assert "libwinpthread" in script

    # 6. Builder calls validate_build_record
    assert "validate_build_record(lock, record" in script
    assert 'hashlib.sha256((output / "encoders.txt").read_bytes()).hexdigest()' in script
    assert "COMMAND_LOG" in script
    assert "run()" in script
    assert "directory must be absent or empty" in script
    assert 'find -L "$directory"' in script
    assert 'run mkdir -p "$PREFIX/include/AMF"' in script
    assert 'run python - "$OUTPUT_DIR"' in script
    assert "x265-cmake-4.4-compatibility" in script
    assert "x265-pkgconfig-libs-private-no-lgcc_s" in script
    assert 'canonical_patch_bytes = patch_bytes.replace(b"\\r\\n", b"\\n")' in script
    assert "hashlib.sha256(canonical_patch_bytes).hexdigest()" in script
    assert "patch_sha=${patch_sha%$'\\r'}" in script
    assert "patch --fuzz" not in script
    assert "patch;" not in script
    assert 'run python - "$patch_path" "$patch_sha" "$SOURCES/x265/source/CMakeLists.txt"' in script
    assert "CMP0025" in script
    assert "CMP0054" in script
    assert "cmake_minimum_required" in script
    assert "-lgcc_s" in script
    assert "if patch_text != expected_patch_text" in script
    assert "for old, new in pairs:" in script
    assert "for old, new in pairs:\n    target_text = target_text.replace(old, new, 1)" in script
    assert '"$SOURCES/x265"' in script
    assert 'PATCHES_DIR=$(cd "$ROOT/packaging/ffmpeg-build/patches" && pwd -P)' in script
    assert '[ "$(dirname "$patch_path")" = "$PATCHES_DIR" ]' in script
    assert 'patch_filename=${patch_rel_path#packaging/ffmpeg-build/patches/}' in script
    assert "locked patch must be a direct child" in script
    assert "while IFS=$'\\t' read -r patch_name patch_rel_path patch_sha; do" in script
    assert 'apply_locked_x265_patch "$patch_name" "$patch_rel_path" "$patch_sha"' in script
    assert 'apply_locked_x265_patch "x265-cmake-4.4-compatibility"' not in script
    assert 'apply_locked_x265_patch "x265-pkgconfig-libs-private-no-lgcc_s"' not in script


def test_apply_locked_x265_patch_heredoc_syntax_and_patch_behavior(tmp_path: Path) -> None:
    script_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    marker = 'run python - "$patch_path" "$patch_sha" "$SOURCES/x265/source/CMakeLists.txt" <<\'PY\''
    assert marker in script_text
    heredoc_code = script_text.split(marker, 1)[1].split("\nPY", 1)[0].strip("\r\n")

    # 1. Heredoc Python code must be syntactically valid Python
    compiled = compile(heredoc_code, "apply_locked_x265_patch_heredoc", "exec")
    assert compiled is not None

    # 2. Patch 1 application behavior against representative CMakeLists.txt
    patch1_path = BUILD_SCRIPT.parent / "patches" / "x265-cmake-4.4-compatibility.patch"
    patch1_bytes = patch1_path.read_bytes()
    patch1_sha = hashlib.sha256(patch1_bytes.replace(b"\r\n", b"\n")).hexdigest()

    cmakelists_sample = (
        "# Some comments\n"
        "if(POLICY CMP0025)\n"
        "    cmake_policy(SET CMP0025 OLD) # report Apple's Clang as just Clang\n"
        "endif()\n"
        "if(POLICY CMP0042)\n"
        "    cmake_policy(SET CMP0042 NEW) # MACOSX_RPATH\n"
        "endif()\n"
        "if(POLICY CMP0054)\n"
        "    cmake_policy(SET CMP0054 OLD) # Only interpret if() arguments as variables or keywords when unquoted\n"
        "endif()\n"
        "\n"
        "project (x265)\n"
        "cmake_minimum_required (VERSION 2.8.8) # OBJECT libraries require 2.8.8\n"
        "    if(PLIBLIST)\n"
        "        # blacklist of libraries that should not be in Libs.private\n"
        '        list(REMOVE_ITEM PLIBLIST "-lc" "-lpthread" "-lmingwex" "-lmingwthrd"\n'
        '            "-lmingw32" "-lmoldname" "-lmsvcrt" "-ladvapi32" "-lshell32"\n'
        '            "-luser32" "-lkernel32")\n'
        '        string(REPLACE ";" " " PRIVATE_LIBS "${PLIBLIST}")\n'
        "    else()\n"
        "# end of header\n"
    )
    target_file = tmp_path / "CMakeLists.txt"
    target_file.write_bytes(cmakelists_sample.encode("utf-8"))

    import subprocess
    import sys
    res1 = subprocess.run(
        [sys.executable, "-c", heredoc_code, str(patch1_path), patch1_sha, str(target_file)],
        capture_output=True,
        text=True,
    )
    assert res1.returncode == 0, f"Patch 1 heredoc failed: {res1.stderr}"

    patched_content = target_file.read_text(encoding="utf-8")
    assert "cmake_policy(SET CMP0025 NEW)" in patched_content
    assert "cmake_policy(SET CMP0054 NEW)" in patched_content
    assert "cmake_minimum_required (VERSION 3.5)" in patched_content
    assert "cmake_policy(SET CMP0025 OLD)" not in patched_content
    assert "cmake_policy(SET CMP0054 OLD)" not in patched_content
    assert "cmake_minimum_required (VERSION 2.8.8)" not in patched_content

    # 3. Patch 2 application behavior against the same CMakeLists.txt
    patch2_path = BUILD_SCRIPT.parent / "patches" / "x265-pkgconfig-libs-private-no-lgcc_s.patch"
    patch2_bytes = patch2_path.read_bytes()
    patch2_sha = hashlib.sha256(patch2_bytes.replace(b"\r\n", b"\n")).hexdigest()

    res2 = subprocess.run(
        [sys.executable, "-c", heredoc_code, str(patch2_path), patch2_sha, str(target_file)],
        capture_output=True,
        text=True,
    )
    assert res2.returncode == 0, f"Patch 2 heredoc failed: {res2.stderr}"

    patched_content2 = target_file.read_bytes().decode("utf-8")
    assert '"-lshell32" "-lgcc_s"' in patched_content2
    assert '"-lshell32"\n' not in patched_content2


def test_build_x265_cmake_policy_version_minimum() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    assert "-DCMAKE_POLICY_VERSION_MINIMUM=3.5" in script


def test_build_svt_av1_cmake_policy_version_minimum() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = script.find("build_svt_av1() {")
    assert start != -1, "build_svt_av1 function not found in script"
    end = script.find("}", start)
    assert end != -1, "closing brace for build_svt_av1 not found"
    svt_block = script[start:end]
    assert "-DCMAKE_POLICY_VERSION_MINIMUM=3.5" in svt_block


def test_build_libvpl_cmake_cxx_flags_stralign() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = script.find("build_libvpl() {")
    assert start != -1, "build_libvpl function not found in script"
    end = script.find("}", start)
    assert end != -1, "closing brace for build_libvpl not found"
    libvpl_block = script[start:end]
    assert "-DCMAKE_CXX_FLAGS=-D__STRALIGN_H_" in libvpl_block
    assert "_MSC_VER" not in libvpl_block


def test_build_ffmpeg_strips_carriage_returns_from_lock_flags() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = script.find("build_ffmpeg() {")
    assert start != -1, "build_ffmpeg function not found in script"
    end = script.find("\n}\n", start)
    assert end != -1, "closing brace for build_ffmpeg not found"
    ffmpeg_block = script[start:end]
    assert 'for i in "${!lock_flags[@]}"; do' in ffmpeg_block
    assert 'lock_flags[i]=${lock_flags[i]%$' in ffmpeg_block
    assert "'\\r'}" in ffmpeg_block


def test_build_ffmpeg_pkg_config_flags_static() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = script.find("build_ffmpeg() {")
    assert start != -1, "build_ffmpeg function not found in script"
    end = script.find("\n}\n", start)
    assert end != -1, "closing brace for build_ffmpeg not found"
    ffmpeg_block = script[start:end]
    assert "--pkg-config-flags=--static" in ffmpeg_block


def test_build_ffmpeg_extra_cflags_incompatible_pointer_types() -> None:
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = script.find("build_ffmpeg() {")
    assert start != -1, "build_ffmpeg function not found in script"
    end = script.find("\n}\n", start)
    assert end != -1, "closing brace for build_ffmpeg not found"
    ffmpeg_block = script[start:end]
    assert '--extra-cflags="-I$PREFIX/include -Wno-error=incompatible-pointer-types"' in ffmpeg_block


def test_build_ffmpeg_extra_ldflags_includes_static() -> None:
    import re
    script = BUILD_SCRIPT.read_text(encoding="utf-8")
    start = script.find("build_ffmpeg() {")
    assert start != -1, "build_ffmpeg function not found in script"
    end = script.find("\n}\n", start)
    assert end != -1, "closing brace for build_ffmpeg not found"
    ffmpeg_block = script[start:end]
    match = re.search(r'--extra-ldflags="([^"]+)"', ffmpeg_block)
    assert match is not None, "--extra-ldflags not found in build_ffmpeg"
    flags = match.group(1).split()
    assert "-static" in flags, "bare '-static' flag not found in --extra-ldflags"
    assert "-L$PREFIX/lib" in flags, "-L$PREFIX/lib not found in --extra-ldflags"
    assert "-static-libgcc" in flags, "-static-libgcc not found in --extra-ldflags"
    assert "-static-libstdc++" in flags, "-static-libstdc++ not found in --extra-ldflags"




def test_validate_build_record_success_and_failures() -> None:
    lock = load_json(LOCK_PATH)
    record = sample_valid_build_record(lock)
    record["command_log_sha256"] = hashlib.sha256(
        ("\n".join(record["commands_executed"]) + "\n").encode("utf-8")
    ).hexdigest()

    # Valid build record passes validation
    validate_build_record(lock, record)

    missing_command_log_digest = copy.deepcopy(record)
    del missing_command_log_digest["command_log_sha256"]
    with pytest.raises(ValueError, match="Missing:.*'command_log_sha256'"):
        validate_build_record(lock, missing_command_log_digest)

    tampered_command_log = copy.deepcopy(record)
    tampered_command_log["commands_executed"].append("make install")
    with pytest.raises(ValueError, match="command_log_sha256 does not match commands_executed"):
        validate_build_record(lock, tampered_command_log)

    for suspicious_dll in (
        "kernel32helper.dll",
        "mfcodec-thirdparty.dll",
        "version-extra.dll",
    ):
        wrong_allowlist = copy.deepcopy(record)
        wrong_allowlist["pe_import_audit"]["ffmpeg.exe"]["imported_dlls"].append(suspicious_dll)
        with pytest.raises(ValueError, match="Illegal non-system/unauthorized DLL import detected"):
            validate_build_record(lock, wrong_allowlist)

    # Invalid lock sha256 (not matching actual lock SHA256)
    bad_lock_sha = copy.deepcopy(record)
    bad_lock_sha["build_lock_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="does not match actual lock sha256"):
        validate_build_record(lock, bad_lock_sha)

    # Wrong source hash
    bad_source_sha = copy.deepcopy(record)
    bad_source_sha["source_identity"]["sources"][0]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="sha256 mismatch"):
        validate_build_record(lock, bad_source_sha)

    # Missing builder script hash
    missing_builder_sha = copy.deepcopy(record)
    del missing_builder_sha["builder_script_sha256"]
    with pytest.raises(ValueError, match="Missing:.*'builder_script_sha256'"):
        validate_build_record(lock, missing_builder_sha)

    # Missing commands / function name instead of raw invoked command strings
    func_command = copy.deepcopy(record)
    func_command["commands_executed"] = ["build_x264"]
    with pytest.raises(ValueError, match="must record actual invoked commands"):
        validate_build_record(lock, func_command)

    # Illegal non-system DLL
    illegal_dll = copy.deepcopy(record)
    illegal_dll["pe_import_audit"]["ffmpeg.exe"]["imported_dlls"].append("some_thirdparty.dll")
    with pytest.raises(ValueError, match="Illegal non-system/unauthorized DLL import detected"):
        validate_build_record(lock, illegal_dll)

    # Wrong recipe hash (recipe mismatch)
    bad_recipe = copy.deepcopy(record)
    bad_recipe["recipe_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="recipe_sha256 does not match lock"):
        validate_build_record(lock, bad_recipe)

    # Missing binary hash / invalid hash
    bad_binary_hash = copy.deepcopy(record)
    bad_binary_hash["outputs"]["binaries"]["ffmpeg.exe"]["sha256"] = "invalid-hex"
    with pytest.raises(ValueError, match="Invalid sha256 for ffmpeg.exe"):
        validate_build_record(lock, bad_binary_hash)

    # Missing required field
    missing_field = copy.deepcopy(record)
    del missing_field["pe_import_audit"]
    with pytest.raises(ValueError, match="Missing:.*'pe_import_audit'"):
        validate_build_record(lock, missing_field)

    # Forbidden DLL import in audit
    forbidden_dll = copy.deepcopy(record)
    forbidden_dll["pe_import_audit"]["ffmpeg.exe"]["forbidden_dlls_detected"] = ["libwinpthread-1.dll"]
    with pytest.raises(ValueError, match="Forbidden DLL imports detected"):
        validate_build_record(lock, forbidden_dll)

    # Missing required encoder
    missing_enc = copy.deepcopy(record)
    missing_enc["encoders"] = [e for e in missing_enc["encoders"] if "libx264" not in e]
    with pytest.raises(ValueError, match="Missing required encoder"):
        validate_build_record(lock, missing_enc)
