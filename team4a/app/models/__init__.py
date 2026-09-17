"""Pydantic data models and custom exceptions for the Team 4A ingestion pipeline.

Task 1.2 introduces:
    - schemas.py:    JobStatus, SourceType, ErrorDetail, JobResponse,
                      YouTubeRequest, IngestionJob, Heading, PDFSegment,
                      VideoSegment, YouTubeSegment, Chunk
    - exceptions.py:  Team4AError, PDFUnreadableError,
                      TranscriptUnavailableError, VideoInaccessibleError

Re-exported here so later modules can do `from app.models import IngestionJob`
etc. without needing to know the internal file layout.
"""

from app.models.exceptions import (
    EmbeddingDimensionMismatchError,
    PDFTooLargeError,
    PDFTooManyPagesError,
    PDFUnreadableError,
    Team4AError,
    TranscriptionError,
    TranscriptUnavailableError,
    UploadTooLargeError,
    VideoInaccessibleError,
    VideoTooLargeError,
    VideoTooLongError,
    VideoUnreadableError,
)
from app.models.schemas import (
    Chunk,
    ChunkMetadata,
    EnrichedChunk,
    ErrorDetail,
    Heading,
    IngestionJob,
    JobResponse,
    JobListResponse,
    JobStatus,
    Keyframe,
    PDFSegment,
    PublicationResult,
    SourceType,
    VideoProcessingResult,
    VideoSegment,
    YouTubeMetadata,
    YouTubeProcessingResult,
    YouTubeRequest,
    YouTubeSegment,
)

__all__ = [
    "JobStatus",
    "SourceType",
    "ErrorDetail",
    "JobResponse",
    "JobListResponse",
    "YouTubeRequest",
    "IngestionJob",
    "Heading",
    "PDFSegment",
    "VideoSegment",
    "Keyframe",
    "VideoProcessingResult",
    "YouTubeSegment",
    "YouTubeMetadata",
    "YouTubeProcessingResult",
    "Chunk",
    "ChunkMetadata",
    "EnrichedChunk",
    "PublicationResult",
    "Team4AError",
    "PDFUnreadableError",
    "PDFTooLargeError",
    "PDFTooManyPagesError",
    "TranscriptUnavailableError",
    "VideoInaccessibleError",
    "VideoUnreadableError",
    "VideoTooLargeError",
    "VideoTooLongError",
    "TranscriptionError",
    "EmbeddingDimensionMismatchError",
    "UploadTooLargeError",
]
