from __future__ import annotations
import pytest

from video_converter.domain.encoders import EncoderProbeResult, EncoderSelectionResult, EncoderType
from video_converter.domain.jobs import ConversionJob, JobStatus
from video_converter.domain.media_info import MediaInfo
from video_converter.domain.presets import Preset
from video_converter.domain.settings import OutputMode
from video_converter.queue.controller import QueueController
from video_converter.queue.worker import ConversionWorker


class TestJobsDomain:
    def test_job_initialization(self):
        info = MediaInfo(
            file_path="test.mp4",
            width=3840,
            height=2160,
            display_width=3840,
            display_height=2160,
            duration_sec=120.0,
            size_bytes=1024 * 1024 * 50,
        )
        job = ConversionJob(
            source_path="C:/videos/test.mp4",
            output_path="C:/videos/test-converted.mp4",
            temp_path="C:/videos/.test-converted.part.mp4",
            media_info=info,
            target_width=1920,
            target_height=1080,
            preset=Preset.P1080,
            crf=24,
            encoder=EncoderType.AUTO,
        )

        assert job.source_filename == "test.mp4"
        assert job.source_resolution_str == "3840x2160"
        assert job.target_resolution_str == "1920x1080"
        assert job.duration_str == "02:00"
        assert "50.00 MB" in job.size_str
        assert job.status == JobStatus.PENDING
        assert not job.is_active
        assert not job.is_finished

    def test_job_status_transitions(self):
        job = ConversionJob()
        assert not job.is_active
        job.status = JobStatus.RUNNING
        assert job.is_active
        assert not job.is_finished
        job.status = JobStatus.COMPLETED
        assert not job.is_active
        assert job.is_finished


class TestWorkerProgressParsing:
    def test_progress_parser(self, qapp):
        worker = ConversionWorker()
        job = ConversionJob(
            source_path="test.mp4",
            media_info=MediaInfo("test.mp4", duration_sec=10.0),
        )
        worker._current_job = job
        worker._duration_us = 10_000_000

        received_progress = []
        worker.progress_updated.connect(lambda jid, p, spd, fps: received_progress.append((p, spd, fps)))

        sample_stdout = "frame=150\nfps=60.5\nout_time_us=5000000\nspeed=2.0x\nprogress=continue\n"
        worker._parse_progress(sample_stdout)

        assert len(received_progress) == 1
        pct, speed, fps = received_progress[0]
        assert pct == 50.0
        assert speed == "2.0x"
        assert fps == 60.5
        assert job.progress == 50.0

    def test_progress_parser_end(self, qapp):
        worker = ConversionWorker()
        job = ConversionJob(source_path="test.mp4")
        worker._current_job = job
        worker._duration_us = 10_000_000

        received = []
        worker.progress_updated.connect(lambda jid, p, spd, fps: received.append(p))

        worker._parse_progress("progress=end\n")
        assert len(received) == 1
        assert received[0] == 100.0
        assert job.progress == 100.0


