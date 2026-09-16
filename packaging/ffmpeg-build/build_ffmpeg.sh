#!/usr/bin/env bash
# Build the locked FFmpeg toolchain in an MSYS2 UCRT64 shell. This script is
# intentionally offline: every source archive is read from --cache-dir.
set -euo pipefail

die() { printf 'build_ffmpeg.sh: %s\n' "$*" >&2; exit 2; }

if [ "${MSYSTEM:-}" != "UCRT64" ]; then
  die 'Run from the MSYS2 UCRT64 shell.'
fi

BUILD_LOCK=''
CACHE_DIR=''
WORK_DIR=''
OUTPUT_DIR=''
while [ "$#" -gt 0 ]; do
  case "$1" in
    --build-lock) BUILD_LOCK=${2:-}; shift 2 ;;
    --cache-dir) CACHE_DIR=${2:-}; shift 2 ;;
    --work-dir) WORK_DIR=${2:-}; shift 2 ;;
    --output-dir) OUTPUT_DIR=${2:-}; shift 2 ;;
    *) die "unknown or incomplete argument: $1" ;;
  esac
done
[ -n "$BUILD_LOCK" ] || die '--build-lock is required'
[ -n "$CACHE_DIR" ] || die '--cache-dir is required'
[ -n "$WORK_DIR" ] || die '--work-dir is required'
[ -n "$OUTPUT_DIR" ] || die '--output-dir is required'

for tool in gcc g++ make nasm cmake ninja meson pkgconf python sha256sum objdump tar; do
  command -v "$tool" >/dev/null 2>&1 || die "required UCRT64 tool is unavailable: $tool"
done

# Verify gcc/g++ resolve to UCRT64 toolchain and target
GCC_RESOLVED=$(type -p gcc || true)
GXX_RESOLVED=$(type -p g++ || true)
case "$GCC_RESOLVED" in
  */ucrt64/bin/gcc*|/ucrt64/bin/gcc*) ;;
  *) die "gcc does not resolve to UCRT64: $GCC_RESOLVED" ;;
esac
case "$GXX_RESOLVED" in
  */ucrt64/bin/g++*|/ucrt64/bin/g++*) ;;
  *) die "g++ does not resolve to UCRT64: $GXX_RESOLVED" ;;
esac

DUMPMACHINE=$(gcc -dumpmachine)
[ "$DUMPMACHINE" = "x86_64-w64-mingw32" ] || die "gcc -dumpmachine is '$DUMPMACHINE', expected 'x86_64-w64-mingw32'"

ROOT=$(cd "$(dirname "$0")/../.." && pwd)
SCRIPT_PATH=$(cd "$(dirname "$0")" && pwd)/$(basename "$0")
ACQUISITION_MANIFEST="$ROOT/packaging/ffmpeg-build/acquisition-manifest.json"
[ -f "$ACQUISITION_MANIFEST" ] || die "acquisition manifest missing at: $ACQUISITION_MANIFEST"
BUILD_LOCK=$(cd "$(dirname "$BUILD_LOCK")" && pwd)/$(basename "$BUILD_LOCK")
CACHE_DIR=$(cd "$CACHE_DIR" && pwd)
for directory in "$WORK_DIR" "$OUTPUT_DIR"; do
  if [ -e "$directory" ] && [ -n "$(find -L "$directory" -mindepth 1 -print -quit)" ]; then
    die "directory must be absent or empty: $directory"
  fi
done
WORK_DIR=$(mkdir -p "$WORK_DIR" && cd "$WORK_DIR" && pwd)
OUTPUT_DIR=$(mkdir -p "$OUTPUT_DIR" && cd "$OUTPUT_DIR" && pwd)
PREFIX="$WORK_DIR/prefix"
SOURCES="$WORK_DIR/sources"
LOG_DIR="$WORK_DIR/logs"
mkdir -p "$PREFIX" "$SOURCES" "$LOG_DIR" "$OUTPUT_DIR/bin"
COMMAND_LOG="$OUTPUT_DIR/commands.log"
: > "$COMMAND_LOG"

