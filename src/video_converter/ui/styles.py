"""Modern dark and light theme stylesheets and styling tokens for VideoConverter."""

from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class ThemePalette:
    bg_main: str
    bg_alt: str
    bg_card: str
    bg_input: str
    bg_hover: str
    bg_pressed: str
    bg_disabled: str
    border_main: str
    border_muted: str
    border_focus: str
    text_main: str
    text_muted: str
    text_disabled: str
    accent: str
    accent_hover: str
    selection_bg: str
    selection_text: str
    tooltip_bg: str
    tooltip_text: str
    tooltip_border: str
    crf_hint_color: str
    splitter_handle: str
    btn_header_bg: str
    btn_header_color: str
    btn_header_hover_border: str
    btn_header_hover_color: str
    btn_header_disabled_border: str
    btn_icon_hover_bg: str
    btn_icon_pressed_bg: str
    btn_action_disabled_bg: str
    btn_action_disabled_color: str
    btn_action_disabled_border: str
    btn_start_stop0: str
    btn_start_stop1: str
    btn_start_border: str
    btn_start_hover0: str
    btn_start_hover1: str
    btn_start_hover_border: str
    btn_start_pressed0: str
    btn_start_pressed1: str
    btn_start_pressed_text: str
    btn_stop_stop0: str
    btn_stop_stop1: str
    btn_stop_border: str
    btn_stop_hover0: str
    btn_stop_hover1: str
    btn_stop_hover_border: str
    btn_stop_pressed0: str
    btn_stop_pressed1: str
    btn_stop_pressed_text: str
    table_bg: str
    table_alt_bg: str
    table_grid: str
    table_border: str
    table_selection_bg: str
    table_selection_text: str
    table_header_bg: str
    table_item_border: str
    table_item_color: str
    scrollbar_bg: str
    scrollbar_handle_hover: str
    input_hover_border: str
    control_checked_color: str
    control_text: str
    slider_groove: str
    slider_subpage: str
    slider_handle_bg: str
    slider_handle_border: str
    slider_handle_hover: str
    slider_handle_hover_border: str
    progress_bg: str
    progress_border: str
    progress_text: str
    progress_chunk_stop0: str
    progress_chunk_stop1: str
    log_bg: str
    log_color: str
    log_border: str
    group_box_title_color: str
    menu_border: str
    zorg_credit_color: str


DARK_PALETTE = ThemePalette(
    bg_main="#1a1b26",
    bg_alt="#1f2335",
    bg_card="#1f2335",
    bg_input="#16161e",
    bg_hover="#2f354f",
    bg_pressed="#1f2335",
    bg_disabled="#161722",
    border_main="#414868",
    border_muted="#292e42",
    border_focus="#7dcfff",
    text_main="#c0caf5",
    text_muted="#7a88cf",
    text_disabled="#414868",
    accent="#7aa2f7",
    accent_hover="#89b4fa",
    selection_bg="#3d59a1",
    selection_text="#ffffff",
    tooltip_bg="#24283b",
    tooltip_text="#c0caf5",
    tooltip_border="#414868",
    crf_hint_color="#565f89",
    splitter_handle="#24283b",
    btn_header_bg="#24283b",
    btn_header_color="#c0caf5",
    btn_header_hover_border="#7aa2f7",
    btn_header_hover_color="#ffffff",
    btn_header_disabled_border="#24283b",
    btn_icon_hover_bg="#2f354f",
    btn_icon_pressed_bg="#1f2335",
    btn_action_disabled_bg="#24283b",
    btn_action_disabled_color="#565f89",
    btn_action_disabled_border="#292e42",
    btn_start_stop0="#10b981",
    btn_start_stop1="#06b6d4",
    btn_start_border="#34d399",
    btn_start_hover0="#34d399",
    btn_start_hover1="#22d3ee",
    btn_start_hover_border="#ffffff",
    btn_start_pressed0="#059669",
    btn_start_pressed1="#0891b2",
    btn_start_pressed_text="#e5e7eb",
    btn_stop_stop0="#ef4444",
    btn_stop_stop1="#f43f5e",
    btn_stop_border="#fb7185",
    btn_stop_hover0="#f87171",
    btn_stop_hover1="#fb7185",
    btn_stop_hover_border="#ffffff",
    btn_stop_pressed0="#dc2626",
    btn_stop_pressed1="#e11d48",
    btn_stop_pressed_text="#e5e7eb",
    table_bg="#16161e",
    table_alt_bg="#1a1b26",
    table_grid="#24283b",
    table_border="#292e42",
    table_selection_bg="#283457",
    table_selection_text="#ffffff",
    table_header_bg="#1f2335",
    table_item_border="#1f2335",
    table_item_color="",
    scrollbar_bg="#16161e",
    scrollbar_handle_hover="#7aa2f7",
    input_hover_border="#7aa2f7",
    control_checked_color="#7aa2f7",
    control_text="#c0caf5",
    slider_groove="#24283b",
    slider_subpage="#7aa2f7",
    slider_handle_bg="#c0caf5",
    slider_handle_border="#7aa2f7",
    slider_handle_hover="#ffffff",
    slider_handle_hover_border="",
    progress_bg="#16161e",
    progress_border="#292e42",
    progress_text="#c0caf5",
    progress_chunk_stop0="#7aa2f7",
    progress_chunk_stop1="#2ac3de",
    log_bg="#13141c",
    log_color="#9aa5ce",
    log_border="#24283b",
    group_box_title_color="#7aa2f7",
    menu_border="#414868",
    zorg_credit_color="#2c324b",
)

