"""Internationalization module for VideoConverter UI.

Simple dict-based i18n with runtime language switching.
Supported languages: 'en' (English, default), 'ru' (Russian).
"""

from __future__ import annotations

from typing import Callable

_current_lang: str = "en"
_listeners: list[Callable[[], None]] = []

TRANSLATIONS: dict[str, dict[str, str]] = {
    # ── Main Window ──
    "window_title": {"ru": "Free Simple Video Converter", "en": "Free Simple Video Converter"},
    "btn_add_files": {"ru": "➕ Добавить файлы", "en": "➕ Add Files"},
    "btn_add_files_tip": {"ru": "Выбрать один или несколько видеофайлов", "en": "Select one or more video files"},
    "btn_add_folder": {"ru": "📁 Добавить папку", "en": "📁 Add Folder"},
    "btn_add_folder_tip": {"ru": "Рекурсивно добавить видео из папки", "en": "Recursively add videos from a folder"},
    "btn_clear_completed": {"ru": "Очистить завершенные", "en": "Clear Completed"},
    "btn_clear_all": {"ru": "Очистить всё", "en": "Clear All"},
    "btn_theme_tip": {"ru": "Переключить тему", "en": "Toggle Theme"},
    "btn_lang_tip": {"ru": "Switch language", "en": "Переключить язык"},
    "btn_start": {"ru": "▶  Конвертировать", "en": "▶  Convert"},
    "btn_stop": {"ru": "⏹  Остановить", "en": "⏹  Stop"},
    "status_ready": {"ru": "Готово к работе", "en": "Ready"},
    "status_converting": {"ru": "Конвертация очереди...", "en": "Converting queue..."},
    "status_stopped": {"ru": "Очередь остановлена / готова", "en": "Queue stopped / ready"},
    "status_empty": {"ru": "Очередь пуста", "en": "Queue empty"},
    "status_progress": {
        "ru": "Обработка: завершено {completed} из {total} ({percent:.1f}%)",
        "en": "Processing: {completed} of {total} done ({percent:.1f}%)",
    },
    "file_filter": {
        "ru": "Видеофайлы (*.mp4 *.avi *.mkv *.mov *.wmv *.asf *.wm *.wma *.flv *.webm *.m4v *.ts *.mts);;Все файлы (*.*)",
        "en": "Video Files (*.mp4 *.avi *.mkv *.mov *.wmv *.asf *.wm *.wma *.flv *.webm *.m4v *.ts *.mts);;All Files (*.*)",
    },
    "dlg_select_files": {"ru": "Выберите видеофайлы", "en": "Select Video Files"},
    "dlg_select_folder": {"ru": "Выберите папку с видеофайлами", "en": "Select Video Folder"},

    # ── Settings Panel ──
    "group_preset": {"ru": "Пресет", "en": "Preset"},
    "group_quality": {"ru": "Качество (CRF): {value}", "en": "Quality (CRF): {value}"},
    "lbl_quality": {"ru": "Качество", "en": "Quality"},
    "lbl_compression": {"ru": "Сжатие", "en": "Compression"},
    "group_encoder": {"ru": "Энкодер", "en": "Encoder"},
    "group_output": {"ru": "Папка назначения", "en": "Output Folder"},
    "radio_same_dir": {"ru": "Рядом с исходным файлом", "en": "Same folder as source"},
    "radio_custom_dir": {"ru": "В выбранную папку:", "en": "Custom folder:"},
    "placeholder_dir": {"ru": "Выберите папку...", "en": "Choose folder..."},
    "btn_browse": {"ru": "Обзор...", "en": "Browse..."},
    "adv_collapsed": {"ru": "▸ Расширенные настройки", "en": "▸ Advanced Settings"},
    "adv_expanded": {"ru": "▾ Расширенные настройки", "en": "▾ Advanced Settings"},
    "lbl_fps": {"ru": "Частота кадров:", "en": "Frame Rate:"},
    "lbl_audio_bitrate": {"ru": "Аудио битрейт:", "en": "Audio Bitrate:"},
    "fps_original": {"ru": "Исходный", "en": "Original"},
    "audio_192k": {"ru": "192k (Рекомендуется)", "en": "192k (Recommended)"},
    "audio_128k": {"ru": "128k (Стандарт)", "en": "128k (Standard)"},
    "audio_96k": {"ru": "96k (Низкое)", "en": "96k (Low)"},
    "audio_64k": {"ru": "64k (Минимальное)", "en": "64k (Minimum)"},
    "audio_32k": {"ru": "32k (Голос)", "en": "32k (Voice)"},
    "audio_256k": {"ru": "256k (Высокое)", "en": "256k (High)"},
    "audio_320k": {"ru": "320k (Максимальное)", "en": "320k (Maximum)"},
    "dlg_select_output": {"ru": "Выберите папку для сохранения видео", "en": "Select Output Folder"},

    # ── Log Console ──
    "log_title": {"ru": "Журнал событий", "en": "Event Log"},
    "log_autoscroll": {"ru": "Автопрокрутка", "en": "Auto-scroll"},
    "log_clear": {"ru": "Очистить лог", "en": "Clear Log"},

    # ── Job Table ──
    "col_index": {"ru": "#", "en": "#"},
    "col_file": {"ru": "Файл", "en": "File"},
    "col_source": {"ru": "Разрешение", "en": "Resolution"},
    "col_duration": {"ru": "Длительность", "en": "Duration"},
    "col_size": {"ru": "Размер", "en": "Size"},
    "col_result": {"ru": "Результат", "en": "Result"},
    "col_preset": {"ru": "Пресет", "en": "Preset"},
    "col_progress": {"ru": "Прогресс", "en": "Progress"},
    "empty_drop_hint": {
        "ru": "📁 Перетащите видеофайлы или папки сюда\nили используйте кнопки добавления выше",
        "en": "📁 Drag and drop video files or folders here\nor use the Add buttons above",
    },
    "ctx_remove_multi": {"ru": "Удалить из очереди ({count})", "en": "Remove from queue ({count})"},
    "ctx_remove_single": {"ru": "Удалить из очереди", "en": "Remove from queue"},

    # ── Job Status Strings ──
    "job_pending": {"ru": "В очереди", "en": "Queued"},
    "job_probing": {"ru": "🔍 Анализ...", "en": "🔍 Analyzing..."},
    "job_completed": {"ru": "✓ Завершено", "en": "✓ Completed"},
    "job_failed": {"ru": "✕ Ошибка", "en": "✕ Error"},
    "job_cancelled": {"ru": "Отменено", "en": "Cancelled"},
    "job_cancelled_by_user": {"ru": "Отменено пользователем", "en": "Cancelled by user"},

    # ── Domain display names ──
    "preset_original": {"ru": "Исходное разрешение", "en": "Original (No Resize)"},
    "preset_480p": {"ru": "480p (до 854px)", "en": "480p (up to 854px)"},
    "preset_720p": {"ru": "720p (до 1280px)", "en": "720p (up to 1280px)"},
    "preset_1080p": {"ru": "1080p (до 1920px)", "en": "1080p (up to 1920px)"},
    "preset_2k": {"ru": "2K (до 2560px)", "en": "2K (up to 2560px)"},
    "preset_4k": {"ru": "4K (до 3840px)", "en": "4K (up to 3840px)"},
    "encoder_auto": {"ru": "Авто (GPU / CPU)", "en": "Auto (GPU / CPU)"},

    # ── JobStatus.display_name ──
    "status_pending": {"ru": "В очереди", "en": "Queued"},
    "status_probing": {"ru": "Анализ...", "en": "Analyzing..."},
    "status_running": {"ru": "Конвертация...", "en": "Converting..."},
    "status_completed": {"ru": "Завершено", "en": "Completed"},
    "status_failed": {"ru": "Ошибка", "en": "Error"},
    "status_cancelled": {"ru": "Отменено", "en": "Cancelled"},
}


def tr(key: str, **kwargs: object) -> str:
    """Translate a key to the current language, with optional format args."""
    entry = TRANSLATIONS.get(key)
    if entry is None:
        return key
    text = entry.get(_current_lang, entry.get("en", key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except (KeyError, ValueError):
            return text
    return text


def get_language() -> str:
    """Return current language code ('ru' or 'en')."""
    return _current_lang


def set_language(lang: str) -> None:
    """Set the current language and notify all registered listeners."""
    global _current_lang
    if lang not in ("ru", "en"):
        lang = "en"
    _current_lang = lang
    for cb in _listeners:
        cb()


def on_language_changed(callback: Callable[[], None]) -> None:
    """Register a callback invoked whenever the language changes."""
    if callback not in _listeners:
        _listeners.append(callback)


def remove_language_listener(callback: Callable[[], None]) -> None:
    """Unregister a language-change callback."""
    if callback in _listeners:
        _listeners.remove(callback)