run() {
  local quoted=''
  local arg
  for arg in "$@"; do
    printf -v arg '%q' "$arg"
    quoted+="${quoted:+ }$arg"
  done
  printf '%s\n' "$quoted" >> "$COMMAND_LOG"
  "$@"
}

export PATH="$PREFIX/bin:$PATH"
export PKG_CONFIG_PATH="$PREFIX/lib/pkgconfig:$PREFIX/share/pkgconfig"
export PKG_CONFIG_LIBDIR="$PKG_CONFIG_PATH"
export CFLAGS="${CFLAGS:-} -O2"
export CXXFLAGS="${CXXFLAGS:-} -O2"

# 1. Lock validation: load acquisition manifest, check raw sha256 against lock,
# validate lock with validate_build_lock(lock, manifest), and validate cache.
PYTHONPATH="$ROOT/src" python - "$BUILD_LOCK" "$ACQUISITION_MANIFEST" "$CACHE_DIR" <<'PY'
import hashlib
from pathlib import Path
import sys
from video_converter.ffmpeg_build_manifest import (
    load_json,
    validate_build_lock,
    validate_cached_inputs,
)

lock_path = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
cache_path = Path(sys.argv[3])

manifest_bytes = manifest_path.read_bytes()
computed_manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()

lock = load_json(lock_path)
manifest = load_json(manifest_path)

lock_manifest_sha = lock.get("acquisition_manifest_sha256")
if lock_manifest_sha != computed_manifest_sha:
    raise ValueError(
        f"Acquisition manifest SHA-256 mismatch! Lock: {lock_manifest_sha}, computed: {computed_manifest_sha}"
    )

validate_build_lock(lock, manifest)
validate_cached_inputs(lock, cache_path)
PY

lock_value() {
  local source_name=$1 field=$2
  PYTHONPATH="$ROOT/src" python - "$BUILD_LOCK" "$source_name" "$field" <<'PY'
from pathlib import Path
import sys
from video_converter.ffmpeg_build_manifest import load_json

lock = load_json(Path(sys.argv[1]))
source = next(item for item in lock["sources"] if item["name"] == sys.argv[2])
value = source
for key in sys.argv[3].split("."):
    value = value[key]
print(value)
PY
}

stage_source() {
  local name=$1 sha filename archive destination
  case "$name" in
    ffmpeg|libopus)
      sha=$(lock_value "$name" sha256)
      filename=$(lock_value "$name" filename)
      ;;
    *)
      sha=$(lock_value "$name" canonical_artifact.sha256)
      filename=$(lock_value "$name" canonical_artifact.filename)
      ;;
  esac
  archive="$CACHE_DIR/$sha"
  [ -f "$archive" ] || die "locked cache artifact is missing for $name: $archive"
  [ "$(sha256sum "$archive" | awk '{print $1}')" = "$sha" ] || die "locked cache artifact hash mismatch for $name"
  destination="$SOURCES/$name"
  run rm -rf "$destination"
  run mkdir -p "$destination"
  case "$filename" in
    *.tar.xz) run tar -xJf "$archive" -C "$destination" --strip-components=1 ;;
    *.tar.gz|*.tgz) run tar -xzf "$archive" -C "$destination" --strip-components=1 ;;
    *) die "unsupported locked archive extension for $name: $filename" ;;
  esac
}

for source in x264 x265 libvpx svt-av1 libopus nv-codec-headers amf libvpl ffmpeg; do
  stage_source "$source"
done

build_x264() {
  cd "$SOURCES/x264"
  run ./configure --host=x86_64-w64-mingw32 --prefix="$PREFIX" --enable-static --disable-shared --disable-cli --enable-pic
  run make -j"$(nproc)"
  run make install
}

