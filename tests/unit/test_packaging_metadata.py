import json
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

# Promoted output location (external, outside the repository).
PROMOTED_OUTPUT_DIR = Path(r"D:\ffmpeg-v1-output")


def _load_promoted_record() -> dict:
    """Load the promoted build record from the active output directory."""
    record_path = PROMOTED_OUTPUT_DIR / "build-record.json"
    if not record_path.is_file():
        pytest.skip(f"Promoted output build record not found: {record_path}")
    return json.loads(record_path.read_text(encoding="utf-8"))


def _sha256_of_file(path: Path) -> str:
    import hashlib

    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def test_artifact_manifest_custom_build():
    manifest_path = REPO_ROOT / "packaging" / "ffmpeg_artifact_manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "gyan" not in data.get("artifact_name", "").lower()
    assert data.get("artifact_name") == "Local Custom UCRT64 FFmpeg 6.1.1 Static"
    assert data.get("archive_url") == "local://ffmpeg-v1-output"
    assert data.get("release_page") is None


def test_metadata_hashes_match_promoted_record():
    """Active manifest binary hashes must equal the promoted record's binary hashes."""
    record = _load_promoted_record()
    binaries = record["outputs"]["binaries"]

    manifest_path = REPO_ROOT / "packaging" / "ffmpeg_artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected = manifest["expected_binaries"]

    assert expected["ffmpeg.exe"]["sha256"] == binaries["ffmpeg.exe"]["sha256"]
    assert expected["ffprobe.exe"]["sha256"] == binaries["ffprobe.exe"]["sha256"]
    assert expected["ffmpeg.exe"]["version_prefix"] == "ffmpeg version 6.1.1"
    assert expected["ffprobe.exe"]["version_prefix"] == "ffprobe version 6.1.1"


