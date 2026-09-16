# FFmpeg Corresponding Source Release Checklist

This document details the exact obligations, archive contents, and pre-release verification procedure required to distribute standalone binary executables of Free Simple Video Converter embedding local custom UCRT64 FFmpeg 6.1.1 static binaries under the **GNU General Public License version 2 or later (GPL-2.0-or-later)**.

> **CRITICAL COMPLIANCE NOTICE**:
> Documenting this procedure does **NOT** fulfill GPL compliance by itself. Compliance is only achieved when the actual matching corresponding-source archive `ffmpeg-6.1.1-custom-source.zip` is compiled and attached alongside the binary release on GitHub Releases.

---

## 1. Upstream Binary Baseline & Provenance

The bundled Windows x64 binary artifact is documented in `packaging/ffmpeg_release_artifact.txt`:
- **Artifact**: Local Custom UCRT64 FFmpeg 6.1.1 Static
- **Build Environment**: MSYS2 MinGW UCRT64 GCC static toolchain
- **Build Output**: `D:\ffmpeg-v1-output`
- **FFmpeg Source Tag**: `n6.1.1`
- **FFmpeg Source Commit**: `e38092ef93`
- **Binary Checksums**:
  - `ffmpeg.exe`: `8BDC09032E11E264807B0E73313D8455D1E333C446A4849494112F27FA287DD5`
  - `ffprobe.exe`: `DC250168D0126A3FBDF5258478753ADBBA174628DE9E9C5936AD77D735460C8C`
- **Builder Script SHA256**: `E16299E0038EFFE91800655C8BEF9AB24F1B9BEC215CE634D8B0D9D40AE954B6`
- **Encoders Inventory SHA256**: `7B6A3D3D0267591B20532396CB8A1C75FF96AA361B82A8089EDEB4C684F4109F`
- **Component License**: GNU General Public License version 2 or later (GPL-2.0-or-later)

---

## 2. Release Asset Delivery Model

Under GPL requirements (such as GPL-2.0 Section 3 or GPL-3.0 Section 6 if chosen for distribution by the publisher), when distributing object code from a designated network location, equivalent no-charge access to the corresponding source must be provided from the same release location. The corresponding-source asset must remain publicly available for the required duration.

- **Per-Release Asset**: For every public GitHub release containing a packaged Windows standalone executable (`FreeSimpleVideoConverter.exe`), attach:
  ```text
  ffmpeg-6.1.1-custom-source.zip
  ```
- **Direct Linkage**: Third-party notices and release notes instruct users to download the matching corresponding source archive directly from the GitHub Release assets for their specific release version.
- **No Fabricated URLs**: Do not link to static or fabricated URLs; source must accompany the release as an actual uploaded release asset.

---

## 3. Required Contents of `ffmpeg-6.1.1-custom-source.zip`

The corresponding source archive must contain all source code, build scripts, configuration metadata, patches, and licenses needed to satisfy GPL corresponding-source obligations:

1. **Exact FFmpeg Source Code**:
   - Clean checkout / release archive of FFmpeg at tag `n6.1.1` (commit `e38092ef93`).
2. **GPL/LGPL External Libraries Source Code**:
   - Exact content-addressed source code archives of all compiled GPL and LGPL libraries linked into the custom static build, specifically:
     - `x264` (`libx264`)
     - `x265` (`libx265`)
     - `libvpx` (`libvpx-vp9`)
     - `svt-av1` (`libsvtav1`)
     - `libopus` (`libopus`)
     - `nv-codec-headers`
     - `amf`
     - `libvpl`
3. **Build Scripts & Configuration**:
   - Build scripts and recipes (`build_ffmpeg.sh`, `acquisition-manifest.json`, `build.lock.json`).
   - Patches (`x265-cmake-4.4-compatibility.patch`, `x265-pkgconfig-libs-private-no-lgcc_s.patch`).
   - Reproduction instructions and host inventory records (`build-record.json`, `config.log`, `commands.log`, `README.md`).
4. **License Texts**:
   - Full text of applicable licenses (GNU General Public License v2 / v3 as applicable).
   - Individual license notices for all incorporated third-party libraries.
5. **SHA256 Manifest**:
   - Manifest listing SHA256 hashes of the source bundle contents and corresponding binary executables.

---

## 4. Pre-Release Verification Checklist

Before publishing any binary release embedding FFmpeg:

- [ ] **1. Verify Local Binaries**: Run `bin\ffmpeg.exe -version` and `bin\ffprobe.exe -version` to ensure version output and hashes match `packaging/ffmpeg_release_artifact.txt`.
- [ ] **2. Assemble Source Archive**: Generate `ffmpeg-6.1.1-custom-source.zip` containing all components outlined in Section 3.
- [ ] **3. Verify Source Archive Integrity**: Ensure the zip archive can be extracted cleanly and contains the complete FFmpeg `n6.1.1` tree, external library sources, configuration dump, and GPL license text.
- [ ] **4. Staging GitHub Release**: Draft GitHub Release with `FreeSimpleVideoConverter.exe` and attach `ffmpeg-6.1.1-custom-source.zip`.
- [ ] **5. Verification Check**: Confirm both the executable and corresponding source zip are present in the release assets before publishing the release.