apply_locked_x265_patch() {
  local patch_name="$1"
  local patch_rel_path="$2"
  local patch_sha="$3"
  local patch_path PATCHES_DIR patch_filename
  patch_sha=${patch_sha%$'\r'}
  [ -n "$patch_name" ] || die "locked x265 patch name is missing"
  PATCHES_DIR=$(cd "$ROOT/packaging/ffmpeg-build/patches" && pwd -P)
  case "$patch_rel_path" in
    packaging/ffmpeg-build/patches/*.patch) ;;
    *) die "locked patch path is outside patches directory: $patch_rel_path" ;;
  esac
  patch_filename=${patch_rel_path#packaging/ffmpeg-build/patches/}
  case "$patch_filename" in *'/'*|*\\*) die "locked patch must be a direct child: $patch_rel_path" ;; esac
  case "$patch_rel_path" in *..*) die "locked patch path contains traversal: $patch_rel_path" ;; esac
  patch_path="$ROOT/$patch_rel_path"
  [ ! -L "$ROOT/packaging" ] && [ ! -L "$ROOT/packaging/ffmpeg-build" ] && [ ! -L "$ROOT/packaging/ffmpeg-build/patches" ] || die "locked patch parent directory is symlinked"
  [ ! -L "$patch_path" ] && [ -f "$patch_path" ] || die "locked patch is missing, symlinked, or not a regular file: $patch_rel_path"
  patch_path=$(cd "$(dirname "$patch_path")" && pwd -P)/$(basename "$patch_path")
  [ "$(dirname "$patch_path")" = "$PATCHES_DIR" ] || die "locked patch must be a direct child of patches directory: $patch_rel_path"
  cd "$SOURCES/x265"
  run python - "$patch_path" "$patch_sha" "$SOURCES/x265/source/CMakeLists.txt" <<'PY'
import hashlib
import sys
from pathlib import Path

patch_path = Path(sys.argv[1])
expected_patch_sha = sys.argv[2]
target_path = Path(sys.argv[3])

patch_bytes = patch_path.read_bytes()
# Git may materialize a text patch with CRLF on Windows even though the lock
# records its canonical LF form. Validate and compare that canonical form.
canonical_patch_bytes = patch_bytes.replace(b"\r\n", b"\n")
if hashlib.sha256(canonical_patch_bytes).hexdigest() != expected_patch_sha:
    raise ValueError(f"Locked patch SHA-256 mismatch for {patch_path}")
patch_text = canonical_patch_bytes.decode("utf-8")

# Recognized and approved locked x265 patches:
APPROVED_PATCHES = {
    "x265-cmake-4.4-compatibility": (
        (
            "--- a/source/CMakeLists.txt\n"
            "+++ b/source/CMakeLists.txt\n"
            "@@ -10,11 +10,11 @@\n"
            "-    cmake_policy(SET CMP0025 OLD) # report Apple's Clang as just Clang\n"
            "+    cmake_policy(SET CMP0025 NEW) # report Apple's Clang as just Clang\n"
            " endif()\n"
            " if(POLICY CMP0042)\n"
            "     cmake_policy(SET CMP0042 NEW) # MACOSX_RPATH\n"
            " endif()\n"
            " if(POLICY CMP0054)\n"
            "-    cmake_policy(SET CMP0054 OLD) # Only interpret if() arguments as variables or keywords when unquoted\n"
            "+    cmake_policy(SET CMP0054 NEW) # Only interpret if() arguments as variables or keywords when unquoted\n"
            " endif()\n"
            " \n"
            " project (x265)\n"
            "-cmake_minimum_required (VERSION 2.8.8) # OBJECT libraries require 2.8.8\n"
            "+cmake_minimum_required (VERSION 3.5) # OBJECT libraries require 2.8.8\n"
        ),
        [
            (
                "    cmake_policy(SET CMP0025 OLD) # report Apple's Clang as just Clang",
                "    cmake_policy(SET CMP0025 NEW) # report Apple's Clang as just Clang",
            ),
            (
                "    cmake_policy(SET CMP0054 OLD) # Only interpret if() arguments as variables or keywords when unquoted",
                "    cmake_policy(SET CMP0054 NEW) # Only interpret if() arguments as variables or keywords when unquoted",
            ),
            (
                "cmake_minimum_required (VERSION 2.8.8) # OBJECT libraries require 2.8.8",
                "cmake_minimum_required (VERSION 3.5) # OBJECT libraries require 2.8.8",
            ),
        ],
    ),
    "x265-pkgconfig-libs-private-no-lgcc_s": (
        (
            "--- a/source/CMakeLists.txt\n"
            "+++ b/source/CMakeLists.txt\n"
            "@@ -703,7 +703,7 @@\n"
            "     if(PLIBLIST)\n"
            "         # blacklist of libraries that should not be in Libs.private\n"
            '         list(REMOVE_ITEM PLIBLIST "-lc" "-lpthread" "-lmingwex" "-lmingwthrd"\n'
            '-            "-lmingw32" "-lmoldname" "-lmsvcrt" "-ladvapi32" "-lshell32"\n'
            '+            "-lmingw32" "-lmoldname" "-lmsvcrt" "-ladvapi32" "-lshell32" "-lgcc_s"\n'
            '             "-luser32" "-lkernel32")\n'
            '         string(REPLACE ";" " " PRIVATE_LIBS "${PLIBLIST}")\n'
            "     else()\n"
        ),
        [
            (
                '            "-lmingw32" "-lmoldname" "-lmsvcrt" "-ladvapi32" "-lshell32"\n',
                '            "-lmingw32" "-lmoldname" "-lmsvcrt" "-ladvapi32" "-lshell32" "-lgcc_s"\n',
            ),
        ],
    ),
}

patch_key = patch_path.stem
if patch_key not in APPROVED_PATCHES:
    raise ValueError(f"Unrecognized patch: {patch_key}")

expected_patch_text, pairs = APPROVED_PATCHES[patch_key]
if patch_text != expected_patch_text:
    raise ValueError("Patch contains unexpected substitutions or context")

target_text = target_path.read_bytes().decode("utf-8")

for old, new in pairs:
    old_count = target_text.count(old)
    new_count = target_text.count(new)
    if old_count != 1:
        raise ValueError(f"Expected old string exactly once in {target_path}, found {old_count}: {old}")
    if new_count != 0:
        raise ValueError(f"Expected new string zero times in {target_path}, found {new_count}: {new}")

for old, new in pairs:
    target_text = target_text.replace(old, new, 1)

for old, new in pairs:
    old_count = target_text.count(old)
    new_count = target_text.count(new)
    if old_count != 0:
        raise ValueError(f"Old string still present after replacement: {old}")
    if new_count != 1:
        raise ValueError(f"Expected new string exactly once after replacement, found {new_count}: {new}")

tmp_target = target_path.with_name(target_path.name + ".tmp")
tmp_target.write_bytes(target_text.encode("utf-8"))
tmp_target.replace(target_path)
PY
}

build_x265() {
  run cmake -S "$SOURCES/x265/source" -B "$WORK_DIR/x265-build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DENABLE_SHARED=OFF -DENABLE_CLI=OFF -DHIGH_BIT_DEPTH=OFF -DMAIN12=OFF
  run cmake --build "$WORK_DIR/x265-build"
  run cmake --install "$WORK_DIR/x265-build"
}

build_libvpx() {
  cd "$SOURCES/libvpx"
  run ./configure --target=x86_64-win64-gcc --prefix="$PREFIX" --enable-static --disable-shared \
    --disable-examples --disable-tools --disable-docs --disable-unit-tests --enable-vp9-encoder --enable-vp9-decoder
  run make -j"$(nproc)"
  run make install
}

build_svt_av1() {
  run cmake -S "$SOURCES/svt-av1" -B "$WORK_DIR/svt-av1-build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DBUILD_SHARED_LIBS=OFF -DBUILD_APPS=OFF -DBUILD_TESTING=OFF
  run cmake --build "$WORK_DIR/svt-av1-build"
  run cmake --install "$WORK_DIR/svt-av1-build"
}

build_opus() {
  cd "$SOURCES/libopus"
  run ./configure --host=x86_64-w64-mingw32 --prefix="$PREFIX" --enable-static --disable-shared --disable-extra-programs --disable-doc
  run make -j"$(nproc)"
  run make install
}

stage_hardware_headers() {
  run make -C "$SOURCES/nv-codec-headers" PREFIX="$PREFIX" install
  run mkdir -p "$PREFIX/include/AMF"
  local amf_include_dir
  amf_include_dir=$(find "$SOURCES/amf" -type d -path '*/public/include' -print -quit)
  if [ -z "$amf_include_dir" ] || [ ! -d "$amf_include_dir" ]; then
    die "Could not discover AMF public/include directory under $SOURCES/amf"
  fi
  run cp -a "$amf_include_dir/." "$PREFIX/include/AMF/"
}

