"""Log console widget with auto-scroll and filtering support."""

from __future__ import annotations

from datetime import datetime
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

from video_converter.ui.i18n import tr, on_language_changed


class LogConsole(QWidget):
    """Real-time application and conversion log viewer."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()
        on_language_changed(self.retranslate_ui)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # Header bar
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(0, 0, 0, 0)

        self.title_label = QLabel(tr("log_title"))
        self.title_label.setObjectName("logTitleLabel")
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        self.auto_scroll_cb = QCheckBox(tr("log_autoscroll"))
        self.auto_scroll_cb.setChecked(True)
        header_layout.addWidget(self.auto_scroll_cb)

        self.clear_btn = QPushButton(tr("log_clear"))
        self.clear_btn.setFixedHeight(26)
        self.clear_btn.clicked.connect(self.clear_logs)
        header_layout.addWidget(self.clear_btn)

        layout.addLayout(header_layout)

        # Text edit console
        self.text_edit = QTextEdit()
        self.text_edit.setObjectName("logConsole")
        self.text_edit.setReadOnly(True)
        self.text_edit.setMinimumHeight(100)
        layout.addWidget(self.text_edit)

    def retranslate_ui(self) -> None:
        self.title_label.setText(tr("log_title"))
        self.auto_scroll_cb.setText(tr("log_autoscroll"))
        self.clear_btn.setText(tr("log_clear"))

    def append_log(self, message: str) -> None:
        """Appends a new line with timestamp to the console."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] {message}"
        self.text_edit.append(formatted)

        if self.auto_scroll_cb.isChecked():
            cursor = self.text_edit.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            self.text_edit.setTextCursor(cursor)

    def clear_logs(self) -> None:
        """Clears all text in the log console."""
        self.text_edit.clear()