def test_active_provenance_includes_builder_and_encoders_digests():
    """
    Active human-readable provenance artifacts must include the promoted
    record's builder_script_sha256 and encoders_sha256 exactly.
    """
    record = _load_promoted_record()
    builder_sha = record["builder_script_sha256"]
    encoders_sha = record["encoders_sha256"]

    artifact_text = (REPO_ROOT / "packaging" / "ffmpeg_release_artifact.txt").read_text(encoding="utf-8")
    checklist_text = (REPO_ROOT / "packaging" / "FFMPEG_SOURCE_RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
    notices_text = (REPO_ROOT / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")

    # Release artifact text (uppercase digests in the document)
    assert builder_sha.upper() in artifact_text
    assert encoders_sha.upper() in artifact_text

    # Checklist (uppercase digests)
    assert builder_sha.upper() in checklist_text.upper()
    assert encoders_sha.upper() in checklist_text.upper()

    # Notices (uppercase digests)
    assert builder_sha.upper() in notices_text.upper()
    assert encoders_sha.upper() in notices_text.upper()


def test_release_artifact_text_provenance():
    artifact_path = REPO_ROOT / "packaging" / "ffmpeg_release_artifact.txt"
    artifact_text = artifact_path.read_text(encoding="utf-8")

    record = _load_promoted_record()
    binaries = record["outputs"]["binaries"]
    ffmpeg_sha = binaries["ffmpeg.exe"]["sha256"].upper()
    ffprobe_sha = binaries["ffprobe.exe"]["sha256"].upper()

    def validate_artifact_text(text: str) -> None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        line_set = set(lines)

        assert "Artifact: Local Custom UCRT64 FFmpeg 6.1.1 Static" in line_set
        assert "Archive Source: local://ffmpeg-v1-output" in line_set
        assert "Provenance: Local MSYS2 UCRT64 Static Build (ffmpeg-v1-output)" in line_set
        assert "FFmpeg Upstream Source Tag: n6.1.1" in line_set
        assert "FFmpeg Upstream Commit: e38092ef93" in line_set
        assert "NVENC Headers Source Commit: 1889e62e2d35ff7aa9baca2bceb14f053785e6f1" in line_set
        assert "NVENC Interface Baseline: NVENC API 12.1" in line_set
        assert f"ffmpeg.exe SHA256: {ffmpeg_sha}" in line_set
        assert f"ffprobe.exe SHA256: {ffprobe_sha}" in line_set
        assert f"Builder Script SHA256: {record['builder_script_sha256'].upper()}" in line_set
        assert f"Encoders Inventory SHA256: {record['encoders_sha256'].upper()}" in line_set
        assert "Effective License: GNU General Public License version 2 or later (GPL-2.0-or-later)" in line_set
        assert (
            "configuration: --prefix=/d/ffmpeg-v1-candidate --bindir=/d/ffmpeg-v1-candidate/bin --enable-static --disable-shared "
            "--pkg-config=pkgconf --pkg-config-flags=--static --extra-cflags='-I/d/ffmpeg-v1-build-requalified/prefix/include "
            "-Wno-error=incompatible-pointer-types' --extra-ldflags='-static -L/d/ffmpeg-v1-build-requalified/prefix/lib "
            "-static-libgcc -static-libstdc++' --target-os=mingw32 --arch=x86_64 --enable-gpl --enable-libx264 "
            "--enable-libx265 --enable-libvpx --enable-libsvtav1 --enable-libopus --enable-nvenc --enable-libvpl "
            "--enable-amf --disable-ffplay --disable-doc"
        ) in line_set

        assert "gyan" not in text.lower()
        assert "--enable-version3" not in text
        assert "n12.1.14.0" not in text

    # Verify mutation rejection
    mutated_wrong_commit = artifact_text.replace("e38092ef93", "badbeef001")
    with pytest.raises(AssertionError):
        validate_artifact_text(mutated_wrong_commit)

    mutated_wrong_license = artifact_text.replace("GPL-2.0-or-later", "MIT")
    with pytest.raises(AssertionError):
        validate_artifact_text(mutated_wrong_license)

    mutated_wrong_config = artifact_text.replace("--enable-gpl", "--enable-version3")
    with pytest.raises(AssertionError):
        validate_artifact_text(mutated_wrong_config)

    mutated_wrong_ffmpeg_sha = artifact_text.replace(ffmpeg_sha, "WRONG_HASH")
    with pytest.raises(AssertionError):
        validate_artifact_text(mutated_wrong_ffmpeg_sha)

    mutated_wrong_builder_sha = artifact_text.replace(record["builder_script_sha256"].upper(), "X" * 64)
    with pytest.raises(AssertionError):
        validate_artifact_text(mutated_wrong_builder_sha)

    # Validate actual document
    validate_artifact_text(artifact_text)


def test_checklist_and_notices_license_and_sources():
    checklist_path = REPO_ROOT / "packaging" / "FFMPEG_SOURCE_RELEASE_CHECKLIST.md"
    notices_path = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
    checklist = checklist_path.read_text(encoding="utf-8")
    notices = notices_path.read_text(encoding="utf-8")

    record = _load_promoted_record()
    binaries = record["outputs"]["binaries"]
    ffmpeg_sha = binaries["ffmpeg.exe"]["sha256"].upper()
    ffprobe_sha = binaries["ffprobe.exe"]["sha256"].upper()
    builder_sha = record["builder_script_sha256"].upper()
    encoders_sha = record["encoders_sha256"].upper()

    def validate_checklist(text: str) -> None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        line_set = set(lines)
        assert "- **Artifact**: Local Custom UCRT64 FFmpeg 6.1.1 Static" in line_set
        assert "- **FFmpeg Source Tag**: `n6.1.1`" in line_set
        assert "- **FFmpeg Source Commit**: `e38092ef93`" in line_set
        assert f"- `ffmpeg.exe`: `{ffmpeg_sha}`" in line_set
        assert f"- `ffprobe.exe`: `{ffprobe_sha}`" in line_set
        assert f"- **Builder Script SHA256**: `{builder_sha}`" in line_set
        assert f"- **Encoders Inventory SHA256**: `{encoders_sha}`" in line_set
        assert "- **Component License**: GNU General Public License version 2 or later (GPL-2.0-or-later)" in line_set
        assert "ffmpeg-6.1.1-custom-source.zip" in line_set
        assert "gyan" not in text.lower()

    def validate_notices(text: str) -> None:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        line_set = set(lines)
        assert "- Exact version line: `ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers`" in line_set
        assert "- Exact version line: `ffprobe version 6.1.1 Copyright (c) 2007-2023 the FFmpeg developers`" in line_set
        assert f"- SHA256: `{ffmpeg_sha}`" in line_set
        assert f"- SHA256: `{ffprobe_sha}`" in line_set
        assert f"- Builder Script SHA256: `{builder_sha}`" in line_set
        assert f"- Encoders Inventory SHA256: `{encoders_sha}`" in line_set

        # Verify canonical component license line appears exactly twice (once for ffmpeg, once for ffprobe)
        license_line = "- Effective License: **GNU General Public License version 2 or later (GPL-2.0-or-later)**."
        assert lines.count(license_line) == 2

        # Semantic clause assertions for embedded FFmpeg/ffprobe binaries licensing
        assert "--enable-gpl" in text
        assert "omitting version 3 enable flags" in text
        assert "GNU General Public License version 2 or later (GPL-2.0-or-later)" in text
        assert "publisher selects a GPLv3 distribution route for binary releases" in text
        assert "allowed publisher choice pursuant to the \"or later\" terms" in text
        assert "rather than the binary's exclusive base license" in text

        assert "gyan" not in text.lower()
        assert "--enable-version3" not in text

    # Test mutation rejection on checklist
    mutated_checklist_hash = checklist.replace(ffmpeg_sha, "WRONG_HASH")
    with pytest.raises(AssertionError):
        validate_checklist(mutated_checklist_hash)

    mutated_checklist_archive = checklist.replace("ffmpeg-6.1.1-custom-source.zip", "wrong-archive.zip")
    with pytest.raises(AssertionError):
        validate_checklist(mutated_checklist_archive)

    mutated_checklist_builder = checklist.replace(builder_sha, "X" * 64)
    with pytest.raises(AssertionError):
        validate_checklist(mutated_checklist_builder)

    # Test mutation rejection on notices
    mutated_notices_license_count = notices.replace(
        "- Effective License: **GNU General Public License version 2 or later (GPL-2.0-or-later)**.",
        "- Effective License: **MIT**.",
        1,
    )
    with pytest.raises(AssertionError):
        validate_notices(mutated_notices_license_count)

    mutated_notices_license = notices.replace("GNU General Public License version 2 or later (GPL-2.0-or-later)", "GPLv3 only")
    with pytest.raises(AssertionError):
        validate_notices(mutated_notices_license)

    mutated_notices_gpl_flag = notices.replace("--enable-gpl", "--enable-version3")
    with pytest.raises(AssertionError):
        validate_notices(mutated_notices_gpl_flag)

    mutated_notices_version3_omission = notices.replace("omitting version 3 enable flags", "including version 3 enable flags")
    with pytest.raises(AssertionError):
        validate_notices(mutated_notices_version3_omission)

    mutated_notices_publisher_option = notices.replace("if the publisher selects a GPLv3 distribution route for binary releases", "always GPLv3")
    with pytest.raises(AssertionError):
        validate_notices(mutated_notices_publisher_option)

    mutated_notices_exclusive_base = notices.replace("rather than the binary's exclusive base license", "as the binary's exclusive base license")
    with pytest.raises(AssertionError):
        validate_notices(mutated_notices_exclusive_base)

    mutated_notices_ffmpeg_sha = notices.replace(ffmpeg_sha, "WRONG_HASH")
    with pytest.raises(AssertionError):
        validate_notices(mutated_notices_ffmpeg_sha)

    mutated_notices_builder_sha = notices.replace(builder_sha, "X" * 64)
    with pytest.raises(AssertionError):
        validate_notices(mutated_notices_builder_sha)

    # Validate actual documents
    validate_checklist(checklist)
    validate_notices(notices)