build_libvpl() {
  run cmake -S "$SOURCES/libvpl" -B "$WORK_DIR/libvpl-build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DCMAKE_CXX_FLAGS=-D__STRALIGN_H_ \
    -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTS=OFF -DBUILD_TOOLS=OFF
  run cmake --build "$WORK_DIR/libvpl-build"
  run cmake --install "$WORK_DIR/libvpl-build"
}

build_ffmpeg() {
  local -a lock_flags
  mapfile -t lock_flags < <(PYTHONPATH="$ROOT/src" python - "$BUILD_LOCK" <<'PY'
from pathlib import Path
import sys
from video_converter.ffmpeg_build_manifest import load_json
for flag in load_json(Path(sys.argv[1]))["configure"]["flags"]:
    print(flag)
PY
)
  local i
  for i in "${!lock_flags[@]}"; do
    lock_flags[i]=${lock_flags[i]%$'\r'}
  done
  cd "$SOURCES/ffmpeg"
  run ./configure --prefix="$OUTPUT_DIR" --bindir="$OUTPUT_DIR/bin" --enable-static --disable-shared \
    --pkg-config=pkgconf --pkg-config-flags=--static --extra-cflags="-I$PREFIX/include -Wno-error=incompatible-pointer-types" --extra-ldflags="-static -L$PREFIX/lib -static-libgcc -static-libstdc++" \
    "${lock_flags[@]}"
  if [ -f "ffbuild/config.log" ]; then
    run cp ffbuild/config.log "$OUTPUT_DIR/config.log"
  elif [ -f "config.log" ]; then
    run cp config.log "$OUTPUT_DIR/config.log"
  else
    die "config.log not found after configure"
  fi
  run make -j"$(nproc)"
  run make install
}

