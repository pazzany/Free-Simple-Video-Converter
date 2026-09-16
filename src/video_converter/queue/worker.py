from __future__ import annotations
import os
import threading
from PySide6.QtCore import QObject, QProcess, Signal

from video_converter.domain.encoders import EncoderProbeResult, EncoderSelectionResult, EncoderType
from video_converter.domain.jobs import ConversionJob, JobStatus
from video_converter.media.binaries import find_ffmpeg
from video_converter.media.command import build_ffmpeg_command
from video_converter.media.encoders import detect_encoder_selection


def _sanitize_stderr_excerpt(stderr: str, max_chars: int = 120) -> str:
    """Extract a single bounded, sanitized first line from stderr if present and useful."""
    if not stderr:
        return ""
    for raw_line in stderr.splitlines():
        line = " ".join(raw_line.strip().split())
        if line:
            return line[:max_chars].strip() + ("..." if len(line) > max_chars else "")
    return ""


def _format_failed_attempt_reason(attempt: EncoderProbeResult) -> str:
    """Format a concise, bounded one-line diagnostic for a failed probe attempt."""
    base_reason = (attempt.reason or f"{attempt.encoder.display_name} probe failed.").strip()
    base_reason = " ".join(base_reason.split())

    excerpt = _sanitize_stderr_excerpt(attempt.stderr)
    if excerpt and excerpt.lower() not in base_reason.lower():
        return f"{base_reason} (details: {excerpt})"

    return base_reason


