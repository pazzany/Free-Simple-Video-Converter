# Contributing to Free Simple Video Converter

Thank you for your interest in contributing to **Free Simple Video Converter**! We welcome bug reports, feature requests, documentation improvements, and pull requests.

---

## 🛠️ Development Setup

### Requirements

- **Python 3.11+**
- **FFmpeg & ffprobe** binaries available in `PATH` or placed locally inside `bin/` during development.

### Setup Instructions

1. **Clone the repository:**
   ```powershell
   git clone https://github.com/pazzany/Free-Simple-Video-Converter.git
   cd Free-Simple-Video-Converter
   ```

2. **Create and activate a virtual environment:**
   - On Windows (PowerShell):
     ```powershell
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1
     ```
   - On Linux / macOS:
     ```bash
     python3 -m venv .venv
     source .venv/bin/activate
     ```

3. **Install editable package and dev dependencies:**
   ```bash
   pip install -e ".[dev]"
   ```

4. **Local FFmpeg binaries for development:**
   - You can install FFmpeg system-wide via package managers:
     - Windows: `choco install ffmpeg` or `winget install Gyan.FFmpeg`
     - Ubuntu/Debian: `sudo apt update && sudo apt install -y ffmpeg`
     - macOS: `brew install ffmpeg`
   - Alternatively, place `ffmpeg.exe` and `ffprobe.exe` into a local `bin/` directory at the repository root.

5. **Run the application from source:**
   ```bash
   python -m video_converter
   ```

---

## 🧪 Running Tests

The project uses `pytest` and `pytest-qt`. Ensure all tests pass before submitting changes:

```bash
# Run all tests (currently 114 tests)
pytest

# Run specific test suites
pytest tests/unit/
pytest tests/ui/
pytest tests/integration/
```

Headless environments (CI, Linux servers) can run Qt tests using `QT_QPA_PLATFORM=offscreen`:
```bash
QT_QPA_PLATFORM=offscreen pytest
```

---

## 📦 Building the Standalone Executable

To build the one-file Windows executable with embedded FFmpeg:

```powershell
python packaging/build_exe.py
```

The output artifact is generated in `dist/FreeSimpleVideoConverter.exe`.

---

## 📋 Code Style and Guidelines

- **Architecture Boundaries**: Keep the clean layer separation:
  - `domain`: Pure Python models (dataclasses, enums) without Qt or FFmpeg dependencies.
  - `media`: Services wrapping FFmpeg/ffprobe invocations and path helpers.
  - `queue`: Qt-based queue management and async worker processes.
  - `ui`: PySide6 widgets, QSS themes, and translation handling.
- **Translations (i18n)**: All user-facing strings must use `tr("key")` from `video_converter.ui.i18n`. Add both English and Russian translations for any new keys.
- **No Binary Commits**: **Never commit compiled binaries, `.exe` files, test videos, or temporary artifacts to Git.** Binaries belong in release assets, not in source control history.
- **Type Annotations**: Use Python standard type hints.

---

## 🚀 Pull Request Guidelines

1. Create a feature branch from `main`:
   ```bash
   git checkout -b feature/my-new-feature
   ```
2. Write unit and/or UI tests for new functionality or bug fixes.
3. Verify that the entire test suite passes (`pytest`).
4. Commit your changes with clear, descriptive commit messages.
5. Push to your fork and submit a Pull Request against `main`.