build_x264
while IFS=$'\t' read -r patch_name patch_rel_path patch_sha; do
  apply_locked_x265_patch "$patch_name" "$patch_rel_path" "$patch_sha"
done < <(PYTHONPATH="$ROOT/src" python - "$BUILD_LOCK" <<'PY'
from pathlib import Path
import sys
from video_converter.ffmpeg_build_manifest import load_json

lock = load_json(Path(sys.argv[1]))
for patch in lock.get("patches", []):
    print(f"{patch['name']}\t{patch['path']}\t{patch['sha256']}")
PY
)
build_x265
build_libvpx
build_svt_av1
build_opus
stage_hardware_headers
build_libvpl
build_ffmpeg

FFMPEG="$OUTPUT_DIR/bin/ffmpeg.exe"
FFPROBE="$OUTPUT_DIR/bin/ffprobe.exe"
[ -x "$FFMPEG" ] || die 'ffmpeg.exe was not produced'
[ -x "$FFPROBE" ] || die 'ffprobe.exe was not produced'
run "$FFMPEG" -hide_banner -buildconf > "$OUTPUT_DIR/ffmpeg-buildconf.txt"
run "$FFPROBE" -hide_banner -buildconf > "$OUTPUT_DIR/ffprobe-buildconf.txt"
run "$FFMPEG" -hide_banner -encoders > "$OUTPUT_DIR/encoders.txt"
for encoder in libx264 libx265 libvpx-vp9 libsvtav1 libopus h264_nvenc hevc_nvenc av1_nvenc h264_qsv hevc_qsv av1_qsv h264_amf hevc_amf av1_amf; do
  run grep -Fq "$encoder" "$OUTPUT_DIR/encoders.txt" || die "required encoder wrapper is absent: $encoder"
done

run objdump -p "$FFMPEG" > "$OUTPUT_DIR/ffmpeg-imports.txt"
run objdump -p "$FFPROBE" > "$OUTPUT_DIR/ffprobe-imports.txt"

