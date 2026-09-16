"""Application entry point for Free Simple Video Converter."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from video_converter.platform_paths import get_bundled_resource, get_config_path
from video_converter.ui.main_window import MainWindow
from video_converter.ui.styles import THEME_QSS


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("FreeSimpleVideoConverter")
    app.setApplicationDisplayName("Free Simple Video Converter")
    app.setApplicationVersion("1.0.0")

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