LIGHT_PALETTE = ThemePalette(
    bg_main="#f8fafc",
    bg_alt="#ffffff",
    bg_card="#ffffff",
    bg_input="#ffffff",
    bg_hover="#f1f5f9",
    bg_pressed="#e2e8f0",
    bg_disabled="#f8fafc",
    border_main="#cbd5e1",
    border_muted="#e2e8f0",
    border_focus="#2563eb",
    text_main="#1e293b",
    text_muted="#64748b",
    text_disabled="#94a3b8",
    accent="#2563eb",
    accent_hover="#1d4ed8",
    selection_bg="#3b82f6",
    selection_text="#ffffff",
    tooltip_bg="#ffffff",
    tooltip_text="#1e293b",
    tooltip_border="#cbd5e1",
    crf_hint_color="#94a3b8",
    splitter_handle="#e2e8f0",
    btn_header_bg="#ffffff",
    btn_header_color="#334155",
    btn_header_hover_border="#3b82f6",
    btn_header_hover_color="#1d4ed8",
    btn_header_disabled_border="#e2e8f0",
    btn_icon_hover_bg="#e2e8f0",
    btn_icon_pressed_bg="#cbd5e1",
    btn_action_disabled_bg="#e2e8f0",
    btn_action_disabled_color="#94a3b8",
    btn_action_disabled_border="#cbd5e1",
    btn_start_stop0="#10b981",
    btn_start_stop1="#06b6d4",
    btn_start_border="#059669",
    btn_start_hover0="#059669",
    btn_start_hover1="#0891b2",
    btn_start_hover_border="#047857",
    btn_start_pressed0="#047857",
    btn_start_pressed1="#0e7490",
    btn_start_pressed_text="#f1f5f9",
    btn_stop_stop0="#ef4444",
    btn_stop_stop1="#f43f5e",
    btn_stop_border="#dc2626",
    btn_stop_hover0="#dc2626",
    btn_stop_hover1="#e11d48",
    btn_stop_hover_border="#b91c1c",
    btn_stop_pressed0="#b91c1c",
    btn_stop_pressed1="#be123c",
    btn_stop_pressed_text="#f1f5f9",
    table_bg="#ffffff",
    table_alt_bg="#f8fafc",
    table_grid="#e2e8f0",
    table_border="#cbd5e1",
    table_selection_bg="#dbeafe",
    table_selection_text="#1e293b",
    table_header_bg="#f1f5f9",
    table_item_border="#f1f5f9",
    table_item_color="color: #1e293b;",
    scrollbar_bg="#f8fafc",
    scrollbar_handle_hover="#94a3b8",
    input_hover_border="#3b82f6",
    control_checked_color="#3b82f6",
    control_text="#334155",
    slider_groove="#e2e8f0",
    slider_subpage="#3b82f6",
    slider_handle_bg="#ffffff",
    slider_handle_border="#3b82f6",
    slider_handle_hover="#f1f5f9",
    slider_handle_hover_border="border-color: #2563eb;",
    progress_bg="#f1f5f9",
    progress_border="#e2e8f0",
    progress_text="#334155",
    progress_chunk_stop0="#3b82f6",
    progress_chunk_stop1="#06b6d4",
    log_bg="#ffffff",
    log_color="#334155",
    log_border="#e2e8f0",
    group_box_title_color="#2563eb",
    menu_border="#e2e8f0",
    zorg_credit_color="#cbd5e1",
)


