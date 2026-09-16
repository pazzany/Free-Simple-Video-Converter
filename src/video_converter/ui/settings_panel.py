"""Settings and encoding parameters panel."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from video_converter.domain.encoders import EncoderType
from video_converter.domain.presets import Preset
from video_converter.domain.settings import AppSettings, OutputMode
from video_converter.ui.i18n import on_language_changed, tr

_PRESET_TR_KEYS = {
    "original": "preset_original",
    "480p": "preset_480p",
    "720p": "preset_720p",
    "1080p": "preset_1080p",
    "2k": "preset_2k",
    "4k": "preset_4k",
}

_AUDIO_BITRATE_ITEMS = [
    ("audio_32k", "32k"),
    ("audio_64k", "64k"),
    ("audio_96k", "96k"),
    ("audio_128k", "128k"),
    ("audio_192k", "192k"),
    ("audio_256k", "256k"),
    ("audio_320k", "320k"),
]


class SettingsPanel(QWidget):
    """Configuration control panel for target resolution, CRF, encoder, and output folder."""

    settings_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._init_ui()
        on_language_changed(self.retranslate_ui)

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(14)

        # 1. Output Preset Group
        self.preset_group = QGroupBox(tr("group_preset"))
        preset_layout = QVBoxLayout(self.preset_group)

        self.preset_combo = QComboBox()
        self._populate_presets()
        # Default to 1080p
        idx = self.preset_combo.findData(Preset.P1080)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.currentIndexChanged.connect(self._on_setting_modified)
        preset_layout.addWidget(self.preset_combo)

        main_layout.addWidget(self.preset_group)

        # 2. Quality / CRF Group with single title value display
        self.crf_group = QGroupBox(tr("group_quality", value=24))
        crf_layout = QVBoxLayout(self.crf_group)

        slider_row = QHBoxLayout()
        self.lbl_quality = QLabel(tr("lbl_quality"))
        self.lbl_quality.setObjectName("crfHintLabel")
        self.lbl_compression = QLabel(tr("lbl_compression"))
        self.lbl_compression.setObjectName("crfHintLabel")

        self.crf_slider = QSlider(Qt.Orientation.Horizontal)
        self.crf_slider.setRange(0, 51)
        self.crf_slider.setValue(24)
        self.crf_slider.valueChanged.connect(self._on_crf_slider_changed)

        slider_row.addWidget(self.lbl_quality)
        slider_row.addWidget(self.crf_slider, 1)
        slider_row.addWidget(self.lbl_compression)

        crf_layout.addLayout(slider_row)
        main_layout.addWidget(self.crf_group)

        # 3. Video Encoder Group
        self.encoder_group = QGroupBox(tr("group_encoder"))
        encoder_layout = QVBoxLayout(self.encoder_group)

        self.encoder_combo = QComboBox()
        self._populate_encoders()
        self.encoder_combo.currentIndexChanged.connect(self._on_setting_modified)
        encoder_layout.addWidget(self.encoder_combo)

        main_layout.addWidget(self.encoder_group)

        # 4. Output Destination Group
        self.output_group = QGroupBox(tr("group_output"))
        output_layout = QVBoxLayout(self.output_group)

        self.radio_same_dir = QRadioButton(tr("radio_same_dir"))
        self.radio_custom_dir = QRadioButton(tr("radio_custom_dir"))
        self.radio_same_dir.setChecked(True)

        self.btn_group_output = QButtonGroup(self)
        self.btn_group_output.addButton(self.radio_same_dir)
        self.btn_group_output.addButton(self.radio_custom_dir)
        self.btn_group_output.buttonToggled.connect(self._on_output_mode_toggled)

        output_layout.addWidget(self.radio_same_dir)
        output_layout.addWidget(self.radio_custom_dir)

        # Custom directory selector row
        self.dir_row_widget = QWidget()
        dir_row_layout = QHBoxLayout(self.dir_row_widget)
        dir_row_layout.setContentsMargins(0, 0, 0, 0)
        dir_row_layout.setSpacing(6)

        self.custom_dir_edit = QLineEdit()
        self.custom_dir_edit.setPlaceholderText(tr("placeholder_dir"))
        self.custom_dir_edit.textChanged.connect(self._on_setting_modified)
        self.browse_dir_btn = QPushButton(tr("btn_browse"))
        self.browse_dir_btn.clicked.connect(self._on_browse_directory)

        dir_row_layout.addWidget(self.custom_dir_edit)
        dir_row_layout.addWidget(self.browse_dir_btn)

        self.dir_row_widget.setEnabled(False)
        output_layout.addWidget(self.dir_row_widget)

        main_layout.addWidget(self.output_group)

        # 5. Collapsible Advanced Options
        self.adv_toggle_btn = QPushButton(tr("adv_collapsed"))
        self.adv_toggle_btn.setFlat(True)
        self.adv_toggle_btn.setObjectName("advToggleBtn")
        self.adv_toggle_btn.clicked.connect(self._toggle_advanced)
        main_layout.addWidget(self.adv_toggle_btn)

        self.adv_widget = QWidget()
        adv_layout = QFormLayout(self.adv_widget)
        adv_layout.setContentsMargins(8, 4, 8, 4)

        self.fps_combo = QComboBox()
        self._populate_fps()
        self.fps_combo.currentIndexChanged.connect(self._on_setting_modified)
        self.lbl_fps_label = QLabel(tr("lbl_fps"))
        adv_layout.addRow(self.lbl_fps_label, self.fps_combo)

        self.audio_bitrate_combo = QComboBox()
        self._populate_audio_bitrate()
        self.audio_bitrate_combo.currentIndexChanged.connect(self._on_setting_modified)
        self.lbl_audio_label = QLabel(tr("lbl_audio_bitrate"))
        adv_layout.addRow(self.lbl_audio_label, self.audio_bitrate_combo)

        self.adv_widget.setVisible(False)
        main_layout.addWidget(self.adv_widget)

        main_layout.addStretch()

    def _populate_presets(self) -> None:
        current = self.preset_combo.currentData()
        self.preset_combo.blockSignals(True)
        self.preset_combo.clear()
        for p in Preset.all_presets():
            tr_key = _PRESET_TR_KEYS.get(p.preset_id, p.preset_id)
            self.preset_combo.addItem(tr(tr_key), p)
        if current is not None:
            idx = self.preset_combo.findData(current)
            if idx >= 0:
                self.preset_combo.setCurrentIndex(idx)
        self.preset_combo.blockSignals(False)

    def _populate_encoders(self) -> None:
        current = self.encoder_combo.currentData()
        self.encoder_combo.blockSignals(True)
        self.encoder_combo.clear()
        for enc in EncoderType.all_options():
            display = tr("encoder_auto") if enc == EncoderType.AUTO else enc.display_name
            self.encoder_combo.addItem(display, enc)
        if current is not None:
            idx = self.encoder_combo.findData(current)
            if idx >= 0:
                self.encoder_combo.setCurrentIndex(idx)
        self.encoder_combo.blockSignals(False)

    def _populate_fps(self) -> None:
        current_idx = max(0, self.fps_combo.currentIndex())
        self.fps_combo.blockSignals(True)
        self.fps_combo.clear()
        self.fps_combo.addItem(tr("fps_original"), "original")
        self.fps_combo.addItem("60 fps", 60)
        self.fps_combo.addItem("30 fps", 30)
        self.fps_combo.addItem("24 fps", 24)
        if current_idx < self.fps_combo.count():
            self.fps_combo.setCurrentIndex(current_idx)
        self.fps_combo.blockSignals(False)

    def _populate_audio_bitrate(self) -> None:
        current_idx = max(0, self.audio_bitrate_combo.currentIndex())
        self.audio_bitrate_combo.blockSignals(True)
        self.audio_bitrate_combo.clear()
        for key, val in _AUDIO_BITRATE_ITEMS:
            self.audio_bitrate_combo.addItem(tr(key), val)
        if current_idx < self.audio_bitrate_combo.count():
            self.audio_bitrate_combo.setCurrentIndex(current_idx)
        self.audio_bitrate_combo.blockSignals(False)

    def retranslate_ui(self) -> None:
        """Update all text elements when language changes."""
        self.preset_group.setTitle(tr("group_preset"))
        self._populate_presets()

        self.crf_group.setTitle(tr("group_quality", value=self.crf_slider.value()))
        self.lbl_quality.setText(tr("lbl_quality"))
        self.lbl_compression.setText(tr("lbl_compression"))

        self.encoder_group.setTitle(tr("group_encoder"))
        self._populate_encoders()

        self.output_group.setTitle(tr("group_output"))
        self.radio_same_dir.setText(tr("radio_same_dir"))
        self.radio_custom_dir.setText(tr("radio_custom_dir"))
        self.custom_dir_edit.setPlaceholderText(tr("placeholder_dir"))
        self.browse_dir_btn.setText(tr("btn_browse"))

        if self.adv_widget.isVisible():
            self.adv_toggle_btn.setText(tr("adv_expanded"))
        else:
            self.adv_toggle_btn.setText(tr("adv_collapsed"))

        self.lbl_fps_label.setText(tr("lbl_fps"))
        self._populate_fps()

        self.lbl_audio_label.setText(tr("lbl_audio_bitrate"))
        self._populate_audio_bitrate()

    def _toggle_advanced(self) -> None:
        visible = not self.adv_widget.isVisible()
        self.adv_widget.setVisible(visible)
        self.adv_toggle_btn.setText(tr("adv_expanded") if visible else tr("adv_collapsed"))

    def _on_crf_slider_changed(self, value: int) -> None:
        self.crf_group.setTitle(tr("group_quality", value=value))
        self._on_setting_modified()

    def _on_output_mode_toggled(self) -> None:
        is_custom = self.radio_custom_dir.isChecked()
        self.dir_row_widget.setEnabled(is_custom)
        self._on_setting_modified()

    def _on_browse_directory(self) -> None:
        selected_dir = QFileDialog.getExistingDirectory(
            self,
            tr("dlg_select_output"),
            self.custom_dir_edit.text() or "",
        )
        if selected_dir:
            self.custom_dir_edit.setText(selected_dir)

    def _on_setting_modified(self) -> None:
        self.settings_changed.emit()

    @property
    def selected_preset(self) -> Preset:
        return self.preset_combo.currentData() or Preset.P1080

    @property
    def selected_crf(self) -> int:
        return self.crf_slider.value()

    @property
    def selected_encoder(self) -> EncoderType:
        return self.encoder_combo.currentData() or EncoderType.AUTO

    @property
    def selected_output_mode(self) -> OutputMode:
        return OutputMode.CUSTOM_DIR if self.radio_custom_dir.isChecked() else OutputMode.SAME_DIR

    @property
    def custom_output_dir(self) -> str:
        return self.custom_dir_edit.text().strip()

    @property
    def selected_fps(self) -> int | None:
        """Return selected FPS, or None for 'original'."""
        data = self.fps_combo.currentData()
        if data is None or data == "original":
            return None
        return int(data)

    @property
    def selected_audio_bitrate(self) -> str:
        """Return selected audio bitrate string like '192k'."""
        return self.audio_bitrate_combo.currentData() or "192k"

    def apply_settings(self, settings: AppSettings) -> None:
        """Populates UI elements from an AppSettings model."""
        idx = self.preset_combo.findData(settings.preset)
        if idx >= 0:
            self.preset_combo.setCurrentIndex(idx)

        self.crf_slider.setValue(settings.crf)
        self.crf_group.setTitle(tr("group_quality", value=settings.crf))

        idx = self.encoder_combo.findData(settings.encoder)
        if idx >= 0:
            self.encoder_combo.setCurrentIndex(idx)

        if settings.output_mode == OutputMode.CUSTOM_DIR:
            self.radio_custom_dir.setChecked(True)
            self.custom_dir_edit.setText(settings.custom_output_dir)
            self.dir_row_widget.setEnabled(True)
        else:
            self.radio_same_dir.setChecked(True)
            self.dir_row_widget.setEnabled(False)

        fps_val = settings.target_fps if settings.target_fps is not None else "original"
        fps_idx = self.fps_combo.findData(fps_val)
        if fps_idx >= 0:
            self.fps_combo.setCurrentIndex(fps_idx)

        audio_idx = self.audio_bitrate_combo.findData(settings.audio_bitrate)
        if audio_idx >= 0:
            self.audio_bitrate_combo.setCurrentIndex(audio_idx)

    def get_settings(self) -> AppSettings:
        """Returns AppSettings dataclass instance reflecting current UI state."""
        return AppSettings(
            preset=self.selected_preset,
            crf=self.selected_crf,
            encoder=self.selected_encoder,
            output_mode=self.selected_output_mode,
            custom_output_dir=self.custom_output_dir,
            target_fps=self.selected_fps,
            audio_bitrate=self.selected_audio_bitrate,
        )

    def set_editable(self, editable: bool) -> None:
        """Enables or disables setting modifications while conversion runs."""
        self.preset_combo.setEnabled(editable)
        self.crf_slider.setEnabled(editable)
        self.encoder_combo.setEnabled(editable)
        self.radio_same_dir.setEnabled(editable)
        self.radio_custom_dir.setEnabled(editable)
        self.custom_dir_edit.setEnabled(editable and self.radio_custom_dir.isChecked())
        self.browse_dir_btn.setEnabled(editable and self.radio_custom_dir.isChecked())
        self.fps_combo.setEnabled(editable)
        self.audio_bitrate_combo.setEnabled(editable)

