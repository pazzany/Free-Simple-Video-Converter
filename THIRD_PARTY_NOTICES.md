# Third-Party Notices and Licenses

Free Simple Video Converter incorporates or interacts with third-party software and components under various open-source licenses. This document summarizes those components, their licenses, and source availability.

---

## 1. Video-Compres-StableDif (Behavioral Reference & Inspiration)

Free Simple Video Converter was created using [orex2121/Video-Compres-StableDif](https://github.com/orex2121/Video-Compres-StableDif) as an initial behavioral reference and architectural inspiration for batch video conversion and UI flows.

- **Author / Copyright**: Copyright (c) 2025 orex2121
- **License**: MIT License
- **Repository**: [https://github.com/orex2121/Video-Compres-StableDif](https://github.com/orex2121/Video-Compres-StableDif)

```text
MIT License

Copyright (c) 2025 orex2121

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

## 2. PySide6 / Qt for Python

The graphical user interface is built using PySide6 (Qt for Python), provided by The Qt Company.

- **License**: GNU Lesser General Public License version 3 (LGPLv3) / GNU General Public License version 2 or 3 (GPLv2/GPLv3) / Commercial license
- **Qt Licensing Details**: [https://www.qt.io/licensing/](https://www.qt.io/licensing/)
- **PySide6 Project & Source**: [https://wiki.qt.io/Qt_for_Python](https://wiki.qt.io/Qt_for_Python) and [https://code.qt.io/cgit/pyside/pyside-setup.git](https://code.qt.io/cgit/pyside/pyside-setup.git)

Under the LGPLv3 terms, users have the right to inspect, modify, and relink the Qt libraries used with this application.

---

## 3. FFmpeg and ffprobe (Multimedia Framework)

Free Simple Video Converter invokes FFmpeg and ffprobe CLI tools for media probing, scaling, and video/audio transcoding.

- **Project Website**: [https://ffmpeg.org](https://ffmpeg.org)
- **Source Code**: [https://ffmpeg.org/download.html](https://ffmpeg.org/download.html)
- **Build Origin**: Local Custom UCRT64 Static Build (MSYS2 MinGW UCRT64 GCC static toolchain)
- **Build Record & Recipe**: `packaging/ffmpeg-build/` and local build reconstruction logs
- **FFmpeg Upstream Source Reference**: Tag `n6.1.1` (commit `e38092ef93`)
- **GNU General Public License Text**: [https://www.gnu.org/licenses/gpl-2.0.html](https://www.gnu.org/licenses/gpl-2.0.html)

### Licensing and Component Architecture

- **Application Source Code**: The Free Simple Video Converter application source code is licensed under the **MIT License** (see `LICENSE`).
- **Embedded FFmpeg/ffprobe Binaries**: The custom static `ffmpeg.exe` and `ffprobe.exe` binaries are compiled with `--enable-gpl` (omitting version 3 enable flags), and their effective license is the **GNU General Public License version 2 or later (GPL-2.0-or-later)**. When packaged and distributed as a standalone binary bundle, if the publisher selects a GPLv3 distribution route for binary releases, that is an allowed publisher choice pursuant to the "or later" terms, rather than the binary's exclusive base license.

### Bundled Local Build Details

The FFmpeg artifact utilized in standalone packaging:

- **ffmpeg**:
  - Exact version line: `ffmpeg version 6.1.1 Copyright (c) 2000-2023 the FFmpeg developers`
  - SHA256: `8BDC09032E11E264807B0E73313D8455D1E333C446A4849494112F27FA287DD5`
  - Build configuration: built with `--enable-gpl` and external libraries (`--enable-libx264`, `--enable-libx265`, `--enable-libvpx`, `--enable-libsvtav1`, `--enable-libopus`, `--enable-nvenc`, `--enable-libvpl`, `--enable-amf`).
  - Builder Script SHA256: `E16299E0038EFFE91800655C8BEF9AB24F1B9BEC215CE634D8B0D9D40AE954B6`
  - Encoders Inventory SHA256: `7B6A3D3D0267591B20532396CB8A1C75FF96AA361B82A8089EDEB4C684F4109F`
  - Effective License: **GNU General Public License version 2 or later (GPL-2.0-or-later)**.
- **ffprobe**:
  - Exact version line: `ffprobe version 6.1.1 Copyright (c) 2007-2023 the FFmpeg developers`
  - SHA256: `DC250168D0126A3FBDF5258478753ADBBA174628DE9E9C5936AD77D735460C8C`
  - Build configuration: built with `--enable-gpl`.
  - Effective License: **GNU General Public License version 2 or later (GPL-2.0-or-later)**.

Complete build configuration capture and runtime details are preserved in `packaging/ffmpeg_release_artifact.txt`.

## 4. Noto Emoji Font (Linux Emoji Fallback)

The Linux application bundle ships the monochrome Noto Emoji font, loaded at
startup only when the host system provides no emoji font family, so symbol
glyphs in button labels render on minimal systems.

- **Author / Copyright**: Copyright (c) Google LLC
- **License**: SIL Open Font License, Version 1.1 ([https://openfontlicense.org](https://openfontlicense.org))
- **Source**: [https://github.com/google/fonts/tree/main/ofl/notoemoji](https://github.com/google/fonts/tree/main/ofl/notoemoji)
- **Bundled file**: `assets/fonts/NotoEmoji.ttf`

### Source Code Delivery for Standalone Releases

Under GPL terms, distribution of binary packages embedding GPL FFmpeg binaries requires providing corresponding source code.

- **Release Asset Delivery**: For every public GitHub Release that distributes a packaged executable containing these tools, the publisher must attach a corresponding source archive named `ffmpeg-6.1.1-custom-source.zip` alongside the executable. Do not publish such a binary release until both assets are present and verified.
- The corresponding source archive is a release-time asset produced during the release process and is not currently asserted to exist in this repository prior to packaging and publication.
- See `packaging/FFMPEG_SOURCE_RELEASE_CHECKLIST.md` for preparation, packaging, and pre-release verification requirements for the corresponding source archive. Compliance is fulfilled only when this archive is actively produced and published alongside the binary release.