class TestQueueController:
    def test_add_and_remove_jobs(self, qapp, tmp_path, monkeypatch):
        # Create dummy video files
        f1 = tmp_path / "vid1.mp4"
        f2 = tmp_path / "vid2.mp4"
        f1.write_bytes(b"dummy")
        f2.write_bytes(b"dummy")

        # Mock probe_file
        monkeypatch.setattr(
            "video_converter.queue.controller.probe_file",
            lambda path: MediaInfo(
                file_path=path,
                width=1920,
                height=1080,
                display_width=1920,
                display_height=1080,
                duration_sec=60.0,
            ),
        )

        controller = QueueController()
        added = controller.add_files(
            paths=[str(f1), str(f2)],
            preset=Preset.P720,
            crf=22,
            encoder=EncoderType.LIBX264,
            output_mode=OutputMode.SAME_DIR,
        )

        assert len(added) == 2
        assert len(controller.jobs) == 2
        assert controller.jobs[0].target_width == 1280
        assert controller.jobs[0].target_height == 720
        assert controller.jobs[0].crf == 22

        # Deduplication test: re-adding same file should not add duplicates
        added2 = controller.add_files(paths=[str(f1)])
        assert len(added2) == 0
        assert len(controller.jobs) == 2

        # Remove job
        job_id = controller.jobs[0].id
        controller.remove_job(job_id)
        assert len(controller.jobs) == 1
        assert controller.jobs[0].id != job_id

        # Clear all
        controller.clear_all()
        assert len(controller.jobs) == 0

    def test_stop_prevents_starting_next_pending_job(self, qapp):
        controller = QueueController()
        job1 = ConversionJob(source_path="vid1.mp4", status=JobStatus.PENDING)
        job2 = ConversionJob(source_path="vid2.mp4", status=JobStatus.PENDING)
        controller._jobs = [job1, job2]

        started_jobs = []

        def mock_start_job(job):
            started_jobs.append(job.source_path)

        def mock_cancel():
            # Simulate worker synchronously triggering job_finished during cancellation
            controller._worker.job_finished.emit(job1.id, False, "Cancelled by user")

        controller._worker.start_job = mock_start_job
        controller._worker.cancel = mock_cancel

        controller.start()
        assert controller.is_running is True
        assert started_jobs == ["vid1.mp4"]

        # Call stop - should NOT proceed to job2 even if job_finished is emitted synchronously
        controller.stop()

        assert controller.is_running is False
        assert started_jobs == ["vid1.mp4"]
        assert job2.status == JobStatus.PENDING

    def test_resume_after_stop_runs_remaining_jobs(self, qapp, tmp_path):
        """Verify that after stopping, remaining pending or cancelled jobs can be converted."""
        controller = QueueController()
        job1 = ConversionJob(source_path="vid1.mp4", status=JobStatus.COMPLETED)
        job2 = ConversionJob(source_path="vid2.mp4", status=JobStatus.CANCELLED)
        job3 = ConversionJob(source_path="vid3.mp4", status=JobStatus.PENDING)
        controller._jobs = [job1, job2, job3]

        # Next pending job should be the cancelled job2
        assert controller._get_next_pending_job() == job2

    def test_worker_ensures_output_dir_exists_or_fails_cleanly(self, qtbot, tmp_path, monkeypatch):
        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")

        target_dir = tmp_path / "custom_nested" / "folder"
        out_path = target_dir / "out.mp4"
        temp_path = target_dir / ".out.part.mp4"

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(out_path),
            temp_path=str(temp_path),
            encoder=EncoderType.LIBX264,
        )

        assert not target_dir.exists()

        finished_events = []
        worker.job_finished.connect(lambda jid, success, err: finished_events.append((success, err)))

        # Mock QProcess to prevent actual execution
        monkeypatch.setattr("PySide6.QtCore.QProcess.start", lambda *args, **kwargs: None)

        worker.start_job(job)
        assert target_dir.exists()

        # Test failure handling if directory creation fails (e.g. permission or os error)
        def fail_makedirs(*args, **kwargs):
            raise OSError("Access denied")

        monkeypatch.setattr("os.makedirs", fail_makedirs)
        job2 = ConversionJob(
            source_path="source2.mp4",
            output_path=str(tmp_path / "denied" / "out.mp4"),
            temp_path=str(tmp_path / "denied" / ".out.part.mp4"),
            encoder=EncoderType.LIBX264,
        )
        worker.start_job(job2)
        assert job2.status == JobStatus.FAILED
        assert "Failed to create output directory" in job2.error_message