def _render_theme_qss(p: ThemePalette) -> str:
    table_item_extra = f"\n    {p.table_item_color}" if p.table_item_color else ""
    slider_handle_hover_extra = f"\n    {p.slider_handle_hover_border}" if p.slider_handle_hover_border else ""
    return f"""/* Global Application Style */
QWidget {{
    background-color: {p.bg_main};
    color: {p.text_main};
    font-family: "Segoe UI", -apple-system, BlinkMacSystemFont, "Roboto", sans-serif;
    font-size: 13px;
    selection-background-color: {p.selection_bg};
    selection-color: {p.selection_text};
}}

/* Tooltips */
QToolTip {{
    background-color: {p.tooltip_bg};
    color: {p.tooltip_text};
    border: 1px solid {p.tooltip_border};
    padding: 4px 8px;
    border-radius: 4px;
}}

/* Bottom Control Bar Frame */
QFrame#bottomFrame {{
    background-color: {p.bg_card};
    border: 1px solid {p.border_muted};
    border-radius: 8px;
}}

/* Log Title */
QLabel#logTitleLabel {{
    font-weight: 600;
    color: {p.accent};
    background: transparent;
}}

/* Status & ETA Labels */
QLabel#statusLabel {{
    font-weight: 600;
    color: {p.text_main};
    background: transparent;
}}

QLabel#etaLabel {{
    color: {p.text_muted};
    font-size: 12px;
    background: transparent;
}}

/* CRF Slider Hint Labels */
QLabel#crfHintLabel {{
    font-size: 11px;
    color: {p.crf_hint_color};
    background: transparent;
}}

/* Advanced Settings Toggle */
QPushButton#advToggleBtn {{
    text-align: left;
    font-weight: 600;
    color: {p.accent};
    border: none;
    padding: 4px;
    background: transparent;
}}

QPushButton#advToggleBtn:hover {{
    color: {p.accent_hover};
}}

/* Splitter */
QSplitter::handle {{
    background-color: transparent;
}}

QSplitter::handle:horizontal {{
    width: 0px;
}}

QSplitter::handle:vertical {{
    height: 4px;
    background-color: {p.splitter_handle};
}}

/* Header Subtitle / Author Credit */
QLabel#zorgCreditLabel {{
    color: {p.zorg_credit_color};
    font-size: 11px;
    font-weight: 500;
    background: transparent;
    padding-right: 6px;
}}

/* Header Action Bar Buttons */
QPushButton {{
    background-color: {p.btn_header_bg};
    color: {p.btn_header_color};
    border: 1px solid {p.border_main};
    border-radius: 6px;
    padding: 7px 14px;
    font-weight: 500;
    min-height: 18px;
}}

QPushButton:hover {{
    background-color: {p.bg_hover};
    border-color: {p.btn_header_hover_border};
    color: {p.btn_header_hover_color};
}}

QPushButton:pressed {{
    background-color: {p.bg_pressed};
}}

QPushButton:disabled {{
    background-color: {p.bg_disabled};
    color: {p.text_disabled};
    border-color: {p.btn_header_disabled_border};
}}

/* Theme Toggle Button */
QPushButton#themeToggle, QPushButton#langToggle {{
    background: transparent;
    border: none;
    font-size: 18px;
    padding: 4px;
    border-radius: 6px;
}}

QPushButton#themeToggle:hover, QPushButton#langToggle:hover {{
    background-color: {p.btn_icon_hover_bg};
    border: 1px solid {p.border_main};
}}

QPushButton#themeToggle:pressed, QPushButton#langToggle:pressed {{
    background-color: {p.btn_icon_pressed_bg};
}}

QPushButton#langToggle {{
    font-size: 12px;
    font-weight: 700;
    color: {p.accent};
}}

/* Primary Action Button (Start Conversion) */
QPushButton#primaryButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.btn_start_stop0}, stop:1 {p.btn_start_stop1});
    color: #ffffff;
    font-weight: 700;
    font-size: 14px;
    border: 1px solid {p.btn_start_border};
    border-radius: 6px;
    padding: 8px 18px;
}}

QPushButton#primaryButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.btn_start_hover0}, stop:1 {p.btn_start_hover1});
    border-color: {p.btn_start_hover_border};
    color: #ffffff;
}}

QPushButton#primaryButton:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.btn_start_pressed0}, stop:1 {p.btn_start_pressed1});
    color: {p.btn_start_pressed_text};
}}

QPushButton#primaryButton:disabled {{
    background: {p.btn_action_disabled_bg};
    color: {p.btn_action_disabled_color};
    border: 1px solid {p.btn_action_disabled_border};
}}

/* Danger / Stop Button (Cancel Conversion) */
QPushButton#dangerButton {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.btn_stop_stop0}, stop:1 {p.btn_stop_stop1});
    color: #ffffff;
    font-weight: 700;
    font-size: 14px;
    border: 1px solid {p.btn_stop_border};
    border-radius: 6px;
    padding: 8px 18px;
}}

QPushButton#dangerButton:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.btn_stop_hover0}, stop:1 {p.btn_stop_hover1});
    border-color: {p.btn_stop_hover_border};
    color: #ffffff;
}}

QPushButton#dangerButton:pressed {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.btn_stop_pressed0}, stop:1 {p.btn_stop_pressed1});
    color: {p.btn_stop_pressed_text};
}}

QPushButton#dangerButton:disabled {{
    background: {p.btn_action_disabled_bg};
    color: {p.btn_action_disabled_color};
    border: 1px solid {p.btn_action_disabled_border};
}}

/* Table View */
QTableWidget, QTableView {{
    background-color: {p.table_bg};
    alternate-background-color: {p.table_alt_bg};
    gridline-color: {p.table_grid};
    border: 1px solid {p.table_border};
    border-radius: 6px;
    selection-background-color: {p.table_selection_bg};
    selection-color: {p.table_selection_text};
    outline: none;
}}

QHeaderView::section {{
    background-color: {p.table_header_bg};
    color: {p.accent};
    padding: 8px;
    border: none;
    border-right: 1px solid {p.border_muted};
    border-bottom: 1px solid {p.border_muted};
    font-weight: 600;
    font-size: 12px;
}}

QTableWidget::item {{
    padding: 4px 6px;
    border-bottom: 1px solid {p.table_item_border};{table_item_extra}
}}

/* Scrollbars */
QScrollBar:vertical {{
    background-color: {p.scrollbar_bg};
    width: 10px;
    margin: 0px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical {{
    background-color: {p.border_main};
    min-height: 20px;
    border-radius: 5px;
}}

QScrollBar::handle:vertical:hover {{
    background-color: {p.scrollbar_handle_hover};
}}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}

QScrollBar:horizontal {{
    background-color: {p.scrollbar_bg};
    height: 10px;
    margin: 0px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal {{
    background-color: {p.border_main};
    min-width: 20px;
    border-radius: 5px;
}}

QScrollBar::handle:horizontal:hover {{
    background-color: {p.scrollbar_handle_hover};
}}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}

/* Settings Panels & GroupBoxes */
QGroupBox {{
    background-color: {p.bg_card};
    border: 1px solid {p.border_muted};
    border-radius: 8px;
    margin-top: 14px;
    font-weight: 600;
    padding-top: 14px;
    color: {p.text_main};
}}

QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 2px 8px;
    background-color: {p.bg_card};
    color: {p.group_box_title_color};
    border-radius: 4px;
}}

/* Form Inputs */
QComboBox, QLineEdit {{
    background-color: {p.bg_input};
    border: 1px solid {p.border_main};
    border-radius: 6px;
    padding: 6px 10px;
    color: {p.text_main};
}}

QComboBox:hover, QLineEdit:hover {{
    border-color: {p.input_hover_border};
}}

QComboBox:focus, QLineEdit:focus {{
    border-color: {p.border_focus};
}}

QComboBox::drop-down {{
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: none;
}}

QComboBox QAbstractItemView {{
    background-color: {p.bg_card};
    border: 1px solid {p.border_main};
    selection-background-color: {p.selection_bg};
    selection-color: {p.selection_text};
    color: {p.text_main};
    outline: none;
}}

/* Radio Buttons */
QRadioButton {{
    spacing: 8px;
    color: {p.text_main};
}}

QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 2px solid {p.border_main};
    background-color: {p.bg_input};
}}

QRadioButton::indicator:checked {{
    border-color: {p.control_checked_color};
    background-color: {p.control_checked_color};
}}

/* Checkboxes */
QCheckBox {{
    spacing: 6px;
    color: {p.control_text};
}}

QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {p.border_main};
    border-radius: 4px;
    background-color: {p.bg_input};
}}

QCheckBox::indicator:checked {{
    background-color: {p.control_checked_color};
    border-color: {p.control_checked_color};
}}

/* Sliders */
QSlider::groove:horizontal {{
    height: 6px;
    background: {p.slider_groove};
    border-radius: 3px;
}}

QSlider::sub-page:horizontal {{
    background: {p.slider_subpage};
    border-radius: 3px;
}}

QSlider::handle:horizontal {{
    background: {p.slider_handle_bg};
    border: 2px solid {p.slider_handle_border};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}

QSlider::handle:horizontal:hover {{
    background: {p.slider_handle_hover};{slider_handle_hover_extra}
}}

/* Progress Bar */
QProgressBar {{
    background-color: {p.progress_bg};
    border: 1px solid {p.progress_border};
    border-radius: 5px;
    text-align: center;
    color: {p.progress_text};
    font-size: 11px;
    font-weight: 600;
}}

QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p.progress_chunk_stop0}, stop:1 {p.progress_chunk_stop1});
    border-radius: 4px;
}}

/* Log Console TextEdit */
QTextEdit#logConsole {{
    background-color: {p.log_bg};
    color: {p.log_color};
    font-family: "Cascadia Code", "Consolas", "Courier New", monospace;
    font-size: 12px;
    border: 1px solid {p.log_border};
    border-radius: 6px;
    padding: 8px;
}}

/* Context Menus */
QMenu {{
    background-color: {p.bg_card};
    border: 1px solid {p.menu_border};
    border-radius: 6px;
    padding: 4px;
}}

QMenu::item {{
    color: {p.text_main};
    padding: 6px 20px;
    border-radius: 4px;
}}

QMenu::item:selected {{
    background-color: {p.selection_bg};
    color: #ffffff;
}}
"""


