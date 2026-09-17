from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.config.settings import Settings
from app.models.schemas import (
    Keyframe,
    SourceType,
    VideoProcessingResult,
    VideoSegment,
    YouTubeMetadata,
    YouTubeProcessingResult,
    YouTubeSegment,
)
from app.pipeline.canonical_extraction import (
    extract_pdf_for_canonical_ingestion,
    extract_video_for_canonical_ingestion,
    extract_youtube_for_canonical_ingestion,
)


@pytest.fixture
def settings():
    return Settings()


def _fake_embedder_embed(texts):
    return [[0.1, 0.2, 0.3] for _ in texts]


class TestVideoExtractionUsesWindowing:
    """Category F: MP4 extraction proven to use the shared windowing fix."""

    def test_multiple_short_video_segments_produce_fewer_coherent_chunks_not_one_per_segment(self, settings):
        segments = [
            VideoSegment(text="Operating system acts", start_time=0.0, end_time=2.0),
            VideoSegment(text="as an interface between", start_time=2.0, end_time=4.0),
            VideoSegment(text="user and hardware devices.", start_time=4.0, end_time=6.0),
        ]
        fake_result = VideoProcessingResult(segments=segments, keyframes=[], audio_absent=False)

        with patch("app.pipeline.canonical_extraction.VideoProcessor") as MockProcessor, patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockProcessor.return_value.process.return_value = fake_result
            MockEmbedder.return_value.embed.side_effect = _fake_embedder_embed

            enriched_chunks, _embeddings = extract_video_for_canonical_ingestion(
                job_id="job-1", file_path=Path("/tmp/fake.mp4"), settings=settings
            )

        # Three tiny 2-4-word segments must NOT become three separate
        # near-empty chunks -- they should be merged into one coherent
        # chunk containing the full sentence.
        assert len(enriched_chunks) == 1
        assert enriched_chunks[0].chunk.text == "Operating system acts as an interface between user and hardware devices."

    def test_merged_video_chunk_has_correct_real_timestamp_range(self, settings):
        segments = [
            VideoSegment(text="First part", start_time=1.0, end_time=2.0),
            VideoSegment(text="second part", start_time=2.0, end_time=3.5),
        ]
        fake_result = VideoProcessingResult(segments=segments, keyframes=[], audio_absent=False)

        with patch("app.pipeline.canonical_extraction.VideoProcessor") as MockProcessor, patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockProcessor.return_value.process.return_value = fake_result
            MockEmbedder.return_value.embed.side_effect = _fake_embedder_embed

            enriched_chunks, _embeddings = extract_video_for_canonical_ingestion(
                job_id="job-1", file_path=Path("/tmp/fake.mp4"), settings=settings
            )

        assert enriched_chunks[0].metadata.start_timestamp == 1.0
        assert enriched_chunks[0].metadata.end_timestamp == 3.5

    def test_video_chunks_carry_source_type_mp4(self, settings):
        segments = [VideoSegment(text="Some content here", start_time=0.0, end_time=1.0)]
        fake_result = VideoProcessingResult(segments=segments, keyframes=[], audio_absent=False)

        with patch("app.pipeline.canonical_extraction.VideoProcessor") as MockProcessor, patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockProcessor.return_value.process.return_value = fake_result
            MockEmbedder.return_value.embed.side_effect = _fake_embedder_embed

            enriched_chunks, _embeddings = extract_video_for_canonical_ingestion(
                job_id="job-1", file_path=Path("/tmp/fake.mp4"), settings=settings
            )

        assert enriched_chunks[0].metadata.source_type == SourceType.MP4


