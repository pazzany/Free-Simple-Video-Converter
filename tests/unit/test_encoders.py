"""Unit tests for encoder domain model and media encoder probing."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from video_converter.domain.encoders import EncoderProbeResult, EncoderSelectionResult, EncoderType
from video_converter.media.binaries import find_ffmpeg
from video_converter.media.encoders import (
    clear_encoder_cache,
    detect_available_encoders,
    detect_best_encoder,
    detect_best_probe,
    detect_encoder_selection,
    get_encoder_args,
    probe_encoder,
    test_encoder_available as check_encoder_available,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_encoder_cache()
    yield
    clear_encoder_cache()


# ---------------------------------------------------------
# EncoderType Domain Tests
# ---------------------------------------------------------

def test_encoder_type_values():
    assert EncoderType.AUTO.codec_name == "auto"
    assert "Auto" in EncoderType.AUTO.display_name
    assert EncoderType.NVENC.codec_name == "h264_nvenc"
    assert "NVENC" in EncoderType.NVENC.display_name
    assert EncoderType.QSV.codec_name == "h264_qsv"
    assert EncoderType.AMF.codec_name == "h264_amf"
    assert EncoderType.LIBX264.codec_name == "libx264"


def test_encoder_type_is_hardware():
    assert EncoderType.NVENC.is_hardware is True
    assert EncoderType.QSV.is_hardware is True
    assert EncoderType.AMF.is_hardware is True
    assert EncoderType.LIBX264.is_hardware is False
    assert EncoderType.AUTO.is_hardware is False


def test_encoder_type_from_codec_name():
    assert EncoderType.from_codec_name("h264_nvenc") == EncoderType.NVENC
    assert EncoderType.from_codec_name("H264_NVENC") == EncoderType.NVENC
    assert EncoderType.from_codec_name("nvenc") == EncoderType.NVENC
    assert EncoderType.from_codec_name("libx264") == EncoderType.LIBX264
    assert EncoderType.from_codec_name("auto") == EncoderType.AUTO
    assert EncoderType.from_codec_name("h264_qsv") == EncoderType.QSV
    assert EncoderType.from_codec_name("h264_amf") == EncoderType.AMF

    with pytest.raises(ValueError, match="Unknown encoder"):
        EncoderType.from_codec_name("non_existent_codec")


def test_encoder_type_all_options():
    options = EncoderType.all_options()
    assert len(options) == 5
    assert EncoderType.AUTO in options
    assert EncoderType.NVENC in options
    assert EncoderType.LIBX264 in options


# ---------------------------------------------------------
# get_encoder_args Tests
# ---------------------------------------------------------

def test_get_encoder_args_libx264():
    args = get_encoder_args(EncoderType.LIBX264, crf=22)
    assert args == ["-c:v", "libx264", "-crf", "22", "-preset", "medium"]


def test_get_encoder_args_auto_fallback():
    args = get_encoder_args(EncoderType.AUTO, crf=26)
    assert args == ["-c:v", "libx264", "-crf", "26", "-preset", "medium"]


def test_get_encoder_args_nvenc():
    args = get_encoder_args(EncoderType.NVENC, crf=24)
    assert args == ["-c:v", "h264_nvenc", "-cq", "24", "-preset", "medium", "-rc", "vbr"]


def test_encoder_selection_result_dataclass():
    probe_nvenc = EncoderProbeResult(
        encoder=EncoderType.NVENC,
        available=False,
        reason="failed",
    )
    probe_cpu = EncoderProbeResult(
        encoder=EncoderType.LIBX264,
        available=True,
        reason="ok",
    )
    sel = EncoderSelectionResult(
        selected_encoder=EncoderType.LIBX264,
        attempts=(probe_nvenc, probe_cpu),
    )
    assert sel.selected_encoder == EncoderType.LIBX264
    assert len(sel.attempts) == 2
    assert sel.attempts[0] == probe_nvenc
    assert sel.attempts[1] == probe_cpu


def test_encoder_probe_result_dataclass():
    result = EncoderProbeResult(
        encoder=EncoderType.NVENC,
        available=True,
        stderr="some warning",
        reason="NVIDIA NVENC hardware encoder initialized successfully with conservative parameters.",
    )
    assert result.encoder == EncoderType.NVENC
    assert result.available is True
    assert result.stderr == "some warning"
    assert "initialized successfully" in result.reason


def test_get_encoder_args_qsv():
    args = get_encoder_args(EncoderType.QSV, crf=20)
    assert args == ["-c:v", "h264_qsv", "-global_quality", "20", "-preset", "medium"]


def test_get_encoder_args_amf():
    args = get_encoder_args(EncoderType.AMF, crf=28)
    assert args == [
        "-c:v",
        "h264_amf",
        "-rc",
        "cqp",
        "-qp_p",
        "28",
        "-qp_i",
        "28",
        "-quality",
        "balanced",
    ]


# ---------------------------------------------------------
# probe_encoder Tests
# ---------------------------------------------------------

@patch("subprocess.run")
def test_probe_frame_meets_hardware_minimum_dimensions(mock_run):
    """Probe frames must satisfy hardware encoder minimum dimensions.

    NVIDIA NVENC (e.g. Turing) rejects frames smaller than 146x146 for
    H.264, so a 64x64 probe falsely reports NVENC as unavailable.
    """
    mock_run.return_value = MagicMock(returncode=0, stderr=b"")
    probe_encoder("ffmpeg.exe", EncoderType.NVENC, use_cache=False)
    cmd = mock_run.call_args[0][0]
    testsrc = cmd[cmd.index("-i") + 1]
    size = testsrc.split("size=")[1].split(":")[0]
    width, height = (int(part) for part in size.split("x"))
    assert min(width, height) >= 146


@patch("subprocess.run")
def test_probe_encoder_exact_args_nvenc(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr=b"")
    res = probe_encoder("ffmpeg.exe", EncoderType.NVENC, use_cache=False)
    assert res.available is True
    assert "initialized successfully" in res.reason
    mock_run.assert_called_once_with(
        [
            "ffmpeg.exe",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.04:size=256x256:rate=25",
            "-c:v",
            "h264_nvenc",
            "-cq",
            "24",
            "-preset",
            "medium",
            "-rc",
            "vbr",
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3,
        startupinfo=mock_run.call_args[1].get("startupinfo"),
        check=False,
    )


@patch("subprocess.run")
def test_probe_encoder_exact_args_qsv(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr=b"")
    res = probe_encoder("ffmpeg.exe", EncoderType.QSV, use_cache=False)
    assert res.available is True
    mock_run.assert_called_once_with(
        [
            "ffmpeg.exe",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.04:size=256x256:rate=25",
            "-c:v",
            "h264_qsv",
            "-global_quality",
            "24",
            "-preset",
            "medium",
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3,
        startupinfo=mock_run.call_args[1].get("startupinfo"),
        check=False,
    )


@patch("subprocess.run")
def test_probe_encoder_exact_args_amf(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr=b"")
    res = probe_encoder("ffmpeg.exe", EncoderType.AMF, use_cache=False)
    assert res.available is True
    mock_run.assert_called_once_with(
        [
            "ffmpeg.exe",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "lavfi",
            "-i",
            "testsrc=duration=0.04:size=256x256:rate=25",
            "-c:v",
            "h264_amf",
            "-rc",
            "cqp",
            "-qp_p",
            "24",
            "-qp_i",
            "24",
            "-quality",
            "balanced",
            "-f",
            "null",
            "-",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=3,
        startupinfo=mock_run.call_args[1].get("startupinfo"),
        check=False,
    )


@patch("subprocess.run")
def test_probe_encoder_failure_captures_stderr_and_diagnostic(mock_run):
    err_output = b"[h264_nvenc] Driver does not support nvenc API 13.1"
    mock_run.return_value = MagicMock(returncode=1, stderr=err_output)
    res = probe_encoder("ffmpeg.exe", EncoderType.NVENC, use_cache=False)
    assert res.available is False
    assert "[h264_nvenc]" in res.stderr
    assert "Falling back to QSV" in res.reason


@patch("subprocess.run")
def test_probe_encoder_caching(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr=b"")
    res1 = probe_encoder("ffmpeg.exe", EncoderType.NVENC, use_cache=True)
    assert res1.available is True
    assert mock_run.call_count == 1
    res2 = probe_encoder("ffmpeg.exe", EncoderType.NVENC, use_cache=True)
    assert res2.available is True
    assert mock_run.call_count == 1


def test_probe_encoder_overlapping_single_flight():
    """Verify that concurrent probes for the same cache key execute subprocess only once."""
    call_count = 0
    barrier = threading.Barrier(2)

    def slow_subprocess_run(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        time.sleep(0.05)
        return MagicMock(returncode=0, stderr=b"")

    results = []

    def probe_worker():
        try:
            barrier.wait(timeout=1)
        except Exception:
            pass
        res = probe_encoder("ffmpeg_flight.exe", EncoderType.NVENC, use_cache=True)
        results.append(res)

    with patch("subprocess.run", side_effect=slow_subprocess_run):
        t1 = threading.Thread(target=probe_worker)
        t2 = threading.Thread(target=probe_worker)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert len(results) == 2
    assert results[0].available is True
    assert results[1].available is True
    assert results[0] == results[1]
    assert call_count == 1


@patch("subprocess.run")
def test_detect_encoder_selection_hardware_succeeds(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr=b"")
    sel = detect_encoder_selection("ffmpeg.exe", use_cache=False)
    assert sel.selected_encoder == EncoderType.NVENC
    assert len(sel.attempts) == 1
    assert sel.attempts[0].encoder == EncoderType.NVENC
    assert sel.attempts[0].available is True


@patch("subprocess.run")
def test_detect_encoder_selection_hardware_fails_cpu_succeeds(mock_run):
    def run_side_effect(cmd, **kwargs):
        # Fail NVENC, QSV, AMF; succeed on libx264
        if "h264_nvenc" in cmd or "h264_qsv" in cmd or "h264_amf" in cmd:
            return MagicMock(returncode=1, stderr=b"hw error")
        return MagicMock(returncode=0, stderr=b"")

    mock_run.side_effect = run_side_effect
    sel = detect_encoder_selection("ffmpeg.exe", use_cache=False)
    assert sel.selected_encoder == EncoderType.LIBX264
    assert len(sel.attempts) == 4
    assert [a.encoder for a in sel.attempts] == [
        EncoderType.NVENC,
        EncoderType.QSV,
        EncoderType.AMF,
        EncoderType.LIBX264,
    ]
    assert all(not a.available for a in sel.attempts[:3])
    assert sel.attempts[3].available is True


@patch("subprocess.run")
def test_detect_encoder_selection_all_fail(mock_run):
    mock_run.return_value = MagicMock(returncode=1, stderr=b"all fail")
    sel = detect_encoder_selection("ffmpeg.exe", use_cache=False)
    assert sel.selected_encoder is None
    assert len(sel.attempts) == 4
    assert all(not a.available for a in sel.attempts)


@patch("subprocess.run")
def test_detect_best_probe_single_subprocess_call_for_nvenc(mock_run):
    mock_run.return_value = MagicMock(returncode=0, stderr=b"")
    enc, probe_res = detect_best_probe("ffmpeg.exe", use_cache=False)
    assert enc == EncoderType.NVENC
    assert probe_res is not None
    assert probe_res.available is True
    assert mock_run.call_count == 1


# ---------------------------------------------------------
# test_encoder_available Tests
# ---------------------------------------------------------

def test_check_encoder_available_builtin_types():
    # AUTO and LIBX264 return True immediately without subprocess invocation
    assert check_encoder_available("dummy_ffmpeg", EncoderType.AUTO) is True
    assert check_encoder_available("dummy_ffmpeg", EncoderType.LIBX264) is True


@patch("subprocess.run")
def test_check_encoder_available_mock_success(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    assert check_encoder_available("ffmpeg.exe", EncoderType.NVENC, use_cache=False) is True
    mock_run.assert_called_once()
    args = mock_run.call_args[0][0]
    assert "ffmpeg.exe" in args
    assert "h264_nvenc" in args


@patch("subprocess.run")
def test_check_encoder_available_mock_failure(mock_run):
    mock_run.return_value = MagicMock(returncode=1)
    assert check_encoder_available("ffmpeg.exe", EncoderType.NVENC, use_cache=False) is False


@patch("subprocess.run")
def test_check_encoder_available_mock_timeout(mock_run):
    mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=3)
    assert check_encoder_available("ffmpeg.exe", EncoderType.NVENC, use_cache=False) is False


@patch("subprocess.run")
def test_check_encoder_available_caching(mock_run):
    mock_run.return_value = MagicMock(returncode=0)
    # First call runs subprocess
    res1 = check_encoder_available("ffmpeg.exe", EncoderType.QSV, use_cache=True)
    assert res1 is True
    assert mock_run.call_count == 1

    # Second call should use cache
    res2 = check_encoder_available("ffmpeg.exe", EncoderType.QSV, use_cache=True)
    assert res2 is True
    assert mock_run.call_count == 1


# ---------------------------------------------------------
# detect_best_encoder & detect_available_encoders Tests
# ---------------------------------------------------------

@patch("video_converter.media.encoders.probe_encoder")
def test_detect_best_encoder_nvenc_first(mock_probe):
    # NVENC available -> returns NVENC
    mock_probe.side_effect = lambda path, enc, **kw: MagicMock(available=(enc == EncoderType.NVENC))
    best = detect_best_encoder(ffmpeg_path="ffmpeg.exe", use_cache=False)
    assert best == EncoderType.NVENC


@patch("video_converter.media.encoders.probe_encoder")
def test_detect_best_encoder_qsv_second(mock_probe):
    # Only QSV available -> returns QSV
    mock_probe.side_effect = lambda path, enc, **kw: MagicMock(available=(enc == EncoderType.QSV))
    best = detect_best_encoder(ffmpeg_path="ffmpeg.exe", use_cache=False)
    assert best == EncoderType.QSV


@patch("video_converter.media.encoders.probe_encoder")
def test_detect_best_encoder_amf_third(mock_probe):
    # Only AMF available -> returns AMF
    mock_probe.side_effect = lambda path, enc, **kw: MagicMock(available=(enc == EncoderType.AMF))
    best = detect_best_encoder(ffmpeg_path="ffmpeg.exe", use_cache=False)
    assert best == EncoderType.AMF


@patch("video_converter.media.encoders.probe_encoder")
def test_detect_best_encoder_cpu_fallback(mock_probe):
    # No HW encoder available -> returns LIBX264
    mock_probe.return_value = MagicMock(available=False)
    best = detect_best_encoder(ffmpeg_path="ffmpeg.exe", use_cache=False)
    assert best == EncoderType.LIBX264


@patch("video_converter.media.encoders.probe_encoder")
def test_detect_best_probe_all_hardware_failed_real_reason(mock_probe):
    # Mock probes for candidate hardware encoders to fail, libx264 software probe to succeed
    def mock_probe_impl(path, enc, **kw):
        if enc == EncoderType.LIBX264:
            return EncoderProbeResult(
                encoder=EncoderType.LIBX264,
                available=True,
                stderr="sample warning",
                reason="Software CPU encoder (libx264) ready.",
            )
        return EncoderProbeResult(
            encoder=enc,
            available=False,
            reason=f"{enc.display_name} probe failed.",
        )

    mock_probe.side_effect = mock_probe_impl
    best_enc, probe_res = detect_best_probe(ffmpeg_path="ffmpeg.exe", use_cache=False)
    assert best_enc == EncoderType.LIBX264
    assert probe_res is not None
    assert probe_res.available is True
    assert probe_res.stderr == "sample warning"
    assert probe_res.reason == (
        "All hardware acceleration probes failed or hardware is absent. "
        "Operating with high-compatibility libx264 CPU encoder."
    )


@patch("video_converter.media.encoders.probe_encoder")
def test_detect_best_probe_all_hardware_failed_and_cpu_failed_preserves_availability_and_stderr(mock_probe):
    # Mock probes for hardware encoders to fail, and libx264 software probe also fails
    def mock_probe_impl(path, enc, **kw):
        if enc == EncoderType.LIBX264:
            return EncoderProbeResult(
                encoder=EncoderType.LIBX264,
                available=False,
                stderr="libx264 initialization error: Unknown encoder 'libx264'",
                reason="Software CPU encoder unavailable.",
            )
        return EncoderProbeResult(
            encoder=enc,
            available=False,
            stderr="hardware unsupported",
            reason=f"{enc.display_name} probe failed.",
        )

    mock_probe.side_effect = mock_probe_impl
    best_enc, probe_res = detect_best_probe(ffmpeg_path="ffmpeg.exe", use_cache=False)
    assert best_enc == EncoderType.LIBX264
    assert probe_res is not None
    assert probe_res.available is False
    assert probe_res.stderr == "libx264 initialization error: Unknown encoder 'libx264'"
    assert probe_res.reason == "Software CPU encoder unavailable."


@patch("video_converter.media.encoders.test_encoder_available")
def test_detect_available_encoders(mock_test):
    # NVENC and AMF available
    mock_test.side_effect = lambda path, enc, **kw: enc in (EncoderType.NVENC, EncoderType.AMF)
    available = detect_available_encoders(ffmpeg_path="ffmpeg.exe", use_cache=False)
    assert EncoderType.NVENC in available
    assert EncoderType.AMF in available
    assert EncoderType.QSV not in available
    assert EncoderType.LIBX264 in available


@patch("video_converter.media.encoders.find_ffmpeg", return_value=None)
def test_detect_best_encoder_no_binary_fallback(mock_find):
    best = detect_best_encoder(ffmpeg_path="", use_cache=False)
    assert best == EncoderType.LIBX264


def test_real_bundled_ffmpeg_probe():
    """Run real detection if bundled ffmpeg.exe exists."""
    ffmpeg = find_ffmpeg()
    if not ffmpeg or not Path(ffmpeg).exists():
        pytest.skip("FFmpeg binary not found")

    best = detect_best_encoder(ffmpeg_path=ffmpeg, use_cache=False)
    assert isinstance(best, EncoderType)

    available = detect_available_encoders(ffmpeg_path=ffmpeg, use_cache=False)
    assert EncoderType.LIBX264 in available
