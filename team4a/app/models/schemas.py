"""Shared Pydantic data models for the Team 4A ingestion pipeline.

Implements exactly the models named in the official Team 4A design document
for this task:

    app/models/schemas.py with Pydantic models:
        JobResponse, JobStatus, YouTubeRequest, IngestionJob, Chunk,
        PDFSegment, VideoSegment, YouTubeSegment

    Requirements: 1.4, 2.5, 2.6, 3.4, 3.5, 8.2, 8.4

This module defines data contracts only. It does not implement PDF
extraction, video/Whisper processing, YouTube fetching, chunking,
embedding, metadata enrichment, or Qdrant publication — those belong to
later tasks (2.1, 3.1, 4.1, 6.1, 7.1, 8.1, 8.2).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from app.config.settings import get_settings


def _utcnow() -> datetime:
    """Timezone-aware "now", used for IngestionJob timestamps."""

    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class JobStatus(str, Enum):
    """Lifecycle states of an Ingestion_Job.

    Exactly the statuses defined in the official requirements:
    Requirement 8.4 (queued, processing, completed, failed) and
    Requirement 7.5 (publish_failed).
    """

    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    PUBLISH_FAILED = "publish_failed"


class SourceType(str, Enum):
    """Ingestion source types supported by Team 4A (Requirement 6.4 / Property 21).

    No source types beyond pdf, mp4, and youtube are defined, per spec.
    """

    PDF = "pdf"
    MP4 = "mp4"
    YOUTUBE = "youtube"


# ---------------------------------------------------------------------------
# Error details (used on IngestionJob.error_details)
# ---------------------------------------------------------------------------


class ErrorDetail(BaseModel):
    """Structured failure information attached to a failed Ingestion_Job.

    Populated from a Team4AError (see app/models/exceptions.py) or from any
    other unexpected failure encountered while processing a job.
    """

    error_type: str = Field(..., description="Exception class name, e.g. 'PDFUnreadableError'.")
    status_code: str = Field(
        ..., description="Machine-readable error code, e.g. 'PDFUnreadable'."
    )
    message: str = Field(..., description="Human-readable description of the failure.")
    detail: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_exception(cls, exc: "Team4AError") -> "ErrorDetail":  # noqa: F821
        """Build an ErrorDetail from a raised Team4AError.

        Imported lazily to avoid a circular import between `schemas.py` and
        `exceptions.py`.
        """

        return cls(**exc.to_error_detail())


# ---------------------------------------------------------------------------
# API-facing models
# ---------------------------------------------------------------------------


class JobResponse(BaseModel):
    """Response returned immediately after an ingestion request is accepted.

    Requirement 9: each /ingest/* endpoint returns a job identifier.
    Defined here as a shared contract; wired into routes in Task 10.1.
    """

    job_id: str
    status: JobStatus


class YouTubeRequest(BaseModel):
    """Request body for POST /ingest/youtube.

    Requirement 3: submit a YouTube URL, with configurable language
    preference (Requirement 3.6). Defined here as a shared contract; wired
    into routes in Task 10.1.
    """

    url: HttpUrl
    language: str = Field(default_factory=lambda: get_settings().youtube_default_language)


# ---------------------------------------------------------------------------
# Ingestion job
# ---------------------------------------------------------------------------


class IngestionJob(BaseModel):
    """A unit of work tracked from submission through Vector DB publication.

    Requirement 8: job identifier, status, and progress tracking.
    Property 25: completed jobs must record status=completed and an accurate
        chunk_count.
    Property 26: job_id values must be unique across jobs.
    Property 27: progress must be exactly 25/50/75/100 at each pipeline
        stage boundary.
    """

    job_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    source_type: SourceType
    status: JobStatus = JobStatus.QUEUED
    progress: int = Field(
        default=0,
        ge=0,
        le=100,
        description=(
            "Percentage complete. Must be 0 (queued) or one of the "
            "configured pipeline stage percentages (default: 25/50/75/100)."
        ),
    )
    chunk_count: int | None = Field(
        default=None,
        ge=0,
        description="Total chunks published for this job. Set only on completion.",
    )
    error_details: ErrorDetail | None = Field(
        default=None,
        description="Populated when status is 'failed' or 'publish_failed'.",
    )
    created_at: datetime = Field(default_factory=_utcnow)
    updated_at: datetime = Field(default_factory=_utcnow)

    @field_validator("job_id")
    @classmethod
    def _job_id_not_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("job_id must be a non-empty string")
        return value

    @field_validator("progress")
    @classmethod
    def _progress_must_be_a_known_stage_value(cls, value: int) -> int:
        settings = get_settings()
        allowed = {
            0,
            settings.progress_extraction_pct,
            settings.progress_chunking_pct,
            settings.progress_embedding_pct,
            settings.progress_publication_pct,
        }
        if value not in allowed:
            raise ValueError(
                f"progress must be one of {sorted(allowed)} (configured pipeline stage "
                f"boundaries), got {value}"
            )
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def _timestamps_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware (UTC)")
        return value

    @model_validator(mode="after")
    def _error_details_consistency(self) -> "IngestionJob":
        if self.status in (JobStatus.FAILED, JobStatus.PUBLISH_FAILED) and self.error_details is None:
            raise ValueError(f"error_details is required when status is '{self.status.value}'")
        return self


class JobListResponse(BaseModel):
    """Response body for GET /jobs (Task 10.1).

    Requirement 9.5: return a paginated list of Ingestion_Jobs with their
    statuses. `total` is the minimum extra information a client needs to
    know when to stop paginating -- not an arbitrary addition -- so that
    "iterating through all pages yields exactly N jobs with no
    duplicates" is actually achievable by a caller.
    """

    jobs: list[IngestionJob]
    page: int = Field(..., ge=1)
    page_size: int = Field(..., ge=1)
    total: int = Field(..., ge=0)


# ---------------------------------------------------------------------------
# Source-specific processor output (Tasks 2.1 / 3.1 / 4.1 will populate these)
# ---------------------------------------------------------------------------


class Heading(BaseModel):
    """A single extracted heading/section title within a PDF page."""

    text: str
    level: int = Field(..., ge=1)


class PDFSegment(BaseModel):
    """One page's extracted content, as produced by the PDF_Processor.

    Requirements 1.1, 1.2, 1.3, 1.5.
    """

    text: str
    page_number: int = Field(..., ge=1, description="1-indexed source page number.")
    headings: list[Heading] = Field(default_factory=list)
    is_image_only: bool = Field(
        default=False,
        description="True when the page has images but no extractable text (Requirement 1.5).",
    )


class VideoSegment(BaseModel):
    """One transcribed audio segment, as produced by the Video_Processor.

    Requirements 2.1, 2.2, 2.6.
    """

    text: str
    start_time: float = Field(..., ge=0)
    end_time: float = Field(..., ge=0)
    frame_reference: str | None = Field(
        default=None, description="Identifier of an associated extracted keyframe, if any."
    )
    transcription_failed: bool = Field(
        default=False,
        description=(
            "True when transcription failed for this specific segment "
            "(Requirement 2.6). Processing of other segments continues regardless."
        ),
    )

    @model_validator(mode="after")
    def _end_not_before_start(self) -> "VideoSegment":
        if self.end_time < self.start_time:
            raise ValueError("end_time must be greater than or equal to start_time")
        return self


class YouTubeSegment(BaseModel):
    """One transcript entry, as produced by the YouTube_Processor.

    Requirement 3.2: preserve start time and duration per segment.
    """

    text: str
    start_time: float = Field(..., ge=0)
    duration: float = Field(..., ge=0)


class YouTubeMetadata(BaseModel):
    """Video-level metadata for a YouTube source, as produced by the
    YouTube_Processor.

    Requirement 3.3: title, channel, duration, publication date.

    Added in Task 4.1 -- video-level facts, not properties of any single
    transcript segment, so they don't belong on `YouTubeSegment` (same
    reasoning as `VideoProcessingResult.audio_absent` in Task 3.1: a
    per-segment model has no field to hold a whole-video fact).

    `duration_seconds` is named distinctly from `YouTubeSegment.duration`
    (a single segment's length) to avoid confusing total video duration
    with transcript segment duration, per Task 4.1's explicit instruction.
    """

    title: str = Field(..., min_length=1)
    channel: str = Field(..., min_length=1)
    duration_seconds: float = Field(
        ..., ge=0, description="Total video duration, distinct from any single segment's duration."
    )
    publication_date: date | None = Field(
        default=None,
        description=(
            "Calendar date the video was published. None when the provider "
            "doesn't expose it -- never fabricated (Task 4.1 instruction)."
        ),
    )


class YouTubeProcessingResult(BaseModel):
    """The full output of processing one YouTube URL: transcript segments
    plus video-level metadata.

    Added in Task 4.1. A bare `list[YouTubeSegment]` cannot represent
    title/channel/duration/publication_date at all -- there is no
    per-segment field for a whole-video fact -- so this wrapper is a
    necessary addition, not a speculative one (same precedent as
    `VideoProcessingResult`, Task 3.1).
    """

    segments: list[YouTubeSegment] = Field(default_factory=list)
    metadata: YouTubeMetadata


class Keyframe(BaseModel):
    """One extracted video keyframe reference, as produced by the
    Video_Processor.

    Requirements 2.3, 2.4: extract keyframes at a configurable interval and
    associate each with its timestamp in the source video.

    Added in Task 3.1. `VideoSegment` (Task 1.2) already carries an
    optional `frame_reference` for the keyframe nearest a given
    transcription segment, but keyframe extraction itself is independent
    of transcription (Property 5 defines keyframe count/timing on its own,
    regardless of whether/how much speech exists), so keyframes need their
    own standalone representation rather than being folded only into
    VideoSegment.
    """

    timestamp: float = Field(..., ge=0)
    frame_reference: str = Field(
        ...,
        min_length=1,
        description=(
            "A stable identifier for this keyframe (e.g. 'kf_1_30s'), not a "
            "persisted file path -- Task 3.1 does not implement keyframe "
            "image storage."
        ),
    )


class VideoProcessingResult(BaseModel):
    """The full output of processing one MP4 file.

    Added in Task 3.1. `process()` cannot return a bare `list[VideoSegment]`
    without losing information the spec requires: `audio_absent` is a
    video/job-level fact (Requirement 2.5), not a property of any one
    segment, and an empty segment list is otherwise ambiguous between "no
    audio track" and "audio present but no speech detected". Keyframes are
    also independent of transcription segments (Property 5) and need their
    own place. `segments` remains the primary field and still uses the
    unmodified Task 1.2 `VideoSegment` model.
    """

    segments: list[VideoSegment] = Field(default_factory=list)
    keyframes: list[Keyframe] = Field(default_factory=list)
    audio_absent: bool = Field(
        default=False,
        description="True when the source MP4 has no audio track (Requirement 2.5).",
    )


class Chunk(BaseModel):
    """Uniform Chunker output, identical in shape regardless of source type.

    Property 14: exactly three fields — text (non-empty), chunk_index (>=0),
    total_chunks (> 0, with chunk_index < total_chunks). Embedding and
    metadata are attached in later stages (Tasks 7.1 and 8.1), not here.
    """

    text: str = Field(..., min_length=1)
    chunk_index: int = Field(..., ge=0)
    total_chunks: int = Field(..., gt=0)

    @model_validator(mode="after")
    def _chunk_index_within_bounds(self) -> "Chunk":
        if self.chunk_index >= self.total_chunks:
            raise ValueError("chunk_index must be less than total_chunks")
        return self


class ChunkMetadata(BaseModel):
    """Metadata attached to one Chunk by the Metadata_Enricher (Task 8.1).

    Requirement 6: common fields (chunk_id, source_type, job_id,
    ingestion_timestamp, embedding_model) apply to every chunk regardless
    of source; the remaining fields are populated only for the source
    type they belong to (Requirements 6.1 PDF, 6.2 video, 6.3 YouTube) and
    left as None otherwise -- never fabricated for a source type that
    doesn't produce that information.

    Added in Task 8.1. Kept as one flat model (matching this project's
    established style, e.g. `VideoProcessingResult`) rather than a
    discriminated union, since a Qdrant payload (Task 8.2) will ultimately
    want a flat JSON-like structure regardless.
    """

    # Common (Requirement 6, all source types)
    chunk_id: str = Field(..., min_length=1)
    source_type: SourceType
    job_id: str = Field(..., min_length=1)
    ingestion_timestamp: datetime
    embedding_model: str = Field(..., min_length=1)
    embedding_model_version: str = Field(
        ...,
        min_length=1,
        description=(
            "Provenance identifier for the exact embedding model snapshot used "
            "(Requirement 6.5) -- e.g. a pinned Hugging Face Hub commit SHA. "
            "Distinct from `embedding_model` (the model name)."
        ),
    )
    chunk_position: int = Field(..., ge=0, description="This chunk's chunk_index within its own chunk group.")

    # ------------------------------------------------------------------
    # Phase 1 (Rev.4.4 canonical identity + ingestion-generation layer).
    #
    # All four fields are Optional[..., default=None] -- purely additive,
    # exactly the same pattern already used for every source-conditional
    # field below (filename, page_number, etc.). This means:
    #   - every existing test/code path that constructs a ChunkMetadata
    #     without these fields continues to work completely unchanged;
    #   - the legacy publication path (Publisher.publish() with no
    #     collection_name_override, targeting `qdrant_collection_name`)
    #     never sees these fields populated at all, since nothing in the
    #     legacy Celery tasks sets them;
    #   - only the NEW canonical path (app/pipeline/canonical_ingestion.py)
    #     populates them, via `ChunkMetadata.model_copy(update={...})` on
    #     an already-produced chunk -- never by mutating MetadataEnricher's
    #     own, unchanged output in place.
    # `None` values are omitted from the Qdrant payload by _build_point's
    # existing `exclude_none=True` dump, so a legacy-path chunk's payload
    # is byte-for-byte identical to before this change.
    # ------------------------------------------------------------------
    document_id: str | None = Field(
        default=None,
        description=(
            "Rev.4.4 canonical document identity (= Team 4C File._id). Supplied by the "
            "trusted internal caller, never generated/derived by Team 4A (no synthetic "
            "value, no derivation from filename/URL/hash/job_id/chunk_id/random UUID)."
        ),
    )
    workspace_id: str | None = Field(
        default=None,
        description=(
            "Rev.4.4 mandatory tenancy boundary. Supplied by the trusted internal caller "
            "(the eventual verified-JWT claim) -- Team 4A never accepts this from "
            "arbitrary/browser-facing input."
        ),
    )
    user_id: str | None = Field(
        default=None,
        description=(
            "Actor/audit metadata only (Rev.4.4 -- NEVER a retrieval/tenancy filter). "
            "Supplied by the trusted internal caller, same provenance as workspace_id."
        ),
    )
    ingestion_generation: int | None = Field(
        default=None,
        ge=1,
        description=(
            "Rev.4.4 monotonic per-document generation number, issued by "
            "app.pipeline.ingestion_lock.IngestionLock.acquire() at lock-acquisition time. "
            "MongoDB File.currentIngestionGeneration -- not this field, and not Redis -- "
            "is the sole authority for which generation is *currently visible*; this field "
            "only records which generation *produced* a given chunk."
        ),
    )

    # PDF (Requirement 6.1) -- also used as the shared "filename" for video.
    filename: str | None = None
    page_number: int | None = Field(default=None, ge=1)
    headings: list[Heading] = Field(default_factory=list)

    # Video (Requirement 6.2) -- also used as the shared "start timestamp"
    # for YouTube, since both represent a position into a media timeline.
    start_timestamp: float | None = Field(default=None, ge=0)
    end_timestamp: float | None = Field(default=None, ge=0)
    frame_reference: str | None = None

    # YouTube (Requirement 6.3)
    duration: float | None = Field(default=None, ge=0)
    video_title: str | None = None
    channel_name: str | None = None
    source_url: str | None = None
    publication_date: date | None = None

    @field_validator("ingestion_timestamp")
    @classmethod
    def _ingestion_timestamp_must_be_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("ingestion_timestamp must be timezone-aware (UTC)")
        return value

    @model_validator(mode="after")
    def _required_fields_present_for_source_type(self) -> "ChunkMetadata":
        if self.source_type == SourceType.PDF:
            required = {"filename": self.filename, "page_number": self.page_number}
        elif self.source_type == SourceType.MP4:
            required = {
                "filename": self.filename,
                "start_timestamp": self.start_timestamp,
                "end_timestamp": self.end_timestamp,
            }
        else:  # SourceType.YOUTUBE
            required = {
                "start_timestamp": self.start_timestamp,
                "duration": self.duration,
                "video_title": self.video_title,
                "channel_name": self.channel_name,
                "source_url": self.source_url,
                # publication_date is deliberately NOT required: the
                # provider may legitimately not expose one (Task 4.1),
                # and it must never be fabricated to satisfy this check.
            }

        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise ValueError(
                f"ChunkMetadata for source_type={self.source_type.value!r} is missing required "
                f"field(s): {', '.join(missing)}"
            )
        return self


class EnrichedChunk(BaseModel):
    """A Chunk paired with its enriched metadata.

    Added in Task 8.1. Wraps the existing, unmodified `Chunk` (Task 6.1)
    rather than duplicating its fields, so no source-specific or chunk
    information already produced upstream is lost or restated.
    """

    chunk: Chunk
    metadata: ChunkMetadata


class PublicationResult(BaseModel):
    """The outcome of one Vector_DB_Publisher.publish() call (Task 8.2).

    Added in Task 8.2 as the smallest additive model needed to report a
    publication outcome, reusing the existing `JobStatus` and
    `ErrorDetail` models rather than redesigning `IngestionJob` or
    implementing the full job lifecycle -- applying this result to a
    persisted `IngestionJob` record is Task 10.2's responsibility.

    Requirement 7.5 / Property 25: a completed publication reports an
    accurate `published_count`; a permanently failed one is marked
    `publish_failed` and retains error information, without claiming
    unpublished records were published.
    """

    status: JobStatus = Field(
        ..., description="Only COMPLETED or PUBLISH_FAILED are valid outcomes of a publish() call."
    )
    published_count: int = Field(..., ge=0, description="Records successfully published before any permanent failure.")
    total_count: int = Field(..., ge=0, description="Total records the publish() call was asked to publish.")
    error_details: ErrorDetail | None = Field(
        default=None, description="Populated when status is publish_failed."
    )

    @model_validator(mode="after")
    def _status_consistency(self) -> "PublicationResult":
        if self.status not in (JobStatus.COMPLETED, JobStatus.PUBLISH_FAILED):
            raise ValueError("PublicationResult.status must be 'completed' or 'publish_failed'")

        if self.published_count > self.total_count:
            raise ValueError("published_count cannot exceed total_count")

        if self.status == JobStatus.PUBLISH_FAILED and self.error_details is None:
            raise ValueError("error_details is required when status is 'publish_failed'")

        if self.status == JobStatus.COMPLETED:
            if self.error_details is not None:
                raise ValueError("error_details must be None when status is 'completed'")
            if self.published_count != self.total_count:
                raise ValueError("a 'completed' result must have published_count == total_count")

        return self
