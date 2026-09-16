"""Platform-specific paths and bundled resource resolution."""

from __future__ import annotations

import sys
from pathlib import Path
from PySide6.QtCore import QStandardPaths

APP_DIR_NAME = "FreeSimpleVideoConverter"
APP_DISPLAY_NAME = "Free Simple Video Converter"

EMOJI_FONT_FAMILIES = frozenset(
    {
        "noto color emoji",
        "noto emoji",
        "segoe ui emoji",
        "apple color emoji",
        "twemoji mozilla",
        "android emoji",
    }
)

BUNDLED_EMOJI_FONT = "assets/fonts/NotoEmoji.ttf"


def system_has_emoji_font(families: list[str]) -> bool:
    """Return True when a system emoji font family is available.

    Takes a plain family-name list so the predicate stays testable without Qt.
    """
    return any(family.strip().lower() in EMOJI_FONT_FAMILIES for family in families)


def get_app_config_dir() -> Path:
    """Get the application configuration directory.

    Uses QStandardPaths.AppConfigLocation. Ensures the final directory is namespaced
    with 'FreeSimpleVideoConverter' without duplicating the namespace if Qt already includes it.
    Creates the directory if it does not exist.
    """
    config_dir_str = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppConfigLocation)
    if not config_dir_str or not config_dir_str.strip():
        # Fallback to home config directory if QStandardPaths returns empty or whitespace
        config_dir = Path.home() / ".config" / APP_DIR_NAME
    else:
        config_dir = Path(config_dir_str)
        # If QStandardPaths returned an unnamespaced generic location (e.g. generic AppData or python directory),
        # ensure APP_DIR_NAME is included in the path hierarchy.
        if APP_DIR_NAME not in config_dir.parts and APP_DISPLAY_NAME not in config_dir.parts:
            config_dir = config_dir / APP_DIR_NAME

    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def get_config_path() -> Path:
    """Get the full path to config.json within the AppConfigLocation directory."""
    return get_app_config_dir() / "config.json"


def get_bundled_resource(name: str | Path) -> Path | None:
    """Resolve a bundled or repository resource path.

    When running frozen (PyInstaller), checks sys._MEIPASS first.
    Checks relative path under _MEIPASS before flattened basename to avoid collisions.
    When running from source/development, checks repository root and its subdirectories.
    """
    path_obj = Path(name)

    # 1. Check frozen PyInstaller bundle directory
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        meipass_dir = Path(getattr(sys, "_MEIPASS"))
        # Check preserving relative path structure first
        candidate_rel = meipass_dir / path_obj
        if candidate_rel.exists():
            return candidate_rel
        # Fall back to direct/flattened lookup under _MEIPASS
        candidate_flat = meipass_dir / path_obj.name
        if candidate_flat.exists():
            return candidate_flat

    # 2. Check source / dev tree
    repo_root = Path(__file__).resolve().parent.parent.parent
    candidate_repo = repo_root / path_obj
    if candidate_repo.exists():
        return candidate_repo

    # Check relative to package directory
    pkg_dir = Path(__file__).resolve().parent
    candidate_pkg = pkg_dir / path_obj
    if candidate_pkg.exists():
        return candidate_pkg

    # Check if direct path exists
    if path_obj.exists():
        return path_obj.resolve()

    return None
