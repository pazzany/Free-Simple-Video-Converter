"""Hardware and software encoder discovery, probing, and argument translation."""

from __future__ import annotations

import subprocess
import sys
import threading

from video_converter.domain.encoders import EncoderProbeResult, EncoderSelectionResult, EncoderType
from video_converter.media.binaries import find_ffmpeg

# Probe frame size. Must stay at or above hardware encoder minimum input
# dimensions (NVIDIA NVENC requires at least 146x146 for H.264); smaller
# frames make working hardware encoders fail initialization and report
# themselves unavailable.
PROBE_FRAME_SIZE = "256x256"

# In-memory cache for probed encoder results: (ffmpeg_path, encoder) -> EncoderProbeResult
_ENCODER_PROBE_CACHE: dict[tuple[str, EncoderType], EncoderProbeResult] = {}
_PROBE_CACHE_LOCK = threading.Lock()
_PROBE_FLIGHT_LOCKS: dict[tuple[str, EncoderType], threading.Lock] = {}

_PROBE_DIAGNOSTIC_REASONS: dict[tuple[EncoderType, bool], str] = {
    (EncoderType.NVENC, True): "NVIDIA NVENC hardware encoder initialized successfully with conservative parameters.",
    (EncoderType.NVENC, False): "NVIDIA driver or hardware rejected NVENC initialization (missing nvencodeapi64.dll, driver/header incompatibility, or unsupported GPU). Falling back to QSV.",
    (EncoderType.QSV, True): "Intel Quick Sync Video hardware encoder initialized successfully with conservative parameters.",
    (EncoderType.QSV, False): "Intel QSV unavailable or driver runtime initialization failed. Falling back to AMF.",
    (EncoderType.AMF, True): "AMD AMF hardware encoder initialized successfully with conservative parameters.",
    (EncoderType.AMF, False): "AMD AMF unavailable or driver runtime initialization failed. Falling back to CPU.",
    (EncoderType.LIBX264, True): "Software CPU encoder (libx264) ready.",
    (EncoderType.LIBX264, False): "Software CPU encoder unavailable.",
}


def clear_encoder_cache() -> None:
    """Clear in-memory encoder availability cache."""
    with _PROBE_CACHE_LOCK:
        _ENCODER_PROBE_CACHE.clear()
        _PROBE_FLIGHT_LOCKS.clear()


def get_encoder_args(encoder: EncoderType, crf: int = 24) -> list[str]:
    """Translate EncoderType and quality value into FFmpeg CLI arguments.

    Args:
        encoder: The target EncoderType.
        crf: CRF / constant quality parameter (typically 0-51).

    Returns:
        List of FFmpeg arguments configuring the video codec, rate control, and preset.
    """
    crf_str = str(crf)
    if encoder == EncoderType.NVENC:
        return ["-c:v", "h264_nvenc", "-cq", crf_str, "-preset", "medium", "-rc", "vbr"]
    elif encoder == EncoderType.QSV:
        return ["-c:v", "h264_qsv", "-global_quality", crf_str, "-preset", "medium"]
    elif encoder == EncoderType.AMF:
        return [
            "-c:v",
            "h264_amf",
            "-rc",
            "cqp",
            "-qp_p",
            crf_str,
            "-qp_i",
            crf_str,
            "-quality",
            "balanced",
        ]
    else:
        # Default for LIBX264, AUTO, or any fallback
        return ["-c:v", "libx264", "-crf", crf_str, "-preset", "medium"]


def probe_encoder(
    ffmpeg_path: str, encoder: EncoderType, use_cache: bool = True
) -> EncoderProbeResult:
    """Probe if a given video encoder is operational using FFmpeg with exact arguments."""
    cache_key = (ffmpeg_path, encoder)
    if use_cache:
        with _PROBE_CACHE_LOCK:
            if cache_key in _ENCODER_PROBE_CACHE:
                return _ENCODER_PROBE_CACHE[cache_key]
            if cache_key not in _PROBE_FLIGHT_LOCKS:
                _PROBE_FLIGHT_LOCKS[cache_key] = threading.Lock()
            flight_lock = _PROBE_FLIGHT_LOCKS[cache_key]

        with flight_lock:
            with _PROBE_CACHE_LOCK:
                if cache_key in _ENCODER_PROBE_CACHE:
                    return _ENCODER_PROBE_CACHE[cache_key]

            probe_result = _execute_probe_subprocess(ffmpeg_path, encoder)

            with _PROBE_CACHE_LOCK:
                _ENCODER_PROBE_CACHE[cache_key] = probe_result
            return probe_result

    return _execute_probe_subprocess(ffmpeg_path, encoder)


