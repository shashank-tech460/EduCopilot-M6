"""Production Hardening Task 3: tests for orphaned-upload cleanup.

CONTEXT (see the Task 3 report for the full inspection): the current
implementation has no application-level "retry, keep the file, try
again later" resting state -- every exception raised inside a pipeline
function is caught and converted into `_mark_failed` *before that
function returns normally*, so no exception ever escapes `process_pdf`/
`process_video` for Celery to see, and no `autoretry_for`/`self.retry()`
is configured anywhere. The only genuine "retry" in the system is
Celery's own crash-redelivery (`task_acks_late=True` +
`visibility_timeout=60`): if a worker process is killed mid-task, the
broker redelivers the same task message later. That scenario is
simulated below by having a pipeline stage raise a `BaseException`
subclass (e.g. `SystemExit`) that escapes the `except Exception` blocks
entirely, exactly as a real process kill would -- proving cleanup code
never runs in that case, since the function never reaches any of its
`return` points.

No live Celery, Redis, Qdrant, Whisper, or YouTube access is used
anywhere in this file.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings as hyp_settings
from hypothesis import strategies as st

from app.api.job_store import InMemoryJobStore
from app.models.exceptions import PDFUnreadableError, VideoUnreadableError
from app.models.schemas import (
    ErrorDetail,
    IngestionJob,
    JobStatus,
    Keyframe,
    PDFSegment,
    PublicationResult,
    SourceType,
    VideoProcessingResult,
    VideoSegment,
    YouTubeMetadata,
    YouTubeProcessingResult,
    YouTubeSegment,
)
from app.tasks import _PipelineDependencies, _cleanup_upload, _run_pdf_pipeline, _run_video_pipeline, _run_youtube_pipeline
from tests.test_tasks import FakeEmbedder, FakePDFProcessor, RecordingPublisher, make_settings


def _write_temp_file(tmp_path, name: str = "upload.pdf", content: bytes = b"fake content") -> str:
    path = tmp_path / name
    path.write_bytes(content)
    return str(path)


# ---------------------------------------------------------------------------
# 1-2. Successful jobs remove the source file (PDF, video)
# ---------------------------------------------------------------------------


def test_successful_pdf_job_removes_source_file(tmp_path):
    file_path = _write_temp_file(tmp_path)
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    processor = FakePDFProcessor([PDFSegment(text="Content here today.", page_number=1)])
    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(tmp_path)),
        job_store=job_store,
        embedder=FakeEmbedder(),
        publisher=RecordingPublisher(),
    )

    result = _run_pdf_pipeline(job.job_id, file_path, deps, processor=processor)

    assert result.status == JobStatus.COMPLETED
    assert not os.path.exists(file_path)


def test_successful_video_job_removes_source_file(tmp_path):
    file_path = _write_temp_file(tmp_path, name="upload.mp4")
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.MP4)
    job_store.create(job)

    class FakeVideoProcessor:
        def process(self, source):
            return VideoProcessingResult(
                segments=[VideoSegment(text="Spoken words here today.", start_time=0.0, end_time=5.0)],
                keyframes=[Keyframe(timestamp=2.0, frame_reference="kf1")],
                audio_absent=False,
            )

    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(tmp_path)),
        job_store=job_store,
        embedder=FakeEmbedder(),
        publisher=RecordingPublisher(),
    )

    result = _run_video_pipeline(job.job_id, file_path, deps, processor=FakeVideoProcessor())

    assert result.status == JobStatus.COMPLETED
    assert not os.path.exists(file_path)


# ---------------------------------------------------------------------------
# 3. Successful YouTube job never attempts to delete a nonexistent local source
# ---------------------------------------------------------------------------


def test_successful_youtube_job_does_not_touch_the_filesystem(tmp_path, monkeypatch):
    """YouTube ingestion never saves a local file -- `_run_youtube_pipeline`
    must not call any cleanup helper, and must not error, crash, or
    otherwise behave as if a local file existed.
    """

    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.YOUTUBE)
    job_store.create(job)

    class FakeYouTubeProcessor:
        def process(self, url, language):
            return YouTubeProcessingResult(
                segments=[YouTubeSegment(text="Welcome to the video today.", start_time=0.0, duration=3.0)],
                metadata=YouTubeMetadata(title="T", channel="C", duration_seconds=100.0),
            )

    calls = []
    import app.tasks as tasks_mod

    monkeypatch.setattr(tasks_mod, "_cleanup_upload", lambda *a, **k: calls.append((a, k)))

    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(tmp_path)),
        job_store=job_store,
        embedder=FakeEmbedder(),
        publisher=RecordingPublisher(),
    )

    result = _run_youtube_pipeline(job.job_id, "https://youtu.be/abc", None, deps, processor=FakeYouTubeProcessor())

    assert result.status == JobStatus.COMPLETED
    assert calls == []  # _cleanup_upload was never called -- nothing to clean up, by construction
    assert os.listdir(tmp_path) == []  # confirms no incidental file was ever created either


# ---------------------------------------------------------------------------
# 4-5. Terminal failure / permanent publish failure remove the source file
# ---------------------------------------------------------------------------


def test_terminal_processing_failure_removes_source_file(tmp_path):
    file_path = _write_temp_file(tmp_path)
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)

    class FailingProcessor:
        def process(self, source):
            raise PDFUnreadableError("corrupt file")

    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(tmp_path)),
        job_store=job_store,
        embedder=FakeEmbedder(),
        publisher=RecordingPublisher(),
    )

    result = _run_pdf_pipeline(job.job_id, file_path, deps, processor=FailingProcessor())

    assert result.status == JobStatus.FAILED
    assert not os.path.exists(file_path)


def test_permanent_publish_failure_removes_source_file(tmp_path):
    file_path = _write_temp_file(tmp_path)
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)

    failure_result = PublicationResult(
        status=JobStatus.PUBLISH_FAILED,
        published_count=0,
        total_count=1,
        error_details=ErrorDetail(error_type="X", status_code="PublicationFailed", message="boom", detail={}),
    )
    processor = FakePDFProcessor([PDFSegment(text="Content here today.", page_number=1)])
    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(tmp_path)),
        job_store=job_store,
        embedder=FakeEmbedder(),
        publisher=RecordingPublisher(result=failure_result),
    )

    result = _run_pdf_pipeline(job.job_id, file_path, deps, processor=processor)

    assert result.status == JobStatus.PUBLISH_FAILED
    assert not os.path.exists(file_path)


# ---------------------------------------------------------------------------
# 6-7. Retryable/crash scenarios preserve the source file
# ---------------------------------------------------------------------------


def test_worker_crash_mid_task_preserves_source_file(tmp_path):
    """Simulates a real worker crash: a `BaseException` (not caught by any
    `except Exception` block, exactly like a real process kill/SystemExit
    would behave) escapes the pipeline function before it ever reaches a
    `return` -- and therefore before `_cleanup_upload` is ever called.
    The file must remain, ready for Celery's crash-redelivery to retry
    the same task later.
    """

    file_path = _write_temp_file(tmp_path)
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)

    class CrashingProcessor:
        def process(self, source):
            raise SystemExit("simulated worker crash")  # BaseException, not Exception

    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(tmp_path)),
        job_store=job_store,
        embedder=FakeEmbedder(),
        publisher=RecordingPublisher(),
    )

    with pytest.raises(SystemExit):
        _run_pdf_pipeline(job.job_id, file_path, deps, processor=CrashingProcessor())

    assert os.path.exists(file_path)  # preserved -- cleanup never ran


def test_redelivered_task_after_crash_still_finds_the_file_and_completes(tmp_path):
    """End-to-end simulation of the exact crash-and-redeliver sequence
    described in this task's own "CRASH SCENARIO" section: (1) file
    saved, (2) job created, (3) worker crashes mid-task, (4) task is
    redelivered, (5) task runs again -- and this time succeeds, cleanly
    finding the same file still in place.
    """

    file_path = _write_temp_file(tmp_path)
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(tmp_path)),
        job_store=job_store,
        embedder=FakeEmbedder(),
        publisher=RecordingPublisher(),
    )

    class CrashOnceProcessor:
        def __init__(self):
            self.attempts = 0

        def process(self, source):
            self.attempts += 1
            if self.attempts == 1:
                raise SystemExit("simulated crash on first (redelivered-later) attempt")
            return [PDFSegment(text="Content here today.", page_number=1)]

    crashing_processor = CrashOnceProcessor()

    # Attempt 1: crashes -- file must survive.
    with pytest.raises(SystemExit):
        _run_pdf_pipeline(job.job_id, file_path, deps, processor=crashing_processor)
    assert os.path.exists(file_path)

    # Attempt 2 (the "redelivered" retry): succeeds using the SAME file.
    result = _run_pdf_pipeline(job.job_id, file_path, deps, processor=crashing_processor)
    assert result.status == JobStatus.COMPLETED
    assert not os.path.exists(file_path)  # now cleaned up, since this attempt reached a terminal outcome


# ---------------------------------------------------------------------------
# 8-10. Cleanup safety: missing file, cleanup failure, path safety
# ---------------------------------------------------------------------------


def test_cleanup_is_safe_when_file_already_missing(tmp_path):
    never_existed = str(tmp_path / "never-existed.pdf")

    _cleanup_upload("job-1", never_existed, str(tmp_path))  # must not raise


def test_cleanup_called_twice_is_idempotent(tmp_path):
    file_path = _write_temp_file(tmp_path)

    _cleanup_upload("job-1", file_path, str(tmp_path))
    assert not os.path.exists(file_path)

    _cleanup_upload("job-1", file_path, str(tmp_path))  # must not raise the second time either


def test_cleanup_failure_does_not_corrupt_terminal_job_state(tmp_path, monkeypatch):
    """If the filesystem itself fails during cleanup (e.g. a permission
    error), the already-persisted COMPLETED status must not be changed.
    """

    file_path = _write_temp_file(tmp_path)
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    processor = FakePDFProcessor([PDFSegment(text="Content here today.", page_number=1)])
    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(tmp_path)),
        job_store=job_store,
        embedder=FakeEmbedder(),
        publisher=RecordingPublisher(),
    )

    def exploding_unlink(self, missing_ok=False):
        raise OSError("simulated permission error")

    monkeypatch.setattr(Path, "unlink", exploding_unlink)

    result = _run_pdf_pipeline(job.job_id, file_path, deps, processor=processor)

    assert result.status == JobStatus.COMPLETED  # unchanged despite the cleanup failure
    assert job_store.get(job.job_id).status == JobStatus.COMPLETED


def test_cleanup_refuses_to_delete_outside_upload_directory(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    sensitive_file = outside_dir / "sensitive.txt"
    sensitive_file.write_bytes(b"important data")

    _cleanup_upload("job-1", str(sensitive_file), str(upload_dir))

    assert sensitive_file.exists()  # untouched -- outside the configured upload directory


def test_cleanup_deletes_file_correctly_placed_inside_upload_directory(tmp_path):
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    file_path = upload_dir / "job-1.pdf"
    file_path.write_bytes(b"content")

    _cleanup_upload("job-1", str(file_path), str(upload_dir))

    assert not file_path.exists()


# ---------------------------------------------------------------------------
# Property tests: generated terminal outcomes -> file does not remain;
# generated crash outcomes -> file remains; idempotent cleanup.
# ---------------------------------------------------------------------------


@given(outcome=st.sampled_from(["completed", "failed", "publish_failed"]), page_count=st.integers(min_value=1, max_value=8))
@hyp_settings(max_examples=30, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_any_terminal_outcome_removes_the_source_file(tmp_path, outcome, page_count):
    """For any generated terminal outcome (completed, failed,
    publish_failed) and any generated source size, the file does not
    remain once the pipeline function returns.
    """

    upload_dir = tmp_path / f"u-{outcome}-{page_count}"
    upload_dir.mkdir()
    file_path = str(upload_dir / "upload.pdf")
    Path(file_path).write_bytes(b"content")

    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)

    if outcome == "failed":
        class FailingProcessor:
            def process(self, source):
                raise PDFUnreadableError("corrupt")

        processor = FailingProcessor()
        publisher = RecordingPublisher()
    else:
        processor = FakePDFProcessor(
            [PDFSegment(text=f"Content for page {i} here today.", page_number=i) for i in range(1, page_count + 1)]
        )
        if outcome == "publish_failed":
            publisher = RecordingPublisher(
                result=PublicationResult(
                    status=JobStatus.PUBLISH_FAILED,
                    published_count=0,
                    total_count=page_count,
                    error_details=ErrorDetail(error_type="X", status_code="PublicationFailed", message="boom", detail={}),
                )
            )
        else:
            publisher = RecordingPublisher()

    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(upload_dir)),
        job_store=job_store,
        embedder=FakeEmbedder(),
        publisher=publisher,
    )

    result = _run_pdf_pipeline(job.job_id, file_path, deps, processor=processor)

    expected_status = {"completed": JobStatus.COMPLETED, "failed": JobStatus.FAILED, "publish_failed": JobStatus.PUBLISH_FAILED}
    assert result.status == expected_status[outcome]
    assert not os.path.exists(file_path)


@given(crash_at=st.sampled_from(["processor", "embedder"]))
@hyp_settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_crash_at_any_stage_preserves_the_source_file(tmp_path, crash_at):
    """For any generated stage a simulated worker crash (BaseException)
    occurs at, the file must survive -- cleanup never runs because the
    function never reaches a return point.
    """

    upload_dir = tmp_path / f"crash-{crash_at}"
    upload_dir.mkdir()
    file_path = str(upload_dir / "upload.pdf")
    Path(file_path).write_bytes(b"content")

    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)

    class CrashingProcessor:
        def process(self, source):
            if crash_at == "processor":
                raise SystemExit("simulated crash")
            return [PDFSegment(text="Content here today.", page_number=1)]

    class CrashingEmbedder:
        def embed(self, texts):
            if crash_at == "embedder":
                raise SystemExit("simulated crash")
            return [[0.1] * 384 for _ in texts]

    deps = _PipelineDependencies(
        settings=make_settings(upload_directory=str(upload_dir)),
        job_store=job_store,
        embedder=CrashingEmbedder(),
        publisher=RecordingPublisher(),
    )

    with pytest.raises(SystemExit):
        _run_pdf_pipeline(job.job_id, file_path, deps, processor=CrashingProcessor())

    assert os.path.exists(file_path)


@given(exists=st.booleans(), second_call_exists=st.just(False))
@hyp_settings(max_examples=10, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_property_cleanup_is_idempotent_regardless_of_initial_existence(tmp_path, exists, second_call_exists):
    upload_dir = tmp_path / f"idem-{exists}"
    upload_dir.mkdir()
    file_path = str(upload_dir / "upload.pdf")
    if exists:
        Path(file_path).write_bytes(b"content")

    _cleanup_upload("job", file_path, str(upload_dir))  # must never raise, present or not
    _cleanup_upload("job", file_path, str(upload_dir))  # calling again must also never raise

    assert not os.path.exists(file_path)