class TestWorkerDiagnosticsAndFallback:
    def test_worker_auto_encoder_nonblocking_probe_and_log_ordering(self, qtbot, tmp_path, monkeypatch):
        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")
        probe_result = EncoderProbeResult(
            encoder=EncoderType.NVENC,
            available=True,
            reason="NVIDIA NVENC hardware encoder initialized successfully with conservative parameters.",
        )
        monkeypatch.setattr(
            "video_converter.queue.worker.detect_encoder_selection",
            lambda ffmpeg_path=None, use_cache=True: EncoderSelectionResult(
                selected_encoder=EncoderType.NVENC,
                attempts=(probe_result,),
            ),
        )

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(tmp_path / "out.mp4"),
            temp_path=str(tmp_path / ".temp.mp4"),
            encoder=EncoderType.AUTO,
        )
        events = []
        worker.log_received.connect(lambda jid, line: events.append(("log", line)))
        worker.status_changed.connect(lambda jid, st: events.append(("status", st)))
        monkeypatch.setattr(
            "PySide6.QtCore.QProcess.start",
            lambda self, exe, args: events.append(("process_start", exe, args)),
        )

        worker.start_job(job)
        # Immediately after dispatch, job must be PROBING
        assert job.status == JobStatus.PROBING

        # Wait for background thread probe to deliver result via Qt signal
        qtbot.waitUntil(lambda: any(e[0] == "process_start" for e in events), timeout=2000)

        assert job.actual_encoder == EncoderType.NVENC
        assert job.status == JobStatus.RUNNING

        # Verify strict single event sequence:
        # 1. status -> PROBING
        # 2. log -> Auto-selected encoder (with diagnostic)
        # 3. status -> RUNNING
        # 4. log -> Starting FFmpeg
        # 5. process_start -> QProcess.start
        status_events = [e for e in events if e[0] == "status"]
        assert len(status_events) == 2
        assert status_events[0] == ("status", JobStatus.PROBING)
        assert status_events[1] == ("status", JobStatus.RUNNING)

        log_events = [e for e in events if e[0] == "log"]
        assert len(log_events) >= 2
        assert "Auto-selected encoder: NVIDIA NVENC" in log_events[0][1]
        assert "NVIDIA NVENC hardware encoder initialized successfully with conservative parameters" in log_events[0][1]
        assert "Starting FFmpeg (NVIDIA NVENC)" in log_events[1][1]

        # Verify order in the single merged event sequence
        first_diag_idx = next(i for i, e in enumerate(events) if e[0] == "log" and "Auto-selected" in e[1])
        ffmpeg_log_idx = next(i for i, e in enumerate(events) if e[0] == "log" and "Starting FFmpeg" in e[1])
        process_start_idx = next(i for i, e in enumerate(events) if e[0] == "process_start")
        assert first_diag_idx < ffmpeg_log_idx < process_start_idx

    def test_worker_canceled_job_stale_probe_result_suppression(self, qtbot, tmp_path, monkeypatch):
        import time

        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")

        def slow_probe(ffmpeg_path=None, use_cache=True):
            time.sleep(0.1)
            return EncoderSelectionResult(
                selected_encoder=EncoderType.NVENC,
                attempts=(EncoderProbeResult(EncoderType.NVENC, True, reason="ok"),),
            )

        monkeypatch.setattr("video_converter.queue.worker.detect_encoder_selection", slow_probe)
        started = []
        monkeypatch.setattr("PySide6.QtCore.QProcess.start", lambda self, exe, args: started.append(exe))

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(tmp_path / "out.mp4"),
            temp_path=str(tmp_path / ".temp.mp4"),
            encoder=EncoderType.AUTO,
        )
        worker.start_job(job)
        assert job.status == JobStatus.PROBING

        # User cancels while probe is in flight
        worker.cancel()
        assert job.status == JobStatus.CANCELLED

        # Wait to ensure background thread completes and delivers stale signal
        qtbot.wait(200)

        # QProcess should NOT have been started for the cancelled job
        assert len(started) == 0
        assert job.status == JobStatus.CANCELLED

    def test_worker_restart_same_job_after_cancel_ignores_old_generation_result(self, qtbot, tmp_path, monkeypatch):
        import time

        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")

        probe_calls = 0

        def slow_probe(ffmpeg_path=None, use_cache=True):
            nonlocal probe_calls
            probe_calls += 1
            call_id = probe_calls
            if call_id == 1:
                # First probe is slow
                time.sleep(0.15)
                return EncoderSelectionResult(
                    selected_encoder=EncoderType.NVENC,
                    attempts=(EncoderProbeResult(EncoderType.NVENC, True, reason="nvenc_gen1"),),
                )
            # Second probe is fast
            return EncoderSelectionResult(
                selected_encoder=EncoderType.AMF,
                attempts=(EncoderProbeResult(EncoderType.AMF, True, reason="amf_gen2"),),
            )

        monkeypatch.setattr("video_converter.queue.worker.detect_encoder_selection", slow_probe)
        started = []
        monkeypatch.setattr("PySide6.QtCore.QProcess.start", lambda self, exe, args: started.append((exe, args)))

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(tmp_path / "out.mp4"),
            temp_path=str(tmp_path / ".temp.mp4"),
            encoder=EncoderType.AUTO,
        )

        # Start 1st run
        worker.start_job(job)
        assert job.status == JobStatus.PROBING

        # Stop/cancel 1st run
        worker.cancel()
        assert job.status == JobStatus.CANCELLED

        # Immediately restart same job (generation 2)
        job.status = JobStatus.PENDING
        worker.start_job(job)
        assert job.status == JobStatus.PROBING

        # Wait for both probes to complete
        qtbot.wait(250)

        # Ensure only generation 2 was accepted and QProcess was started exactly once
        assert len(started) == 1
        assert job.actual_encoder == EncoderType.AMF
        assert job.status == JobStatus.RUNNING

    def test_worker_probe_unexpected_exception_fails_cleanly(self, qtbot, tmp_path, monkeypatch):
        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")

        def exploding_probe(ffmpeg_path=None, use_cache=True):
            raise RuntimeError("Unexpected low-level probe crash!")

        monkeypatch.setattr("video_converter.queue.worker.detect_encoder_selection", exploding_probe)
        started = []
        finished = []
        status_changes = []
        monkeypatch.setattr("PySide6.QtCore.QProcess.start", lambda self, exe, args: started.append(exe))
        worker.job_finished.connect(lambda jid, ok, err: finished.append((ok, err)))
        worker.status_changed.connect(lambda jid, st: status_changes.append(st))

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(tmp_path / "out.mp4"),
            temp_path=str(tmp_path / ".temp.mp4"),
            encoder=EncoderType.AUTO,
        )

        worker.start_job(job)
        assert job.status == JobStatus.PROBING

        qtbot.waitUntil(lambda: len(finished) == 1, timeout=2000)

        assert len(started) == 0
        assert job.status == JobStatus.FAILED
        assert finished[0] == (False, "No suitable video encoder available")
        assert JobStatus.FAILED in status_changes

    def test_worker_cpu_probe_fails_fails_cleanly_without_process(self, qtbot, tmp_path, monkeypatch):
        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")

        selection = EncoderSelectionResult(
            selected_encoder=None,
            attempts=(
                EncoderProbeResult(EncoderType.NVENC, False, stderr="fail"),
                EncoderProbeResult(EncoderType.QSV, False, stderr="fail"),
                EncoderProbeResult(EncoderType.AMF, False, stderr="fail"),
                EncoderProbeResult(EncoderType.LIBX264, False, stderr="fail", reason="Software CPU encoder unavailable."),
            ),
        )
        monkeypatch.setattr(
            "video_converter.queue.worker.detect_encoder_selection",
            lambda ffmpeg_path=None, use_cache=True: selection,
        )

        started = []
        finished = []
        status_changes = []
        logs = []
        monkeypatch.setattr("PySide6.QtCore.QProcess.start", lambda self, exe, args: started.append(exe))
        worker.job_finished.connect(lambda jid, ok, err: finished.append((ok, err)))
        worker.status_changed.connect(lambda jid, st: status_changes.append(st))
        worker.log_received.connect(lambda jid, line: logs.append(line))

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(tmp_path / "out.mp4"),
            temp_path=str(tmp_path / ".temp.mp4"),
            encoder=EncoderType.AUTO,
        )

        worker.start_job(job)
        assert job.status == JobStatus.PROBING

        qtbot.waitUntil(lambda: len(finished) == 1, timeout=2000)

        assert len(started) == 0
        assert job.status == JobStatus.FAILED
        expected_err = "No suitable video encoder available: Software CPU encoder unavailable. (details: fail)"
        assert finished == [(False, expected_err)]
        assert job.error_message == expected_err
        assert expected_err in logs
        assert JobStatus.FAILED in status_changes

    def test_worker_all_hardware_failed_cpu_diagnostic(self, qtbot, tmp_path, monkeypatch):
        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")

        selection = EncoderSelectionResult(
            selected_encoder=EncoderType.LIBX264,
            attempts=(
                EncoderProbeResult(EncoderType.NVENC, False, stderr="nvenc err", reason="NVENC failed"),
                EncoderProbeResult(EncoderType.QSV, False, stderr="qsv err", reason="QSV failed"),
                EncoderProbeResult(EncoderType.AMF, False, stderr="amf err", reason="AMF failed"),
                EncoderProbeResult(EncoderType.LIBX264, True, reason="Software CPU encoder (libx264) ready."),
            ),
        )
        monkeypatch.setattr(
            "video_converter.queue.worker.detect_encoder_selection",
            lambda ffmpeg_path=None, use_cache=True: selection,
        )

        started = []
        monkeypatch.setattr("PySide6.QtCore.QProcess.start", lambda self, exe, args: started.append(exe))

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(tmp_path / "out.mp4"),
            temp_path=str(tmp_path / ".temp.mp4"),
            encoder=EncoderType.AUTO,
        )
        logs = []
        worker.log_received.connect(lambda jid, line: logs.append(line))

        worker.start_job(job)
        qtbot.waitUntil(lambda: len(started) == 1, timeout=2000)

        assert job.actual_encoder == EncoderType.LIBX264
        assert len(started) == 1

        # Per-failed-attempt lines should be logged concisely
        assert any("Encoder probe skipped NVIDIA NVENC: NVENC failed" in line for line in logs)
        assert any("Encoder probe skipped Intel QuickSync: QSV failed" in line for line in logs)

        # Check that concise summary was logged BEFORE the selected line
        expected_summary = "Hardware acceleration unavailable (NVIDIA NVENC, Intel QuickSync, AMD AMF). Operating with high-compatibility libx264 CPU encoder."
        assert expected_summary in logs
        summary_idx = logs.index(expected_summary)
        selected_idx = next(i for i, line in enumerate(logs) if "Auto-selected encoder: CPU (libx264)" in line)
        assert summary_idx < selected_idx

    def test_worker_explicit_encoder_starts_immediately_without_probing(self, qtbot, tmp_path, monkeypatch):
        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")
        started = []
        monkeypatch.setattr("PySide6.QtCore.QProcess.start", lambda self, exe, args: started.append(exe))

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(tmp_path / "out.mp4"),
            temp_path=str(tmp_path / ".temp.mp4"),
            encoder=EncoderType.NVENC,
        )
        worker.start_job(job)

        # Explicit encoder should start immediately in RUNNING state without PROBING
        assert job.status == JobStatus.RUNNING
        assert len(started) == 1

    def test_worker_hardware_failure_triggers_cpu_fallback_with_diagnostic(self, qapp, tmp_path, monkeypatch):
        from PySide6.QtCore import QProcess

        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")
        monkeypatch.setattr("PySide6.QtCore.QProcess.start", lambda *args, **kwargs: None)

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(tmp_path / "out.mp4"),
            temp_path=str(tmp_path / ".temp.mp4"),
            encoder=EncoderType.NVENC,
        )
        fallback_events = []
        worker.fallback_triggered.connect(lambda jid, reason: fallback_events.append(reason))

        worker.start_job(job)
        assert job.actual_encoder == EncoderType.NVENC
        assert not job.fallback_attempted

        # Simulate hardware encode process failing with exit code 1
        worker._on_process_finished(1, QProcess.ExitStatus.NormalExit)

        assert job.fallback_attempted is True
        assert job.actual_encoder == EncoderType.LIBX264
        assert len(fallback_events) == 1
        assert "Encoder NVIDIA NVENC failed (exit code 1). Retrying with CPU (libx264)." in fallback_events[0]
        assert any("Retrying with CPU (libx264)" in line for line in job.log_lines)

    def test_controller_fallback_logs_diagnostic_reason(self, qapp):
        controller = QueueController()
        job = ConversionJob(source_path="clip.mp4", encoder=EncoderType.NVENC)
        controller._jobs = [job]

        logs = []
        controller.global_log.connect(logs.append)

        controller._on_worker_fallback(job.id, "Encoder NVIDIA NVENC failed (exit code 1). Retrying with CPU (libx264).")

        assert len(logs) == 1
        assert logs[0] == "⚠️ clip.mp4: Encoder NVIDIA NVENC failed (exit code 1). Retrying with CPU (libx264)."

    def test_worker_sanitized_bounded_stderr_and_concise_failed_reasons(self, qtbot, tmp_path, monkeypatch):
        worker = ConversionWorker()
        monkeypatch.setattr("video_converter.queue.worker.find_ffmpeg", lambda: "mock_ffmpeg")

        long_stderr_line = "Error: " + ("x" * 200)
        multiline_stderr = f"{long_stderr_line}\nSecond line of crash\nThird line spam"
        selection = EncoderSelectionResult(
            selected_encoder=EncoderType.LIBX264,
            attempts=(
                EncoderProbeResult(
                    EncoderType.NVENC,
                    False,
                    stderr=multiline_stderr,
                    reason="NVENC initialization rejected by driver.",
                ),
                EncoderProbeResult(
                    EncoderType.QSV,
                    False,
                    stderr="qsv device not found",
                    reason="Intel QSV unavailable.",
                ),
                EncoderProbeResult(
                    EncoderType.LIBX264,
                    True,
                    reason="Software CPU encoder (libx264) ready.",
                ),
            ),
        )
        monkeypatch.setattr(
            "video_converter.queue.worker.detect_encoder_selection",
            lambda ffmpeg_path=None, use_cache=True: selection,
        )

        started = []
        logs = []
        monkeypatch.setattr("PySide6.QtCore.QProcess.start", lambda self, exe, args: started.append(exe))
        worker.log_received.connect(lambda jid, line: logs.append(line))

        job = ConversionJob(
            source_path="source.mp4",
            output_path=str(tmp_path / "out.mp4"),
            temp_path=str(tmp_path / ".temp.mp4"),
            encoder=EncoderType.AUTO,
        )
        worker.start_job(job)
        qtbot.waitUntil(lambda: len(started) == 1, timeout=2000)

        nvenc_log = next(line for line in logs if "Encoder probe skipped NVIDIA NVENC" in line)
        # Bounded excerpt checks: no newlines, bounded to max 120 chars excerpt + ellipses
        assert "\n" not in nvenc_log
        assert "Second line of crash" not in nvenc_log
        assert "Third line spam" not in nvenc_log
        assert "details: Error: " in nvenc_log
        assert "..." in nvenc_log
        assert len(nvenc_log) < 250

        qsv_log = next(line for line in logs if "Encoder probe skipped Intel QuickSync" in line)
        assert "\n" not in qsv_log
        assert "details: qsv device not found" in qsv_log



