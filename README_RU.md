# Free Simple Video Converter

[English version](README.md)

Пакетная конвертация видеофайлов с пресетами разрешения и поддержкой аппаратного кодирования.

![Интерфейс Free Simple Video Converter](docs/images/ru.jpg)

## Возможности

- **Пакетная обработка** — добавление отдельных видеофайлов или папок вместе с вложенными каталогами.
- **Пресеты разрешения** — **Original**, **480p**, **720p**, **1080p**, **2K** и **4K**. Выбранный пресет задаёт максимальное разрешение выходного файла. Если исходное разрешение ниже, оно сохраняется без увеличения.
- **Кодирование** — программное кодирование через `libx264` везде; аппаратное ускорение там, где позволяют драйверы (Windows: NVIDIA NVENC, Intel Quick Sync, AMD AMF; Linux: NVIDIA NVENC, Intel Quick Sync / VAAPI, AMD VAAPI).
- **Параметры вывода** — частота кадров, аудиобитрейт, папка сохранения и автоматическая нумерация файлов.
- **Интерфейс** — светлая и тёмная темы, русский и английский языки.

## Системные требования

- **Windows**: Windows 10 64-bit или новее.
- **Linux**: Ubuntu 22.04 или новее (либо совместимый дистрибутив), x86_64.
- **Аппаратное ускорение** (опционально): GPU NVIDIA со свежим драйвером для NVENC; GPU Intel с медиа-драйверами для Quick Sync / VAAPI; GPU AMD с драйверами Mesa VAAPI (Linux) или средой AMF (Windows).

## Поддерживаемые входные файлы

Очередь принимает файлы `.mp4`, `.mkv`, `.avi`, `.mov`, `.wmv`, `.asf`, `.wm`, `.wma`, `.flv`, `.webm`, `.m4v`, `.ts`, `.mts`, `.m2ts`, `.3gp`, `.vob` и `.ogv`. При добавлении папки программа также находит подходящие файлы во вложенных каталогах.

## Загрузка и быстрый старт

Скачайте архив на странице **Releases** репозитория. На Windows распакуйте его и запустите `FreeSimpleVideoConverter.exe`; установка не требуется. На Linux (Ubuntu 22.04+ x86_64) распакуйте архив `linux-x86_64.tar.gz` и запустите `./FreeSimpleVideoConverter`, либо сделайте `linux-x86_64.AppImage` исполняемым (`chmod +x`) и запускайте напрямую.

Добавьте файлы или папку, выберите пресет и энкодер, укажите папку для результата и запустите конвертацию. Очередь показывает прогресс каждого файла, а журнал событий содержит сведения о конвертации.

## Запуск из исходников

```powershell
git clone https://github.com/pazzany/Free-Simple-Video-Converter.git
cd Free-SimpleVideo-Converter
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
python -m video_converter
```

На Linux:

```bash
git clone https://github.com/pazzany/Free-Simple-Video-Converter.git
cd Free-SimpleVideo-Converter
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m video_converter
```

## Сборка автономного приложения

Для development-сборки нужны соответствующие `ffmpeg.exe` и `ffprobe.exe` в локальной игнорируемой папке `bin/`. Затем выполните:

```powershell
python packaging/build_exe.py
```

Портативный EXE будет создан по пути `dist/FreeSimpleVideoConverter.exe`.

На Linux поместите соответствующие `ffmpeg` и `ffprobe` в папку `bin/` и выполните `python packaging/build_linux_app.py --repo-root . --bin-dir bin --manifest packaging/ffmpeg_artifact_manifest_linux.json --dist-dir dist-linux --work-dir build-linux`, чтобы получить tarball приложения.

## Поведение конвертации

Приложение создаёт MP4-файлы. Во время конвертации используется временный файл `.part.mp4`, поэтому незавершённый результат не заменяет итоговый файл. Пропорции сохраняются, а размеры выходного файла остаются чётными.

На Windows встроенный медиа-движок — custom FFmpeg 6.1.1 UCRT64 build; на Linux (Ubuntu 22.04+ x86_64) — custom FFmpeg 6.1.1 build с поддержкой NVENC, QSV и VAAPI. Аппаратное кодирование зависит от установленного устройства и драйверов. Настройки приложения хранятся в `%LOCALAPPDATA%/FreeSimpleVideoConverter/config.json` на Windows и `~/.config/FreeSimpleVideoConverter/config.json` на Linux.

## Лицензия и уведомления

Проект распространяется по [лицензии MIT](LICENSE). Сведения о лицензиях встроенных компонентов и атрибуции приведены в [уведомлениях о сторонних компонентах](THIRD_PARTY_NOTICES.md).

Процесс предоставления соответствующих исходных текстов для custom FFmpeg build описан в [контрольном списке source release FFmpeg](packaging/FFMPEG_SOURCE_RELEASE_CHECKLIST.md). Исходный рабочий процесс проекта был вдохновлён [orex2121/Video-Compres-StableDif](https://github.com/orex2121/Video-Compres-StableDif).