THEME_QSS = _render_theme_qss(DARK_PALETTE)
LIGHT_THEME_QSS = _render_theme_qss(LIGHT_PALETTE)

COLOR_PENDING = "#565f89"
COLOR_RUNNING = "#7aa2f7"
COLOR_COMPLETED = "#9ece6a"
COLOR_FAILED = "#f7768e"
COLOR_WARNING = "#e0af68"
COLOR_BG_DARK = "#16161e"
COLOR_BG_CARD = "#1f2335"
COLOR_BORDER = "#292e42"
COLOR_TEXT_PRIMARY = "#c0caf5"
COLOR_TEXT_MUTED = "#7a88cf"
COLOR_ACCENT = "#2ac3de"

LIGHT_COLOR_PENDING = "#64748b"
LIGHT_COLOR_RUNNING = "#2563eb"
LIGHT_COLOR_COMPLETED = "#16a34a"
LIGHT_COLOR_FAILED = "#dc2626"
LIGHT_COLOR_WARNING = "#d97706"
LIGHT_COLOR_BG_MAIN = "#f8fafc"
LIGHT_COLOR_BG_CARD = "#ffffff"
LIGHT_COLOR_BORDER = "#e2e8f0"
LIGHT_COLOR_TEXT_PRIMARY = "#1e293b"
LIGHT_COLOR_TEXT_MUTED = "#64748b"
LIGHT_COLOR_ACCENT = "#0284c7"


def get_theme(dark: bool = True) -> str:
    """Returns the QSS stylesheet for dark (default) or light theme."""
    return THEME_QSS if dark else LIGHT_THEME_QSS