class TestYouTubeExtractionUsesWindowing:
    """Category E: YouTube extraction proven to use the shared windowing fix --
    the exact live-reproduced scenario from the forensic audit."""

    def test_fragmented_captions_produce_coherent_chunks_not_isolated_filler_words(self, settings):
        segments = [
            YouTubeSegment(text="Operating system acts as an interface", start_time=0.27, duration=2.0),
            YouTubeSegment(text="okay", start_time=2.27, duration=0.3),
            YouTubeSegment(text="between the user and the hardware", start_time=2.57, duration=2.0),
        ]
        metadata = YouTubeMetadata(title="OS Lecture", channel="Test Channel", duration_seconds=1200.0)
        fake_result = YouTubeProcessingResult(segments=segments, metadata=metadata)

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor") as MockProcessor, patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockProcessor.return_value.process.return_value = fake_result
            MockEmbedder.return_value.embed.side_effect = _fake_embedder_embed

            enriched_chunks, _embeddings = extract_youtube_for_canonical_ingestion(
                job_id="job-1", file_url="https://youtu.be/fake", settings=settings
            )

        # The exact live-reproduced defect: "okay" must never become its
        # own isolated chunk.
        assert all(chunk.chunk.text.strip() != "okay" for chunk in enriched_chunks)
        assert len(enriched_chunks) == 1
        assert "okay" in enriched_chunks[0].chunk.text
        assert "interface" in enriched_chunks[0].chunk.text
        assert "hardware" in enriched_chunks[0].chunk.text

    def test_merged_youtube_chunk_duration_reflects_the_real_merged_span(self, settings):
        segments = [
            YouTubeSegment(text="First segment", start_time=10.0, duration=2.0),
            YouTubeSegment(text="second segment", start_time=12.0, duration=3.0),
        ]
        metadata = YouTubeMetadata(title="T", channel="C", duration_seconds=100.0)
        fake_result = YouTubeProcessingResult(segments=segments, metadata=metadata)

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor") as MockProcessor, patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockProcessor.return_value.process.return_value = fake_result
            MockEmbedder.return_value.embed.side_effect = _fake_embedder_embed

            enriched_chunks, _embeddings = extract_youtube_for_canonical_ingestion(
                job_id="job-1", file_url="https://youtu.be/fake", settings=settings
            )

        # start=10.0, real span end = 12.0+3.0=15.0 -> duration = 5.0.
        # Never the per-video-wide duration_seconds=100.0, never fabricated.
        assert enriched_chunks[0].metadata.start_timestamp == 10.0
        assert enriched_chunks[0].metadata.duration == 5.0
        assert enriched_chunks[0].metadata.duration != metadata.duration_seconds

    def test_youtube_chunks_carry_source_type_youtube_and_video_metadata(self, settings):
        segments = [YouTubeSegment(text="Some content here", start_time=0.0, duration=1.0)]
        metadata = YouTubeMetadata(title="My Lecture", channel="My Channel", duration_seconds=60.0)
        fake_result = YouTubeProcessingResult(segments=segments, metadata=metadata)

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor") as MockProcessor, patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockProcessor.return_value.process.return_value = fake_result
            MockEmbedder.return_value.embed.side_effect = _fake_embedder_embed

            enriched_chunks, _embeddings = extract_youtube_for_canonical_ingestion(
                job_id="job-1", file_url="https://youtu.be/fake", settings=settings
            )

        assert enriched_chunks[0].metadata.source_type == SourceType.YOUTUBE
        assert enriched_chunks[0].metadata.video_title == "My Lecture"
        assert enriched_chunks[0].metadata.channel_name == "My Channel"


class TestCanonicalMetadataPreserved:
    """Category H: all required universal metadata fields survive
    windowing + chunking + enrichment, for both video and YouTube."""

    def test_video_chunk_has_all_required_universal_fields(self, settings):
        segments = [VideoSegment(text="Some content here for testing", start_time=0.0, end_time=2.0)]
        fake_result = VideoProcessingResult(segments=segments, keyframes=[], audio_absent=False)

        with patch("app.pipeline.canonical_extraction.VideoProcessor") as MockProcessor, patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockProcessor.return_value.process.return_value = fake_result
            MockEmbedder.return_value.embed.side_effect = _fake_embedder_embed

            enriched_chunks, _embeddings = extract_video_for_canonical_ingestion(
                job_id="job-1", file_path=Path("/tmp/fake.mp4"), settings=settings
            )

        metadata = enriched_chunks[0].metadata
        assert metadata.chunk_id
        assert metadata.job_id == "job-1"
        assert metadata.ingestion_timestamp is not None
        assert metadata.embedding_model
        assert metadata.embedding_model_version
        assert metadata.chunk_position == 0


class TestPDFExtractionUnaffected:
    """Category G: PDF extraction is byte-for-byte unchanged -- still
    one chunk call per page segment, no windowing involved."""

    def test_pdf_extraction_never_imports_or_calls_windowing(self):
        import inspect

        source = inspect.getsource(extract_pdf_for_canonical_ingestion)
        assert "group_segments_into_windows" not in source
        assert "window" not in source.lower()

    def test_pdf_extraction_still_calls_chunker_once_per_page_segment(self, settings):
        from app.models.schemas import PDFSegment

        pdf_segments = [
            PDFSegment(text="Page one content.", page_number=1, headings=[]),
            PDFSegment(text="Page two content.", page_number=2, headings=[]),
        ]

        with patch("app.pipeline.canonical_extraction.PDFProcessor") as MockProcessor, patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockProcessor.return_value.process.return_value = pdf_segments
            MockEmbedder.return_value.embed.side_effect = _fake_embedder_embed

            enriched_chunks, _embeddings = extract_pdf_for_canonical_ingestion(
                job_id="job-1", file_path=Path("/tmp/fake.pdf"), settings=settings
            )

        # One chunk per page (each page's text is short, well under
        # chunk_size) -- confirms page-level segments are still chunked
        # independently, unaffected by the video/YouTube windowing fix.
        assert len(enriched_chunks) == 2
        assert enriched_chunks[0].metadata.page_number == 1
        assert enriched_chunks[1].metadata.page_number == 2
