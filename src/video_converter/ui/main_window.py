"""Main Application Window for VideoConverter."""

from __future__ import annotations

import json
import os
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from video_converter.domain.jobs import ConversionJob, JobStatus
from video_converter.domain.settings import AppSettings
from video_converter.platform_paths import get_config_path
from video_converter.queue.controller import QueueController
from video_converter.ui.i18n import get_language, on_language_changed, set_language, tr
from video_converter.ui.job_table import JobTableWidget
from video_converter.ui.log_console import LogConsole
from video_converter.ui.settings_panel import SettingsPanel
from video_converter.ui.styles import get_theme


class MainWindow(QMainWindow):
    """Primary application window coordinating UI interactions and queue controller."""

    def __init__(
        self,
        controller: QueueController | None = None,
        config_path: str | Path | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.controller = controller or QueueController(self)
        self.config_path = Path(config_path) if config_path else get_config_path()
        self._dark_theme: bool = True

        # 1. Load configuration and restore saved locale/theme BEFORE building widgets
        self._pre_init_settings()

        self.setWindowTitle(tr("window_title"))
        self.resize(1180, 720)
        self.setMinimumSize(850, 550)
        self.setAcceptDrops(True)

        on_language_changed(self._retranslate_ui)
        self._init_ui()
        self._apply_loaded_settings()
        self._connect_signals()
        self._update_action_buttons_state()

    def _pre_init_settings(self) -> None:
        """Loads language and theme before UI construction so widgets instantiate in the right locale."""
        if self.config_path.is_file():
            try:
                settings = AppSettings.load_from_file(self.config_path)
                if settings.language in ("ru", "en"):
                    set_language(settings.language)
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and "dark_theme" in data:
                    self._dark_theme = bool(data["dark_theme"])
                    app_instance = QApplication.instance()
                    if app_instance:
                        app_instance.setStyleSheet(get_theme(self._dark_theme))
            except Exception:
                pass

    def _init_ui(self) -> None:
        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)

        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(16, 16, 16, 16)
        root_layout.setSpacing(12)

        # 1. Top Action Toolbar
        top_bar = QHBoxLayout()
        top_bar.setSpacing(8)

        self.btn_add_files = QPushButton(tr("btn_add_files"))
        self.btn_add_files.setToolTip(tr("btn_add_files_tip"))
        self.btn_add_folder = QPushButton(tr("btn_add_folder"))
        self.btn_add_folder.setToolTip(tr("btn_add_folder_tip"))

        self.btn_clear_completed = QPushButton(tr("btn_clear_completed"))
        self.btn_clear_all = QPushButton(tr("btn_clear_all"))

        top_bar.addWidget(self.btn_add_files)
        top_bar.addWidget(self.btn_add_folder)
        top_bar.addSpacing(16)
        top_bar.addWidget(self.btn_clear_completed)
        top_bar.addWidget(self.btn_clear_all)
        top_bar.addStretch()

        self.lbl_zorg_credit = QLabel("by Jean-Baptiste Emanuel Zorg")
        self.lbl_zorg_credit.setObjectName("zorgCreditLabel")
        top_bar.addWidget(self.lbl_zorg_credit)

        self.btn_theme_toggle = QPushButton("🌙")
        self.btn_theme_toggle.setObjectName("themeToggle")
        self.btn_theme_toggle.setToolTip(tr("btn_theme_tip"))
        self.btn_theme_toggle.setFixedSize(36, 36)
        top_bar.addWidget(self.btn_theme_toggle)

        self.btn_lang_toggle = QPushButton("EN")
        self.btn_lang_toggle.setObjectName("langToggle")
        self.btn_lang_toggle.setToolTip(tr("btn_lang_tip"))
        self.btn_lang_toggle.setFixedSize(36, 36)
        top_bar.addWidget(self.btn_lang_toggle)

        root_layout.addLayout(top_bar)

        # 2. Central Split View: Left (Job Table + Log Console) / Right (Settings Panel)
        content_layout = QHBoxLayout()
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(16)

        # Left panel (Table + Collapsible Logs)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        self.job_table = JobTableWidget()
        self.log_console = LogConsole()

        left_splitter = QSplitter(Qt.Orientation.Vertical)
        left_splitter.addWidget(self.job_table)
        left_splitter.addWidget(self.log_console)
        left_splitter.setStretchFactor(0, 4)
        left_splitter.setStretchFactor(1, 1)

        left_layout.addWidget(left_splitter)
        content_layout.addWidget(left_widget, 1)

        # Right panel (Settings)
        self.settings_panel = SettingsPanel()
        self.settings_panel.setFixedWidth(300)
        content_layout.addWidget(self.settings_panel, 0)

        root_layout.addLayout(content_layout, 1)

        # 3. Bottom Status and Master Control Bar
        bottom_frame = QFrame()
        bottom_frame.setObjectName("bottomFrame")
        bottom_layout = QHBoxLayout(bottom_frame)
        bottom_layout.setContentsMargins(16, 12, 16, 12)
        bottom_layout.setSpacing(16)

        # Status & Total Progress Info
        progress_info_layout = QVBoxLayout()
        progress_info_layout.setContentsMargins(0, 0, 0, 0)
        progress_info_layout.setSpacing(4)

        status_meta_layout = QHBoxLayout()
        status_meta_layout.setContentsMargins(0, 0, 0, 0)
        self.status_label = QLabel(tr("status_ready"))
        self.status_label.setObjectName("statusLabel")
        self.eta_label = QLabel("")
        self.eta_label.setObjectName("etaLabel")
        self.eta_label.hide()

        status_meta_layout.addWidget(self.status_label)
        status_meta_layout.addWidget(self.eta_label)

        self.total_progress_bar = QProgressBar()
        self.total_progress_bar.setFixedHeight(20)
        self.total_progress_bar.setRange(0, 100)
        self.total_progress_bar.setValue(0)
        self.total_progress_bar.setTextVisible(True)
        self.total_progress_bar.setFormat("%p%")

        progress_info_layout.addLayout(status_meta_layout)
        progress_info_layout.addWidget(self.total_progress_bar)

        bottom_layout.addLayout(progress_info_layout)

        # Action Execution Buttons
        self.btn_start = QPushButton(tr("btn_start"))
        self.btn_start.setObjectName("primaryButton")
        self.btn_start.setMinimumHeight(44)
        self.btn_start.setMinimumWidth(180)
        self.btn_start.setEnabled(False)

        self.btn_stop = QPushButton(tr("btn_stop"))
        self.btn_stop.setObjectName("dangerButton")
        self.btn_stop.setMinimumHeight(44)
        self.btn_stop.setMinimumWidth(140)
        self.btn_stop.setEnabled(False)

        bottom_layout.addWidget(self.btn_start)
        bottom_layout.addWidget(self.btn_stop)

        root_layout.addWidget(bottom_frame)

    def _connect_signals(self) -> None:
        # Toolbar actions
        self.btn_add_files.clicked.connect(self._on_add_files_clicked)
        self.btn_add_folder.clicked.connect(self._on_add_folder_clicked)
        self.btn_clear_completed.clicked.connect(self.controller.clear_completed)
        self.btn_clear_all.clicked.connect(self.controller.clear_all)
        self.btn_theme_toggle.clicked.connect(self._on_toggle_theme)
        self.btn_lang_toggle.clicked.connect(self._on_toggle_language)

        # Execution actions
        self.btn_start.clicked.connect(self.controller.start)
        self.btn_stop.clicked.connect(self.controller.stop)

        # Table & Drag/Drop interactions
        self.job_table.remove_job_requested.connect(self.controller.remove_job)
        self.job_table.files_dropped.connect(self._on_files_dropped)
        self.job_table.selection_changed.connect(self._on_table_selection_changed)

        # Queue Controller Signals
        self.controller.job_added.connect(self._on_job_added)
        self.controller.job_updated.connect(self._on_job_updated)
        self.controller.job_removed.connect(self._on_job_removed)
        self.controller.queue_cleared.connect(self._on_queue_cleared)
        self.controller.queue_state_changed.connect(self._on_queue_state_changed)
        self.controller.total_progress_updated.connect(self._on_total_progress_updated)
        self.controller.global_log.connect(self.log_console.append_log)

        # Settings changed (global default or selected items)
        self.settings_panel.settings_changed.connect(self._on_settings_modified)

    def _on_toggle_theme(self) -> None:
        self._dark_theme = not self._dark_theme
        app_instance = QApplication.instance()
        if app_instance:
            app_instance.setStyleSheet(get_theme(self._dark_theme))
        self.btn_theme_toggle.setText("🌙" if self._dark_theme else "☀️")
        self._save_settings()

    def _on_toggle_language(self) -> None:
        new_lang = "en" if get_language() == "ru" else "ru"
        set_language(new_lang)
        self._save_settings()

    def _retranslate_ui(self) -> None:
        """Update all translatable text in this window."""
        self.setWindowTitle(tr("window_title"))
        self.btn_add_files.setText(tr("btn_add_files"))
        self.btn_add_files.setToolTip(tr("btn_add_files_tip"))
        self.btn_add_folder.setText(tr("btn_add_folder"))
        self.btn_add_folder.setToolTip(tr("btn_add_folder_tip"))
        self.btn_clear_completed.setText(tr("btn_clear_completed"))
        self.btn_clear_all.setText(tr("btn_clear_all"))
        self.btn_theme_toggle.setToolTip(tr("btn_theme_tip"))
        self.btn_lang_toggle.setToolTip(tr("btn_lang_tip"))
        self.btn_lang_toggle.setText("RU" if get_language() == "en" else "EN")
        self.btn_start.setText(tr("btn_start"))
        self.btn_stop.setText(tr("btn_stop"))
        if not self.controller.is_running:
            self.status_label.setText(tr("status_ready"))

    def _load_settings(self) -> None:
        try:
            # First load raw config to set language and theme before settings panel is initialized
            if self.config_path.is_file():
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    if "language" in data:
                        lang = data["language"]
                        if lang in ("ru", "en"):
                            set_language(lang)
                    if "dark_theme" in data:
                        self._dark_theme = bool(data["dark_theme"])
                        app_instance = QApplication.instance()
                        if app_instance:
                            app_instance.setStyleSheet(get_theme(self._dark_theme))
        except Exception as e:
            self.log_console.append_log(f"Config load error: {e}")

    def _apply_loaded_settings(self) -> None:
        try:
            config_exists = self.config_path.is_file()
            settings = AppSettings.load_from_file(self.config_path)
            self.settings_panel.apply_settings(settings)

            self.btn_theme_toggle.setText("🌙" if self._dark_theme else "☀️")
            self.btn_lang_toggle.setText("RU" if get_language() == "en" else "EN")

            if not config_exists:
                self._save_settings()
        except Exception as e:
            self.log_console.append_log(f"Settings apply error: {e}")

    def _save_settings(self) -> None:
        try:
            settings = self.settings_panel.get_settings()
            data = settings.to_dict()
            data["dark_theme"] = self._dark_theme
            data["language"] = get_language()

            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            self.log_console.append_log(f"Config save error: {e}")

    def _on_settings_modified(self) -> None:
        self._save_settings()
        selected_ids = self.job_table.get_selected_job_ids()
        if selected_ids:
            settings = self.settings_panel.get_settings()
            for jid in selected_ids:
                self.controller.update_job_settings(
                    job_id=jid,
                    preset=settings.preset,
                    crf=settings.crf,
                    encoder=settings.encoder,
                    target_fps=self.settings_panel.selected_fps,
                    audio_bitrate=self.settings_panel.selected_audio_bitrate,
                )

    def _on_table_selection_changed(self, selected_ids: list[str]) -> None:
        if len(selected_ids) == 1:
            job = self.controller.get_job(selected_ids[0])
            if job and not job.is_active:
                self.settings_panel.blockSignals(True)
                # Sync panel with selected job's settings
                idx = self.settings_panel.preset_combo.findData(job.preset)
                if idx >= 0:
                    self.settings_panel.preset_combo.setCurrentIndex(idx)
                self.settings_panel.crf_slider.setValue(job.crf)
                self.settings_panel.crf_group.setTitle(tr("group_quality", value=job.crf))
                enc_idx = self.settings_panel.encoder_combo.findData(job.encoder)
                if enc_idx >= 0:
                    self.settings_panel.encoder_combo.setCurrentIndex(enc_idx)

                fps_val = job.target_fps if job.target_fps is not None else "original"
                fps_idx = self.settings_panel.fps_combo.findData(fps_val)
                if fps_idx >= 0:
                    self.settings_panel.fps_combo.setCurrentIndex(fps_idx)

                audio_idx = self.settings_panel.audio_bitrate_combo.findData(job.audio_bitrate)
                if audio_idx >= 0:
                    self.settings_panel.audio_bitrate_combo.setCurrentIndex(audio_idx)

                self.settings_panel.blockSignals(False)
        elif not selected_ids:
            # Restore saved global defaults
            self._load_settings()

    def _has_pending_jobs(self) -> bool:
        return any(j.status in (JobStatus.PENDING, JobStatus.CANCELLED) for j in self.controller.jobs)

    def _update_action_buttons_state(self) -> None:
        is_running = self.controller.is_running
        has_pending = self._has_pending_jobs()

        self.btn_start.setEnabled(not is_running and has_pending)
        self.btn_stop.setEnabled(is_running)
        self.settings_panel.set_editable(not is_running)
        self.btn_add_files.setEnabled(not is_running)
        self.btn_add_folder.setEnabled(not is_running)
        self.btn_clear_all.setEnabled(not is_running)
        self.btn_clear_completed.setEnabled(not is_running)

    def _on_job_added(self, job: ConversionJob) -> None:
        self.job_table.add_job(job)
        self._update_action_buttons_state()

    def _on_job_updated(self, job: ConversionJob) -> None:
        self.job_table.update_job(job)
        self._update_action_buttons_state()

    def _on_job_removed(self, job_id: str) -> None:
        self.job_table.remove_job(job_id)
        self._update_action_buttons_state()

    def _on_add_files_clicked(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(
            self,
            tr("dlg_select_files"),
            "",
            tr("file_filter"),
        )
        if files:
            self._enqueue_paths(files)

    def _on_add_folder_clicked(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            tr("dlg_select_folder"),
            "",
        )
        if folder:
            self._enqueue_paths([folder])

    def _on_files_dropped(self, paths: list[str]) -> None:
        self._enqueue_paths(paths)

    def _enqueue_paths(self, paths: list[str]) -> None:
        settings = self.settings_panel.get_settings()
        self.controller.add_files(
            paths=paths,
            preset=settings.preset,
            crf=settings.crf,
            encoder=settings.encoder,
            output_mode=settings.output_mode,
            custom_dir=settings.custom_output_dir or None,
            target_fps=self.settings_panel.selected_fps,
            audio_bitrate=self.settings_panel.selected_audio_bitrate,
        )

    def _on_queue_cleared(self) -> None:
        self.job_table.clear()
        self._update_action_buttons_state()

    def _on_queue_state_changed(self, is_running: bool) -> None:
        self._update_action_buttons_state()
        if is_running:
            self.status_label.setText(tr("status_converting"))
        else:
            self.status_label.setText(tr("status_stopped"))

    def _on_total_progress_updated(
        self, percent: float, completed_count: int, total_count: int
    ) -> None:
        self.total_progress_bar.setValue(int(percent))
        if total_count > 0:
            self.status_label.setText(
                tr("status_progress", completed=completed_count, total=total_count, percent=percent)
            )
        else:
            self.status_label.setText(tr("status_empty"))

    # Window drag and drop support
    def dragEnterEvent(self, event) -> None:  # type: ignore
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # type: ignore
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # type: ignore
        urls = event.mimeData().urls()
        paths = [u.toLocalFile() for u in urls if u.isLocalFile()]
        if paths:
            self._enqueue_paths(paths)
            event.acceptProposedAction()
