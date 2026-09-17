"""Phase 2C-R -- produces `(EnrichedChunk list, embeddings)` for the
canonical `/v1/ingest` route, using the EXACT SAME existing, unmodified
`Chunker`/`Embedder`/`MetadataEnricher` calls `app/tasks.py`'s
`_run_pdf_pipeline`/`_run_video_pipeline`/`_run_youtube_pipeline` already
use -- this module does not reimplement or alter that logic, it reuses it
for a different orchestration path (the canonical route + Phase 1's
`CanonicalIngestionOrchestrator`, instead of the legacy route + Celery +
`Publisher.publish()` directly).

`app/tasks.py` itself is NOT imported or modified -- its internal
pipeline functions are private (`_run_*_pipeline`) and tied to
Celery/job-store bookkeeping this canonical path does not use, so the
three functions below are new, small, direct call sequences against the
same underlying processor/chunker/embedder/enricher objects, not a
dependency on `app/tasks.py`'s own internals.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from app.config.settings import Settings
from app.models.exceptions import TranscriptUnavailableError
from app.models.schemas import EnrichedChunk, VideoSegment, YouTubeProcessingResult, YouTubeSegment
from app.pipeline.chunker import Chunker
from app.pipeline.embedder import Embedder
from app.pipeline.metadata import MetadataEnricher
from app.pipeline.transcript_windowing import group_segments_into_windows
from app.processors.pdf_processor import PDFProcessor
from app.processors.video_processor import VideoProcessor
from app.processors.youtube_processor import YouTubeProcessor

#: M6 correction: shared window-sizing basis for BOTH video/YouTube
#: extraction below -- deliberately derived from the EXISTING
#: `chunk_size` setting rather than a new configuration field, per this
#: task's own instruction to preserve existing chunk-size policy unless
#: proven necessary to change it. `target_window_words` gives the
#: sentence-aware `Chunker` a coherent, page-like block of text to work
#: with (comparable to `chunk_size`, in words rather than tokens -- an
#: approximation, not required to be exact, since `Chunker` still does
#: its own precise token accounting on the resulting window text).
#: `min_window_words` is the floor below which a trailing window is
#: merged into its predecessor instead of standing alone (see
#: `transcript_windowing.py`'s own docstring for why).
def _target_window_words(settings: Settings) -> int:
    return settings.chunk_size


def _min_window_words(settings: Settings) -> int:
    return max(10, settings.chunk_size // 10)


def extract_pdf_for_canonical_ingestion(
    job_id: str, file_path: Path, settings: Settings
) -> tuple[list[EnrichedChunk], list[list[float]]]:
    processor = PDFProcessor(settings=settings)
    chunker = Chunker()
    embedder = Embedder(settings=settings)
    metadata_enricher = MetadataEnricher()

    filename = file_path.name
    created_at = datetime.now(timezone.utc)

    segments = processor.process(str(file_path))
    segments_with_chunks = [(segment, chunker.chunk(segment.text)) for segment in segments]
    flat_texts = [chunk.text for _, chunks in segments_with_chunks for chunk in chunks]
    embeddings = embedder.embed(flat_texts)
    enriched_chunks = metadata_enricher.enrich_pdf(job_id, filename, created_at, segments_with_chunks)
    return enriched_chunks, embeddings


def extract_video_for_canonical_ingestion(
    job_id: str, file_path: Path, settings: Settings
) -> tuple[list[EnrichedChunk], list[list[float]]]:
    processor = VideoProcessor(settings=settings)
    chunker = Chunker()
    embedder = Embedder(settings=settings)
    metadata_enricher = MetadataEnricher()

    filename = file_path.name
    created_at = datetime.now(timezone.utc)

    result = processor.process(str(file_path))

    # M6 correction: group raw, per-transcription-chunk `VideoSegment`s
    # (each often only a few words) into coherent transcript windows
    # BEFORE chunking, instead of chunking each raw segment in
    # isolation -- see `transcript_windowing.py`'s module docstring for
    # the full root-cause explanation. Each window becomes a synthetic
    # `VideoSegment` (the SAME model type `MetadataEnricher.enrich_video`
    # already expects -- that method is otherwise completely unchanged)
    # carrying the window's own real, non-fabricated start/end
    # timestamp range. `frame_reference`/`transcription_failed` are not
    # meaningful properties of a merged window, so the synthetic segment
    # uses their defaults (`None`/`False`) -- `enrich_video_chunks`
    # separately (and unchanged) correlates a keyframe against the
    # window's own real `start_time`.
    windows = group_segments_into_windows(
        [(segment.text, segment.start_time, segment.end_time) for segment in result.segments],
        target_window_words=_target_window_words(settings),
        min_window_words=_min_window_words(settings),
    )
    windowed_segments = [
        VideoSegment(text=window.text, start_time=window.start, end_time=window.end) for window in windows
    ]

    segments_with_chunks = [(segment, chunker.chunk(segment.text)) for segment in windowed_segments]
    flat_texts = [chunk.text for _, chunks in segments_with_chunks for chunk in chunks]
    embeddings = embedder.embed(flat_texts)
    enriched_chunks = metadata_enricher.enrich_video(job_id, filename, created_at, result.keyframes, segments_with_chunks)
    return enriched_chunks, embeddings


def _fetch_youtube_transcript_with_language_fallback(
    processor: YouTubeProcessor, file_url: str, settings: Settings
) -> YouTubeProcessingResult:
    """MVP M6 English+Hindi correction -- deterministic, non-LLM transcript
    language fallback for the CANONICAL YouTube path only.

    Tries `settings.youtube_default_language` (English by default) first,
    exactly as before this correction. If that specific attempt raises
    `TranscriptUnavailableError` (the video is reachable, but no
    transcript exists in that language -- never raised for a genuinely
    inaccessible video, which is `VideoInaccessibleError` instead and is
    never caught here), and `settings.youtube_fallback_language` is set
    (Hindi by default), exactly ONE further attempt is made in that
    language before letting the final `TranscriptUnavailableError`
    propagate unchanged to the existing, already-correct 502 handling in
    `app/api/canonical_ingest.py` -- that error-mapping code is not
    touched by this correction at all.

    When the primary language succeeds, the fallback language is NEVER
    attempted -- English is strictly preferred, and no unnecessary
    second network request is made on the common path. This performs a
    second, ordinary transcript-track request when needed -- never a
    translation, never an LLM call, never a substitution of one
    language's content for another; whichever language actually
    succeeds is what gets ingested, verbatim, through the unchanged rest
    of this pipeline.
    """

    primary_language = settings.youtube_default_language
    try:
        return processor.process(file_url, language=primary_language)
    except TranscriptUnavailableError:
        fallback_language = settings.youtube_fallback_language
        if fallback_language is None or fallback_language == primary_language:
            raise
        return processor.process(file_url, language=fallback_language)


def extract_youtube_for_canonical_ingestion(
    job_id: str, file_url: str, settings: Settings
) -> tuple[list[EnrichedChunk], list[list[float]]]:
    """`file_url` is the real YouTube URL itself -- passed straight to
    `YouTubeProcessor.process()`, exactly as the legacy `/ingest/youtube`
    route already does. `app.pipeline.remote_source_resolver` is
    deliberately never involved for this branch -- see that module's own
    docstring and the canonical route's YouTube handling."""

    processor = YouTubeProcessor(settings=settings)
    chunker = Chunker()
    embedder = Embedder(settings=settings)
    metadata_enricher = MetadataEnricher()

    created_at = datetime.now(timezone.utc)

    result = _fetch_youtube_transcript_with_language_fallback(processor, file_url, settings)

    # M6 correction: identical grouping step to the video path above --
    # see that function's own comment and `transcript_windowing.py`'s
    # module docstring for the full explanation. `duration` on the
    # synthetic `YouTubeSegment` is derived as `end - start` from the
    # window's own real timestamp range, matching `YouTubeSegment`'s
    # existing `start_time`/`duration` field shape exactly (never
    # `end_time`, which this model does not have).
    windows = group_segments_into_windows(
        [(segment.text, segment.start_time, segment.start_time + segment.duration) for segment in result.segments],
        target_window_words=_target_window_words(settings),
        min_window_words=_min_window_words(settings),
    )
    windowed_segments = [
        YouTubeSegment(text=window.text, start_time=window.start, duration=window.end - window.start)
        for window in windows
    ]

    segments_with_chunks = [(segment, chunker.chunk(segment.text)) for segment in windowed_segments]
    flat_texts = [chunk.text for _, chunks in segments_with_chunks for chunk in chunks]
    embeddings = embedder.embed(flat_texts)
    enriched_chunks = metadata_enricher.enrich_youtube(job_id, file_url, created_at, result.metadata, segments_with_chunks)
    return enriched_chunks, embeddings
