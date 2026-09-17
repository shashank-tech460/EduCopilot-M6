from pathlib import Path
from unittest.mock import patch

import pytest

from app.config.settings import Settings
from app.models.exceptions import TranscriptUnavailableError, VideoInaccessibleError
from app.models.schemas import SourceType
from app.pipeline.canonical_extraction import extract_youtube_for_canonical_ingestion
from app.processors.youtube_processor import YouTubeProcessor


class FakeMetadataClient:
    def __init__(self, fetch_count_tracker: list[int] | None = None) -> None:
        self._fetch_count_tracker = fetch_count_tracker

    def fetch(self, url: str) -> dict:
        if self._fetch_count_tracker is not None:
            self._fetch_count_tracker.append(1)
        return {"title": "Test Video", "channel": "Test Channel", "duration": 600, "upload_date": "20240101"}


class FakeTranscriptClient:
    """Simulates per-language transcript availability. `available` maps
    language -> list of raw entries (or omit the key entirely to
    simulate that language being unavailable, raising
    TranscriptUnavailableError exactly like the real client does for
    TranscriptsDisabled/NoTranscriptFound)."""

    def __init__(self, available: dict[str, list[dict]], calls: list[str] | None = None) -> None:
        self._available = available
        self._calls = calls if calls is not None else []

    def fetch(self, video_id: str, language: str) -> list[dict]:
        self._calls.append(language)
        if language not in self._available:
            raise TranscriptUnavailableError(f"No transcript available for this video in language '{language}'")
        return self._available[language]


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def _entries(text: str) -> list[dict]:
    return [{"text": text, "start": 0.0, "duration": 2.0}]


def _embedder_stub(texts):
    return [[0.1, 0.2, 0.3] for _ in texts]


class TestEnglishOnlySuccess:
    def test_english_available_succeeds_without_attempting_hindi(self):
        calls: list[str] = []
        transcript_client = FakeTranscriptClient(available={"en": _entries("Hello world.")}, calls=calls)
        processor = YouTubeProcessor(
            settings=_settings(), transcript_client=transcript_client, metadata_client=FakeMetadataClient()
        )

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor", return_value=processor), patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockEmbedder.return_value.embed.side_effect = _embedder_stub
            enriched_chunks, _ = extract_youtube_for_canonical_ingestion(
                job_id="job-1", file_url="https://youtu.be/fake", settings=_settings()
            )

        assert calls == ["en"]  # Hindi never attempted
        assert enriched_chunks[0].chunk.text == "Hello world."


class TestHindiOnlyFallback:
    def test_english_fails_hindi_succeeds(self):
        calls: list[str] = []
        transcript_client = FakeTranscriptClient(available={"hi": _entries("नमस्ते दुनिया।")}, calls=calls)
        processor = YouTubeProcessor(
            settings=_settings(), transcript_client=transcript_client, metadata_client=FakeMetadataClient()
        )

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor", return_value=processor), patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockEmbedder.return_value.embed.side_effect = _embedder_stub
            enriched_chunks, _ = extract_youtube_for_canonical_ingestion(
                job_id="job-1", file_url="https://youtu.be/fake", settings=_settings()
            )

        assert calls == ["en", "hi"]  # English tried first, then Hindi
        assert enriched_chunks[0].chunk.text == "नमस्ते दुनिया।"  # original Hindi text, never translated

    def test_hindi_transcript_timestamps_are_preserved(self):
        entries = [
            {"text": "पहला भाग", "start": 5.0, "duration": 2.0},
            {"text": "दूसरा भाग", "start": 7.0, "duration": 3.0},
        ]
        transcript_client = FakeTranscriptClient(available={"hi": entries})
        processor = YouTubeProcessor(
            settings=_settings(), transcript_client=transcript_client, metadata_client=FakeMetadataClient()
        )

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor", return_value=processor), patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockEmbedder.return_value.embed.side_effect = _embedder_stub
            enriched_chunks, _ = extract_youtube_for_canonical_ingestion(
                job_id="job-1", file_url="https://youtu.be/fake", settings=_settings()
            )

        assert enriched_chunks[0].metadata.start_timestamp == 5.0
        assert enriched_chunks[0].metadata.duration == 5.0  # 7.0 + 3.0 - 5.0, real merged span

    def test_hindi_fallback_chunks_preserve_canonical_metadata(self):
        transcript_client = FakeTranscriptClient(available={"hi": _entries("परीक्षण सामग्री यहाँ है")})
        processor = YouTubeProcessor(
            settings=_settings(), transcript_client=transcript_client, metadata_client=FakeMetadataClient()
        )

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor", return_value=processor), patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockEmbedder.return_value.embed.side_effect = _embedder_stub
            enriched_chunks, _ = extract_youtube_for_canonical_ingestion(
                job_id="job-42", file_url="https://youtu.be/fake", settings=_settings()
            )

        metadata = enriched_chunks[0].metadata
        assert metadata.job_id == "job-42"
        assert metadata.source_type == SourceType.YOUTUBE
        assert metadata.chunk_id
        assert metadata.chunk_position == 0
        assert metadata.video_title == "Test Video"
        assert metadata.channel_name == "Test Channel"


