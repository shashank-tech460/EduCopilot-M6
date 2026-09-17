"""Unit tests for Task 8.1: MetadataEnricher.

No network access, no Qdrant, no real model downloads: uses the real
Chunker (Task 6.1) to produce genuine Chunk objects and real
PDFSegment/VideoSegment/YouTubeSegment/Keyframe/YouTubeMetadata model
instances (Task 1.2/3.1/4.1) as fixtures.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.config.settings import Settings
from app.models.schemas import (
    Chunk,
    ChunkMetadata,
    EnrichedChunk,
    Heading,
    Keyframe,
    PDFSegment,
    SourceType,
    VideoSegment,
    YouTubeMetadata,
    YouTubeSegment,
)
from app.pipeline.chunker import Chunker
from app.pipeline.metadata import MetadataEnricher

NOW = datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def chunker() -> Chunker:
    return Chunker()


@pytest.fixture
def enricher() -> MetadataEnricher:
    return MetadataEnricher()


# ---------------------------------------------------------------------------
# 1. Common metadata completeness
# ---------------------------------------------------------------------------


def test_common_metadata_fields_present_for_pdf(enricher, chunker):
    segment = PDFSegment(text="Some page content here.", page_number=3)
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_pdf_chunks("job-123", "doc.pdf", NOW, segment, chunks)

    for r in results:
        assert r.metadata.chunk_id
        assert r.metadata.source_type == SourceType.PDF
        assert r.metadata.job_id == "job-123"
        assert r.metadata.ingestion_timestamp == NOW
        assert r.metadata.embedding_model == "all-MiniLM-L6-v2"
        assert r.metadata.embedding_model_version != ""


def test_common_metadata_uses_configured_embedding_model_not_hardcoded(chunker):
    settings = Settings(embedding_model_name="some-other-model", _env_file=None)
    enricher = MetadataEnricher(settings=settings)
    segment = PDFSegment(text="Content.", page_number=1)
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    assert results[0].metadata.embedding_model == "some-other-model"


def test_common_metadata_uses_configured_embedding_model_version_not_hardcoded(chunker):
    """Task 8.3 remediation (Requirement 6.5 / Property 21):
    embedding_model_version must come from configuration, not be
    hardcoded, so it always reflects whatever model snapshot is actually
    pinned/loaded.
    """

    settings = Settings(embedding_model_revision="deadbeef1234567890", _env_file=None)
    enricher = MetadataEnricher(settings=settings)
    segment = PDFSegment(text="Content.", page_number=1)
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    assert results[0].metadata.embedding_model_version == "deadbeef1234567890"


# ---------------------------------------------------------------------------
# 2-3. Chunk ID determinism / uniqueness
# ---------------------------------------------------------------------------


def test_chunk_id_is_deterministic_across_repeated_calls(enricher, chunker):
    segment = PDFSegment(text="Repeated content for determinism check.", page_number=1)
    chunks = chunker.chunk(segment.text)

    result_a = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)
    result_b = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    assert [r.metadata.chunk_id for r in result_a] == [r.metadata.chunk_id for r in result_b]


def test_chunk_id_is_a_deterministic_uuid_not_a_random_one(enricher, chunker):
    """Task 8.3 remediation: Property 21 requires chunk_id to be a UUID.
    A deterministic, name-based UUID (uuid5, version 5) is used --
    verified here both by format (parses as a UUID) and by its version
    bits (5, not 4), which independently proves it was NOT generated via
    `uuid.uuid4()` (random).
    """

    import uuid

    segment = PDFSegment(text="Some content.", page_number=1)
    chunks = chunker.chunk(segment.text)

    result_a = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)
    result_b = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    # Same inputs -> same ID, not a fresh random value each time.
    assert result_a[0].metadata.chunk_id == result_b[0].metadata.chunk_id
    # Must parse as a real UUID (Property 21's literal format requirement).
    parsed = uuid.UUID(result_a[0].metadata.chunk_id)
    # Version 5 (name-based/deterministic) rather than version 4 (random)
    # is what proves determinism at the format level, not just by observation.
    assert parsed.version == 5


def test_different_pages_produce_different_chunk_ids(enricher, chunker):
    segment_1 = PDFSegment(text="Page one has this exact content.", page_number=1)
    segment_2 = PDFSegment(text="Page one has this exact content.", page_number=2)
    chunks_1 = chunker.chunk(segment_1.text)
    chunks_2 = chunker.chunk(segment_2.text)

    result_1 = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment_1, chunks_1)
    result_2 = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment_2, chunks_2)

    # Same text, different page -> different chunk_id (segment_key differs).
    assert result_1[0].metadata.chunk_id != result_2[0].metadata.chunk_id


def test_different_chunk_text_produces_different_chunk_ids(enricher, chunker):
    segment = PDFSegment(text="First sentence here. Second sentence differs entirely.", page_number=1)
    chunks = chunker.chunk(segment.text)
    assert len(chunks) >= 1

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    ids = [r.metadata.chunk_id for r in results]
    assert len(ids) == len(set(ids))  # all unique


def test_different_jobs_produce_different_chunk_ids_for_identical_content(enricher, chunker):
    segment = PDFSegment(text="Identical content across two jobs.", page_number=1)
    chunks = chunker.chunk(segment.text)

    result_job_a = enricher.enrich_pdf_chunks("job-a", "doc.pdf", NOW, segment, chunks)
    result_job_b = enricher.enrich_pdf_chunks("job-b", "doc.pdf", NOW, segment, chunks)

    assert result_job_a[0].metadata.chunk_id != result_job_b[0].metadata.chunk_id


# ---------------------------------------------------------------------------
# 4. PDF metadata completeness
# ---------------------------------------------------------------------------


def test_pdf_metadata_includes_page_heading_filename_chunk_position(enricher, chunker):
    segment = PDFSegment(
        text="Chapter content goes here across a couple of sentences.",
        page_number=7,
        headings=[Heading(text="Chapter 3", level=1)],
    )
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_pdf_chunks("job-1", "report.pdf", NOW, segment, chunks)

    for r in results:
        assert r.metadata.page_number == 7
        assert r.metadata.headings == [Heading(text="Chapter 3", level=1)]
        assert r.metadata.filename == "report.pdf"
        assert r.metadata.chunk_position == r.chunk.chunk_index


def test_pdf_metadata_headings_empty_list_when_none_present_not_fabricated(enricher, chunker):
    segment = PDFSegment(text="Plain body text with no headings at all.", page_number=2, headings=[])
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    assert results[0].metadata.headings == []


def test_pdf_metadata_missing_required_fields_raises():
    with pytest.raises(ValidationError):
        ChunkMetadata(
            chunk_id="x",
            source_type=SourceType.PDF,
            job_id="job-1",
            ingestion_timestamp=NOW,
            embedding_model="all-MiniLM-L6-v2",
            embedding_model_version="test-revision-abc123",
            chunk_position=0,
            # filename and page_number deliberately omitted
        )


def test_enrich_pdf_document_level_preserves_order_across_pages(enricher, chunker):
    seg1 = PDFSegment(text="Page one text content here.", page_number=1)
    seg2 = PDFSegment(text="Page two text content here.", page_number=2)
    seg3 = PDFSegment(text="Page three text content here.", page_number=3)
    segments_with_chunks = [(seg, chunker.chunk(seg.text)) for seg in (seg1, seg2, seg3)]

    results = enricher.enrich_pdf("job-1", "doc.pdf", NOW, segments_with_chunks)

    assert [r.metadata.page_number for r in results] == [1, 2, 3]


# ---------------------------------------------------------------------------
# 5. Video metadata completeness
# ---------------------------------------------------------------------------


def test_video_metadata_includes_start_end_filename_frame_reference(enricher, chunker):
    segment = VideoSegment(text="Spoken words go here in this segment.", start_time=30.0, end_time=45.0)
    keyframes = [Keyframe(timestamp=32.0, frame_reference="kf_1_32s")]
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_video_chunks("job-1", "lecture.mp4", NOW, segment, chunks, keyframes)

    for r in results:
        assert r.metadata.start_timestamp == 30.0
        assert r.metadata.end_timestamp == 45.0
        assert r.metadata.filename == "lecture.mp4"
        assert r.metadata.frame_reference == "kf_1_32s"


def test_video_metadata_frame_reference_none_when_no_keyframes_not_fabricated(enricher, chunker):
    segment = VideoSegment(text="Short segment with no nearby keyframes.", start_time=1.0, end_time=2.0)
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_video_chunks("job-1", "short.mp4", NOW, segment, chunks, keyframes=[])

    assert results[0].metadata.frame_reference is None


def test_video_metadata_picks_nearest_keyframe_when_none_in_range(enricher, chunker):
    segment = VideoSegment(text="Segment text content here.", start_time=100.0, end_time=110.0)
    keyframes = [
        Keyframe(timestamp=10.0, frame_reference="far"),
        Keyframe(timestamp=98.0, frame_reference="near"),
    ]
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_video_chunks("job-1", "video.mp4", NOW, segment, chunks, keyframes)

    assert results[0].metadata.frame_reference == "near"


def test_video_metadata_missing_required_fields_raises():
    with pytest.raises(ValidationError):
        ChunkMetadata(
            chunk_id="x",
            source_type=SourceType.MP4,
            job_id="job-1",
            ingestion_timestamp=NOW,
            embedding_model="all-MiniLM-L6-v2",
            embedding_model_version="test-revision-abc123",
            chunk_position=0,
            # filename, start_timestamp, end_timestamp deliberately omitted
        )


def test_enrich_video_document_level_preserves_order_across_segments(enricher, chunker):
    seg1 = VideoSegment(text="First segment text here.", start_time=0.0, end_time=5.0)
    seg2 = VideoSegment(text="Second segment text here.", start_time=5.0, end_time=10.0)
    keyframes = [Keyframe(timestamp=2.0, frame_reference="kf1")]
    segments_with_chunks = [(seg1, chunker.chunk(seg1.text)), (seg2, chunker.chunk(seg2.text))]

    results = enricher.enrich_video("job-1", "video.mp4", NOW, keyframes, segments_with_chunks)

    assert [r.metadata.start_timestamp for r in results] == [0.0, 5.0]


# ---------------------------------------------------------------------------
# 6. YouTube metadata completeness
# ---------------------------------------------------------------------------


def test_youtube_metadata_includes_all_required_fields(enricher, chunker):
    from datetime import date

    segment = YouTubeSegment(text="Welcome to the channel today.", start_time=12.0, duration=4.0)
    video_metadata = YouTubeMetadata(
        title="Great Video", channel="Great Channel", duration_seconds=600.0, publication_date=date(2023, 5, 1)
    )
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_youtube_chunks(
        "job-1", "https://www.youtube.com/watch?v=abc123", NOW, video_metadata, segment, chunks
    )

    for r in results:
        assert r.metadata.start_timestamp == 12.0
        assert r.metadata.duration == 4.0
        assert r.metadata.video_title == "Great Video"
        assert r.metadata.channel_name == "Great Channel"
        assert r.metadata.source_url == "https://www.youtube.com/watch?v=abc123"
        assert r.metadata.publication_date == date(2023, 5, 1)


def test_youtube_metadata_publication_date_none_not_fabricated(enricher, chunker):
    segment = YouTubeSegment(text="Some spoken content here.", start_time=0.0, duration=2.0)
    video_metadata = YouTubeMetadata(title="T", channel="C", duration_seconds=100.0, publication_date=None)
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_youtube_chunks("job-1", "https://youtu.be/abc", NOW, video_metadata, segment, chunks)

    assert results[0].metadata.publication_date is None
    # This must NOT raise, per Task 8.1's explicit instruction that the
    # existing "do not fabricate a publication date" behavior is preserved.


def test_youtube_metadata_missing_required_fields_raises():
    with pytest.raises(ValidationError):
        ChunkMetadata(
            chunk_id="x",
            source_type=SourceType.YOUTUBE,
            job_id="job-1",
            ingestion_timestamp=NOW,
            embedding_model="all-MiniLM-L6-v2",
            embedding_model_version="test-revision-abc123",
            chunk_position=0,
            # start_timestamp, duration, video_title, channel_name, source_url omitted
        )


def test_enrich_youtube_document_level_preserves_order_across_segments(enricher, chunker):
    seg1 = YouTubeSegment(text="First part of the talk.", start_time=0.0, duration=3.0)
    seg2 = YouTubeSegment(text="Second part of the talk.", start_time=3.0, duration=3.0)
    video_metadata = YouTubeMetadata(title="T", channel="C", duration_seconds=60.0)
    segments_with_chunks = [(seg1, chunker.chunk(seg1.text)), (seg2, chunker.chunk(seg2.text))]

    results = enricher.enrich_youtube("job-1", "https://youtu.be/xyz", NOW, video_metadata, segments_with_chunks)

    assert [r.metadata.start_timestamp for r in results] == [0.0, 3.0]


# ---------------------------------------------------------------------------
# 7. Source-specific information preserved (cross-source non-leakage)
# ---------------------------------------------------------------------------


def test_pdf_metadata_does_not_populate_video_or_youtube_fields(enricher, chunker):
    segment = PDFSegment(text="PDF content here for this test.", page_number=1)
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    for r in results:
        assert r.metadata.start_timestamp is None
        assert r.metadata.end_timestamp is None
        assert r.metadata.frame_reference is None
        assert r.metadata.video_title is None
        assert r.metadata.channel_name is None
        assert r.metadata.source_url is None


def test_video_metadata_does_not_populate_pdf_or_youtube_fields(enricher, chunker):
    segment = VideoSegment(text="Video content here for this test.", start_time=0.0, end_time=5.0)
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_video_chunks("job-1", "video.mp4", NOW, segment, chunks, keyframes=[])

    for r in results:
        assert r.metadata.page_number is None
        assert r.metadata.headings == []
        assert r.metadata.video_title is None
        assert r.metadata.channel_name is None
        assert r.metadata.source_url is None


# ---------------------------------------------------------------------------
# 8. Ordering / count preservation
# ---------------------------------------------------------------------------


def test_enriched_count_matches_chunk_count(enricher, chunker):
    segment = PDFSegment(
        text=" ".join(f"This is sentence number {i} in the document." for i in range(1, 60)), page_number=1
    )
    chunks = chunker.chunk(segment.text)
    assert len(chunks) > 1  # ensure this genuinely exercises multiple chunks

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    assert len(results) == len(chunks)


def test_enriched_chunk_ordering_matches_chunk_index_order(enricher, chunker):
    segment = PDFSegment(
        text=" ".join(f"This is sentence number {i} in the document." for i in range(1, 60)), page_number=1
    )
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    assert [r.chunk.chunk_index for r in results] == list(range(len(results)))
    assert [r.metadata.chunk_position for r in results] == list(range(len(results)))


def test_enriched_chunk_n_wraps_exactly_chunk_n(enricher, chunker):
    segment = PDFSegment(
        text=" ".join(f"This is sentence number {i} in the document." for i in range(1, 60)), page_number=1
    )
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    for i, chunk in enumerate(chunks):
        assert results[i].chunk is chunk


# ---------------------------------------------------------------------------
# 9. Empty input behavior
# ---------------------------------------------------------------------------


def test_empty_chunks_list_produces_empty_result(enricher):
    segment = PDFSegment(text="Some page.", page_number=1)
    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks=[])
    assert results == []


def test_empty_segments_with_chunks_list_produces_empty_result(enricher):
    results = enricher.enrich_pdf("job-1", "doc.pdf", NOW, segments_with_chunks=[])
    assert results == []


# ---------------------------------------------------------------------------
# 10. Multiple chunks from the same source remain distinguishable
# ---------------------------------------------------------------------------


def test_multiple_chunks_from_same_page_are_distinguishable(enricher):
    from app.config.settings import Settings as _Settings
    from types import SimpleNamespace

    small_chunker = Chunker(settings=SimpleNamespace(chunk_size=5, chunk_overlap=0))
    segment = PDFSegment(
        text="Alpha bravo charlie. Delta echo foxtrot. Golf hotel india. Juliett kilo lima.",
        page_number=4,
    )
    chunks = small_chunker.chunk(segment.text)
    assert len(chunks) > 1

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    chunk_ids = [r.metadata.chunk_id for r in results]
    assert len(chunk_ids) == len(set(chunk_ids))
    for r in results:
        assert r.metadata.page_number == 4  # same page, but distinguishable by chunk_id/position


# ---------------------------------------------------------------------------
# 11. No unexpected mutation of source/chunk data
# ---------------------------------------------------------------------------


def test_enrichment_does_not_mutate_original_segment(enricher, chunker):
    segment = PDFSegment(text="Original content that must not change.", page_number=5, headings=[])
    chunks = chunker.chunk(segment.text)

    enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    assert segment.page_number == 5
    assert segment.text == "Original content that must not change."
    assert segment.headings == []


def test_enrichment_does_not_mutate_original_chunks(enricher, chunker):
    segment = PDFSegment(text="Content for mutation check here.", page_number=1)
    chunks = chunker.chunk(segment.text)
    original_snapshot = [c.model_dump() for c in chunks]

    enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    assert [c.model_dump() for c in chunks] == original_snapshot


def test_enrichment_does_not_mutate_youtube_metadata(enricher, chunker):
    video_metadata = YouTubeMetadata(title="T", channel="C", duration_seconds=100.0)
    segment = YouTubeSegment(text="Some content here today.", start_time=0.0, duration=2.0)
    chunks = chunker.chunk(segment.text)

    enricher.enrich_youtube_chunks("job-1", "https://youtu.be/abc", NOW, video_metadata, segment, chunks)

    assert video_metadata.title == "T"
    assert video_metadata.channel == "C"
    assert video_metadata.publication_date is None


# ---------------------------------------------------------------------------
# EnrichedChunk / ChunkMetadata model shape
# ---------------------------------------------------------------------------


def test_enriched_chunk_wraps_chunk_and_metadata_types(enricher, chunker):
    segment = PDFSegment(text="Some content here today.", page_number=1)
    chunks = chunker.chunk(segment.text)

    results = enricher.enrich_pdf_chunks("job-1", "doc.pdf", NOW, segment, chunks)

    for r in results:
        assert isinstance(r, EnrichedChunk)
        assert isinstance(r.chunk, Chunk)
        assert isinstance(r.metadata, ChunkMetadata)


def test_ingestion_timestamp_must_be_timezone_aware():
    with pytest.raises(ValidationError):
        ChunkMetadata(
            chunk_id="x",
            source_type=SourceType.PDF,
            job_id="job-1",
            ingestion_timestamp=datetime(2026, 1, 1),  # naive
            embedding_model="all-MiniLM-L6-v2",
            embedding_model_version="test-revision-abc123",
            chunk_position=0,
            filename="doc.pdf",
            page_number=1,
        )