# Copy libvpl.dll if produced and audit it
if find "$PREFIX" -iname 'libvpl*.dll' -type f -print -quit | grep -q .; then
  vpl_source=$(find "$PREFIX" -iname 'libvpl*.dll' -type f -print -quit)
  run cp -p "$vpl_source" "$OUTPUT_DIR/bin/libvpl.dll"
  run objdump -p "$OUTPUT_DIR/bin/libvpl.dll" > "$OUTPUT_DIR/libvpl-imports.txt"
fi

# PE Audit: Reject GPU driver runtime DLLs and unwanted MinGW runtime DLLs
# Case-insensitive check of DLL imports using Python validator
LOCK_SHA=$(sha256sum "$BUILD_LOCK" | awk '{print $1}')
BUILDER_SCRIPT_SHA=$(sha256sum "$SCRIPT_PATH" | awk '{print $1}')

PYTHONPATH="$ROOT/src" run python - "$OUTPUT_DIR" "$BUILD_LOCK" "$LOCK_SHA" "$BUILDER_SCRIPT_SHA" "$DUMPMACHINE" "$GCC_RESOLVED" "$GXX_RESOLVED" "$COMMAND_LOG" <<'PY'
import hashlib
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys
from video_converter.ffmpeg_build_manifest import load_json, validate_build_record

output = Path(sys.argv[1])
lock_path = Path(sys.argv[2])
lock_sha = sys.argv[3]
builder_script_sha = sys.argv[4]
dumpmachine = sys.argv[5]
gcc_resolved = sys.argv[6]
gxx_resolved = sys.argv[7]
command_log_path = Path(sys.argv[8])
command_log_sha = sha256(command_log_path.read_bytes()).hexdigest()

lock_raw_bytes = lock_path.read_bytes()
lock = load_json(lock_path)
recipe_sha = lock.get("recipe_sha256", "")

