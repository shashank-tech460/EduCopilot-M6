"""Unit tests for Task 1.2: shared Pydantic models (JobStatus, SourceType,
IngestionJob, Chunk, PDFSegment, VideoSegment, YouTubeSegment, JobResponse,
YouTubeRequest, ErrorDetail).
"""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.exceptions import PDFUnreadableError
from app.models.schemas import (
    Chunk,
    ErrorDetail,
    Heading,
    IngestionJob,
    JobResponse,
    JobStatus,
    PDFSegment,
    SourceType,
    VideoSegment,
    YouTubeRequest,
    YouTubeSegment,
)


# ---------------------------------------------------------------------------
# JobStatus
# ---------------------------------------------------------------------------


def test_job_status_has_exactly_the_required_values():
    assert {s.value for s in JobStatus} == {
        "queued",
        "processing",
        "completed",
        "failed",
        "publish_failed",
    }


def test_invalid_job_status_rejected():
    with pytest.raises(ValueError):
        JobStatus("cancelled")


# ---------------------------------------------------------------------------
# SourceType
# ---------------------------------------------------------------------------


def test_source_type_has_exactly_the_required_values():
    assert {s.value for s in SourceType} == {"pdf", "mp4", "youtube"}


def test_invalid_source_type_rejected():
    with pytest.raises(ValueError):
        SourceType("docx")


# ---------------------------------------------------------------------------
# IngestionJob
# ---------------------------------------------------------------------------


def test_ingestion_job_creation_with_defaults():
    job = IngestionJob(source_type=SourceType.PDF)

    assert job.status == JobStatus.QUEUED
    assert job.progress == 0
    assert job.chunk_count is None
    assert job.error_details is None
    assert job.created_at.tzinfo is not None
    assert job.updated_at.tzinfo is not None
    assert len(job.job_id) > 0


def test_ingestion_job_ids_are_unique():
    job_a = IngestionJob(source_type=SourceType.MP4)
    job_b = IngestionJob(source_type=SourceType.MP4)
    assert job_a.job_id != job_b.job_id


def test_ingestion_job_requires_source_type():
    with pytest.raises(ValidationError):
        IngestionJob()  # type: ignore[call-arg]


@pytest.mark.parametrize("valid_progress", [0, 25, 50, 75, 100])
def test_ingestion_job_accepts_valid_progress_values(valid_progress):
    job = IngestionJob(source_type=SourceType.YOUTUBE, progress=valid_progress)
    assert job.progress == valid_progress


@pytest.mark.parametrize("invalid_progress", [-1, 10, 40, 60, 99, 101])
def test_ingestion_job_rejects_invalid_progress_values(invalid_progress):
    with pytest.raises(ValidationError):
        IngestionJob(source_type=SourceType.YOUTUBE, progress=invalid_progress)


def test_ingestion_job_rejects_invalid_source_type():
    with pytest.raises(ValidationError):
        IngestionJob(source_type="docx")  # type: ignore[arg-type]


def test_completed_job_can_carry_chunk_count():
    job = IngestionJob(
        source_type=SourceType.PDF,
        status=JobStatus.COMPLETED,
        progress=100,
        chunk_count=42,
    )
    assert job.status == JobStatus.COMPLETED
    assert job.chunk_count == 42


def test_failed_job_requires_error_details():
    with pytest.raises(ValidationError):
        IngestionJob(source_type=SourceType.PDF, status=JobStatus.FAILED)


def test_failed_job_with_error_details_is_valid():
    error = ErrorDetail.from_exception(PDFUnreadableError("cannot open PDF file"))
    job = IngestionJob(source_type=SourceType.PDF, status=JobStatus.FAILED, error_details=error)
    assert job.error_details.status_code == "PDFUnreadable"


def test_publish_failed_job_requires_error_details():
    with pytest.raises(ValidationError):
        IngestionJob(source_type=SourceType.MP4, status=JobStatus.PUBLISH_FAILED)