class TestBothLanguagesAvailable:
    def test_english_is_preferred_and_hindi_is_never_fetched(self):
        calls: list[str] = []
        transcript_client = FakeTranscriptClient(
            available={"en": _entries("English content."), "hi": _entries("हिंदी सामग्री।")}, calls=calls
        )
        processor = YouTubeProcessor(
            settings=_settings(), transcript_client=transcript_client, metadata_client=FakeMetadataClient()
        )

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor", return_value=processor), patch(
            "app.pipeline.canonical_extraction.Embedder"
        ) as MockEmbedder:
            MockEmbedder.return_value.embed.side_effect = _embedder_stub
            enriched_chunks, _ = extract_youtube_for_canonical_ingestion(
                job_id="job-1", file_url="https://youtu.be/fake", settings=_settings()
            )

        assert calls == ["en"]
        assert enriched_chunks[0].chunk.text == "English content."


class TestNeitherLanguageAvailable:
    def test_controlled_failure_when_neither_english_nor_hindi_exists(self):
        transcript_client = FakeTranscriptClient(available={})  # neither en nor hi
        processor = YouTubeProcessor(
            settings=_settings(), transcript_client=transcript_client, metadata_client=FakeMetadataClient()
        )

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor", return_value=processor):
            with pytest.raises(TranscriptUnavailableError) as exc_info:
                extract_youtube_for_canonical_ingestion(
                    job_id="job-1", file_url="https://youtu.be/fake", settings=_settings()
                )

        # The final error is the FALLBACK language's own error (the last
        # attempt made), clearly naming the language that was missing --
        # never silently substituting or fabricating content.
        assert "'hi'" in str(exc_info.value)

    def test_video_inaccessible_is_never_caught_by_the_fallback(self):
        """VideoInaccessibleError must propagate immediately -- the
        fallback only ever catches TranscriptUnavailableError, since a
        genuinely inaccessible video won't have ANY transcript in ANY
        language, and retrying is pointless and would mask the real
        error type."""

        class _AlwaysInaccessibleClient:
            def fetch(self, video_id: str, language: str) -> list[dict]:
                raise VideoInaccessibleError("YouTube video is inaccessible or could not be retrieved")

        processor = YouTubeProcessor(
            settings=_settings(), transcript_client=_AlwaysInaccessibleClient(), metadata_client=FakeMetadataClient()
        )

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor", return_value=processor):
            with pytest.raises(VideoInaccessibleError):
                extract_youtube_for_canonical_ingestion(
                    job_id="job-1", file_url="https://youtu.be/fake", settings=_settings()
                )


class TestFallbackDisabled:
    def test_fallback_can_be_disabled_via_settings_matching_pre_correction_behavior(self):
        transcript_client = FakeTranscriptClient(available={"hi": _entries("हिंदी")})
        processor = YouTubeProcessor(
            settings=_settings(youtube_fallback_language=None),
            transcript_client=transcript_client,
            metadata_client=FakeMetadataClient(),
        )

        with patch("app.pipeline.canonical_extraction.YouTubeProcessor", return_value=processor):
            with pytest.raises(TranscriptUnavailableError):
                extract_youtube_for_canonical_ingestion(
                    job_id="job-1",
                    file_url="https://youtu.be/fake",
                    settings=_settings(youtube_fallback_language=None),
                )


class TestSettingsDefaults:
    def test_default_fallback_language_is_hindi(self):
        assert Settings().youtube_fallback_language == "hi"

    def test_default_primary_language_is_still_english(self):
        assert Settings().youtube_default_language == "en"
