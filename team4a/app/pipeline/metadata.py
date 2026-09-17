"""Team 4A Metadata_Enricher.

Location matches the same pattern as the Chunker and Embedder
(app/pipeline/chunker.py, app/pipeline/embedder.py): app/pipeline/metadata.py.

Implements Requirement 6:
    6.1 For a chunk from a PDF source, attach page_number, heading
        context (if available), source filename, and chunk position.
    6.2 For a chunk from an MP4 source, attach start_timestamp,
        end_timestamp, source filename, and frame_reference (if
        applicable).
    6.3 For a chunk from a YouTube source, attach start_timestamp,
        duration, video_title, channel_name, source_url, and
        publication_date.
    6.4 Every chunk, regardless of source, is attached chunk_id,
        source_type, job_id, ingestion_timestamp, and the embedding
        model identifier.

Does not implement Qdrant publication, job orchestration, or Celery
tasks -- those belong to later tasks (8.2, 10.x). Makes no network calls,
re-runs no processor (no ffmpeg/Whisper/YouTube requests, no PDF
re-parsing), and does not modify PDFProcessor, VideoProcessor,
YouTubeProcessor, Chunker, or Embedder output -- it only reads from them.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.config.settings import Settings, get_settings
from app.models.schemas import (
    Chunk,
    ChunkMetadata,
    EnrichedChunk,
    Keyframe,
    PDFSegment,
    SourceType,
    VideoSegment,
    YouTubeMetadata,
    YouTubeSegment,
)

#: Fixed, arbitrary namespace UUID used to derive a deterministic
#: name-based UUID (uuid5) chunk_id -- Property 21 requires chunk_id to
#: be a UUID; this namespace is only used to make the SHA-1-based name
#: hashing well-defined and collision-resistant against IDs from other
#: contexts, per RFC 4122's intended use of namespace UUIDs.
_CHUNK_ID_NAMESPACE = uuid.UUID("2f8b6c4a-2f7e-4a76-9c6f-8e0a3f1d5b2c")


def _make_chunk_id(job_id: str, source_type: SourceType, segment_key: str, chunk: Chunk) -> str:
    """Deterministically derive a stable, UUID-formatted chunk_id.

    Task 8.3 remediation: Property 21 requires "chunk_id (UUID)". A
    name-based UUID (`uuid.uuid5`, RFC 4122) is used rather than a random
    `uuid.uuid4()` (Task 8.1 explicitly forbids randomness here, since
    repeated enrichment of the same chunk must produce the same ID):
    `uuid5` deterministically derives a UUID from a namespace + a "name"
    string, so the same inputs always produce the same UUID, while still
    satisfying the literal UUID format requirement. The "name" is a
    composite of everything that uniquely identifies this chunk within
    this job:
        job_id + source_type + segment_key + chunk_index + chunk text.

    `segment_key` disambiguates chunks with the same chunk_index that
    came from *different* segments (e.g. page 1's chunk 0 vs page 2's
    chunk 0) -- it is the PDF page number, the video segment's start
    timestamp, or the YouTube segment's start timestamp, all of which are
    already unique-enough, real (non-fabricated) identifiers already
    produced upstream. Including the chunk's own text additionally
    guards against any residual key collision and ties the ID to the
    chunk's actual content.

    A UUID's version bits make "deterministic, not random" independently
    verifiable: `uuid.UUID(chunk_id).version == 5` for every chunk_id
    produced here, whereas `uuid.uuid4()` always sets version 4.
    """

    composite = f"{job_id}|{source_type.value}|{segment_key}|{chunk.chunk_index}|{chunk.text}"
    return str(uuid.uuid5(_CHUNK_ID_NAMESPACE, composite))


def _nearest_keyframe_reference(segment: VideoSegment, keyframes: list[Keyframe]) -> str | None:
    """Find the keyframe most relevant to a transcription segment's time range.

    Prefers a keyframe whose timestamp falls within
    [segment.start_time, segment.end_time]; if none does, falls back to
    the keyframe nearest the segment's start time. Returns None (never a
    fabricated reference) if there are no keyframes at all -- e.g. a
    video shorter than the configured keyframe interval.
    """

    if not keyframes:
        return None

    within_range = [kf for kf in keyframes if segment.start_time <= kf.timestamp <= segment.end_time]
    if within_range:
        # Deterministic tie-break: the earliest in-range keyframe.
        return min(within_range, key=lambda kf: kf.timestamp).frame_reference

    nearest = min(keyframes, key=lambda kf: abs(kf.timestamp - segment.start_time))
    return nearest.frame_reference


class MetadataEnricher:
    """Attaches source-specific and common metadata to Chunker output.

    One `enrich_*_chunks` method per source type, each processing the
    chunks produced from a *single* upstream segment at a time (a
    PDFSegment/VideoSegment/YouTubeSegment) -- this is what allows every
    chunk to inherit its real page number / timestamps / heading context
    directly from that segment, with no fabrication and no need to
    re-parse the original PDF/video/YouTube source. Per-document
    convenience wrappers (`enrich_pdf`, `enrich_video`, `enrich_youtube`)
    are provided for the common case of enriching a whole document's
    segments at once, preserving overall ordering.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    # ------------------------------------------------------------------
    # PDF (Requirement 6.1)
    # ------------------------------------------------------------------

    def enrich_pdf_chunks(
        self,
        job_id: str,
        filename: str,
        ingestion_timestamp: datetime,
        segment: PDFSegment,
        chunks: list[Chunk],
    ) -> list[EnrichedChunk]:
        """Enrich the chunks produced from one PDF page (`segment`).

        `page_number` and `headings` come directly from `segment` --
        never re-derived by re-parsing the PDF.
        """

        segment_key = str(segment.page_number)
        enriched: list[EnrichedChunk] = []
        for chunk in chunks:
            metadata = ChunkMetadata(
                chunk_id=_make_chunk_id(job_id, SourceType.PDF, segment_key, chunk),
                source_type=SourceType.PDF,
                job_id=job_id,
                ingestion_timestamp=ingestion_timestamp,
                embedding_model=self._settings.embedding_model_name,
                embedding_model_version=self._settings.embedding_model_revision,
                chunk_position=chunk.chunk_index,
                filename=filename,
                page_number=segment.page_number,
                headings=list(segment.headings),
            )
            enriched.append(EnrichedChunk(chunk=chunk, metadata=metadata))
        return enriched

    def enrich_pdf(
        self,
        job_id: str,
        filename: str,
        ingestion_timestamp: datetime,
        segments_with_chunks: list[tuple[PDFSegment, list[Chunk]]],
    ) -> list[EnrichedChunk]:
        """Enrich every page's chunks for one PDF document, preserving order."""

        enriched: list[EnrichedChunk] = []
        for segment, chunks in segments_with_chunks:
            enriched.extend(self.enrich_pdf_chunks(job_id, filename, ingestion_timestamp, segment, chunks))
        return enriched

    # ------------------------------------------------------------------
    # Video (Requirement 6.2)
    # ------------------------------------------------------------------

    def enrich_video_chunks(
        self,
        job_id: str,
        filename: str,
        ingestion_timestamp: datetime,
        segment: VideoSegment,
        chunks: list[Chunk],
        keyframes: list[Keyframe],
    ) -> list[EnrichedChunk]:
        """Enrich the chunks produced from one transcription segment.

        `start_timestamp`/`end_timestamp` come directly from `segment`.
        `frame_reference` is correlated against `keyframes` (already
        produced by VideoProcessor -- Task 3.1's audit identified this
        correlation as Task 8.1's responsibility). No ffmpeg is invoked
        and no keyframes are regenerated here.
        """

        segment_key = str(segment.start_time)
        frame_reference = _nearest_keyframe_reference(segment, keyframes)

        enriched: list[EnrichedChunk] = []
        for chunk in chunks:
            metadata = ChunkMetadata(
                chunk_id=_make_chunk_id(job_id, SourceType.MP4, segment_key, chunk),
                source_type=SourceType.MP4,
                job_id=job_id,
                ingestion_timestamp=ingestion_timestamp,
                embedding_model=self._settings.embedding_model_name,
                embedding_model_version=self._settings.embedding_model_revision,
                chunk_position=chunk.chunk_index,
                filename=filename,
                start_timestamp=segment.start_time,
                end_timestamp=segment.end_time,
                frame_reference=frame_reference,
            )
            enriched.append(EnrichedChunk(chunk=chunk, metadata=metadata))
        return enriched

    def enrich_video(
        self,
        job_id: str,
        filename: str,
        ingestion_timestamp: datetime,
        keyframes: list[Keyframe],
        segments_with_chunks: list[tuple[VideoSegment, list[Chunk]]],
    ) -> list[EnrichedChunk]:
        """Enrich every transcription segment's chunks for one video, preserving order."""

        enriched: list[EnrichedChunk] = []
        for segment, chunks in segments_with_chunks:
            enriched.extend(
                self.enrich_video_chunks(job_id, filename, ingestion_timestamp, segment, chunks, keyframes)
            )
        return enriched

    # ------------------------------------------------------------------
    # YouTube (Requirement 6.3)
    # ------------------------------------------------------------------

    def enrich_youtube_chunks(
        self,
        job_id: str,
        url: str,
        ingestion_timestamp: datetime,
        video_metadata: YouTubeMetadata,
        segment: YouTubeSegment,
        chunks: list[Chunk],
    ) -> list[EnrichedChunk]:
        """Enrich the chunks produced from one YouTube transcript segment.

        `start_timestamp`/`duration` come from `segment`; `video_title`/
        `channel_name`/`publication_date` come from `video_metadata`
        (Task 4.1's YouTubeMetadata) -- `publication_date` is passed
        through as-is, including None, and is never fabricated here, per
        Task 4.1's own established behavior. No new YouTube network
        request is made.
        """

        segment_key = str(segment.start_time)
        enriched: list[EnrichedChunk] = []
        for chunk in chunks:
            metadata = ChunkMetadata(
                chunk_id=_make_chunk_id(job_id, SourceType.YOUTUBE, segment_key, chunk),
                source_type=SourceType.YOUTUBE,
                job_id=job_id,
                ingestion_timestamp=ingestion_timestamp,
                embedding_model=self._settings.embedding_model_name,
                embedding_model_version=self._settings.embedding_model_revision,
                chunk_position=chunk.chunk_index,
                start_timestamp=segment.start_time,
                duration=segment.duration,
                video_title=video_metadata.title,
                channel_name=video_metadata.channel,
                source_url=url,
                publication_date=video_metadata.publication_date,
            )
            enriched.append(EnrichedChunk(chunk=chunk, metadata=metadata))
        return enriched

    def enrich_youtube(
        self,
        job_id: str,
        url: str,
        ingestion_timestamp: datetime,
        video_metadata: YouTubeMetadata,
        segments_with_chunks: list[tuple[YouTubeSegment, list[Chunk]]],
    ) -> list[EnrichedChunk]:
        """Enrich every transcript segment's chunks for one YouTube video, preserving order."""

        enriched: list[EnrichedChunk] = []
        for segment, chunks in segments_with_chunks:
            enriched.extend(
                self.enrich_youtube_chunks(job_id, url, ingestion_timestamp, video_metadata, segment, chunks)
            )
        return enriched