def _execute_probe_subprocess(ffmpeg_path: str, encoder: EncoderType) -> EncoderProbeResult:
    """Execute probe subprocess without holding probe cache locks."""
    startupinfo = None
    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "lavfi",
        "-i",
        f"testsrc=duration=0.04:size={PROBE_FRAME_SIZE}:rate=25",
        *get_encoder_args(encoder, crf=24),
        "-f",
        "null",
        "-",
    ]

    stderr_text = ""
    try:
        res = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=3,
            startupinfo=startupinfo,
            check=False,
        )
        stderr_text = res.stderr.decode("utf-8", errors="replace").strip()
        is_available = res.returncode == 0
    except Exception as exc:
        stderr_text = str(exc)
        is_available = False

    reason = _PROBE_DIAGNOSTIC_REASONS.get(
        (encoder, is_available),
        f"{encoder.display_name} probe {'succeeded' if is_available else 'failed'}.",
    )

    return EncoderProbeResult(
        encoder=encoder,
        available=is_available,
        stderr=stderr_text,
        reason=reason,
    )


def test_encoder_available(
    ffmpeg_path: str, encoder: EncoderType, use_cache: bool = True
) -> bool:
    """Test if a given video encoder is operational using FFmpeg.

    Runs probe_encoder and returns whether it is available.
    """
    if encoder in (EncoderType.AUTO, EncoderType.LIBX264):
        return True

    return probe_encoder(ffmpeg_path, encoder, use_cache=use_cache).available


def detect_encoder_selection(
    ffmpeg_path: str | None = None, use_cache: bool = True
) -> EncoderSelectionResult:
    """Detect encoder selection preserving ordered candidate attempts."""
    resolved_path = ffmpeg_path or find_ffmpeg()
    if not resolved_path:
        return EncoderSelectionResult(selected_encoder=None, attempts=())

    attempts: list[EncoderProbeResult] = []
    priority = [EncoderType.NVENC, EncoderType.QSV, EncoderType.AMF]
    for enc in priority:
        probe_res = probe_encoder(resolved_path, enc, use_cache=use_cache)
        attempts.append(probe_res)
        if probe_res.available:
            return EncoderSelectionResult(selected_encoder=enc, attempts=tuple(attempts))

    raw_cpu_probe = probe_encoder(resolved_path, EncoderType.LIBX264, use_cache=use_cache)
    attempts.append(raw_cpu_probe)
    if raw_cpu_probe.available:
        return EncoderSelectionResult(
            selected_encoder=EncoderType.LIBX264,
            attempts=tuple(attempts),
        )

    return EncoderSelectionResult(selected_encoder=None, attempts=tuple(attempts))


def detect_best_probe(
    ffmpeg_path: str | None = None, use_cache: bool = True
) -> tuple[EncoderType, EncoderProbeResult | None]:
    """Detect the highest priority working video encoder and its probe result."""
    selection = detect_encoder_selection(ffmpeg_path=ffmpeg_path, use_cache=use_cache)
    if not selection.attempts:
        return EncoderType.LIBX264, None

    if selection.selected_encoder and selection.selected_encoder.is_hardware:
        last_attempt = selection.attempts[-1]
        return selection.selected_encoder, last_attempt

    # Hardware probes failed or CPU was evaluated
    cpu_attempt = next((a for a in selection.attempts if a.encoder == EncoderType.LIBX264), None)
    if cpu_attempt:
        if cpu_attempt.available:
            reason = (
                "All hardware acceleration probes failed or hardware is absent. "
                "Operating with high-compatibility libx264 CPU encoder."
            )
        else:
            reason = cpu_attempt.reason or "Software CPU encoder unavailable."
        cpu_probe = EncoderProbeResult(
            encoder=EncoderType.LIBX264,
            available=cpu_attempt.available,
            stderr=cpu_attempt.stderr,
            reason=reason,
        )
        return EncoderType.LIBX264, cpu_probe

    return EncoderType.LIBX264, None


def detect_best_encoder(
    ffmpeg_path: str | None = None, use_cache: bool = True
) -> EncoderType:
    """Detect the highest priority working video encoder (NVENC -> QSV -> AMF -> LIBX264)."""
    enc, _ = detect_best_probe(ffmpeg_path=ffmpeg_path, use_cache=use_cache)
    return enc


def detect_available_encoders(
    ffmpeg_path: str | None = None, use_cache: bool = True
) -> list[EncoderType]:
    """Detect and return all working encoders, always including LIBX264."""
    resolved_path = ffmpeg_path or find_ffmpeg()
    available: list[EncoderType] = []

    if not resolved_path:
        return [EncoderType.LIBX264]

    hw_encoders = [EncoderType.NVENC, EncoderType.QSV, EncoderType.AMF]
    for enc in hw_encoders:
        if test_encoder_available(resolved_path, enc, use_cache=use_cache):
            available.append(enc)

    available.append(EncoderType.LIBX264)
    return available
