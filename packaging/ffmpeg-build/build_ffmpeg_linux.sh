#!/usr/bin/env bash
# Build the locked FFmpeg toolchain natively on Ubuntu 22.04 x86_64.
# Offline for pinned sources: every source archive is read from --cache-dir.
# System toolchain and VA/DRM development headers come from apt (versions
# recorded in build-linux.lock.json).
set -euo pipefail

die() { printf 'build_ffmpeg_linux.sh: %s\n' "$*" >&2; exit 2; }

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

for tool in gcc make nasm cmake ninja python3 sha256sum tar; do
  command -v "$tool" >/dev/null 2>&1 || die "required build tool is unavailable: $tool"
done
command -v pkgconf >/dev/null 2>&1 || command -v pkg-config >/dev/null 2>&1 \
  || die "required build tool is unavailable: pkgconf (or pkg-config)"

[ "$(uname -m)" = "x86_64" ] || die "only x86_64 is supported"

CACHE_DIR=$(cd "$CACHE_DIR" && pwd)
# WORK_DIR may be reused across runs: every stage restages its sources and
# rebuilds deterministically. OUTPUT_DIR must be empty so stale binaries
# can never mix with a new build.
if [ -e "$OUTPUT_DIR" ] && [ -n "$(find -L "$OUTPUT_DIR" -mindepth 1 -print -quit)" ]; then
  die "directory must be absent or empty: $OUTPUT_DIR"
fi
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
export CFLAGS="${CFLAGS:-} -O2 -fPIC"
export CXXFLAGS="${CXXFLAGS:-} -O2 -fPIC"

# 1. Validate locked cache artifacts.
python3 - "$BUILD_LOCK" "$CACHE_DIR" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

lock = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
cache = Path(sys.argv[2])
for src in lock["sources"]:
    name = src["name"]
    if "canonical_artifact" in src:
        sha = src["canonical_artifact"]["sha256"]
    else:
        sha = src["sha256"]
    artifact = cache / sha
    if not artifact.is_file():
        raise ValueError(f"locked cache artifact is missing for {name}: {artifact}")
    actual = hashlib.sha256(artifact.read_bytes()).hexdigest()
    if actual != sha:
        raise ValueError(f"locked cache artifact hash mismatch for {name}")
print(f"cache OK: {len(lock['sources'])} sources")
PY

stage_source() {
  local name=$1 sha filename archive destination
  sha=$(python3 - "$BUILD_LOCK" "$name" <<'PY'
import json
import sys
from pathlib import Path
lock = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
src = next(item for item in lock["sources"] if item["name"] == sys.argv[2])
print(src.get("canonical_artifact", src).get("sha256") or src["sha256"])
PY
)
  filename=$(python3 - "$BUILD_LOCK" "$name" <<'PY'
import json
import sys
from pathlib import Path
lock = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
src = next(item for item in lock["sources"] if item["name"] == sys.argv[2])
print(src.get("canonical_artifact", src).get("filename") or src["filename"])
PY
)
  archive="$CACHE_DIR/$sha"
  destination="$SOURCES/$name"
  run rm -rf "$destination"
  run mkdir -p "$destination"
  case "$filename" in
    *.tar.xz) run tar -xJf "$archive" -C "$destination" --strip-components=1 ;;
    *.tar.gz|*.tgz) run tar -xzf "$archive" -C "$destination" --strip-components=1 ;;
    *) die "unsupported locked archive extension for $name: $filename" ;;
  esac
}

for source in x264 x265 libvpx svt-av1 libopus nv-codec-headers libvpl ffmpeg; do
  stage_source "$source"
done

build_x264() {
  cd "$SOURCES/x264"
  run ./configure --prefix="$PREFIX" --enable-static --disable-shared --disable-cli --enable-pic
  run make -j"$(nproc)"
  run make install
}

build_x265() {
  run cmake -S "$SOURCES/x265/source" -B "$WORK_DIR/x265-build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DENABLE_SHARED=OFF -DENABLE_CLI=OFF
  run cmake --build "$WORK_DIR/x265-build"
  run cmake --install "$WORK_DIR/x265-build"
}

build_libvpx() {
  cd "$SOURCES/libvpx"
  run ./configure --target=x86_64-linux-gcc --prefix="$PREFIX" --enable-static --disable-shared \
    --disable-examples --disable-tools --disable-docs --disable-unit-tests \
    --enable-vp8 --enable-vp9
  run make -j"$(nproc)"
  run make install
}