class ConversionWorker(QObject):
    """Executes a single video conversion job via FFmpeg QProcess."""

    progress_updated = Signal(str, float, str, float)  # (job_id, percent, speed, fps)
    log_received = Signal(str, str)  # (job_id, line)
    job_finished = Signal(str, bool, str)  # (job_id, success, error_message)
    fallback_triggered = Signal(str, str)  # (job_id, reason)
    status_changed = Signal(str, object)  # (job_id, JobStatus)
    _probe_finished = Signal(str, int, object)  # (job_id, generation, selection_res: EncoderSelectionResult)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process: QProcess | None = None
        self._current_job: ConversionJob | None = None
        self._user_cancelled: bool = False
        self._duration_us: int = 0
        self._buffer: str = ""
        self._probe_generation: int = 0
        self._probe_finished.connect(self._on_probe_finished)

    @property
    def current_job(self) -> ConversionJob | None:
        return self._current_job

    @property
    def is_running(self) -> bool:
        if self._current_job and self._current_job.status == JobStatus.PROBING:
            return True
        return self._process is not None and self._process.state() != QProcess.ProcessState.NotRunning

    def start_job(self, job: ConversionJob) -> None:
        if self.is_running:
            raise RuntimeError("Worker is already executing a job")

        self._current_job = job
        self._user_cancelled = False
        self._buffer = ""

        # Calculate duration in microseconds for accurate progress
        if job.media_info and job.media_info.duration_sec > 0:
            self._duration_us = int(job.media_info.duration_sec * 1_000_000)
        else:
            self._duration_us = 0

        # Resolve encoder
        ffmpeg_path = find_ffmpeg()
        if job.encoder == EncoderType.AUTO and not job.fallback_attempted:
            job.status = JobStatus.PROBING
            job.progress = 0.0
            self.status_changed.emit(job.id, JobStatus.PROBING)

            self._probe_generation += 1
            gen = self._probe_generation

            def _run_probe() -> None:
                try:
                    selection = detect_encoder_selection(ffmpeg_path)
                except Exception:
                    selection = EncoderSelectionResult(selected_encoder=None, attempts=())
                self._probe_finished.emit(job.id, gen, selection)

            thread = threading.Thread(target=_run_probe, daemon=True)
            thread.start()
            return

        if job.encoder == EncoderType.AUTO and job.fallback_attempted:
            job.actual_encoder = EncoderType.LIBX264
        else:
            job.actual_encoder = EncoderType.LIBX264 if job.fallback_attempted else job.encoder

        self._launch_process(ffmpeg_path)

    def _on_probe_finished(
        self, job_id: str, generation: int, selection: EncoderSelectionResult
    ) -> None:
        if (
            generation != self._probe_generation
            or self._current_job is None
            or self._current_job.id != job_id
            or self._user_cancelled
            or self._current_job.status == JobStatus.CANCELLED
        ):
            return

        best_enc = selection.selected_encoder
        if not best_enc:
            self._current_job.status = JobStatus.FAILED
            cpu_attempt = next((a for a in selection.attempts if a.encoder == EncoderType.LIBX264), None)
            if cpu_attempt:
                cpu_reason = _format_failed_attempt_reason(cpu_attempt)
                err_msg = f"No suitable video encoder available: {cpu_reason}"
            else:
                err_msg = "No suitable video encoder available"
            self._current_job.error_message = err_msg
            self._current_job.log_lines.append(err_msg)
            self.log_received.emit(self._current_job.id, err_msg)
            self.status_changed.emit(self._current_job.id, JobStatus.FAILED)
            self.job_finished.emit(self._current_job.id, False, err_msg)
            return

        self._current_job.actual_encoder = best_enc

        # Log concise per-failed-attempt reason for hardware encoders evaluated before selection
        for attempt in selection.attempts:
            if attempt.encoder != best_enc and not attempt.available:
                reason_str = _format_failed_attempt_reason(attempt)
                warn_msg = f"Encoder probe skipped {attempt.encoder.display_name}: {reason_str}"
                self._current_job.log_lines.append(warn_msg)
                self.log_received.emit(self._current_job.id, warn_msg)

        # Build concise failure summary for hardware encoders tested before selected
        failed_hw_displays = [
            attempt.encoder.display_name
            for attempt in selection.attempts
            if attempt.encoder.is_hardware and not attempt.available
        ]
        if failed_hw_displays and best_enc == EncoderType.LIBX264:
            hw_summary = (
                "Hardware acceleration unavailable ("
                + ", ".join(failed_hw_displays)
                + "). Operating with high-compatibility libx264 CPU encoder."
            )
            self._current_job.log_lines.append(hw_summary)
            self.log_received.emit(self._current_job.id, hw_summary)
        elif failed_hw_displays:
            hw_summary = f"Hardware encoders unavailable: {', '.join(failed_hw_displays)}."
            self._current_job.log_lines.append(hw_summary)
            self.log_received.emit(self._current_job.id, hw_summary)

        chosen_attempt = next((a for a in selection.attempts if a.encoder == best_enc), None)
        diag = f": {chosen_attempt.reason}" if chosen_attempt and chosen_attempt.reason else ""
        log_msg = f"Auto-selected encoder: {best_enc.display_name}{diag}"
        self._current_job.log_lines.append(log_msg)
        self.log_received.emit(self._current_job.id, log_msg)

        ffmpeg_path = find_ffmpeg()
        self._launch_process(ffmpeg_path)

    def _launch_process(self, ffmpeg_path: str | None) -> None:
        job = self._current_job
        if not job:
            return

        job.status = JobStatus.RUNNING
        job.progress = 0.0
        self.status_changed.emit(job.id, JobStatus.RUNNING)

        if not ffmpeg_path:
            job.status = JobStatus.FAILED
            job.error_message = "ffmpeg binary not found"
            self.job_finished.emit(job.id, False, job.error_message)
            return

        # Ensure destination directory for output and temp output exists
        try:
            os.makedirs(os.path.dirname(os.path.abspath(job.temp_path)), exist_ok=True)
            os.makedirs(os.path.dirname(os.path.abspath(job.output_path)), exist_ok=True)
        except Exception as e:
            job.status = JobStatus.FAILED
            job.error_message = f"Failed to create output directory: {e}"
            self.job_finished.emit(job.id, False, job.error_message)
            return

        cmd = build_ffmpeg_command(
            input_path=job.source_path,
            temp_output_path=job.temp_path,
            preset=job.preset,
            encoder=job.actual_encoder,
            crf=job.crf,
            ffmpeg_path=ffmpeg_path,
            fps=job.target_fps,
            audio_bitrate=job.audio_bitrate,
        )

        log_msg = f"Starting FFmpeg ({job.actual_encoder.display_name}): {' '.join(cmd)}"
        job.log_lines.append(log_msg)
        self.log_received.emit(job.id, log_msg)

        self._process = QProcess(self)
        self._process.readyReadStandardOutput.connect(self._on_stdout_ready)
        self._process.readyReadStandardError.connect(self._on_stderr_ready)
        self._process.finished.connect(self._on_process_finished)

        executable = cmd[0]
        arguments = cmd[1:]
        self._process.start(executable, arguments)

    def cancel(self) -> None:
        self._user_cancelled = True
        self._probe_generation += 1

        if self._current_job and self._current_job.status == JobStatus.PROBING:
            self._cleanup_temp_file()
            self._current_job.status = JobStatus.CANCELLED
            self._current_job.error_message = "Cancelled by user"
            self.job_finished.emit(self._current_job.id, False, "Cancelled by user")
            return

        if not self.is_running or not self._process:
            return

        self._process.terminate()
        if not self._process.waitForFinished(1500):
            self._process.kill()
            self._process.waitForFinished(1000)

        self._cleanup_temp_file()

        if self._current_job:
            self._current_job.status = JobStatus.CANCELLED
            self._current_job.error_message = "Cancelled by user"
            self.job_finished.emit(self._current_job.id, False, "Cancelled by user")

    def _on_stdout_ready(self) -> None:
        if not self._process:
            return
        data = self._process.readAllStandardOutput().data().decode("utf-8", errors="replace")
        self._parse_progress(data)

    def _on_stderr_ready(self) -> None:
        if not self._process:
            return
        data = self._process.readAllStandardError().data().decode("utf-8", errors="replace")
        for line in data.splitlines():
            line = line.strip()
            if line:
                if self._current_job:
                    self._current_job.log_lines.append(line)
                    self.log_received.emit(self._current_job.id, line)

    def _parse_progress(self, text: str) -> None:
        if not self._current_job:
            return

        self._buffer += text
        lines = self._buffer.split("\n")
        self._buffer = lines[-1]

        kv: dict[str, str] = {}
        for line in lines[:-1]:
            line = line.strip()
            if "=" in line:
                key, val = line.split("=", 1)
                kv[key.strip()] = val.strip()

        if not kv:
            return

        # Parse speed and fps
        if "speed" in kv:
            self._current_job.speed = kv["speed"]
        if "fps" in kv:
            try:
                self._current_job.fps = float(kv["fps"])
            except ValueError:
                pass

        # Parse out_time_us or out_time_ms
        out_time_us = None
        if "out_time_us" in kv:
            try:
                out_time_us = int(kv["out_time_us"])
            except ValueError:
                pass
        elif "out_time_ms" in kv:
            try:
                out_time_us = int(kv["out_time_ms"])
            except ValueError:
                pass

        if out_time_us is not None and self._duration_us > 0:
            percent = min(99.9, max(0.0, (out_time_us / self._duration_us) * 100.0))
            self._current_job.progress = percent
            self.progress_updated.emit(
                self._current_job.id,
                percent,
                self._current_job.speed,
                self._current_job.fps,
            )

        if kv.get("progress") == "end":
            self._current_job.progress = 100.0
            self.progress_updated.emit(
                self._current_job.id,
                100.0,
                self._current_job.speed,
                self._current_job.fps,
            )

    def _on_process_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        job = self._current_job
        self._process = None

        if not job:
            return

        if self._user_cancelled:
            self._cleanup_temp_file()
            return

        if exit_code == 0 and os.path.exists(job.temp_path):
            try:
                # Capture finished file size before moving
                output_size = os.path.getsize(job.temp_path)
                job.output_size_bytes = output_size

                # Atomically move temp file to target output path
                if os.path.exists(job.output_path):
                    os.remove(job.output_path)
                os.replace(job.temp_path, job.output_path)
                job.status = JobStatus.COMPLETED
                job.progress = 100.0
                self.job_finished.emit(job.id, True, "")
            except Exception as e:
                self._cleanup_temp_file()
                job.status = JobStatus.FAILED
                job.error_message = f"Failed to finalize output file: {e}"
                self.job_finished.emit(job.id, False, job.error_message)
        else:
            self._cleanup_temp_file()
            # Check if hardware fallback should be attempted
            if job.actual_encoder.is_hardware and not job.fallback_attempted:
                reason = f"Encoder {job.actual_encoder.display_name} failed (exit code {exit_code}). Retrying with CPU (libx264)."
                job.fallback_attempted = True
                job.actual_encoder = EncoderType.LIBX264
                job.log_lines.append(reason)
                self.fallback_triggered.emit(job.id, reason)
                # Restart job with CPU
                self.start_job(job)
            else:
                job.status = JobStatus.FAILED
                job.error_message = f"FFmpeg failed with exit code {exit_code}"
                self.job_finished.emit(job.id, False, job.error_message)

    def _cleanup_temp_file(self) -> None:
        if self._current_job and self._current_job.temp_path and os.path.exists(self._current_job.temp_path):
            try:
                os.remove(self._current_job.temp_path)
            except Exception:
                pass
