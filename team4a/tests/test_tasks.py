"""Unit tests for Task 10.2: Celery ingestion task orchestration.

No live Celery worker, Redis, Qdrant, Whisper, or YouTube access: every
test calls the plain, dependency-injectable `_run_pdf_pipeline` /
`_run_video_pipeline` / `_run_youtube_pipeline` functions directly (the
same functions the `@celery_app.task`-decorated entry points delegate to),
with fake processors/embedder/publisher and an `InMemoryJobStore` /
`FakeRedis` client.
"""

from __future__ import annotations

from datetime import date, timezone

import pytest

from app.api.job_store import InMemoryJobStore
from app.config.settings import Settings
from app.models.exceptions import (
    PDFUnreadableError,
    TranscriptUnavailableError,
    VideoUnreadableError,
)
from app.models.schemas import (
    ErrorDetail,
    Heading,
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
from app.tasks import _PipelineDependencies, _run_pdf_pipeline, _run_video_pipeline, _run_youtube_pipeline


class FakeRedis:
    """Records every progress key set -- used to verify the 25/50/75/100 sequence."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []

    def set(self, name: str, value: str):
        self.store[name] = value
        self.set_calls.append((name, value))
        return True

    def get(self, name: str):
        return self.store.get(name)


class FakeEmbedder:
    def __init__(self) -> None:
        self.embed_calls: list[list[str]] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.embed_calls.append(list(texts))
        return [[0.1] * 384 for _ in texts]


class RecordingPublisher:
    """Records exactly what it was called with, and returns a configured result."""

    def __init__(self, result: PublicationResult | None = None) -> None:
        self._result = result
        self.calls: list[tuple[list, list]] = []

    def publish(self, enriched_chunks, embeddings) -> PublicationResult:
        self.calls.append((list(enriched_chunks), list(embeddings)))
        if self._result is not None:
            return self._result
        return PublicationResult(
            status=JobStatus.COMPLETED,
            published_count=len(enriched_chunks),
            total_count=len(enriched_chunks),
        )


def make_settings(**overrides) -> Settings:
    return Settings(_env_file=None, **overrides)


def make_deps(job_store=None, embedder=None, publisher=None, redis_client=None, settings=None) -> _PipelineDependencies:
    return _PipelineDependencies(
        settings=settings or make_settings(),
        job_store=job_store or InMemoryJobStore(),
        embedder=embedder or FakeEmbedder(),
        publisher=publisher or RecordingPublisher(),
        redis_client=redis_client if redis_client is not None else FakeRedis(),
    )


# ---------------------------------------------------------------------------
# 1-3. Stage order / 4. Progress sequence -- PDF as the representative case
# ---------------------------------------------------------------------------


class FakePDFProcessor:
    def __init__(self, segments) -> None:
        self._segments = segments
        self.process_calls: list[str] = []

    def process(self, source):
        self.process_calls.append(source)
        return self._segments


def test_pdf_pipeline_calls_stages_in_correct_order():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)

    processor = FakePDFProcessor([PDFSegment(text="Some page content here today.", page_number=1)])
    embedder = FakeEmbedder()
    publisher = RecordingPublisher()
    redis_client = FakeRedis()
    deps = make_deps(job_store=job_store, embedder=embedder, publisher=publisher, redis_client=redis_client)

    result = _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=processor)

    assert processor.process_calls == ["/tmp/doc.pdf"]
    assert len(embedder.embed_calls) == 1
    assert len(publisher.calls) == 1
    assert result.status == JobStatus.COMPLETED


def test_progress_sequence_is_25_50_75_100(job_store=None):
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    redis_client = FakeRedis()
    deps = make_deps(job_store=job_store, redis_client=redis_client)

    processor = FakePDFProcessor([PDFSegment(text="Content here today for progress test.", page_number=1)])
    _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=processor)

    progress_values = [int(v) for _, v in redis_client.set_calls]
    assert progress_values == [25, 50, 75, 100]


def test_job_enters_processing_status(monkeypatch):
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)

    observed_statuses = []
    original_update = job_store.update

    def recording_update(updated_job):
        observed_statuses.append(updated_job.status)
        original_update(updated_job)

    monkeypatch.setattr(job_store, "update", recording_update)

    deps = make_deps(job_store=job_store)
    processor = FakePDFProcessor([PDFSegment(text="Content here today.", page_number=1)])
    _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=processor)

    assert observed_statuses[0] == JobStatus.PROCESSING


def test_successful_publication_results_in_completed():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    deps = make_deps(job_store=job_store)
    processor = FakePDFProcessor([PDFSegment(text="Content here today.", page_number=1)])

    result = _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=processor)

    assert result.status == JobStatus.COMPLETED
    assert result.progress == 100
    assert job_store.get(job.job_id).status == JobStatus.COMPLETED


def test_job_id_is_preserved_throughout(job_store=None):
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    deps = make_deps(job_store=job_store)
    processor = FakePDFProcessor([PDFSegment(text="Content here today.", page_number=1)])

    result = _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=processor)

    assert result.job_id == job.job_id


# ---------------------------------------------------------------------------
# 7. Processing failure -> failed
# ---------------------------------------------------------------------------


def test_pdf_processing_failure_results_in_failed_with_error_details():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    deps = make_deps(job_store=job_store)

    class FailingProcessor:
        def process(self, source):
            raise PDFUnreadableError("corrupt file")

    result = _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=FailingProcessor())

    assert result.status == JobStatus.FAILED
    assert result.error_details is not None
    assert result.error_details.status_code == "PDFUnreadable"
    assert result.error_details.message


def test_video_processing_failure_results_in_failed():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.MP4)
    job_store.create(job)
    deps = make_deps(job_store=job_store)

    class FailingVideoProcessor:
        def process(self, source):
            raise VideoUnreadableError("corrupt video")

    result = _run_video_pipeline(job.job_id, "/tmp/v.mp4", deps, processor=FailingVideoProcessor())

    assert result.status == JobStatus.FAILED
    assert result.error_details.status_code == "VideoUnreadable"


def test_youtube_processing_failure_results_in_failed():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.YOUTUBE)
    job_store.create(job)
    deps = make_deps(job_store=job_store)

    class FailingYouTubeProcessor:
        def process(self, url, language):
            raise TranscriptUnavailableError("no transcript")

    result = _run_youtube_pipeline(job.job_id, "https://youtu.be/abc", None, deps, processor=FailingYouTubeProcessor())

    assert result.status == JobStatus.FAILED
    assert result.error_details.status_code == "TranscriptUnavailable"


def test_generic_unexpected_exception_does_not_crash_and_is_classified():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    deps = make_deps(job_store=job_store)

    class BuggyProcessor:
        def process(self, source):
            raise RuntimeError("some unexpected bug")

    result = _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=BuggyProcessor())

    assert result.status == JobStatus.FAILED
    assert result.error_details.status_code == "ProcessingFailed"
    assert "unexpected bug" in result.error_details.message


# ---------------------------------------------------------------------------
# 8. Publisher permanent failure -> publish_failed
# ---------------------------------------------------------------------------


def test_publisher_permanent_failure_results_in_publish_failed():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)

    failure_result = PublicationResult(
        status=JobStatus.PUBLISH_FAILED,
        published_count=0,
        total_count=1,
        error_details=ErrorDetail(
            error_type="PublicationFailedError", status_code="PublicationFailed", message="qdrant down", detail={}
        ),
    )
    deps = make_deps(job_store=job_store, publisher=RecordingPublisher(result=failure_result))
    processor = FakePDFProcessor([PDFSegment(text="Content here today.", page_number=1)])

    result = _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=processor)

    assert result.status == JobStatus.PUBLISH_FAILED
    assert result.error_details.message == "qdrant down"
    # Progress must not falsely claim 100% publication completion.
    assert result.progress != 100 or result.status != JobStatus.PUBLISH_FAILED


def test_publish_failed_does_not_claim_full_completion():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)

    failure_result = PublicationResult(
        status=JobStatus.PUBLISH_FAILED,
        published_count=0,
        total_count=1,
        error_details=ErrorDetail(error_type="X", status_code="PublicationFailed", message="boom", detail={}),
    )
    deps = make_deps(job_store=job_store, publisher=RecordingPublisher(result=failure_result))
    processor = FakePDFProcessor([PDFSegment(text="Content here today.", page_number=1)])

    result = _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=processor)

    assert result.status != JobStatus.COMPLETED
    assert result.chunk_count == 0


# ---------------------------------------------------------------------------
# 11. PDF source metadata preserved through orchestration
# ---------------------------------------------------------------------------


def test_pdf_source_metadata_preserved_through_orchestration():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    publisher = RecordingPublisher()
    deps = make_deps(job_store=job_store, publisher=publisher)

    segment = PDFSegment(
        text="Chapter content spans a couple of sentences here.",
        page_number=7,
        headings=[Heading(text="Chapter 3", level=1)],
    )
    processor = FakePDFProcessor([segment])

    _run_pdf_pipeline(job.job_id, "/tmp/report.pdf", deps, processor=processor)

    enriched_chunks, _embeddings = publisher.calls[0]
    assert len(enriched_chunks) >= 1
    for enriched in enriched_chunks:
        assert enriched.metadata.page_number == 7
        assert enriched.metadata.headings == [Heading(text="Chapter 3", level=1)]
        assert enriched.metadata.filename == "report.pdf"
        assert enriched.metadata.source_type == SourceType.PDF


# ---------------------------------------------------------------------------
# 12. MP4 timestamp/frame metadata preserved
# ---------------------------------------------------------------------------


def test_video_timestamp_and_frame_metadata_preserved():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.MP4)
    job_store.create(job)
    publisher = RecordingPublisher()
    deps = make_deps(job_store=job_store, publisher=publisher)

    class FakeVideoProcessor:
        def process(self, source):
            return VideoProcessingResult(
                segments=[VideoSegment(text="Spoken words go here today.", start_time=30.0, end_time=45.0)],
                keyframes=[Keyframe(timestamp=32.0, frame_reference="kf_1_32s")],
                audio_absent=False,
            )

    _run_video_pipeline(job.job_id, "/tmp/lecture.mp4", deps, processor=FakeVideoProcessor())

    enriched_chunks, _embeddings = publisher.calls[0]
    assert len(enriched_chunks) >= 1
    for enriched in enriched_chunks:
        assert enriched.metadata.start_timestamp == 30.0
        assert enriched.metadata.end_timestamp == 45.0
        assert enriched.metadata.filename == "lecture.mp4"
        assert enriched.metadata.frame_reference == "kf_1_32s"


# ---------------------------------------------------------------------------
# 13. YouTube timestamp/duration metadata preserved
# ---------------------------------------------------------------------------


def test_youtube_metadata_preserved_through_orchestration():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.YOUTUBE)
    job_store.create(job)
    publisher = RecordingPublisher()
    deps = make_deps(job_store=job_store, publisher=publisher)

    class FakeYouTubeProcessor:
        def process(self, url, language):
            return YouTubeProcessingResult(
                segments=[YouTubeSegment(text="Welcome to today's video.", start_time=12.0, duration=4.0)],
                metadata=YouTubeMetadata(
                    title="Great Video", channel="Great Channel", duration_seconds=600.0,
                    publication_date=date(2023, 5, 1),
                ),
            )

    _run_youtube_pipeline(job.job_id, "https://www.youtube.com/watch?v=abc123", "en", deps, processor=FakeYouTubeProcessor())

    enriched_chunks, _embeddings = publisher.calls[0]
    assert len(enriched_chunks) >= 1
    for enriched in enriched_chunks:
        assert enriched.metadata.start_timestamp == 12.0
        assert enriched.metadata.duration == 4.0
        assert enriched.metadata.video_title == "Great Video"
        assert enriched.metadata.channel_name == "Great Channel"
        assert enriched.metadata.source_url == "https://www.youtube.com/watch?v=abc123"
        assert enriched.metadata.publication_date == date(2023, 5, 1)


# ---------------------------------------------------------------------------
# 14. audio_absent is not converted into a transcription success
# ---------------------------------------------------------------------------


def test_audio_absent_does_not_fabricate_a_transcription():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.MP4)
    job_store.create(job)
    publisher = RecordingPublisher()
    deps = make_deps(job_store=job_store, publisher=publisher)

    class AudioAbsentProcessor:
        def process(self, source):
            return VideoProcessingResult(
                segments=[],
                keyframes=[Keyframe(timestamp=30.0, frame_reference="kf1")],
                audio_absent=True,
            )

    result = _run_video_pipeline(job.job_id, "/tmp/silent.mp4", deps, processor=AudioAbsentProcessor())

    # No fabricated text was ever embedded or published.
    enriched_chunks, embeddings = publisher.calls[0]
    assert enriched_chunks == []
    assert embeddings == []
    # The job still completes -- audio_absent is not itself a failure.
    assert result.status == JobStatus.COMPLETED
    assert result.chunk_count == 0


# ---------------------------------------------------------------------------
# 15. transcription_failed segment information is not silently discarded
# ---------------------------------------------------------------------------


def test_transcription_failed_segment_does_not_block_successful_segments():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.MP4)
    job_store.create(job)
    publisher = RecordingPublisher()
    deps = make_deps(job_store=job_store, publisher=publisher)

    class MixedProcessor:
        def process(self, source):
            return VideoProcessingResult(
                segments=[
                    VideoSegment(text="This segment succeeded today.", start_time=0.0, end_time=5.0),
                    VideoSegment(text="", start_time=5.0, end_time=10.0, transcription_failed=True),
                    VideoSegment(text="This segment also succeeded.", start_time=10.0, end_time=15.0),
                ],
                keyframes=[],
                audio_absent=False,
            )

    result = _run_video_pipeline(job.job_id, "/tmp/mixed.mp4", deps, processor=MixedProcessor())

    enriched_chunks, embeddings = publisher.calls[0]
    published_texts = [ec.chunk.text for ec in enriched_chunks]
    assert "This segment succeeded today." in published_texts
    assert "This segment also succeeded." in published_texts
    # The failed segment's (empty) text was never published as content.
    assert "" not in published_texts
    assert result.status == JobStatus.COMPLETED


# ---------------------------------------------------------------------------
# 16-18. No stage skipped / embeddings aligned with chunks / publisher gets matching inputs
# ---------------------------------------------------------------------------


def test_no_stage_is_skipped_for_multi_segment_pdf():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    embedder = FakeEmbedder()
    publisher = RecordingPublisher()
    redis_client = FakeRedis()
    deps = make_deps(job_store=job_store, embedder=embedder, publisher=publisher, redis_client=redis_client)

    processor = FakePDFProcessor(
        [
            PDFSegment(text="Page one has some content here.", page_number=1),
            PDFSegment(text="Page two has some content here.", page_number=2),
        ]
    )

    _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=processor)

    assert len(processor.process_calls) == 1  # extraction happened exactly once
    assert len(embedder.embed_calls) == 1  # embedding happened exactly once
    assert len(publisher.calls) == 1  # publishing happened exactly once
    assert [int(v) for _, v in redis_client.set_calls] == [25, 50, 75, 100]  # all four stages recorded


def test_embeddings_remain_aligned_with_chunks():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.PDF)
    job_store.create(job)
    publisher = RecordingPublisher()
    deps = make_deps(job_store=job_store, publisher=publisher)

    processor = FakePDFProcessor(
        [
            PDFSegment(text="Alpha bravo charlie content one.", page_number=1),
            PDFSegment(text="Delta echo foxtrot content two.", page_number=2),
        ]
    )

    _run_pdf_pipeline(job.job_id, "/tmp/doc.pdf", deps, processor=processor)

    enriched_chunks, embeddings = publisher.calls[0]
    assert len(enriched_chunks) == len(embeddings)
    for enriched in enriched_chunks:
        assert enriched.metadata.chunk_position == enriched.chunk.chunk_index


def test_publisher_receives_matching_enriched_chunks_and_embeddings_counts():
    job_store = InMemoryJobStore()
    job = IngestionJob(source_type=SourceType.YOUTUBE)
    job_store.create(job)
    publisher = RecordingPublisher()
    deps = make_deps(job_store=job_store, publisher=publisher)

    class FakeYouTubeProcessor:
        def process(self, url, language):
            return YouTubeProcessingResult(
                segments=[
                    YouTubeSegment(text="First part of the talk today.", start_time=0.0, duration=3.0),
                    YouTubeSegment(text="Second part of the talk today.", start_time=3.0, duration=3.0),
                ],
                metadata=YouTubeMetadata(title="T", channel="C", duration_seconds=60.0),
            )

    _run_youtube_pipeline(job.job_id, "https://youtu.be/xyz", None, deps, processor=FakeYouTubeProcessor())

    enriched_chunks, embeddings = publisher.calls[0]
    assert len(enriched_chunks) == len(embeddings)
    assert len(enriched_chunks) >= 2


# ---------------------------------------------------------------------------
# Unknown job_id handling
# ---------------------------------------------------------------------------


def test_unknown_job_id_raises_value_error():
    deps = make_deps()
    processor = FakePDFProcessor([PDFSegment(text="content", page_number=1)])

    with pytest.raises(ValueError, match="Unknown job_id"):
        _run_pdf_pipeline("does-not-exist", "/tmp/doc.pdf", deps, processor=processor)


# ---------------------------------------------------------------------------
# Celery task registration (no live worker/broker needed)
# ---------------------------------------------------------------------------


def test_celery_tasks_are_registered_on_the_existing_celery_app():
    from app.celery_app import celery_app

    assert "team4a.process_pdf" in celery_app.tasks
    assert "team4a.process_video" in celery_app.tasks
    assert "team4a.process_youtube" in celery_app.tasks


def test_no_second_celery_application_was_created():
    import app.tasks as tasks_module
    from app.celery_app import celery_app as the_one_celery_app

    assert tasks_module.celery_app is the_one_celery_app