def digest(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()

def extract_imported_dlls(import_dump_path: Path) -> list[str]:
    dlls = []
    if not import_dump_path.is_file():
        return dlls
    pattern = re.compile(r"^\s*DLL Name:\s*(\S+)", re.IGNORECASE)
    for line in import_dump_path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = pattern.match(line)
        if m:
            dlls.append(m.group(1))
    return sorted(list(set(dlls)), key=str.lower)

# Positive system DLLs allowed vs forbidden DLL patterns
# Forbidden:
# 1. GPU driver runtimes: nvencodeapi, nvcuda, amfrt, igfx, libmfx
# 2. MinGW runtimes: libgcc_s, libstdc++, libwinpthread
FORBIDDEN_DLL_PATTERN = re.compile(
    r"^(nvencodeapi|nvcuda|amfrt|igfx|libmfx|libgcc_s|libstdc\+\+|libwinpthread)",
    re.IGNORECASE,
)

pe_audit: dict = {}
for bin_name, txt_name in [
    ("ffmpeg.exe", "ffmpeg-imports.txt"),
    ("ffprobe.exe", "ffprobe-imports.txt"),
]:
    imported = extract_imported_dlls(output / txt_name)
    forbidden = [d for d in imported if FORBIDDEN_DLL_PATTERN.search(d)]
    pe_audit[bin_name] = {
        "imported_dlls": imported,
        "forbidden_dlls_detected": forbidden,
    }
    if forbidden:
        raise RuntimeError(f"Forbidden DLL imports detected in {bin_name}: {forbidden}")

vpl_dll = output / "bin" / "libvpl.dll"
if vpl_dll.is_file():
    imported = extract_imported_dlls(output / "libvpl-imports.txt")
    forbidden = [d for d in imported if FORBIDDEN_DLL_PATTERN.search(d)]
    pe_audit["libvpl.dll"] = {
        "imported_dlls": imported,
        "forbidden_dlls_detected": forbidden,
    }
    if forbidden:
        raise RuntimeError(f"Forbidden DLL imports detected in libvpl.dll: {forbidden}")

# Collect pacman -Q host evidence against lock packages without demanding identical versions
locked_pkgs = lock.get("msys2", {}).get("packages", [])
msys2_packages_inventory = []
for pkg in locked_pkgs:
    pkg_name = pkg.get("name") if isinstance(pkg, dict) else pkg
    locked_ver = pkg.get("version") if isinstance(pkg, dict) else "unknown"
    try:
        q_out = subprocess.check_output(["pacman", "-Q", pkg_name], text=True, stderr=subprocess.DEVNULL).strip()
        version_installed = q_out.split()[1] if len(q_out.split()) > 1 else q_out
    except Exception:
        version_installed = "not-found-on-host"
    msys2_packages_inventory.append({
        "package": pkg_name,
        "locked_version": locked_ver,
        "version_installed": version_installed,
        "matches_lock": (version_installed == locked_ver),
    })

tool_versions = {}
for tool in ("gcc", "g++", "make", "nasm", "cmake", "ninja", "meson", "pkgconf", "python", "sha256sum", "objdump", "tar"):
    try:
        out = subprocess.check_output([tool, "--version"], text=True, errors="replace").splitlines()[0]
    except Exception:
        out = "unknown"
    tool_versions[tool] = out

ffmpeg_bin = output / "bin" / "ffmpeg.exe"
ffprobe_bin = output / "bin" / "ffprobe.exe"
config_log_path = output / "config.log"

binaries_out = {
    "ffmpeg.exe": {
        "sha256": digest(ffmpeg_bin),
        "size_bytes": ffmpeg_bin.stat().st_size,
    },
    "ffprobe.exe": {
        "sha256": digest(ffprobe_bin),
        "size_bytes": ffprobe_bin.stat().st_size,
    },
}
if vpl_dll.is_file():
    binaries_out["libvpl.dll"] = {
        "sha256": digest(vpl_dll),
        "size_bytes": vpl_dll.stat().st_size,
    }

ffmpeg_version_line = subprocess.check_output([str(ffmpeg_bin), "-version"], text=True, errors="replace").splitlines()[0]
ffprobe_version_line = subprocess.check_output([str(ffprobe_bin), "-version"], text=True, errors="replace").splitlines()[0]

source_identities = []
for s in lock.get("sources", []):
    s_name = s.get("name")
    if s.get("acquisition_type") == "commit_archive":
        s_sha = s.get("canonical_artifact", {}).get("sha256")
    else:
        s_sha = s.get("sha256")
    source_identities.append({"name": s_name, "sha256": s_sha})

record = {
    "schema_version": "1.0.0",
    "build_lock_sha256": lock_sha,
    "recipe_sha256": recipe_sha,
    "builder_script_sha256": builder_script_sha,
    "command_log_sha256": command_log_sha,
    "source_identity": {"sources": source_identities},
    "configure": {"flags": lock.get("configure", {}).get("flags", [])},
    "commands_executed": command_log_path.read_text(encoding="utf-8").splitlines(),
    "host_inventory": {
        "toolchain": {
            "environment": "UCRT64",
            "target": "x86_64-w64-mingw32",
            "gcc_dumpmachine": dumpmachine,
            "gcc_path": gcc_resolved,
            "gxx_path": gxx_resolved,
        },
        "msys2_packages": msys2_packages_inventory,
        "tool_versions": tool_versions,
    },
    "outputs": {
        "binaries": binaries_out,
    },
    "encoders_sha256": hashlib.sha256((output / "encoders.txt").read_bytes()).hexdigest(),
    "encoders": [line for line in (output / "encoders.txt").read_text(encoding="utf-8", errors="replace").splitlines() if any(name in line for name in ("libx264", "libx265", "libvpx-vp9", "libsvtav1", "libopus", "_nvenc", "_qsv", "_amf"))],
    "pe_import_audit": pe_audit,
    "buildconf": {
        "ffmpeg": (output / "ffmpeg-buildconf.txt").read_text(encoding="utf-8", errors="replace").strip(),
        "ffprobe": (output / "ffprobe-buildconf.txt").read_text(encoding="utf-8", errors="replace").strip(),
    },
    "config_log": {
        "path": "config.log",
        "sha256": digest(config_log_path),
    },
    "versions": {
        "ffmpeg": ffmpeg_version_line,
        "ffprobe": ffprobe_version_line,
    },
}

validate_build_record(lock, record, lock_raw_bytes)
(output / "build-record.json").write_text(json.dumps(record, sort_keys=True, indent=2) + "\n", encoding="utf-8")
PY

printf 'Build complete: %s\n' "$OUTPUT_DIR"