def test_ingestion_job_rejects_naive_timestamps():
    with pytest.raises(ValidationError):
        IngestionJob(source_type=SourceType.PDF, created_at=datetime(2026, 1, 1))


def test_ingestion_job_serialization_round_trip():
    job = IngestionJob(source_type=SourceType.YOUTUBE, progress=25)
    payload = job.model_dump_json()
    restored = IngestionJob.model_validate_json(payload)
    assert restored == job


# ---------------------------------------------------------------------------
# JobResponse / YouTubeRequest
# ---------------------------------------------------------------------------


def test_job_response_serializes_status_as_string_value():
    response = JobResponse(job_id="abc-123", status=JobStatus.QUEUED)
    assert response.model_dump()["status"] == JobStatus.QUEUED
    assert response.model_dump_json() == '{"job_id":"abc-123","status":"queued"}'


def test_youtube_request_defaults_language_from_settings():
    request = YouTubeRequest(url="https://www.youtube.com/watch?v=abc123")
    assert request.language == "en"


def test_youtube_request_rejects_invalid_url():
    with pytest.raises(ValidationError):
        YouTubeRequest(url="not-a-url")


# ---------------------------------------------------------------------------
# PDFSegment
# ---------------------------------------------------------------------------


def test_pdf_segment_defaults():
    segment = PDFSegment(text="hello world", page_number=1)
    assert segment.headings == []
    assert segment.is_image_only is False


def test_pdf_segment_with_headings():
    segment = PDFSegment(
        text="Chapter 1",
        page_number=1,
        headings=[Heading(text="Chapter 1", level=1)],
    )
    assert segment.headings[0].text == "Chapter 1"
    assert segment.headings[0].level == 1


def test_pdf_segment_rejects_zero_page_number():
    with pytest.raises(ValidationError):
        PDFSegment(text="x", page_number=0)


def test_pdf_segment_image_only_page_has_empty_text():
    segment = PDFSegment(text="", page_number=3, is_image_only=True)
    assert segment.is_image_only is True
    assert segment.text == ""


# ---------------------------------------------------------------------------
# VideoSegment
# ---------------------------------------------------------------------------


def test_video_segment_defaults():
    segment = VideoSegment(text="hello", start_time=0.0, end_time=5.0)
    assert segment.frame_reference is None
    assert segment.transcription_failed is False


def test_video_segment_rejects_end_before_start():
    with pytest.raises(ValidationError):
        VideoSegment(text="hello", start_time=10.0, end_time=5.0)


def test_video_segment_can_mark_transcription_failed():
    segment = VideoSegment(text="", start_time=0.0, end_time=5.0, transcription_failed=True)
    assert segment.transcription_failed is True


# ---------------------------------------------------------------------------
# YouTubeSegment
# ---------------------------------------------------------------------------


def test_youtube_segment_creation():
    segment = YouTubeSegment(text="hello", start_time=1.5, duration=3.2)
    assert segment.start_time == 1.5
    assert segment.duration == 3.2


def test_youtube_segment_rejects_negative_duration():
    with pytest.raises(ValidationError):
        YouTubeSegment(text="hello", start_time=0.0, duration=-1.0)


# ---------------------------------------------------------------------------
# Chunk
# ---------------------------------------------------------------------------


def test_chunk_valid_construction():
    chunk = Chunk(text="some text", chunk_index=0, total_chunks=3)
    assert chunk.chunk_index == 0
    assert chunk.total_chunks == 3


def test_chunk_rejects_empty_text():
    with pytest.raises(ValidationError):
        Chunk(text="", chunk_index=0, total_chunks=1)


def test_chunk_rejects_index_out_of_bounds():
    with pytest.raises(ValidationError):
        Chunk(text="x", chunk_index=3, total_chunks=3)


def test_chunk_rejects_non_positive_total_chunks():
    with pytest.raises(ValidationError):
        Chunk(text="x", chunk_index=0, total_chunks=0)