build_svt_av1() {
  run cmake -S "$SOURCES/svt-av1" -B "$WORK_DIR/svt-av1-build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DBUILD_SHARED_LIBS=OFF -DBUILD_APPS=OFF -DBUILD_TESTING=OFF
  run cmake --build "$WORK_DIR/svt-av1-build"
  run cmake --install "$WORK_DIR/svt-av1-build"
}

build_opus() {
  cd "$SOURCES/libopus"
  run ./configure --prefix="$PREFIX" --enable-static --disable-shared --disable-extra-programs --disable-doc
  run make -j"$(nproc)"
  run make install
}

stage_hardware_headers() {
  run make -C "$SOURCES/nv-codec-headers" PREFIX="$PREFIX" install
}

build_libvpl() {
  run cmake -S "$SOURCES/libvpl" -B "$WORK_DIR/libvpl-build" -G Ninja \
    -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$PREFIX" \
    -DBUILD_SHARED_LIBS=OFF -DBUILD_TESTS=OFF -DBUILD_TOOLS=OFF
  run cmake --build "$WORK_DIR/libvpl-build"
  run cmake --install "$WORK_DIR/libvpl-build"
}

build_ffmpeg() {
  local -a lock_flags
  mapfile -t lock_flags < <(python3 - "$BUILD_LOCK" <<'PY'
import json
import sys
from pathlib import Path
for flag in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))["configure"]["flags"]:
    print(flag)
PY
)
  cd "$SOURCES/ffmpeg"
  run ./configure --prefix="$OUTPUT_DIR" --bindir="$OUTPUT_DIR/bin" --enable-static --disable-shared \
    --pkg-config=pkgconf --pkg-config-flags=--static --extra-cflags="-I$PREFIX/include" --extra-ldflags="-L$PREFIX/lib" \
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
build_x265
build_libvpx
build_svt_av1
build_opus
stage_hardware_headers
build_libvpl
build_ffmpeg

# Reconstruction evidence and build record.
"$OUTPUT_DIR/bin/ffmpeg" -hide_banner -encoders > "$OUTPUT_DIR/encoders.txt"
"$OUTPUT_DIR/bin/ffmpeg" -hide_banner -buildconf > "$OUTPUT_DIR/ffmpeg-buildconf.txt" 2>&1 || "$OUTPUT_DIR/bin/ffmpeg" -buildconf > "$OUTPUT_DIR/ffmpeg-buildconf.txt"
"$OUTPUT_DIR/bin/ffprobe" -hide_banner -buildconf > "$OUTPUT_DIR/ffprobe-buildconf.txt" 2>&1 || "$OUTPUT_DIR/bin/ffprobe" -buildconf > "$OUTPUT_DIR/ffprobe-buildconf.txt"
ldd "$OUTPUT_DIR/bin/ffmpeg" > "$OUTPUT_DIR/ffmpeg-deps.txt" 2>&1 || true
ldd "$OUTPUT_DIR/bin/ffprobe" > "$OUTPUT_DIR/ffprobe-deps.txt" 2>&1 || true
"$OUTPUT_DIR/bin/ffmpeg" -hide_banner -hwaccels > "$OUTPUT_DIR/hwaccels.txt" 2>&1 || true

python3 - "$OUTPUT_DIR" "$BUILD_LOCK" "$0" <<'PY'
import hashlib
import json
import sys
from pathlib import Path

output_dir = Path(sys.argv[1])
lock = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
builder_bytes = Path(sys.argv[3]).read_bytes()

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

binaries = {}
for out in lock["outputs"]:
    name = Path(out["path"]).name
    data = (output_dir / out["path"]).read_bytes()
    binaries[name] = {"sha256": hashlib.sha256(data).hexdigest(), "size_bytes": len(data)}

record = {
    "schema_version": "1.0.0",
    "target": lock["target"],
    "toolchain": lock["toolchain"],
    "builder_script_sha256": hashlib.sha256(builder_bytes).hexdigest(),
    "configure_flags": lock["configure"]["flags"],
    "config_log": {"sha256": sha(output_dir / "config.log")},
    "command_log_sha256": sha(output_dir / "commands.log"),
    "encoders_sha256": sha(output_dir / "encoders.txt"),
    "buildconf": {
        "ffmpeg": (output_dir / "ffmpeg-buildconf.txt").read_text(encoding="utf-8", errors="replace"),
        "ffprobe": (output_dir / "ffprobe-buildconf.txt").read_text(encoding="utf-8", errors="replace"),
    },
    "outputs": {"binaries": binaries},
}
(output_dir / "build-record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"status": "built", "binaries": binaries}, indent=2))
PY

printf 'Linux FFmpeg build complete: %s\n' "$OUTPUT_DIR"
