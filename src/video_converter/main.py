"""Application entry point for Free Simple Video Converter."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from PySide6.QtGui import QFontDatabase, QIcon
from PySide6.QtWidgets import QApplication

from video_converter.platform_paths import (
    BUNDLED_EMOJI_FONT,
    get_bundled_resource,
    get_config_path,
    system_has_emoji_font,
)
from video_converter.ui.main_window import MainWindow
from video_converter.ui.styles import THEME_QSS


def ensure_emoji_font() -> None:
    """Load the bundled emoji fallback font when the system has none.

    Minimal Linux/WSL systems ship without an emoji font, which leaves the
    symbol glyphs used in button labels blank. Systems that already provide
    an emoji family keep their native (usually color) rendering untouched.
    """
    if system_has_emoji_font(QFontDatabase.families()):
        return
    font_path = get_bundled_resource(BUNDLED_EMOJI_FONT)
    if font_path and font_path.is_file():
        QFontDatabase.addApplicationFont(str(font_path))


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("FreeSimpleVideoConverter")
    app.setApplicationDisplayName("Free Simple Video Converter")
    app.setApplicationVersion("1.0.1")

    # Load bundled emoji fallback when the system provides no emoji font.
    ensure_emoji_font()

    # Set Application Icon if available
    icon_path = get_bundled_resource("assets/icon.ico") or get_bundled_resource("icon.ico")
    if icon_path and icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Apply global stylesheet
    app.setStyleSheet(THEME_QSS)

    # Pre-load saved language preference before building UI widgets
    config_file = get_config_path()
    if config_file.is_file():
        try:
            import json
            from video_converter.ui.i18n import set_language
            with open(config_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and "language" in data:
                saved_lang = data["language"]
                if saved_lang in ("ru", "en"):
                    set_language(saved_lang)
        except Exception:
            pass

    window = MainWindow(config_path=config_file)
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