# ---------------------------------------------------------------------------
# ErrorDetail
# ---------------------------------------------------------------------------


def test_error_detail_from_exception():
    exc = PDFUnreadableError("PDF is corrupted", detail={"file_path": "/tmp/a.pdf"})
    error_detail = ErrorDetail.from_exception(exc)

    assert error_detail.error_type == "PDFUnreadableError"
    assert error_detail.status_code == "PDFUnreadable"
    assert error_detail.message == "PDF is corrupted"
    assert error_detail.detail == {"file_path": "/tmp/a.pdf"}


# ---------------------------------------------------------------------------
# Keyframe / VideoProcessingResult (Task 3.1 additions)
# ---------------------------------------------------------------------------


def test_keyframe_creation():
    from app.models.schemas import Keyframe

    kf = Keyframe(timestamp=30.0, frame_reference="kf_1_30s")
    assert kf.timestamp == 30.0
    assert kf.frame_reference == "kf_1_30s"


def test_keyframe_rejects_negative_timestamp():
    from app.models.schemas import Keyframe

    with pytest.raises(ValidationError):
        Keyframe(timestamp=-1.0, frame_reference="kf_1")


def test_keyframe_rejects_empty_frame_reference():
    from app.models.schemas import Keyframe

    with pytest.raises(ValidationError):
        Keyframe(timestamp=0.0, frame_reference="")


def test_video_processing_result_defaults():
    from app.models.schemas import VideoProcessingResult

    result = VideoProcessingResult()
    assert result.segments == []
    assert result.keyframes == []
    assert result.audio_absent is False


def test_video_processing_result_with_content():
    from app.models.schemas import Keyframe, VideoProcessingResult

    result = VideoProcessingResult(
        segments=[VideoSegment(text="hi", start_time=0.0, end_time=1.0)],
        keyframes=[Keyframe(timestamp=30.0, frame_reference="kf_1_30s")],
        audio_absent=False,
    )
    assert len(result.segments) == 1
    assert len(result.keyframes) == 1


# ---------------------------------------------------------------------------
# YouTubeMetadata / YouTubeProcessingResult (Task 4.1 additions)
# ---------------------------------------------------------------------------


def test_youtube_metadata_creation():
    from datetime import date

    from app.models.schemas import YouTubeMetadata

    metadata = YouTubeMetadata(
        title="A Video", channel="A Channel", duration_seconds=125.0, publication_date=date(2023, 1, 15)
    )
    assert metadata.title == "A Video"
    assert metadata.publication_date == date(2023, 1, 15)


def test_youtube_metadata_publication_date_defaults_to_none():
    from app.models.schemas import YouTubeMetadata

    metadata = YouTubeMetadata(title="A Video", channel="A Channel", duration_seconds=125.0)
    assert metadata.publication_date is None


def test_youtube_metadata_rejects_empty_title():
    from app.models.schemas import YouTubeMetadata

    with pytest.raises(ValidationError):
        YouTubeMetadata(title="", channel="C", duration_seconds=1.0)


def test_youtube_metadata_rejects_negative_duration():
    from app.models.schemas import YouTubeMetadata

    with pytest.raises(ValidationError):
        YouTubeMetadata(title="T", channel="C", duration_seconds=-1.0)


def test_youtube_processing_result_creation():
    from app.models.schemas import YouTubeMetadata, YouTubeProcessingResult

    result = YouTubeProcessingResult(
        segments=[YouTubeSegment(text="hi", start_time=0.0, duration=1.0)],
        metadata=YouTubeMetadata(title="T", channel="C", duration_seconds=10.0),
    )
    assert len(result.segments) == 1
    assert result.metadata.title == "T"


def test_youtube_processing_result_defaults_to_empty_segments():
    from app.models.schemas import YouTubeMetadata, YouTubeProcessingResult

    result = YouTubeProcessingResult(metadata=YouTubeMetadata(title="T", channel="C", duration_seconds=10.0))
    assert result.segments == []
