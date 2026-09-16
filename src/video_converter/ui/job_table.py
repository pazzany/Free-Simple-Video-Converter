"""Job queue table widget and custom status rendering."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QMenu,
    QProgressBar,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from video_converter.domain.jobs import ConversionJob, JobStatus
from video_converter.ui.i18n import tr, on_language_changed


class JobTableWidget(QWidget):
    """Table view displaying queue conversion jobs with progress and status."""

    remove_job_requested = Signal(str)  # job_id
    files_dropped = Signal(list)  # list[str]
    selection_changed = Signal(list)  # list[str] job_ids

    COL_INDEX = 0
    COL_NAME = 1
    COL_SRC_RES = 2
    COL_DURATION = 3
    COL_SIZE = 4
    COL_TGT_RES = 5
    COL_SETTINGS = 6
    COL_STATUS = 7

    def _get_headers(self) -> list[str]:
        return [
            tr("col_index"),
            tr("col_file"),
            tr("col_source"),
            tr("col_duration"),
            tr("col_size"),
            tr("col_result"),
            tr("col_preset"),
            tr("col_progress"),
        ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self._job_id_to_row: dict[str, int] = {}
        self._row_to_job_id: dict[int, str] = {}
        self._init_ui()
        on_language_changed(self.retranslate_ui)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Table widget
        self.table = QTableWidget()
        headers = self._get_headers()
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(42)
        self.table.setShowGrid(False)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)
        self.table.itemSelectionChanged.connect(self._on_item_selection_changed)

        # Header sizing
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COL_INDEX, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_NAME, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(self.COL_SRC_RES, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_DURATION, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_SIZE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_TGT_RES, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_SETTINGS, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(self.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(self.COL_STATUS, 125)

        layout.addWidget(self.table)

        # Empty state overlay placeholder
        self.empty_label = QLabel(
            tr("empty_drop_hint"),
            self.table,
        )
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setStyleSheet(
            "color: #565f89; font-size: 15px; font-weight: 500; background: transparent;"
        )
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        self._update_empty_state()

    def retranslate_ui(self) -> None:
        """Updates table headers, empty state text, and existing status cells on language change."""
        self.table.setHorizontalHeaderLabels(self._get_headers())
        self.empty_label.setText(tr("empty_drop_hint"))
        for row in range(self.table.rowCount()):
            widget = self.table.cellWidget(row, self.COL_STATUS)
            if isinstance(widget, JobStatusCellWidget) and hasattr(widget, "_last_job"):
                widget.update_status(widget._last_job)

    def resizeEvent(self, event) -> None:  # type: ignore
        super().resizeEvent(event)
        self.empty_label.setGeometry(self.table.rect())

    def _update_empty_state(self) -> None:
        is_empty = self.table.rowCount() == 0
        self.empty_label.setVisible(is_empty)
        if is_empty:
            self.empty_label.setGeometry(self.table.rect())

    def add_job(self, job: ConversionJob) -> None:
        """Appends a new job row to the table."""
        if job.id in self._job_id_to_row:
            self.update_job(job)
            return

        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setRowHeight(row, 44)

        self._job_id_to_row[job.id] = row
        self._row_to_job_id[row] = job.id

        # # Column
        item_idx = QTableWidgetItem(str(row + 1))
        item_idx.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_INDEX, item_idx)

        # Name Column
        item_name = QTableWidgetItem(job.source_filename)
        item_name.setToolTip(job.source_path)
        self.table.setItem(row, self.COL_NAME, item_name)

        # Source Res
        item_src_res = QTableWidgetItem(job.source_resolution_str)
        item_src_res.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_SRC_RES, item_src_res)

        # Duration
        item_dur = QTableWidgetItem(job.duration_str)
        item_dur.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_DURATION, item_dur)

        # Size
        item_size = QTableWidgetItem(job.size_str)
        item_size.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_SIZE, item_size)

        # Target Res
        item_tgt_res = QTableWidgetItem(job.target_resolution_str)
        item_tgt_res.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_TGT_RES, item_tgt_res)

        # Settings (Preset / CRF / Encoder)
        enc_display = job.encoder.codec_name
        settings_text = f"{job.preset.preset_id.upper()} (CRF {job.crf}, {enc_display})"
        item_settings = QTableWidgetItem(settings_text)
        item_settings.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        self.table.setItem(row, self.COL_SETTINGS, item_settings)

        # Status / Progress Column
        status_widget = self._create_status_widget(job)
        self.table.setCellWidget(row, self.COL_STATUS, status_widget)

        self._update_empty_state()

    def update_job(self, job: ConversionJob) -> None:
        """Updates row presentation for an existing job."""
        if job.id not in self._job_id_to_row:
            self.add_job(job)
            return

        row = self._job_id_to_row[job.id]

        # Update dynamic fields
        item_src_res = self.table.item(row, self.COL_SRC_RES)
        if item_src_res:
            item_src_res.setText(job.source_resolution_str)

        item_dur = self.table.item(row, self.COL_DURATION)
        if item_dur:
            item_dur.setText(job.duration_str)

        item_size = self.table.item(row, self.COL_SIZE)
        if item_size:
            item_size.setText(job.size_str)

        item_tgt_res = self.table.item(row, self.COL_TGT_RES)
        if item_tgt_res:
            item_tgt_res.setText(job.target_resolution_str)

        # Update Preset / Settings
        enc_display = job.encoder.codec_name
        settings_text = f"{job.preset.preset_id.upper()} (CRF {job.crf}, {enc_display})"
        item_settings = self.table.item(row, self.COL_SETTINGS)
        if item_settings:
            item_settings.setText(settings_text)
        else:
            item_settings = QTableWidgetItem(settings_text)
            item_settings.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, self.COL_SETTINGS, item_settings)

        # Update status cell widget
        existing_widget = self.table.cellWidget(row, self.COL_STATUS)
        if isinstance(existing_widget, JobStatusCellWidget):
            existing_widget.update_status(job)
        else:
            status_widget = self._create_status_widget(job)
            self.table.setCellWidget(row, self.COL_STATUS, status_widget)

    def remove_job(self, job_id: str) -> None:
        """Removes job row from the table and re-indexes."""
        if job_id not in self._job_id_to_row:
            return

        row_to_remove = self._job_id_to_row[job_id]
        self.table.removeRow(row_to_remove)
        self._rebuild_row_mappings()
        self._update_empty_state()

    def clear(self) -> None:
        """Clears all table rows and mappings."""
        self.table.setRowCount(0)
        self._job_id_to_row.clear()
        self._row_to_job_id.clear()
        self._update_empty_state()

    def _rebuild_row_mappings(self) -> None:
        self._job_id_to_row.clear()
        self._row_to_job_id.clear()
        for r in range(self.table.rowCount()):
            # Update index numbers
            idx_item = self.table.item(r, self.COL_INDEX)
            if idx_item:
                idx_item.setText(str(r + 1))

            status_widget = self.table.cellWidget(r, self.COL_STATUS)
            if isinstance(status_widget, JobStatusCellWidget):
                jid = status_widget.job_id
                self._job_id_to_row[jid] = r
                self._row_to_job_id[r] = jid

    def _create_status_widget(self, job: ConversionJob) -> QWidget:
        widget = JobStatusCellWidget(job)
        return widget

    def get_selected_job_ids(self) -> list[str]:
        selected_rows = sorted(
            list({index.row() for index in self.table.selectedIndexes()})
        )
        job_ids = []
        for r in selected_rows:
            jid = self._row_to_job_id.get(r)
            if jid:
                job_ids.append(jid)
        return job_ids

    def _on_item_selection_changed(self) -> None:
        self.selection_changed.emit(self.get_selected_job_ids())

    def _show_context_menu(self, pos) -> None:  # type: ignore
        selected_rows = sorted(
            list({index.row() for index in self.table.selectedIndexes()}),
            reverse=True,
        )
        if not selected_rows:
            return

        menu = QMenu(self)
        remove_action = menu.addAction(
            tr("ctx_remove_multi", count=len(selected_rows))
            if len(selected_rows) > 1
            else tr("ctx_remove_single")
        )
        action = menu.exec(self.table.viewport().mapToGlobal(pos))
        if action == remove_action:
            for r in selected_rows:
                job_id = self._row_to_job_id.get(r)
                if job_id:
                    self.remove_job_requested.emit(job_id)

    # Drag and Drop Events
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
            self.files_dropped.emit(paths)
            event.acceptProposedAction()


class JobStatusCellWidget(QWidget):
    """Custom progress and badge renderer cell widget for job status with no overlapping elements."""

    def __init__(self, job: ConversionJob, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.job_id = job.id
        self._init_ui()
        self.update_status(job)

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.label = QLabel()
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("font-size: 11px; font-weight: 600;")

        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedHeight(8)
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 100)

        layout.addWidget(self.label)
        layout.addWidget(self.progress_bar)

    def update_status(self, job: ConversionJob) -> None:
        self._last_job = job
        if job.status == JobStatus.RUNNING:
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(int(job.progress))
            speed_info = f" • {job.speed}" if job.speed else ""
            self.label.setText(f"{job.progress:.1f}%{speed_info}")
            self.label.setStyleSheet("color: #7aa2f7; font-weight: 600; font-size: 11px;")
        elif job.status == JobStatus.PROBING:
            self.progress_bar.setVisible(False)
            self.label.setText(tr("job_probing"))
            self.label.setStyleSheet("color: #e0af68; font-weight: 500; font-size: 11px;")
        elif job.status == JobStatus.COMPLETED:
            self.progress_bar.setVisible(False)
            if job.output_size_str:
                self.label.setText(f"{tr('job_completed')}\n{job.output_size_str}")
            else:
                self.label.setText(tr("job_completed"))
            self.label.setStyleSheet("color: #9ece6a; font-weight: 600; font-size: 11px;")
        elif job.status == JobStatus.FAILED:
            self.progress_bar.setVisible(False)
            self.label.setText(tr("job_failed"))
            self.label.setStyleSheet("color: #f7768e; font-weight: 600; font-size: 11px;")
            if job.error_message:
                self.label.setToolTip(job.error_message)
        elif job.status == JobStatus.CANCELLED:
            self.progress_bar.setVisible(False)
            cancelled_text = tr("job_cancelled_by_user") if job.error_message == "Cancelled by user" else tr("job_cancelled")
            self.label.setText(cancelled_text)
            self.label.setStyleSheet("color: #565f89; font-weight: 500; font-size: 11px;")
        else:  # PENDING
            self.progress_bar.setVisible(False)
            self.label.setText(tr("job_pending"))
            self.label.setStyleSheet("color: #565f89; font-weight: 500; font-size: 11px;")
