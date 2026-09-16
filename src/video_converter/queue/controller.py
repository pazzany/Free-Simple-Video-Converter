from __future__ import annotations
import os
from PySide6.QtCore import QObject, Signal

_UNSET = object()

from video_converter.domain.encoders import EncoderType
from video_converter.domain.jobs import ConversionJob, JobStatus
from video_converter.domain.presets import Preset
from video_converter.domain.settings import OutputMode
from video_converter.media.paths import collect_video_files, resolve_output_path, get_temp_output_path
from video_converter.media.probe import probe_file
from video_converter.media.scaling import calculate_target_resolution
from video_converter.queue.worker import ConversionWorker


class QueueController(QObject):
    """Coordinates batch conversion queue and worker execution."""

    job_added = Signal(ConversionJob)
    job_updated = Signal(ConversionJob)
    job_removed = Signal(str)  # job_id
    queue_cleared = Signal()
    queue_state_changed = Signal(bool)  # is_running
    total_progress_updated = Signal(float, int, int)  # (percent, completed_count, total_count)
    global_log = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._jobs: list[ConversionJob] = []
        self._worker = ConversionWorker(self)
        self._is_running: bool = False

        self._worker.progress_updated.connect(self._on_worker_progress)
        self._worker.log_received.connect(self._on_worker_log)
        self._worker.job_finished.connect(self._on_worker_job_finished)
        self._worker.fallback_triggered.connect(self._on_worker_fallback)
        self._worker.status_changed.connect(self._on_worker_status_changed)

    @property
    def jobs(self) -> list[ConversionJob]:
        return list(self._jobs)

    @property
    def is_running(self) -> bool:
        return self._is_running

    def get_job(self, job_id: str) -> ConversionJob | None:
        for job in self._jobs:
            if job.id == job_id:
                return job
        return None

    def add_files(
        self,
        paths: list[str],
        preset: Preset = Preset.P1080,
        crf: int = 24,
        encoder: EncoderType = EncoderType.AUTO,
        output_mode: OutputMode = OutputMode.SAME_DIR,
        custom_dir: str | None = None,
        target_fps: int | None = None,
        audio_bitrate: str = "192k",
    ) -> list[ConversionJob]:
        """Collects video files and appends new jobs to queue."""
        video_files = collect_video_files(paths)
        existing_sources = {j.source_path.lower() for j in self._jobs}

        added_jobs: list[ConversionJob] = []
        for file_path in video_files:
            if file_path.lower() in existing_sources:
                continue

            # Probe media metadata
            try:
                media_info = probe_file(file_path)
            except Exception as e:
                self.global_log.emit(f"Warning: probe failed for {file_path}: {e}")
                media_info = None

            # Calculate target resolution
            if media_info and media_info.width > 0 and media_info.height > 0:
                t_w, t_h = calculate_target_resolution(
                    media_info.width,
                    media_info.height,
                    preset.limit,
                    media_info.rotation,
                )
            else:
                t_w, t_h = 0, 0

            # Resolve non-colliding output path
            out_path = resolve_output_path(
                input_path=file_path,
                mode=output_mode,
                custom_dir=custom_dir,
            )
            temp_path = get_temp_output_path(out_path)

            job = ConversionJob(
                source_path=file_path,
                output_path=out_path,
                temp_path=temp_path,
                media_info=media_info,
                target_width=t_w,
                target_height=t_h,
                preset=preset,
                crf=crf,
                encoder=encoder,
                target_fps=target_fps,
                audio_bitrate=audio_bitrate,
                status=JobStatus.PENDING,
            )

            self._jobs.append(job)
            added_jobs.append(job)
            self.job_added.emit(job)

        self._update_total_progress()
        return added_jobs

    def remove_job(self, job_id: str) -> None:
        job = self.get_job(job_id)
        if not job or job.is_active:
            return
        self._jobs = [j for j in self._jobs if j.id != job_id]
        self.job_removed.emit(job_id)
        self._update_total_progress()

    def update_job_settings(
        self,
        job_id: str,
        preset: Preset | None = None,
        crf: int | None = None,
        encoder: EncoderType | None = None,
        target_fps: int | None | object = _UNSET,
        audio_bitrate: str | None = None,
    ) -> bool:
        """Updates preset/crf/encoder for a pending job and recalculates target resolution."""
        job = self.get_job(job_id)
        if not job or job.is_active:
            return False

        if preset is not None:
            job.preset = preset
            if job.media_info and job.media_info.width > 0 and job.media_info.height > 0:
                t_w, t_h = calculate_target_resolution(
                    job.media_info.width,
                    job.media_info.height,
                    preset.limit,
                    job.media_info.rotation,
                )
                job.target_width = t_w
                job.target_height = t_h
        if crf is not None:
            job.crf = crf
        if encoder is not None:
            job.encoder = encoder
        if target_fps is not _UNSET:
            job.target_fps = target_fps  # type: ignore[assignment]
        if audio_bitrate is not None:
            job.audio_bitrate = audio_bitrate

        self.job_updated.emit(job)
        return True

    def clear_completed(self) -> None:
        self._jobs = [j for j in self._jobs if not j.is_finished]
        self.queue_cleared.emit()
        for j in self._jobs:
            self.job_added.emit(j)
        self._update_total_progress()

    def clear_all(self) -> None:
        if self._is_running:
            self.stop()
        self._jobs.clear()
        self.queue_cleared.emit()
        self._update_total_progress()

    def start(self) -> None:
        if self._is_running:
            return

        next_job = self._get_next_pending_job()
        if not next_job:
            self.global_log.emit("No pending jobs to run.")
            return

        self._is_running = True
        self.queue_state_changed.emit(True)
        self.global_log.emit("Starting batch conversion...")
        self._run_job(next_job)

    def stop(self) -> None:
        if not self._is_running:
            return

        self.global_log.emit("Stopping queue...")
        self._is_running = False
        self._worker.cancel()
        self.queue_state_changed.emit(False)

    def _get_next_pending_job(self) -> ConversionJob | None:
        for job in self._jobs:
            if job.status in (JobStatus.PENDING, JobStatus.CANCELLED):
                return job
        return None

    def _run_job(self, job: ConversionJob) -> None:
        self.job_updated.emit(job)
        self._worker.start_job(job)

    def _on_worker_progress(self, job_id: str, percent: float, speed: str, fps: float) -> None:
        job = self.get_job(job_id)
        if job:
            job.progress = percent
            job.speed = speed
            job.fps = fps
            self.job_updated.emit(job)
            self._update_total_progress()

    def _on_worker_log(self, job_id: str, line: str) -> None:
        self.global_log.emit(f"[{job_id[:8]}] {line}")

    def _on_worker_status_changed(self, job_id: str, status: JobStatus) -> None:
        job = self.get_job(job_id)
        if job:
            job.status = status
            self.job_updated.emit(job)

    def _on_worker_fallback(self, job_id: str, reason: str) -> None:
        job = self.get_job(job_id)
        if job:
            self.job_updated.emit(job)
            self.global_log.emit(f"⚠️ {job.source_filename}: {reason}")

    def _on_worker_job_finished(self, job_id: str, success: bool, error_message: str) -> None:
        job = self.get_job(job_id)
        if job:
            self.job_updated.emit(job)
            status_text = "COMPLETED" if success else f"FAILED ({error_message})"
            self.global_log.emit(f"Job {job.source_filename} -> {status_text}")

        self._update_total_progress()

        if self._is_running:
            next_job = self._get_next_pending_job()
            if next_job:
                self._run_job(next_job)
            else:
                self._is_running = False
                self.queue_state_changed.emit(False)
                self.global_log.emit("All conversion jobs finished.")

    def _update_total_progress(self) -> None:
        total = len(self._jobs)
        if total == 0:
            self.total_progress_updated.emit(0.0, 0, 0)
            return

        completed = sum(1 for j in self._jobs if j.status == JobStatus.COMPLETED)
        sum_progress = sum(j.progress for j in self._jobs)
        avg_progress = sum_progress / total
        self.total_progress_updated.emit(avg_progress, completed, total)
